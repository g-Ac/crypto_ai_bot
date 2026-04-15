"""Run matrix — orchestrates Baseline vs RAVR backtests across symbols and scenarios.

Usage:
    python -m backtest.run_matrix [--days 180] [--stress] [--force-download]

Produces:
  - Individual run artifacts in data/backtest_runs/<run_id>/
  - Summary matrix in data/backtest_runs/matrix_summary.md
"""
from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backtest.backtest_engine import BacktestEngine
from backtest.data_fetcher import fetch_and_cache, load_cached_candles
from backtest.data_loader import validate_data
from backtest.metrics import MetricsSummary, compute_metrics
from backtest.persistence import save_run
from defensive.config import DefensiveConfig
from defensive.enums import Strategy
from defensive.models import BacktestRunMeta, ClosedTrade

logger = logging.getLogger(__name__)

MATRIX_DIR = Path("data/backtest_runs")


# ---------------------------------------------------------------------------
# Stress scenarios
# ---------------------------------------------------------------------------

def _base_config() -> DefensiveConfig:
    """Base configuration — v0.1 frozen."""
    return DefensiveConfig(param_version="v0.1")


def _v02_base_config() -> DefensiveConfig:
    """v0.2: compression as prior state, volume optional, wider reclaim."""
    return DefensiveConfig(
        param_version="v0.2",
        compression_memory_window=12,    # Look back 12 candles for recent compression
        breakout_require_volume=False,   # Volume spike is secondary, not required
        breakout_reclaim_window=6,       # Expanded from 3 to 6 candles
    )


def _ravr_base_config() -> DefensiveConfig:
    """RAVR v1: regime-aware value reversion — frozen parameters."""
    return DefensiveConfig(
        param_version="ravr-v1",
        baseline_enabled=False,
        ravr_enabled=True,
        ravr_zscore_threshold=2.0,   # Frozen: 2 standard deviations
        ravr_vwap_period=96,         # Frozen: 24h rolling VWAP
        atr_sl_multiplier=1.5,       # Frozen: structural stop
        min_rr=2.0,                  # Frozen: minimum reward:risk
        timeout_candles=12,          # Frozen: 3h max hold
    )


# ---------------------------------------------------------------------------
# RAVR v2 variant configs (exit-only changes, entry frozen)
# ---------------------------------------------------------------------------

def _ravr_v2_base() -> DefensiveConfig:
    """Shared RAVR v2 base: same entry as v1."""
    return DefensiveConfig(
        baseline_enabled=False,
        ravr_enabled=True,
        ravr_zscore_threshold=2.0,
        ravr_vwap_period=96,
        atr_sl_multiplier=1.5,
        min_rr=2.0,
        timeout_candles=12,
    )


def _ravr_v2a_config() -> DefensiveConfig:
    """Variant A — Control: identical to RAVR v1."""
    c = _ravr_v2_base()
    c.param_version = "ravr-v2a-control"
    # v1 defaults: TP1=full VWAP, TP2=VWAP+50%
    c.ravr_tp1_mode = "vwap"
    c.ravr_tp1_vwap_frac = 1.0
    c.ravr_tp2_vwap_frac = 1.5
    return c


def _ravr_v2b_config() -> DefensiveConfig:
    """Variant B — Partial TP mais realista.

    TP1 = 40% da distancia ate VWAP, TP2 = VWAP completa, breakeven apos TP1.
    """
    c = _ravr_v2_base()
    c.param_version = "ravr-v2b-partial"
    c.ravr_tp1_mode = "vwap"
    c.ravr_tp1_vwap_frac = 0.4
    c.ravr_tp2_vwap_frac = 1.0
    c.tp1_partial_pct = 50.0  # 50% sai no TP1, 50% tenta TP2
    return c


def _ravr_v2c_config() -> DefensiveConfig:
    """Variant C — Protecao mais cedo.

    TP1 = 1R (SL distance), breakeven, TP2 = 60% da distancia ate VWAP.
    """
    c = _ravr_v2_base()
    c.param_version = "ravr-v2c-protect"
    c.ravr_tp1_mode = "rr"
    c.ravr_tp1_rr_mult = 1.0       # TP1 at 1R
    c.ravr_tp2_vwap_frac = 0.6     # TP2 at 60% of VWAP distance
    c.tp1_partial_pct = 50.0
    return c


