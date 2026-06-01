"""
EXP-009 — K Crowded Long OI Chase
Test suite (TDD RED phase)

Estes testes são escritos ANTES da implementação. Todos devem FALHAR
inicialmente — o módulo scripts/exp009_backtest.py ainda não existe.

Critérios travados em:
  ~/obsidian-vault/context/decisoes/2026-05-06-exp009-abertura-criterios-pre-commit.md

Regra: nenhum threshold abaixo é negociável durante a implementação.
Mudar threshold => abrir EXP-009b, não editar este arquivo.

Autor: Hermes + Gabriel
Data: 2026-05-06 (sessão de abertura)
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

# ============================================================
# Constantes travadas (espelho do documento de critérios)
# ============================================================

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")
CRITERIA_DOC = Path(
    "/home/pi/obsidian-vault/context/decisoes/"
    "2026-05-06-exp009-abertura-criterios-pre-commit.md"
)

UNIVERSE = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT",
    "SUIUSDT", "1000PEPEUSDT",
)

REQUIRED_TABLES = ("k_prices", "k_ratios", "k_funding_rates", "k_open_interest")

ROUND_TRIP_COST = 0.0012   # 12 bps
LIQ_FACTOR = 0.90          # adverse >= 0.90/L => liquida
LIQ_PNL_RETURN = -0.90     # PnL retornado quando liquidado

LEVERAGES_REPORT = (1, 2, 3, 5)
LEVERAGES_STRESS = (10,)
LEVERAGES_BANNED = (20, 50)

HORIZONS_HOURS = (6, 12, 24, 48)
ENTRY_POLICIES = ("ingenuous", "defensible", "conservative")

# Critérios de passagem
P1_NET_EDGE_MIN = 2 * ROUND_TRIP_COST   # 0.0024 = 0.24% por trade
P1_NW_T_MIN = 2.0
P1_LIQ_MAX = 0.05                        # 5%
P3_MIN_POSITIVE_SYMBOLS = 5
P3_MAX_PNL_CONCENTRATION = 0.50          # nenhum símbolo > 50% do PnL agregado
P4_DEFENSIBLE_VS_INGENUOUS_MIN = 0.80    # defensible >= 80% magnitude ingenuous
P5_MIN_REGIMES = 2                        # passa em >= 2 dos 3 regimes BTC

# Limite de amostra
MIN_TRADES_FOR_VERDICT = 200

# Modos de sinal (espelho do documento)
SIGNAL_MODES = ("A0", "A1", "A2", "A3")

# Paths proibidos (anti-fabricação)
BANNED_PATH_PREFIXES = ("/home/workdir", "/tmp/synthetic", "/var/synthetic")
BANNED_FUNCTION_NAMES = ("generate_synthetic_data", "make_fake_data", "synth_ohlcv")


# ============================================================
# Helper: import lazy do módulo (vai falhar no RED)
# ============================================================

def _import_backtest():
    """Importa o módulo de backtest. Falha esperada na fase RED."""
    import importlib
    return importlib.import_module("scripts.exp009_backtest")


@pytest.fixture(scope="session")
def bt():
    """Módulo de backtest. Skip-friendly enquanto não existir (RED)."""
    try:
        return _import_backtest()
    except (ImportError, ModuleNotFoundError) as e:
        pytest.fail(f"RED phase: scripts.exp009_backtest ainda não existe ({e})")


@pytest.fixture(scope="session")
def db_conn():
    if not DB_PATH.exists():
        pytest.fail(f"DB real ausente: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# GRUPO 1 — Carregamento de dados (proibir sintético)
# ============================================================

class TestGroup1DataLoading:

    def test_load_uses_only_real_db(self, bt):
        """load_dataset deve apontar exclusivamente para bot.db real."""
        ds = bt.load_dataset()
        assert ds.source_path == DB_PATH, (
            f"dataset deve vir de {DB_PATH}, veio de {ds.source_path}"
        )

    def test_load_rejects_synthetic_flag(self, bt):
        """Qualquer kwarg synthetic= ou fake= deve ser rejeitado."""
        with pytest.raises((TypeError, RuntimeError, ValueError)):
            bt.load_dataset(synthetic=True)

    def test_load_returns_14_symbols(self, bt):
        ds = bt.load_dataset()
        assert tuple(sorted(ds.symbols)) == tuple(sorted(UNIVERSE))

    def test_load_has_required_tables(self, db_conn):
        cur = db_conn.cursor()
        existing = {
            r["name"] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for t in REQUIRED_TABLES:
            assert t in existing, f"tabela obrigatória ausente: {t}"


# ============================================================
# GRUPO 2 — Sinais sem lookahead
# ============================================================

class TestGroup2NoLookahead:

    def test_signal_uses_close_t_only(self, bt):
        """Feature em t não pode depender de close[t+k] para k>=1."""
        ds = bt.load_dataset()
        # API esperada: build_features(ds) retorna DataFrame indexado por (symbol, ts)
        feats = bt.build_features(ds)
        # Probe: se eu zerar tudo após ts0, features em ts <= ts0 devem ser idênticas
        ts0 = bt.midpoint_timestamp(ds)
        feats_truncated = bt.build_features(bt.truncate_after(ds, ts0))
        diff = bt.compare_features_up_to(feats, feats_truncated, ts0)
        assert diff == 0, f"lookahead detectado: {diff} células divergentes"

    def test_three_entry_policies_differ_in_timestamps(self, bt):
        ds = bt.load_dataset()
        for policy in ENTRY_POLICIES:
            offset = bt.entry_offset_seconds(policy)
            assert offset is not None
        # ingenuous=0, defensible=3600, conservative>=3600 (e diferentes)
        offsets = {p: bt.entry_offset_seconds(p) for p in ENTRY_POLICIES}
        assert offsets["ingenuous"] == 0
        assert offsets["defensible"] >= 3600
        assert offsets["conservative"] > offsets["defensible"]

    def test_signal_modes_match_locked_definitions(self, bt):
        """Thresholds A0/A1/A2/A3 devem bater com o documento."""
        for mode in SIGNAL_MODES:
            spec = bt.get_signal_spec(mode)
            assert spec is not None, f"modo {mode} não definido"
        a0 = bt.get_signal_spec("A0")
        assert a0["ret24_min"] == pytest.approx(0.02)
        assert a0["oi24_min"] == pytest.approx(0.03)
        assert a0["funding_ann_min"] == pytest.approx(0.0)
        assert a0["top_long_min"] == pytest.approx(0.52)
        assert a0["global_long_min"] == pytest.approx(0.50)

        a1 = bt.get_signal_spec("A1")
        assert a1["ret24_min"] == pytest.approx(0.03)
        assert a1["oi24_min"] == pytest.approx(0.05)
        assert a1["funding_ann_min"] == pytest.approx(10.0)
        assert a1["top_long_min"] == pytest.approx(0.55)
        assert a1["global_long_min"] == pytest.approx(0.52)

        a2 = bt.get_signal_spec("A2")
        assert a2["ret24_min"] == pytest.approx(0.05)
        assert a2["oi24_min"] == pytest.approx(0.10)
        assert a2["funding_ann_min"] == pytest.approx(0.0)


# ============================================================
# GRUPO 3 — Custos e funding
# ============================================================

class TestGroup3CostsAndFunding:

    def test_round_trip_cost_is_12_bps(self, bt):
        gross = 0.05
        net = bt.apply_costs(gross_return=gross, side="SHORT",
                             entry_ts=0, exit_ts=86400, symbol="BTCUSDT",
                             funding_events=[])
        assert net == pytest.approx(gross - ROUND_TRIP_COST, abs=1e-9)

    def test_funding_summed_short_receives_positive(self, bt):
        events = [{"funding_time": 100, "funding_rate": 0.0001},
                  {"funding_time": 200, "funding_rate": 0.0002}]
        net_short = bt.apply_costs(gross_return=0.0, side="SHORT",
                                   entry_ts=0, exit_ts=300, symbol="BTCUSDT",
                                   funding_events=events)
        net_long = bt.apply_costs(gross_return=0.0, side="LONG",
                                  entry_ts=0, exit_ts=300, symbol="BTCUSDT",
                                  funding_events=events)
        # short recebe +0.0003 (menos custo); long paga -0.0003 (menos custo)
        assert net_short == pytest.approx(0.0003 - ROUND_TRIP_COST, abs=1e-9)
        assert net_long == pytest.approx(-0.0003 - ROUND_TRIP_COST, abs=1e-9)

    def test_no_funding_outside_window(self, bt):
        events = [{"funding_time": 50, "funding_rate": 0.001},   # antes da entrada
                  {"funding_time": 500, "funding_rate": 0.001}]  # depois da saída
        net = bt.apply_costs(gross_return=0.0, side="SHORT",
                             entry_ts=100, exit_ts=400, symbol="BTCUSDT",
                             funding_events=events)
        assert net == pytest.approx(-ROUND_TRIP_COST, abs=1e-9)


# ============================================================
# GRUPO 4 — Liquidação aproximada
# ============================================================

class TestGroup4Liquidation:

    @pytest.mark.parametrize("L", [1, 2, 3, 5, 10])
    def test_liquidation_threshold_formula(self, bt, L):
        thr = bt.liquidation_threshold(leverage=L)
        assert thr == pytest.approx(LIQ_FACTOR / L, abs=1e-9)

    def test_adverse_above_threshold_liquidates(self, bt):
        pnl = bt.compute_levered_pnl(net_unlev=0.05, adverse=0.10,
                                     leverage=10)
        # 10x liquida em 9% adverso; aqui 10% > 9% => -0.90
        assert pnl == pytest.approx(LIQ_PNL_RETURN, abs=1e-9)

    def test_adverse_below_threshold_does_not_liquidate(self, bt):
        pnl = bt.compute_levered_pnl(net_unlev=0.02, adverse=0.05,
                                     leverage=10)
        # 10x liquida em 9% adverso; aqui 5% < 9% => 0.02 * 10 = 0.20
        assert pnl == pytest.approx(0.20, abs=1e-9)


# ============================================================
# GRUPO 5 — Métricas obrigatórias
# ============================================================

class TestGroup5Metrics:

    def test_metrics_keyed_by_mode_horizon_leverage(self, bt):
        report = bt.run_full_backtest()
        for mode in SIGNAL_MODES:
            for h in HORIZONS_HOURS:
                for L in LEVERAGES_REPORT:
                    key = (mode, h, L)
                    assert key in report.cells, f"missing cell {key}"

    def test_nw_t_correction_uses_n_eff(self, bt):
        # NW_t deve usar n_eff = N / H, não N puro.
        # construo cenário sintético interno do bt e verifico magnitude.
        nw = bt.compute_nw_t(values=[0.01] * 240, horizon_hours=24)
        # Com mean=0.01, std=0, NW_t é inf — usar valores variados:
        import random
        random.seed(0)
        vals = [0.01 + random.gauss(0, 0.02) for _ in range(240)]
        nw_h24 = bt.compute_nw_t(values=vals, horizon_hours=24)
        nw_h1 = bt.compute_nw_t(values=vals, horizon_hours=1)
        # com h=24 o n_eff=10, com h=1 o n_eff=240 => |nw_h1| > |nw_h24|
        assert abs(nw_h1) > abs(nw_h24)

    def test_folds_are_three_equal_temporal(self, bt):
        report = bt.run_full_backtest()
        folds = report.folds_for(("A0", 24, 3))
        assert len(folds) == 3
        # divisão temporal: ts_max(fold[i]) <= ts_min(fold[i+1])
        for i in range(2):
            assert folds[i].ts_max <= folds[i + 1].ts_min

    def test_per_symbol_breakdown_has_14_rows(self, bt):
        report = bt.run_full_backtest()
        per_sym = report.per_symbol(("A0", 24, 3))
        assert tuple(sorted(per_sym.keys())) == tuple(sorted(UNIVERSE))

    def test_regime_btc_classification_thresholds(self, bt):
        # +2% / -2% sobre o horizonte
        assert bt.classify_btc_regime(ret=0.025, horizon_hours=24) == "up"
        assert bt.classify_btc_regime(ret=-0.025, horizon_hours=24) == "down"
        assert bt.classify_btc_regime(ret=0.01, horizon_hours=24) == "sideways"
        assert bt.classify_btc_regime(ret=-0.01, horizon_hours=24) == "sideways"


# ============================================================
# GRUPO 6 — Critérios de passagem (P1–P5)
# ============================================================

class TestGroup6PassingCriteria:

    def test_p1_requires_net_edge_min(self, bt):
        # cell com net_edge < 0.24% NÃO passa P1
        cell = bt.make_cell_for_test(net_edge=0.001, nw_t=3.0, liq=0.01, n=300)
        assert bt.passes_p1(cell) is False

    def test_p1_requires_nw_t_min(self, bt):
        cell = bt.make_cell_for_test(net_edge=0.005, nw_t=1.5, liq=0.01, n=300)
        assert bt.passes_p1(cell) is False

    def test_p1_requires_liquidation_max(self, bt):
        cell = bt.make_cell_for_test(net_edge=0.005, nw_t=3.0, liq=0.10, n=300)
        assert bt.passes_p1(cell) is False

    def test_p1_passes_when_all_three_meet(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=P1_NET_EDGE_MIN + 0.001,
            nw_t=P1_NW_T_MIN + 0.5,
            liq=P1_LIQ_MAX - 0.01,
            n=MIN_TRADES_FOR_VERDICT + 50,
        )
        assert bt.passes_p1(cell) is True

    def test_p2_blocks_negative_fold(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            fold_means=[0.01, 0.005, -0.003],
        )
        assert bt.passes_p2(cell) is False

    def test_p3_requires_min_positive_symbols(self, bt):
        cell_few = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            positive_symbols=3,
        )
        cell_ok = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            positive_symbols=P3_MIN_POSITIVE_SYMBOLS + 1,
        )
        assert bt.passes_p3(cell_few) is False
        assert bt.passes_p3(cell_ok) is True

    def test_p3_blocks_pnl_concentration(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            positive_symbols=8, max_symbol_pnl_share=0.65,
        )
        assert bt.passes_p3(cell) is False

    def test_p4_defensible_vs_ingenuous_ratio(self, bt):
        ratio_low = bt.defensible_vs_ingenuous_ratio(
            ingenuous=0.010, defensible=0.005,
        )
        assert ratio_low == pytest.approx(0.5, abs=1e-9)
        assert bt.passes_p4(ratio_low) is False
        ratio_ok = bt.defensible_vs_ingenuous_ratio(
            ingenuous=0.010, defensible=0.009,
        )
        assert bt.passes_p4(ratio_ok) is True

    def test_p5_two_of_three_regimes_required(self, bt):
        cell_one = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            regimes_passing=["up"],
        )
        cell_two = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            regimes_passing=["up", "sideways"],
        )
        assert bt.passes_p5(cell_one) is False
        assert bt.passes_p5(cell_two) is True


# ============================================================
# GRUPO 7 — Critérios de falha (F1–F5)
# ============================================================

class TestGroup7FailureCriteria:

    def test_f1_no_combination_passes_yields_no_go(self, bt):
        report = bt.synthesize_report_for_test(any_p1_pass=False)
        assert bt.final_verdict(report) == "NO-GO"

    def test_f2_fold3_negative_when_others_positive(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            fold_means=[0.012, 0.009, -0.004],
        )
        assert bt.triggers_f2(cell) is True

    def test_f3_edge_concentrated_in_two_or_fewer(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01, n=300,
            positive_symbols=2,
        )
        assert bt.triggers_f3(cell) is True

    def test_f4_only_passes_at_5x(self, bt):
        # 1x falha P1 mas 5x passa => F4
        report = bt.synthesize_report_for_test(
            mode="A0", horizon=24,
            edge_by_lev={1: 0.0005, 2: 0.0010, 3: 0.0018, 5: 0.0030},
        )
        assert bt.triggers_f4(report) is True

    def test_f5_leak_detected_when_defensible_ratio_low(self, bt):
        # ratio < 80% = leak
        assert bt.triggers_f5(defensible_ratio=0.6) is True
        assert bt.triggers_f5(defensible_ratio=0.85) is False


# ============================================================
# GRUPO 8 — Anti-fabricação
# ============================================================

class TestGroup8AntiFabrication:

    def test_no_synthetic_function_in_module(self, bt):
        for banned in BANNED_FUNCTION_NAMES:
            assert not hasattr(bt, banned), (
                f"função proibida presente: {banned}"
            )

    def test_no_workdir_paths_in_module(self):
        src = Path("/home/pi/crypto_ai_bot/scripts/exp009_backtest.py")
        if not src.exists():
            pytest.fail("RED phase: módulo ainda não existe")
        text = src.read_text()
        for banned in BANNED_PATH_PREFIXES:
            assert banned not in text, f"path proibido encontrado: {banned}"

    def test_leverages_above_5x_only_in_stress_section(self, bt):
        report = bt.run_full_backtest()
        for L in LEVERAGES_REPORT:
            assert L in report.report_section_leverages
        for L in LEVERAGES_STRESS:
            assert L in report.stress_section_leverages
            assert L not in report.report_section_leverages
        for L in LEVERAGES_BANNED:
            assert L not in report.report_section_leverages
            assert L not in report.stress_section_leverages

    def test_criteria_doc_hash_matches_pinned(self, bt):
        """O módulo deve carregar e validar o hash do documento de critérios.
        Se alguém editar o doc após esta sessão, todos os runs falham até
        o EXP-009b ser aberto formalmente."""
        assert CRITERIA_DOC.exists(), "criteria doc desapareceu"
        actual = hashlib.sha256(CRITERIA_DOC.read_bytes()).hexdigest()
        pinned = bt.PINNED_CRITERIA_HASH
        assert actual == pinned, (
            "documento de critérios foi modificado pós-abertura. "
            "Abrir EXP-009b ao invés de editar."
        )

    def test_min_trades_for_verdict_enforced(self, bt):
        cell = bt.make_cell_for_test(
            net_edge=0.005, nw_t=3.0, liq=0.01,
            n=MIN_TRADES_FOR_VERDICT - 50,
        )
        # com N abaixo do mínimo, verdict = DADO INSUFICIENTE
        assert bt.cell_verdict(cell) == "DADO INSUFICIENTE"
