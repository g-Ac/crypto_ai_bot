"""Testes da blindagem do k_collector (gap detection, sanity de relógio, watchdog logic).

Foco em lógica pura — sem HTTP real, sem Telegram real. Cobre:
  - last_bucket_ts: retorna MAX correto por símbolo e None se vazio
  - compute_dynamic_limit: ajusta limit ao gap, respeita teto/piso, lida com first_run
  - check_clock_sanity: aceita ano atual, rejeita ano absurdo
  - watchdog.collect_staleness: mesma lógica que compute_dynamic_limit
  - watchdog.is_stale: threshold + tolerância maior pra funding
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import k_collector as kc  # noqa: E402
import watchdog_k_collector as wd  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(kc.SCHEMA)
    yield c
    c.close()


def _insert_ratio(conn, symbol, bucket_ts, source="top_position",
                  ratio=1.0, collected_at=0):
    conn.execute(
        "INSERT OR IGNORE INTO k_ratios "
        "(symbol, bucket_ts, source, long_short_ratio, collected_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (symbol, bucket_ts, source, ratio, collected_at),
    )


def _insert_price(conn, symbol, bucket_ts, collected_at=0):
    conn.execute(
        "INSERT OR IGNORE INTO k_prices "
        "(symbol, bucket_ts, open_price, close_price, high_price, "
        " low_price, volume, collected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol, bucket_ts, 100.0, 101.0, 102.0, 99.0, 1000.0, collected_at),
    )


# ─── last_bucket_ts ─────────────────────────────────────────────────────────
def test_last_bucket_ts_none_quando_tabela_vazia(conn):
    assert kc.last_bucket_ts(conn, "k_ratios", "BTCUSDT") is None


def test_last_bucket_ts_retorna_max_por_simbolo(conn):
    _insert_ratio(conn, "BTCUSDT", 1_000_000)
    _insert_ratio(conn, "BTCUSDT", 2_000_000)
    _insert_ratio(conn, "BTCUSDT", 1_500_000)
    _insert_ratio(conn, "ETHUSDT", 5_000_000)
    assert kc.last_bucket_ts(conn, "k_ratios", "BTCUSDT") == 2_000_000
    assert kc.last_bucket_ts(conn, "k_ratios", "ETHUSDT") == 5_000_000
    assert kc.last_bucket_ts(conn, "k_ratios", "SOLUSDT") is None


def test_last_bucket_ts_funding_usa_funding_time(conn):
    conn.execute(
        "INSERT INTO k_funding_rates "
        "(symbol, funding_time, funding_rate, collected_at) "
        "VALUES (?, ?, ?, ?)", ("BTCUSDT", 9_000_000, 0.0001, 0)
    )
    assert kc.last_bucket_ts(conn, "k_funding_rates",
                             "BTCUSDT", "funding_time") == 9_000_000


# ─── compute_dynamic_limit ──────────────────────────────────────────────────
def test_compute_dynamic_limit_first_run_retorna_backfill_limit(conn):
    # tabelas vazias -> never_collected -> força BACKFILL_LIMIT
    now = 1_800_000_000
    limit, staleness = kc.compute_dynamic_limit(conn, now)
    assert limit == kc.BACKFILL_LIMIT
    assert staleness["k_ratios"]["never_collected"] is True


def test_compute_dynamic_limit_gap_pequeno_retorna_overlap(conn):
    """Se gap = 0h, limit deve ser OVERLAP_LIMIT (12h base + 6h margem = 18, pego min)."""
    now = 1_800_000_000
    # Insere TODOS os símbolos da config com bucket_ts recente
    recent = now - 3600  # 1h atrás
    for sym in kc.SYMBOLS:
        _insert_ratio(conn, sym, recent)
        _insert_price(conn, sym, recent)
        conn.execute(
            "INSERT INTO k_open_interest "
            "(symbol, bucket_ts, sum_open_interest, collected_at) "
            "VALUES (?, ?, ?, ?)", (sym, recent, 1000.0, 0)
        )
    limit, staleness = kc.compute_dynamic_limit(conn, now)
    # gap=1h, needed=1+6=7, min(BACKFILL, 7)=7, max(OVERLAP=12, 7)=12
    assert limit == kc.OVERLAP_LIMIT
    assert staleness["k_ratios"]["gap_hours"] == 1


def test_compute_dynamic_limit_gap_grande_aumenta_limit(conn):
    """Se um símbolo defasou 50h, limit cresce pra 56 (50+6)."""
    now = 1_800_000_000
    recent = now - 3600
    old = now - 50 * 3600  # 50h atrás
    for sym in kc.SYMBOLS:
        _insert_ratio(conn, sym, recent)
        _insert_price(conn, sym, recent)
        conn.execute(
            "INSERT INTO k_open_interest "
            "(symbol, bucket_ts, sum_open_interest, collected_at) "
            "VALUES (?, ?, ?, ?)", (sym, recent, 1000.0, 0)
        )
    # ETHUSDT em k_prices defasou
    _insert_price(conn, "ETHUSDT", old)  # cria entry antiga
    # ETHUSDT já tem entry recente acima — MAX continua recent
    # Pra realmente defasar, deletar a recente:
    conn.execute("DELETE FROM k_prices WHERE symbol='ETHUSDT' AND bucket_ts > ?", (old,))
    limit, staleness = kc.compute_dynamic_limit(conn, now)
    # k_prices: oldest_last_ts (ETHUSDT) = old, gap = 50h
    # needed = 50 + 6 = 56
    assert staleness["k_prices"]["gap_hours"] == 50
    assert limit == 56


def test_compute_dynamic_limit_cap_no_backfill_limit(conn):
    """Gap absurdo (>1000h) deve ser caped em BACKFILL_LIMIT."""
    now = 1_800_000_000
    very_old = now - 2000 * 3600
    for sym in kc.SYMBOLS:
        _insert_ratio(conn, sym, very_old)
        _insert_price(conn, sym, very_old)
        conn.execute(
            "INSERT INTO k_open_interest "
            "(symbol, bucket_ts, sum_open_interest, collected_at) "
            "VALUES (?, ?, ?, ?)", (sym, very_old, 1000.0, 0)
        )
    limit, _ = kc.compute_dynamic_limit(conn, now)
    assert limit == kc.BACKFILL_LIMIT


# ─── check_clock_sanity ─────────────────────────────────────────────────────
def test_check_clock_sanity_aceita_ano_atual():
    ok, msg = kc.check_clock_sanity()
    assert ok is True
    assert "clock ok" in msg


def test_check_clock_sanity_rejeita_relogio_antigo():
    """Simula Pi com relógio voltando pra 1970 (sem RTC + sem NTP ainda)."""
    import datetime as dt

    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

    with mock.patch("datetime.datetime", FakeDatetime):
        ok, msg = kc.check_clock_sanity()
        assert ok is False
        assert "1970" in msg
        assert "Aborta" in msg


# ─── watchdog.collect_staleness ─────────────────────────────────────────────
def test_watchdog_collect_staleness_never_collected_em_tabela_vazia(conn):
    st = wd.collect_staleness(conn, now=1_800_000_000)
    assert st["k_ratios"]["never_collected"] is True
    assert st["k_funding_rates"]["never_collected"] is True


def test_watchdog_collect_staleness_calcula_gap_horas(conn):
    now = 1_800_000_000
    # Insere todos com gap diferente; staleness pega o pior (oldest)
    for sym in kc.SYMBOLS:
        _insert_ratio(conn, sym, now - 1 * 3600)
    # SOLUSDT muito antigo
    _insert_ratio(conn, "SOLUSDT", now - 10 * 3600)
    # Deletar o recente do SOL
    conn.execute(
        "DELETE FROM k_ratios WHERE symbol='SOLUSDT' AND bucket_ts > ?",
        (now - 10 * 3600,)
    )
    st = wd.collect_staleness(conn, now)
    assert st["k_ratios"]["gap_hours"] == 10  # ditado pelo pior símbolo


# ─── watchdog.is_stale ──────────────────────────────────────────────────────
def test_is_stale_dispara_se_gap_maior_que_threshold():
    staleness = {
        "k_ratios": {"oldest_last_ts": 0, "gap_hours": 5},
        "k_prices": {"oldest_last_ts": 0, "gap_hours": 1},
    }
    stale, tables = wd.is_stale(staleness, threshold_hours=2)
    assert stale is True
    assert any("k_ratios" in t for t in tables)
    assert all("k_prices" not in t for t in tables)


def test_is_stale_funding_tem_tolerancia_4x_maior():
    """Funding liquida a cada 8h — threshold efetivo é 4x maior."""
    staleness = {
        "k_funding_rates": {"oldest_last_ts": 0, "gap_hours": 6},
    }
    # threshold=2h, efetivo pra funding=8h → 6h não dispara
    stale, _ = wd.is_stale(staleness, threshold_hours=2)
    assert stale is False
    # threshold=2h, efetivo=8h, mas gap=10h → dispara
    staleness["k_funding_rates"]["gap_hours"] = 10
    stale, tables = wd.is_stale(staleness, threshold_hours=2)
    assert stale is True
    assert any("k_funding_rates" in t for t in tables)


def test_is_stale_never_collected_sempre_dispara():
    staleness = {"k_ratios": {"never_collected": True}}
    stale, tables = wd.is_stale(staleness, threshold_hours=2)
    assert stale is True
    assert any("never" in t for t in tables)


# ─── watchdog.format_staleness_report ───────────────────────────────────────
def test_format_staleness_report_inclui_gap():
    staleness = {
        "k_ratios": {"oldest_last_ts": 0, "gap_hours": 5},
        "k_prices": {"never_collected": True},
    }
    text = wd.format_staleness_report(staleness)
    assert "k_ratios" in text and "5h" in text
    assert "k_prices" in text and "NUNCA" in text