def _ravr_v2d_config() -> DefensiveConfig:
    """Variant D — Exit por perda de forca (z-score decay).

    Sai quando |z-score| cai para <= 0.8 (reversao perdeu momentum).
    """
    c = _ravr_v2_base()
    c.param_version = "ravr-v2d-zscore"
    c.ravr_tp1_mode = "vwap"
    c.ravr_tp1_vwap_frac = 0.4     # TP1 realista tambem
    c.ravr_tp2_vwap_frac = 1.0
    c.ravr_zscore_exit_threshold = 0.8  # Sai quando z-score normaliza
    return c


def _ravr_v2e_config() -> DefensiveConfig:
    """Variant E — Timeout inteligente.

    Se apos 8 candles (2h) estiver positivo, realiza. Timeout normal em 12.
    """
    c = _ravr_v2_base()
    c.param_version = "ravr-v2e-smart-to"
    c.ravr_tp1_mode = "vwap"
    c.ravr_tp1_vwap_frac = 0.4
    c.ravr_tp2_vwap_frac = 1.0
    c.ravr_smart_timeout_candles = 8      # Check at 2h
    c.ravr_smart_timeout_min_pnl_pct = 0.0  # Any positive = take it
    return c


RAVR_V2_VARIANTS = {
    "v2a": _ravr_v2a_config,
    "v2b": _ravr_v2b_config,
    "v2c": _ravr_v2c_config,
    "v2d": _ravr_v2d_config,
    "v2e": _ravr_v2e_config,
}


def _stress_slippage_config(base_fn=_base_config) -> DefensiveConfig:
    """2x slippage stress test."""
    c = base_fn()
    c.param_version = f"{c.param_version}-stress-slip"
    c.slippage_normal = 0.04          # 2x normal
    c.slippage_failed_breakout = 0.10  # 2x
    c.slippage_regime_shift = 0.06     # 2x
    return c


def _stress_full_config(base_fn=_base_config) -> DefensiveConfig:
    """Fee + slippage stress + exclude dead/asia sessions."""
    c = base_fn()
    c.param_version = f"{c.param_version}-stress-full"
    c.slippage_normal = 0.04
    c.slippage_failed_breakout = 0.10
    c.slippage_regime_shift = 0.06
    c.fee_per_side = 0.06              # 1.5x fees (taker instead of maker)
    c.elevated_sessions = ["asia", "dead"]
    c.elevated_trap_score = 100        # Effectively block these sessions
    return c


def _get_scenarios(base_fn):
    """Build stress scenarios from a base config factory."""
    return {
        "base": base_fn,
        "stress_slippage": lambda: _stress_slippage_config(base_fn),
        "stress_full": lambda: _stress_full_config(base_fn),
    }


