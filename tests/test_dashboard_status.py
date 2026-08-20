"""Contrato do /api/status — momentum-only, honesto e liquido.

Nasceu de um bug que passou 6 dias despercebido: o dashboard reportava
`overall=degraded`, `last_cycle_ok=False` e `errors_today=0` com o bot 100%
saudavel, porque procurava um log com o nome do dia (`main_bot_<hoje>.log`)
enquanto o supervisor mantinha aberto o do dia do spawn. Nao havia UM teste
sobre esse payload.
"""
import json
import os
import time

import pytest

import dashboard_server as ds


# ── Resolucao do log ativo ───────────────────────────────────────────────────

def _write_log(tmp_path, name, content="linha\n", age_seconds=0):
    path = tmp_path / name
    path.write_text(content)
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(path, (past, past))
    return path


def test_resolve_active_log_ordena_por_mtime_nao_por_nome(tmp_path, monkeypatch):
    """O bug original: o log ativo carrega a data do SPAWN, nao a de hoje.

    O ativo aqui e o de nome lexicograficamente MENOR — assim ordenar por nome
    (a implementacao errada) da resposta diferente de ordenar por mtime.
    """
    monkeypatch.setattr(ds, "LOG_DIR", tmp_path)
    _write_log(tmp_path, "main_bot_2026-07-01.log", "ativo\n")
    _write_log(tmp_path, "main_bot_2026-12-31.log", "velho\n", age_seconds=86400)

    resolved = ds._resolve_active_log("main_bot")

    assert resolved.endswith("main_bot_2026-07-01.log"), \
        "resolveu por nome; tem que ser por mtime"


def test_resolve_active_log_sem_candidatos_devolve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "LOG_DIR", tmp_path)
    assert ds._resolve_active_log("main_bot") is None


def test_get_recent_logs_le_o_log_ativo_de_outro_dia(tmp_path, monkeypatch):
    """/api/logs?source=main voltava {"logs": []} pelo mesmo motivo."""
    monkeypatch.setattr(ds, "LOG_DIR", tmp_path)
    _write_log(tmp_path, "main_bot_2026-07-28.log", "primeira\nsegunda\n")

    assert ds._get_recent_logs(source="main", lines=10) == ["primeira", "segunda"]


# ── Contagem de erros ────────────────────────────────────────────────────────

def test_count_recent_errors_pega_o_marcador_real_do_main(tmp_path):
    """main.py imprime 'Erro: {e}' SEM colchetes — contar so '[erro]' era cego.

    Esse e o handler de topo do loop: se ele dispara, o ciclo inteiro falhou.
    """
    log = _write_log(tmp_path, "x.log", "ok\nErro: division by zero\nok\n")
    assert ds._count_recent_errors(str(log)) == 1


def test_count_recent_errors_conta_marcadores(tmp_path):
    log = _write_log(
        tmp_path, "x.log",
        "ok\n[ERRO] falhou\nok\nTraceback (most recent call last):\n",
    )
    assert ds._count_recent_errors(str(log)) == 2


def test_count_recent_errors_ignora_o_que_o_codigo_declara_ignorado(tmp_path):
    """'[copiloto] erro na vigia (ignorado)' nao derruba ciclo — nao e erro."""
    log = _write_log(tmp_path, "x.log", "[copiloto] erro na vigia (ignorado): x\n")
    assert ds._count_recent_errors(str(log)) == 0


def test_count_recent_errors_le_so_a_cauda(tmp_path):
    """O log ativo acumula dias; ler o arquivo todo custa I/O a cada refresh."""
    log = _write_log(tmp_path, "x.log", "Erro: antigo\n" + "ok\n" * 5000)
    assert ds._count_recent_errors(str(log), tail_bytes=64) == 0


def test_count_recent_errors_arquivo_ausente_nao_explode(tmp_path):
    assert ds._count_recent_errors(str(tmp_path / "nao_existe.log")) == 0


# ── Portao de saude ──────────────────────────────────────────────────────────

@pytest.fixture
def bot_env(tmp_path, monkeypatch):
    """Isola log e heartbeat, e finge processo vivo."""
    monkeypatch.setattr(ds, "LOG_DIR", tmp_path)
    state = tmp_path / "momentum_state.json"
    state.write_text("{}")
    monkeypatch.setattr(ds, "MOMENTUM_STATE_FILE", state)

    class _Ok:
        returncode = 0
    monkeypatch.setattr(ds.subprocess if hasattr(ds, "subprocess") else __import__("subprocess"),
                        "run", lambda *a, **k: _Ok())
    return tmp_path, state


