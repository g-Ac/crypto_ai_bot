"""Backtest report builder — generates structured markdown output.

Sections per BACKTEST_SPEC.md:
  1. Executive summary
  2. Comparative (Baseline vs Enhanced vs RAVR)
  3. Breakdowns (symbol, regime, direction, session, exit reason, trap)
  4. Trade distribution (PnL histogram, MAE/MFE)
  5. Walk-forward (if multiple windows)
  6. Decision funnel
  7. Metadata
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from backtest.metrics import (
    FunnelStats,
    MetricsSummary,
    breakdown_by_direction,
    breakdown_by_exit_reason,
    breakdown_by_regime,
    breakdown_by_session,
    breakdown_by_symbol,
    breakdown_by_trap_evidence,
    compute_metrics,
)
from defensive.enums import Outcome
from defensive.models import BacktestRunMeta, ClosedTrade, TradeDecision


def _fmt(val: float, decimals: int = 2) -> str:
    return f"{val:.{decimals}f}"


def _metrics_row(label: str, m: MetricsSummary) -> str:
    return (
        f"| {label} | {m.total_trades} | {_fmt(m.win_rate * 100, 1)}% "
        f"| {_fmt(m.profit_factor)} | {_fmt(m.expectancy, 3)}% "
        f"| {_fmt(m.max_drawdown_pct)}% | {_fmt(m.avg_hold_candles, 1)} |"
    )


def build_report(
    meta: BacktestRunMeta,
    trades: List[ClosedTrade],
    decisions: List[TradeDecision],
    config_hash: str = "",
    compare_trades: Optional[Dict[str, List[ClosedTrade]]] = None,
) -> str:
    """Build full backtest report as markdown string.

    Args:
        meta: Run metadata.
        trades: All closed trades from the run.
        decisions: All pipeline decisions (trade + no-trade).
        config_hash: Config hash for metadata section.
        compare_trades: Optional dict of {strategy_name: trades} for comparison.

    Returns:
        Markdown-formatted report string.
    """
    lines: List[str] = []
    overall = compute_metrics(trades)

    # ---- Section 1: Executive Summary ----
    verdict = _verdict(overall)
    lines.append("# Backtest Report")
    lines.append("")
    lines.append(f"## 1. Resumo Executivo")
    lines.append("")
    lines.append(f"- **Estrategia:** {meta.strategy.value}")
    lines.append(f"- **Periodo:** {meta.period_start} → {meta.period_end}")
    lines.append(f"- **Total trades:** {overall.total_trades}")
    lines.append(f"- **Win Rate:** {_fmt(overall.win_rate * 100, 1)}%")
    lines.append(f"- **Profit Factor:** {_fmt(overall.profit_factor)}")
    lines.append(f"- **Expectancy:** {_fmt(overall.expectancy, 3)}%")
    lines.append(f"- **Max Drawdown:** {_fmt(overall.max_drawdown_pct)}%")
    lines.append(f"- **PnL Total:** {_fmt(overall.total_pnl_pct)}%")
    lines.append(f"- **Veredicto:** {verdict}")
    lines.append("")

    # ---- Section 2: Comparative ----
    if compare_trades:
        lines.append("## 2. Comparativo")
        lines.append("")
        lines.append("| Estrategia | Trades | WR | PF | Expectancy | Max DD | Avg Hold |")
        lines.append("|---|---|---|---|---|---|---|")
        lines.append(_metrics_row(meta.strategy.value, overall))
        for name, t_list in compare_trades.items():
            m = compute_metrics(t_list)
            lines.append(_metrics_row(name, m))
        lines.append("")

    # ---- Section 3: Breakdowns ----
    lines.append("## 3. Breakdowns")
    lines.append("")

    # 3a: By symbol
    lines.append("### Por ativo")
    lines.append("")
    by_sym = breakdown_by_symbol(trades)
    lines.append("| Ativo | Trades | WR | PF | Expectancy | Max DD | Avg Hold |")
    lines.append("|---|---|---|---|---|---|---|")
    for sym, m in sorted(by_sym.items()):
        lines.append(_metrics_row(sym, m))
    lines.append("")

    # 3b: By regime
    lines.append("### Por regime")
    lines.append("")
    by_reg = breakdown_by_regime(trades)
    lines.append("| Regime | Trades | WR | PF | Expectancy | Max DD | Avg Hold |")
    lines.append("|---|---|---|---|---|---|---|")
    for reg, m in sorted(by_reg.items()):
        lines.append(_metrics_row(reg, m))
    lines.append("")

    # 3c: By direction
    lines.append("### Por direcao")
    lines.append("")
    by_dir = breakdown_by_direction(trades)
    lines.append("| Direcao | Trades | WR | PF | Expectancy | Max DD | Avg Hold |")
    lines.append("|---|---|---|---|---|---|---|")
    for d, m in sorted(by_dir.items()):
        lines.append(_metrics_row(d, m))
    lines.append("")

    # 3d: By session
    lines.append("### Por sessao")
    lines.append("")
    by_ses = breakdown_by_session(trades)
    lines.append("| Sessao | Trades | WR | PF | Expectancy | Max DD | Avg Hold |")
    lines.append("|---|---|---|---|---|---|---|")
    for s, m in sorted(by_ses.items()):
        lines.append(_metrics_row(s, m))
    lines.append("")

    # 3e: By exit reason
    lines.append("### Por exit reason")
    lines.append("")
    by_exit = breakdown_by_exit_reason(trades)
    lines.append("| Exit Reason | Count | % | PF | Avg PnL |")
    lines.append("|---|---|---|---|---|")
    for er, m in sorted(by_exit.items()):
        pct = m.total_trades / overall.total_trades * 100 if overall.total_trades > 0 else 0
        avg_pnl = m.total_pnl_pct / m.total_trades if m.total_trades > 0 else 0
        lines.append(f"| {er} | {m.total_trades} | {_fmt(pct, 1)}% | {_fmt(m.profit_factor)} | {_fmt(avg_pnl, 3)}% |")
    lines.append("")

    # 3f: Trap evidence ablation (Enhanced only)
    if any(t.trap_score > 0 for t in trades):
        lines.append("### Ablation: trap evidence")
        lines.append("")
        by_trap = breakdown_by_trap_evidence(trades)
        lines.append("| Evidence | Trades com | WR com | PF com | Trades sem | WR sem | PF sem |")
        lines.append("|---|---|---|---|---|---|---|")
        for ev_name, groups in sorted(by_trap.items()):
            w = groups["with"]
            wo = groups["without"]
            lines.append(
                f"| {ev_name} | {w.total_trades} | {_fmt(w.win_rate * 100, 1)}% | {_fmt(w.profit_factor)} "
                f"| {wo.total_trades} | {_fmt(wo.win_rate * 100, 1)}% | {_fmt(wo.profit_factor)} |"
            )
        lines.append("")

    # ---- Section 4: Trade Distribution ----
    lines.append("## 4. Distribuicao de Trades")
    lines.append("")
    if trades:
        pnls = [t.pnl_pct for t in trades]
        lines.append(f"- **Media PnL:** {_fmt(sum(pnls) / len(pnls), 3)}%")
        lines.append(f"- **Mediana PnL:** {_fmt(sorted(pnls)[len(pnls) // 2], 3)}%")
        lines.append(f"- **Melhor trade:** {_fmt(max(pnls), 3)}%")
        lines.append(f"- **Pior trade:** {_fmt(min(pnls), 3)}%")
        lines.append(f"- **MAE medio:** {_fmt(overall.avg_mae_pct, 3)}%")
        lines.append(f"- **MFE medio:** {_fmt(overall.avg_mfe_pct, 3)}%")
    lines.append("")

    # ---- Section 5: Walk-Forward (placeholder) ----
    lines.append("## 5. Walk-Forward")
    lines.append("")
    lines.append("*Disponivel quando multiplas janelas forem executadas.*")
    lines.append("")

    # ---- Section 6: Decision Funnel ----
    lines.append("## 6. Funil de Decisao")
    lines.append("")
    funnel = _build_funnel(decisions)
    lines.append(f"- **Total ciclos avaliados:** {funnel.total_cycles}")
    lines.append(f"- **Trades abertos:** {funnel.trades_opened}")
    lines.append(f"- **Taxa de conversao:** {_fmt(funnel.conversion_rate * 100, 2)}%")
    lines.append("")
    if funnel.blocked_by:
        lines.append("| Motivo | Count | % |")
        lines.append("|---|---|---|")
        for reason, count in sorted(funnel.blocked_by.items(), key=lambda x: -x[1]):
            pct = count / funnel.total_cycles * 100 if funnel.total_cycles > 0 else 0
            lines.append(f"| {reason} | {count} | {_fmt(pct, 1)}% |")
        lines.append("")

    # ---- Section 7: Metadata ----
    lines.append("## 7. Metadados")
    lines.append("")
    lines.append(f"- **Run ID:** {meta.run_id}")
    lines.append(f"- **Config hash:** {meta.config_hash}")
    lines.append(f"- **Param version:** {meta.param_version}")
    lines.append(f"- **Git SHA:** {meta.git_sha}")
    lines.append(f"- **Candles totais:** {meta.candles_total}")
    lines.append(f"- **Timestamp:** {meta.timestamp}")
    lines.append("")

    return "\n".join(lines)


def _verdict(m: MetricsSummary) -> str:
    """PASS / FAIL / REVIEW based on Go/No-Go gates."""
    if m.total_trades < 10:
        return "REVIEW (amostra insuficiente)"
    if m.profit_factor >= 1.3 and m.expectancy > 0.001 and m.max_drawdown_pct <= 15:
        return "PASS"
    if m.profit_factor < 1.0 or m.expectancy < 0:
        return "FAIL"
    return "REVIEW"


def _build_funnel(decisions: List[TradeDecision]) -> FunnelStats:
    """Build funnel stats from decision log."""
    funnel = FunnelStats()
    funnel.total_cycles = len(decisions)
    funnel.trades_opened = sum(1 for d in decisions if d.outcome == Outcome.TRADE)

    blocked = Counter()
    for d in decisions:
        if d.outcome != Outcome.TRADE:
            blocked[d.outcome.value] += 1
    funnel.blocked_by = dict(blocked)

    funnel.compute_conversion()
    return funnel