STRESS_SCENARIOS = _get_scenarios(_base_config)


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def _split_walk_forward(
    df: pd.DataFrame, n_windows: int = 4,
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """Split data into walk-forward windows.

    Returns list of (train, test) DataFrames.
    Each window: 70% train, 30% test, rolling forward.
    """
    total = len(df)
    window_size = total // (n_windows + 1)  # Overlap factor
    train_size = int(window_size * 2.5)      # ~70% of usable
    test_size = int(window_size * 1.0)       # ~30% of usable

    windows = []
    for i in range(n_windows):
        start = i * window_size
        train_end = start + train_size
        test_end = train_end + test_size

        if test_end > total:
            test_end = total
        if train_end >= total:
            break

        train = df.iloc[start:train_end].copy().reset_index(drop=True)
        test = df.iloc[train_end:test_end].copy().reset_index(drop=True)

        if len(test) > 100:  # Need minimum data
            windows.append((train, test))

    return windows


# ---------------------------------------------------------------------------
# Single backtest run
# ---------------------------------------------------------------------------

def _run_single(
    symbol: str,
    candles_15m: pd.DataFrame,
    candles_1h: pd.DataFrame,
    config: DefensiveConfig,
    scenario: str,
    tag: str = "",
) -> Tuple[BacktestRunMeta, List[ClosedTrade]]:
    """Run a single backtest and persist artifacts."""
    engine = BacktestEngine(config)
    meta = engine.run(candles_15m, candles_1h, symbol=symbol)
    meta.dataset_id = f"{symbol}_{scenario}_{tag}"

    # Data quality
    quality = validate_data(candles_15m, timeframe="15m")
    meta.coverage_ohlcv_pct = quality.coverage_pct

    # Persist
    save_run(meta, engine.trades, engine.decisions)

    return meta, engine.trades


# ---------------------------------------------------------------------------
# Matrix runner
# ---------------------------------------------------------------------------

def run_matrix(
    days: int = 180,
    run_stress: bool = True,
    force_download: bool = False,
    symbols: Optional[List[str]] = None,
    version: str = "v0.1",
) -> str:
    """Run the full research matrix.

    Steps:
    1. Download/load data for all symbols
    2. Run Baseline for each symbol (full period)
    3. Run RAVR for each symbol (full period)
    4. Walk-forward for Baseline
    5. Stress tests (if enabled)
    6. Generate comparison summary

    Args:
        version: "v0.1", "v0.2", or "ravr" — selects config factory.

    Returns:
        Path to matrix summary file.
    """
    symbols = symbols or ["BTCUSDT", "ETHUSDT"]
    results: List[Dict] = []
    walk_forward_results: List[Dict] = []

    # Select config factory based on version
    if version == "ravr":
        base_config_fn = _ravr_base_config
        strategy_label = "RAVR"
    elif version == "v0.2":
        base_config_fn = _v02_base_config
        strategy_label = "CFER_v0.2"
    else:
        base_config_fn = _base_config
        strategy_label = "CFER_Baseline"

    scenarios = _get_scenarios(base_config_fn)

    for symbol in symbols:
        logger.info("=" * 60)
        logger.info("Processing %s (%s)", symbol, version)
        logger.info("=" * 60)

        # Load data
        candles_15m = fetch_and_cache(symbol, "15m", days=days, force=force_download)
        candles_1h = fetch_and_cache(symbol, "1h", days=days, force=force_download)

        if len(candles_15m) < 200:
            logger.warning("Insufficient data for %s: %d candles", symbol, len(candles_15m))
            continue

        # --- Baseline (full period) ---
        logger.info("Running %s for %s...", strategy_label, symbol)
        config_base = base_config_fn()
        meta_bl, trades_bl = _run_single(
            symbol, candles_15m, candles_1h, config_base, "baseline",
        )
        m_bl = compute_metrics(trades_bl)
        results.append(_result_row(symbol, strategy_label, "base", m_bl, meta_bl))

        # --- RAVR comparison (skip if already running RAVR as main) ---
        if version != "ravr":
            logger.info("Running RAVR for %s...", symbol)
            config_ravr = base_config_fn()
            config_ravr.baseline_enabled = False
            config_ravr.ravr_enabled = True
            config_ravr.param_version = f"{version}-ravr"

            meta_ravr, trades_ravr = _run_single(
                symbol, candles_15m, candles_1h, config_ravr, "ravr",
            )
            m_ravr = compute_metrics(trades_ravr)
            results.append(_result_row(symbol, "RAVR", "base", m_ravr, meta_ravr))

        # --- Walk-forward ---
        logger.info("Walk-forward for %s (%s)...", symbol, version)
        windows = _split_walk_forward(candles_15m)
        candles_1h_aligned = candles_1h  # Use full 1h for all windows

        for wi, (train, test) in enumerate(windows):
            config_wf = base_config_fn()
            config_wf.param_version = f"{version}-wf{wi}"
            engine_wf = BacktestEngine(config_wf)
            meta_wf = engine_wf.run(test, candles_1h_aligned, symbol=symbol)
            meta_wf.dataset_id = f"{symbol}_wf_window{wi}"
            m_wf = compute_metrics(engine_wf.trades)

            save_run(meta_wf, engine_wf.trades, engine_wf.decisions)

            walk_forward_results.append({
                "symbol": symbol,
                "window": wi,
                "trades": m_wf.total_trades,
                "pf": m_wf.profit_factor,
                "expectancy": m_wf.expectancy,
                "win_rate": m_wf.win_rate,
                "period": f"{meta_wf.period_start} → {meta_wf.period_end}",
            })

        # --- Stress tests ---
        if run_stress:
            for scenario_name, config_fn in scenarios.items():
                if scenario_name == "base":
                    continue  # Already ran
                logger.info("Stress test %s for %s...", scenario_name, symbol)
                config_stress = config_fn()
                meta_st, trades_st = _run_single(
                    symbol, candles_15m, candles_1h, config_stress, scenario_name,
                )
                m_st = compute_metrics(trades_st)
                results.append(_result_row(symbol, strategy_label, scenario_name, m_st, meta_st))

    # --- Generate summary ---
    summary = _build_matrix_summary(results, walk_forward_results)
    summary_path = MATRIX_DIR / "matrix_summary.md"
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")

    # Also save raw results as JSON
    raw_path = MATRIX_DIR / "matrix_results.json"
    raw_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    logger.info("Matrix summary saved to %s", summary_path)
    return str(summary_path)


def _result_row(
    symbol: str, strategy: str, scenario: str,
    m: MetricsSummary, meta: BacktestRunMeta,
) -> Dict:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "scenario": scenario,
        "run_id": meta.run_id,
        "trades": m.total_trades,
        "win_rate": round(m.win_rate * 100, 1),
        "profit_factor": round(m.profit_factor, 2),
        "expectancy": round(m.expectancy, 4),
        "max_dd": round(m.max_drawdown_pct, 2),
        "total_pnl": round(m.total_pnl_pct, 2),
        "avg_hold": round(m.avg_hold_candles, 1),
        "avg_mae": round(m.avg_mae_pct, 3),
        "avg_mfe": round(m.avg_mfe_pct, 3),
        "period": f"{meta.period_start} → {meta.period_end}",
        "config_hash": meta.config_hash,
    }