def test_bot_status_healthy_sem_pump_scanner(bot_env):
    """O portao exigia pump_scanner (aposentado) e travava em degraded."""
    tmp_path, _ = bot_env
    _write_log(tmp_path, "main_bot_2026-07-28.log", "ciclo ok\n")

    status = ds._get_bot_status()

    assert status["overall"] == "healthy"
    assert status["last_cycle_ok"] is True
    assert status["last_cycle_ago"].endswith("s")
    assert status["last_cycle_ago"] != "N/A"
    assert "pump_scanner" not in status


def test_bot_status_degrada_quando_ha_erros(bot_env):
    tmp_path, _ = bot_env
    _write_log(tmp_path, "main_bot_2026-07-28.log", "Erro: algo quebrou\n")

    status = ds._get_bot_status()

    assert status["errors_recent"] == 1
    assert status["overall"] == "degraded"


def test_ciclo_nao_sai_do_log_e_sim_do_heartbeat(bot_env):
    """Crash loop: o supervisor reescreve o log a cada respawn (backoff <= 300s).

    Se o ciclo saisse do mtime do log, um main.py que morre no boot pareceria
    saudavel — falso positivo, pior que o falso negativo que isto veio consertar.
    """
    tmp_path, state = bot_env
    _write_log(tmp_path, "main_bot_2026-07-28.log", "Iniciado em ...\n")  # fresco
    antigo = time.time() - 3600
    os.utime(state, (antigo, antigo))  # nenhum ciclo ha 1h

    status = ds._get_bot_status()

    assert status["last_cycle_ok"] is False, "log fresco nao pode valer por ciclo"
    assert status["overall"] != "healthy"


def test_bot_status_ciclo_velho_nao_e_healthy(bot_env):
    """Heartbeat parado ha 20min: processo vivo, mas o ciclo travou."""
    _, state = bot_env
    antigo = time.time() - 1200
    os.utime(state, (antigo, antigo))

    status = ds._get_bot_status()

    assert status["last_cycle_ok"] is False
    assert status["overall"] != "healthy"


# ── Metricas: LIQUIDO, nunca bruto ───────────────────────────────────────────

def _trade(pnl_pct, pnl_usd, net_pct=None, net_usd=None, symbol="BTCUSDT", ts="2026-08-01"):
    return {
        "timestamp": ts, "symbol": symbol,
        "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
        "net_pnl_pct": net_pct, "net_pnl_usd": net_usd,
    }


def test_metricas_usam_o_liquido_nao_o_bruto():
    """O caso que motiva tudo: gross positivo, liquido negativo."""
    trades = [
        _trade(0.5, 5.0, net_pct=-0.5, net_usd=-5.0),
        _trade(0.5, 5.0, net_pct=-0.5, net_usd=-5.0),
    ]
    metrics = ds._compute_momentum_metrics(trades, 1000)

    assert metrics["win_rate"] == 0.0        # pelo bruto seriam 100%
    assert metrics["avg_pnl_pct"] == -0.5
    assert metrics["profit_factor"] == 0     # sem ganhos liquidos
    assert metrics["is_net"] is True


def test_metricas_caem_para_o_bruto_quando_a_fee_nao_foi_medida():
    """Linhas antigas tem net NULL — usa o gross em vez de tratar como zero."""
    metrics = ds._compute_momentum_metrics([_trade(1.0, 10.0)], 1000)
    assert metrics["avg_pnl_pct"] == 1.0
    assert metrics["total_trades"] == 1


def test_drawdown_reconstroi_a_curva_liquida():
    """capital_after e bruto; o drawdown tem que sair do net acumulado.

    Ordem de entrada e a do banco (mais recente primeiro).
    """
    trades = [
        _trade(0, 0, net_pct=-2.0, net_usd=-200.0, ts="2026-08-02"),  # 1000 -> 800
        _trade(0, 0, net_pct=1.0, net_usd=100.0, ts="2026-08-01"),    # 900 -> 1000
    ]
    metrics = ds._compute_momentum_metrics(trades, 900)

    assert metrics["max_drawdown_pct"] == 20.0  # pico 1000 -> vale 800


def test_metricas_sem_trades_nao_explodem():
    metrics = ds._compute_momentum_metrics([], 1000)
    assert metrics["total_trades"] == 0
    assert metrics["max_drawdown_pct"] == 0


def test_equity_chart_acumula_o_liquido_por_dia():
    trades = [
        _trade(0, 0, net_pct=0, net_usd=-5.0, ts="2026-08-02T10:00:00"),
        _trade(0, 0, net_pct=0, net_usd=10.0, ts="2026-08-01T10:00:00"),
        _trade(0, 0, net_pct=0, net_usd=2.0, ts="2026-08-01T12:00:00"),
    ]
    chart = ds._momentum_equity_chart(trades)

    assert chart == [
        {"day": "2026-08-01", "pnl": 12.0},
        {"day": "2026-08-02", "pnl": 7.0},
    ]


