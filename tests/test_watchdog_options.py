"""Testes do watchdog do options_collector (EXP-019).

Cobre a lógica pura de classificação (classify), a combinação por símbolo
(worst — símbolo mais defasado domina, BTC canônico não basta) e a integração
real com a tabela k_options_features (feature_age_seconds -> worst).
"""
import os
import sqlite3
import sys

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import options_collector as oc  # noqa: E402
import watchdog_options as wo  # noqa: E402


# ─── Lógica pura: classify ──────────────────────────────────────────────────
def test_classify_never_when_age_none():
    assert wo.classify(None, 2) == ("never", None)


def test_classify_ok_well_below_threshold():
    status, gap = wo.classify(600, 2)  # 10 min
    assert status == "ok"
    assert gap == 600 / 3600.0


def test_classify_boundary_exact_is_ok():
    # exatamente no threshold NÃO é stale (usa '>' estrito)
    status, gap = wo.classify(2 * 3600, 2)
    assert status == "ok"
    assert gap == 2.0


def test_classify_stale_just_over_threshold():
    status, _ = wo.classify(2 * 3600 + 1, 2)
    assert status == "stale"


def test_classify_stale_well_over():
    status, gap = wo.classify(5 * 3600, 2)
    assert status == "stale"
    assert gap == 5.0


# ─── Combinação por símbolo: worst ──────────────────────────────────────────
def test_worst_never_dominates_when_symbol_missing():
    # BTC fresco, ETH nunca coletou -> never (canônico não basta)
    status, sym, gap = wo.worst({"BTC": 600, "ETH": None}, 2)
    assert status == "never"
    assert sym == "ETH"
    assert gap is None


def test_worst_picks_most_stale_symbol():
    # ambos têm dado; ETH mais velho domina
    status, sym, _ = wo.worst({"BTC": 600, "ETH": 3 * 3600}, 2)
    assert status == "stale"
    assert sym == "ETH"


def test_worst_ok_when_all_fresh():
    status, sym, _ = wo.worst({"BTC": 600, "ETH": 1200}, 2)
    assert status == "ok"
    assert sym == "ETH"  # mais defasado entre os dois, mas ainda dentro do threshold


def test_worst_empty_is_never():
    assert wo.worst({}, 2) == ("never", None, None)


# ─── Integração com a tabela real (k_options_features) ──────────────────────
def _mem_conn():
    c = sqlite3.connect(":memory:")
    oc.init_db(c)
    return c


def _insert(conn, symbol, bucket_ts):
    oc.upsert_features(conn, {"symbol": symbol, "bucket_ts": bucket_ts}, bucket_ts)
    conn.commit()


def test_integration_fresh_is_ok():
    c = _mem_conn()
    now = 1_780_000_000
    _insert(c, "BTC", now - 600)   # 10 min
    _insert(c, "ETH", now - 1200)  # 20 min
    ages = wo.feature_age_seconds(c, now, ["BTC", "ETH"])
    assert wo.worst(ages, 2)[0] == "ok"


def test_integration_old_is_stale():
    c = _mem_conn()
    now = 1_780_000_000
    _insert(c, "BTC", now - 3 * 3600)  # 3h
    _insert(c, "ETH", now - 3 * 3600)
    ages = wo.feature_age_seconds(c, now, ["BTC", "ETH"])
    assert wo.worst(ages, 2)[0] == "stale"


def test_integration_empty_table_is_never():
    c = _mem_conn()
    ages = wo.feature_age_seconds(c, 1_780_000_000, ["BTC", "ETH"])
    assert ages == {"BTC": None, "ETH": None}
    assert wo.worst(ages, 2)[0] == "never"


def test_integration_one_symbol_fresh_other_missing_is_never():
    c = _mem_conn()
    now = 1_780_000_000
    _insert(c, "BTC", now - 600)  # só BTC coletou
    ages = wo.feature_age_seconds(c, now, ["BTC", "ETH"])
    assert ages["BTC"] is not None and ages["ETH"] is None
    assert wo.worst(ages, 2) == ("never", "ETH", None)


def test_integration_btc_fresh_eth_stale_is_stale():
    # caso assimétrico: BTC ok mas ETH parou -> stale apontando ETH
    c = _mem_conn()
    now = 1_780_000_000
    _insert(c, "BTC", now - 600)       # fresco
    _insert(c, "ETH", now - 4 * 3600)  # 4h parado
    ages = wo.feature_age_seconds(c, now, ["BTC", "ETH"])
    status, sym, _ = wo.worst(ages, 2)
    assert status == "stale"
    assert sym == "ETH"


def test_feature_age_uses_latest_bucket_per_symbol():
    # MAX(bucket_ts): linha antiga não "envelhece" o símbolo se há uma recente
    c = _mem_conn()
    now = 1_780_000_000
    _insert(c, "BTC", now - 10 * 3600)  # antiga
    _insert(c, "BTC", now - 600)        # recente
    ages = wo.feature_age_seconds(c, now, ["BTC"])
    assert ages["BTC"] == 600


# ─── Artefatos de deploy systemd ─────────────────────────────────────────────
def _repo_file(relative):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, relative), encoding="utf-8") as f:
        return f.read()


def test_systemd_service_options_tem_exec_env_log_e_exit_status():
    service = _repo_file("systemd/options-watchdog.service")
    assert "User=pi" in service
    assert "EnvironmentFile=-/home/pi/crypto_ai_bot/.env" in service
    assert "ExecStart=/home/pi/crypto_ai_bot/.venv/bin/python /home/pi/crypto_ai_bot/scripts/watchdog_options.py" in service
    assert "StandardOutput=append:/home/pi/crypto_ai_bot/logs/watchdog_options.log" in service
    assert "SuccessExitStatus=0 1" in service


def test_systemd_timer_options_roda_no_minuto_40_e_e_persistente():
    timer = _repo_file("systemd/options-watchdog.timer")
    assert "Requires=options-watchdog.service" in timer
    assert "OnCalendar=*-*-* *:40:00" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer


def test_install_e_uninstall_incluem_options_watchdog():
    install = _repo_file("systemd/install_systemd_units.sh")
    uninstall = _repo_file("systemd/uninstall_systemd_units.sh")
    for text in (install, uninstall):
        assert '"options-watchdog.service"' in text
        assert '"options-watchdog.timer"' in text