def _build_matrix_summary(
    results: List[Dict],
    walk_forward: List[Dict],
) -> str:
    """Build markdown summary of the full matrix."""
    lines = [
        "# Matriz de Pesquisa — CFER Baseline vs RAVR",
        "",
        f"**Data:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Resultados por ativo e cenario",
        "",
        "| Ativo | Estrategia | Cenario | Trades | WR | PF | Expectancy | Max DD | PnL Total |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        lines.append(
            f"| {r['symbol']} | {r['strategy']} | {r['scenario']} "
            f"| {r['trades']} | {r['win_rate']}% | {r['profit_factor']} "
            f"| {r['expectancy']}% | {r['max_dd']}% | {r['total_pnl']}% |"
        )

    lines.extend(["", "## Walk-Forward (Baseline)", ""])

    if walk_forward:
        lines.append("| Ativo | Window | Trades | PF | Expectancy | WR | Periodo |")
        lines.append("|---|---|---|---|---|---|---|")
        for w in walk_forward:
            lines.append(
                f"| {w['symbol']} | {w['window']} | {w['trades']} "
                f"| {w['pf']} | {w['expectancy']}% | {round(w['win_rate'] * 100, 1)}% "
                f"| {w['period']} |"
            )

        # Consistency check
        for symbol in set(w["symbol"] for w in walk_forward):
            sym_windows = [w for w in walk_forward if w["symbol"] == symbol]
            positive_pf = sum(1 for w in sym_windows if w["pf"] > 1.0)
            total_windows = len(sym_windows)
            stable = positive_pf >= 3
            lines.append("")
            lines.append(
                f"**{symbol}**: PF positivo em {positive_pf}/{total_windows} janelas "
                f"→ {'CONSISTENTE' if stable else 'INSTAVEL'}"
            )
    else:
        lines.append("*Sem dados suficientes para walk-forward.*")

    # Stress comparison
    lines.extend(["", "## Stress Tests", ""])
    base_results = [r for r in results if r["scenario"] == "base"]
    stress_results = [r for r in results if r["scenario"] != "base"]

    if base_results and stress_results:
        for br in base_results:
            sym = br["symbol"]
            strat = br["strategy"]
            lines.append(f"### {sym} — {strat}")
            lines.append("")
            lines.append("| Cenario | PF | Expectancy | Max DD | Delta PF |")
            lines.append("|---|---|---|---|---|")
            lines.append(
                f"| base | {br['profit_factor']} | {br['expectancy']}% "
                f"| {br['max_dd']}% | — |"
            )
            for sr in stress_results:
                if sr["symbol"] == sym and sr["strategy"] == strat:
                    delta = round(sr["profit_factor"] - br["profit_factor"], 2)
                    lines.append(
                        f"| {sr['scenario']} | {sr['profit_factor']} "
                        f"| {sr['expectancy']}% | {sr['max_dd']}% | {delta} |"
                    )
            lines.append("")

    # Verdict
    lines.extend(["", "## Veredicto", ""])
    for br in base_results:
        if br["strategy"] == "CFER_Baseline":
            if br["trades"] < 10:
                verdict = "AMOSTRA INSUFICIENTE"
            elif br["profit_factor"] >= 1.3 and br["expectancy"] > 0.001:
                verdict = "GO para paper"
            elif br["profit_factor"] < 1.0:
                verdict = "NO-GO"
            else:
                verdict = "REVIEW"
            lines.append(f"- **{br['symbol']} Baseline**: {verdict} (PF={br['profit_factor']}, trades={br['trades']})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RAVR v2 matrix: 5 variants × 2 symbols, no stress (exit-only comparison)
# ---------------------------------------------------------------------------

def run_ravr_v2_matrix(
    days: int = 180,
    force_download: bool = False,
    symbols: Optional[List[str]] = None,
) -> str:
    """Run RAVR v2 exit-focused variant comparison.

    Runs variants A-E for each symbol (no stress tests — this is
    about exit structure, not cost sensitivity).

    Returns:
        Path to summary file.
    """
    symbols = symbols or ["BTCUSDT", "ETHUSDT"]
    results: List[Dict] = []

    for symbol in symbols:
        logger.info("=" * 60)
        logger.info("RAVR v2 variants for %s", symbol)
        logger.info("=" * 60)

        candles_15m = fetch_and_cache(symbol, "15m", days=days, force=force_download)
        candles_1h = fetch_and_cache(symbol, "1h", days=days, force=force_download)

        if len(candles_15m) < 200:
            logger.warning("Insufficient data for %s: %d candles", symbol, len(candles_15m))
            continue

        for variant_name, config_fn in RAVR_V2_VARIANTS.items():
            logger.info("Running %s for %s...", variant_name, symbol)
            config = config_fn()
            meta, trades = _run_single(
                symbol, candles_15m, candles_1h, config, variant_name,
            )
            m = compute_metrics(trades)

            # Exit reason breakdown
            exit_counts = {}
            for t in trades:
                er = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
                exit_counts[er] = exit_counts.get(er, 0) + 1

            row = _result_row(symbol, variant_name, "base", m, meta)
            row["exit_breakdown"] = exit_counts
            results.append(row)

    # Build summary
    summary = _build_ravr_v2_summary(results)
    summary_path = MATRIX_DIR / "ravr_v2_summary.md"
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary, encoding="utf-8")

    raw_path = MATRIX_DIR / "ravr_v2_results.json"
    raw_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    logger.info("RAVR v2 summary saved to %s", summary_path)
    return str(summary_path)