def test_by_symbol_classifica_pelo_liquido():
    trades = [
        _trade(1.0, 10.0, net_pct=-0.2, net_usd=-2.0, symbol="ETHUSDT"),
        _trade(1.0, 10.0, net_pct=0.4, net_usd=4.0, symbol="BTCUSDT"),
    ]
    rows = ds._momentum_by_symbol(trades)

    assert [r["symbol"] for r in rows] == ["BTCUSDT", "ETHUSDT"]
    eth = next(r for r in rows if r["symbol"] == "ETHUSDT")
    assert eth["losses"] == 1 and eth["wins"] == 0  # pelo bruto seria vitoria


# ── Contrato do payload ──────────────────────────────────────────────────────
#
# Banco e state SINTETICOS: rodar contra runtime/baseline/bot.db amarrava a suite
# a esta maquina (runtime/ e gitignored — em clone limpo, worktree ou BOT_ID novo
# as tabelas nem existem) e trocava asserções de CONTRATO por asserções de DADO
# ("fee_usd > 0" e falso num runtime sem trades, mesmo com o codigo correto).
# Com numeros conhecidos da para exigir valores EXATOS.

# 3 trades: gross +30 USD, fee 45 USD => net -15 USD. O caso que motiva tudo.
_TRADES = [
    # (timestamp, symbol, direction, pnl_pct, pnl_usd, fee, net_pct, net_usd)
    ("2026-08-01T10:00:00", "BTCUSDT", "LONG",   2.0,  20.0, 15.0,  0.5,   5.0),
    ("2026-08-02T10:00:00", "ETHUSDT", "SHORT",  2.0,  20.0, 15.0,  0.5,   5.0),
    ("2026-08-03T10:00:00", "BTCUSDT", "LONG",  -1.0, -10.0, 15.0, -2.5, -25.0),
]
_DECISIONS = [
    # (outcome, blocked_by, n)
    ("trade", "none", 3),            # viraram posicao
    ("trade", "max_positions", 12),  # sinal foi de trade, mas NAO abriu
    ("regime_blocked", "regime_blocked", 5),
]
_INITIAL_CAPITAL = 1000.0


@pytest.fixture
def fake_runtime(tmp_path, monkeypatch):
    """Banco + state sinteticos, isolados do runtime real."""
    db_file = tmp_path / "bot.db"
    monkeypatch.setattr(ds.db, "DB_FILE", str(db_file))
    ds.db.init_db()  # cria tabelas e roda as migracoes de fee

    conn = ds.db._get_conn()
    for ts, sym, direction, pct, usd, fee, npct, nusd in _TRADES:
        conn.execute(
            "INSERT INTO momentum_trades (timestamp, symbol, direction, pnl_pct, "
            "pnl_usd, total_fee_usd, net_pnl_pct, net_pnl_usd, capital_after) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, sym, direction, pct, usd, fee, npct, nusd, 0),
        )
    for outcome, blocked_by, n in _DECISIONS:
        for _ in range(n):
            conn.execute(
                "INSERT INTO momentum_decisions (timestamp, outcome, blocked_by) "
                "VALUES (datetime('now'), ?, ?)",
                (outcome, blocked_by),
            )
    conn.commit()
    conn.close()

    state = tmp_path / "momentum_state.json"
    # fee do state DIVERGE do banco de proposito (15 vs 45): e o bug real —
    # o state so acumula os trades com fee medida na hora.
    state.write_text(json.dumps({
        "capital": 1030.0, "positions": {}, "total_fee_usd": 15.0,
        "total_pnl_usd": 30.0, "total_trades": 3,
    }))
    monkeypatch.setattr(ds, "MOMENTUM_STATE_FILE", str(state))
    monkeypatch.setattr(ds, "MOMENTUM_INITIAL_CAPITAL", _INITIAL_CAPITAL)
    monkeypatch.setattr(ds, "get_capital_status", lambda: {"Momentum": 1030.0})
    return tmp_path


@pytest.fixture
def status(fake_runtime):
    return ds._build_status(include_logs=False, include_trades=False)


def test_payload_nao_carrega_sistemas_aposentados(status):
    assert set(status["capital"]) == {"momentum"}
    assert set(status["stats_today"]) == {"momentum"}
    assert set(status["metrics"]["per_system"]) == {"momentum"}


def test_payload_nao_carrega_mais_o_ai_brain(status):
    """Eram ~25 dos 30 KB, com decisoes de abril, a cada refresh."""
    assert "ai_brain" not in status
    assert len(json.dumps(status)) < 15_000


def test_capital_expoe_liquido_e_bruto_separados(status):
    momentum = status["capital"]["momentum"]
    # gross 1030 (+3%) vs net 985 (-1,5%): sinais OPOSTOS no mesmo payload
    assert momentum["value"] == 1030.0
    assert momentum["ret"] == 3.0
    assert momentum["net_value"] == 985.0     # 1000 + (-15) de net acumulado
    assert momentum["net_ret"] == -1.5
    assert momentum["fee_usd"] == 45.0


def test_liquido_vem_do_banco_e_nao_do_state(status):
    """O state subestima a fee: acumula so os trades com fee medida na hora.

    Aqui o state diz 15 e o banco soma 45. Se a implementacao voltar a ler o
    state, fee_usd vira 15 e net_value vira 1015 — este teste reprova.
    """
    momentum = status["capital"]["momentum"]
    assert momentum["fee_usd"] == 45.0, "fee_usd voltou a sair do state"
    assert momentum["net_value"] != 1015.0, "net derivado do state (capital - fee)"
    assert status["summary"]["net_total_usd"] == -15.0


def test_headline_do_portfolio_e_o_liquido(status):
    assert status["summary"]["portfolio_value"] == 985.0
    assert status["summary"]["portfolio_ret"] == -1.5
    assert status["summary"]["gross_value"] == 1030.0
    assert status["summary"]["gross_ret"] == 3.0
    assert status["summary"]["is_net"] is True


def test_metricas_do_payload_sao_liquidas(status):
    """2 trades com net +5 e 1 com net -25: WR 66,7%, PF 0,4 — nunca o gross."""
    metrics = status["metrics"]
    assert metrics["total_trades"] == 3
    assert metrics["win_rate"] == 66.7
    assert metrics["profit_factor"] == 0.4     # 10 de ganho / 25 de perda
    assert metrics["largest_loss"] == -2.5     # pelo gross seria -1.0


def test_funnel_conta_opened_por_blocked_by_nao_por_outcome(status):
    """outcome='trade' inclui sinais barrados depois (max_positions/cooldown).

    Aqui sao 15 linhas com outcome='trade' para 3 posicoes reais: contar por
    outcome daria opened=15 e um pass rate 5x maior que a realidade.
    """
    funnel = status["funnel"]
    assert "scalping_funnel" not in status
    assert funnel["opened"] == 3, "opened saiu de outcome='trade', nao de blocked_by"
    assert funnel["breakdown"]["max_positions"] == 12
    assert funnel["breakdown"]["regime_blocked"] == 5
    assert funnel["total"] == 20


def test_by_symbol_e_liquido_e_percentual(status):
    """avg_pnl_pct tem que ser MEDIA DE PERCENTUAIS — o codigo antigo punha USD/trade aqui."""
    btc = next(r for r in status["by_symbol"] if r["symbol"] == "BTCUSDT")
    assert btc["trades"] == 2
    assert btc["wins"] == 1 and btc["losses"] == 1   # pelo gross seriam 1/1 tambem, mas...
    assert btc["total_pnl"] == -20.0                 # ...no gross seria +10
    assert btc["avg_pnl_pct"] == -1.0                # media de (+0.5, -2.5)
    assert btc["avg_pnl_usd"] == -10.0               # o campo que guarda USD/trade


def test_campos_que_o_frontend_le_continuam_presentes(status):
    """Guarda contra remover campo consumido pela UI.

    Caminhos ANINHADOS, nao so chaves de topo: e assim que o frontend le, e foi
    exatamente onde o rename errors_today->errors_recent quebrou o /legacy.
    """
    caminhos = [
        # base.html
        "bot_status.overall", "bot_status.last_cycle_ago", "paused",
        "instance.version_tag", "instance.bot_id", "last_update",
        "health.uptime", "funnel.total", "funnel.breakdown",
        "summary.last_trade_ts",
        # system.html
        "bot_status.errors_recent", "capital.momentum.cb", "stats_today.momentum",
        # dashboard.js
        "summary.portfolio_value", "summary.portfolio_ret", "summary.today_pnl_usd",
        "summary.week_pnl_usd", "summary.open_positions", "summary.exposure_pct",
        "metrics.win_rate", "metrics.profit_factor", "metrics.max_drawdown_pct",
        "chart.total", "capital.momentum.net_value", "capital.momentum.net_ret",
        "capital.momentum.fee_usd", "metrics.per_system.momentum",
        # index.html (/legacy)
        "summary.best_system.key", "metrics.total_trades", "by_symbol",
        "insights.system_leaderboard",
    ]
    for caminho in caminhos:
        node = status
        for parte in caminho.split("."):
            assert isinstance(node, dict) and parte in node, f"faltou {caminho}"
            node = node[parte]
    assert isinstance(status["by_symbol"], list)
    assert isinstance(status["insights"]["system_leaderboard"], list)


def test_leaderboard_reporta_liquido_com_bruto_ao_lado(status):
    row = status["insights"]["system_leaderboard"][0]
    assert row["key"] == "momentum"
    assert row["capital_value"] == 985.0 and row["return_pct"] == -1.5
    assert row["gross_capital_value"] == 1030.0 and row["gross_return_pct"] == 3.0