def _build_ravr_v2_summary(results: List[Dict]) -> str:
    """Build markdown comparison of RAVR v2 variants."""
    lines = [
        "# RAVR v2 — Comparacao de Variantes de Saida",
        "",
        f"**Data:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "**Regra:** entrada identica (z-score >= 2.0, VWAP 24h, regime gate).",
        "Apenas a estrutura de saida muda entre variantes.",
        "",
        "## Variantes",
        "",
        "| ID | Descricao |",
        "|---|---|",
        "| v2a | Controle (v1: TP1=VWAP, TP2=VWAP+50%) |",
        "| v2b | TP1=40% VWAP, TP2=VWAP, breakeven apos TP1 |",
        "| v2c | TP1=1R, breakeven, TP2=60% VWAP |",
        "| v2d | TP1=40% VWAP + z-score decay exit (|z|<=0.8) |",
        "| v2e | TP1=40% VWAP + smart timeout (positivo em 8 candles = sai) |",
        "",
        "## Resultados",
        "",
        "| Ativo | Variante | Trades | WR | PF | Expectancy | Max DD | PnL Total | Avg Hold |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        lines.append(
            f"| {r['symbol']} | {r['strategy']} | {r['trades']} "
            f"| {r['win_rate']}% | {r['profit_factor']} "
            f"| {r['expectancy']}% | {r['max_dd']}% | {r['total_pnl']}% "
            f"| {r['avg_hold']} |"
        )

    # Exit breakdown per variant
    lines.extend(["", "## Breakdown de Saidas", ""])
    lines.append("| Ativo | Variante | SL | TP1 | TP2 | Timeout | ZScore | SmartTO | Regime |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for r in results:
        eb = r.get("exit_breakdown", {})
        lines.append(
            f"| {r['symbol']} | {r['strategy']} "
            f"| {eb.get('sl', 0)} | {eb.get('tp1', 0)} | {eb.get('tp2', 0)} "
            f"| {eb.get('timeout', 0)} | {eb.get('zscore_decay', 0)} "
            f"| {eb.get('smart_timeout', 0)} | {eb.get('regime_shift', 0)} |"
        )

    # Comparison vs control
    lines.extend(["", "## Delta vs Controle (v2a)", ""])
    control_by_sym = {}
    for r in results:
        if r["strategy"] == "v2a":
            control_by_sym[r["symbol"]] = r

    if control_by_sym:
        lines.append("| Ativo | Variante | Delta PF | Delta WR | Delta DD | Delta PnL |")
        lines.append("|---|---|---|---|---|---|")

        for r in results:
            if r["strategy"] == "v2a":
                continue
            ctrl = control_by_sym.get(r["symbol"])
            if not ctrl:
                continue
            d_pf = round(r["profit_factor"] - ctrl["profit_factor"], 2)
            d_wr = round(r["win_rate"] - ctrl["win_rate"], 1)
            d_dd = round(r["max_dd"] - ctrl["max_dd"], 2)
            d_pnl = round(r["total_pnl"] - ctrl["total_pnl"], 2)
            sign = lambda v: f"+{v}" if v > 0 else str(v)
            lines.append(
                f"| {r['symbol']} | {r['strategy']} "
                f"| {sign(d_pf)} | {sign(d_wr)}% | {sign(d_dd)}% | {sign(d_pnl)}% |"
            )

    # Verdict
    lines.extend(["", "## Veredicto", ""])
    for sym in sorted(set(r["symbol"] for r in results)):
        sym_results = [r for r in results if r["symbol"] == sym and r["strategy"] != "v2a"]
        best = max(sym_results, key=lambda r: r["profit_factor"]) if sym_results else None
        if best:
            ctrl = control_by_sym.get(sym)
            improved = best["profit_factor"] > (ctrl["profit_factor"] if ctrl else 0)
            passed = best["profit_factor"] >= 1.0
            lines.append(
                f"- **{sym}**: melhor variante = {best['strategy']} "
                f"(PF={best['profit_factor']}, WR={best['win_rate']}%). "
                f"{'MELHORA vs v1' if improved else 'NAO melhora vs v1'}. "
                f"{'PF >= 1.0 — candidata a paper' if passed else 'PF < 1.0 — edge insuficiente'}."
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run backtest research matrix")
    parser.add_argument("--days", type=int, default=180, help="Days of history")
    parser.add_argument("--no-stress", action="store_true", help="Skip stress tests")
    parser.add_argument("--force-download", action="store_true", help="Force re-download data")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--version", default="v0.1",
                        choices=["v0.1", "v0.2", "ravr", "ravr-v2"],
                        help="Config version")
    args = parser.parse_args()

    if args.version == "ravr-v2":
        path = run_ravr_v2_matrix(
            days=args.days,
            force_download=args.force_download,
            symbols=args.symbols,
        )
    else:
        path = run_matrix(
            days=args.days,
            run_stress=not args.no_stress,
            force_download=args.force_download,
            symbols=args.symbols,
            version=args.version,
        )
    print(f"\nMatrix summary: {path}")
