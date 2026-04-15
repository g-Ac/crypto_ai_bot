"""Backtest metrics: PF, expectancy, drawdown, MAE/MFE, breakdowns.

All functions are pure — take a list of ClosedTrade and return numbers/dicts.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from defensive.enums import Direction, ExitReason, Regime, Session, Strategy, TrapEvidence
from defensive.models import ClosedTrade


@dataclass
class MetricsSummary:
    """Aggregate metrics for a set of trades."""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_rr_realized: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl_pct: float = 0.0
    total_pnl_usd: float = 0.0
    avg_hold_candles: float = 0.0
    avg_mae_pct: float = 0.0
    avg_mfe_pct: float = 0.0
    no_trade_rate: float = 0.0  # Set externally (needs total cycles)


def compute_metrics(trades: List[ClosedTrade]) -> MetricsSummary:
    """Compute aggregate metrics from a list of closed trades."""
    m = MetricsSummary()
    if not trades:
        return m

    m.total_trades = len(trades)

    winning = [t for t in trades if t.pnl_pct > 0]
    losing = [t for t in trades if t.pnl_pct <= 0]

    m.wins = len(winning)
    m.losses = len(losing)
    m.win_rate = m.wins / m.total_trades if m.total_trades > 0 else 0.0

    m.gross_profit = sum(t.pnl_pct for t in winning)
    m.gross_loss = abs(sum(t.pnl_pct for t in losing))

    m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else (
        float("inf") if m.gross_profit > 0 else 0.0
    )

    m.avg_win_pct = m.gross_profit / m.wins if m.wins > 0 else 0.0
    m.avg_loss_pct = m.gross_loss / m.losses if m.losses > 0 else 0.0

    m.expectancy = (m.win_rate * m.avg_win_pct) - ((1 - m.win_rate) * m.avg_loss_pct)

    m.avg_rr_realized = m.avg_win_pct / m.avg_loss_pct if m.avg_loss_pct > 0 else 0.0

    m.total_pnl_pct = sum(t.pnl_pct for t in trades)
    m.total_pnl_usd = sum(t.pnl_usd for t in trades)

    m.avg_hold_candles = sum(t.duration_candles for t in trades) / m.total_trades
    m.avg_mae_pct = sum(t.mae_pct for t in trades) / m.total_trades
    m.avg_mfe_pct = sum(t.mfe_pct for t in trades) / m.total_trades

    # Drawdown from equity curve
    m.max_drawdown_pct = compute_max_drawdown(trades)

    return m


def compute_max_drawdown(trades: List[ClosedTrade]) -> float:
    """Max drawdown % from cumulative PnL curve."""
    if not trades:
        return 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for t in trades:
        cumulative += t.pnl_pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return max_dd


def compute_equity_curve(
    trades: List[ClosedTrade], initial_capital: float = 1000.0,
) -> List[Dict]:
    """Build equity curve from trade sequence.

    Returns list of {timestamp, equity, trade_pnl_pct}.
    """
    equity = initial_capital
    curve = [{"timestamp": "", "equity": equity, "trade_pnl_pct": 0.0}]

    for t in trades:
        equity += t.pnl_usd
        curve.append({
            "timestamp": t.timestamp_close,
            "equity": equity,
            "trade_pnl_pct": t.pnl_pct,
        })

    return curve


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

def breakdown_by_field(
    trades: List[ClosedTrade], field_name: str,
) -> Dict[str, MetricsSummary]:
    """Group trades by a field and compute metrics per group."""
    groups: Dict[str, List[ClosedTrade]] = defaultdict(list)
    for t in trades:
        key = str(getattr(t, field_name, "unknown"))
        groups[key] = groups.get(key, [])
        groups[key].append(t)

    return {k: compute_metrics(v) for k, v in groups.items()}


def breakdown_by_symbol(trades: List[ClosedTrade]) -> Dict[str, MetricsSummary]:
    return breakdown_by_field(trades, "symbol")


def breakdown_by_regime(trades: List[ClosedTrade]) -> Dict[str, MetricsSummary]:
    return breakdown_by_field(trades, "regime")


def breakdown_by_direction(trades: List[ClosedTrade]) -> Dict[str, MetricsSummary]:
    return breakdown_by_field(trades, "direction")


def breakdown_by_session(trades: List[ClosedTrade]) -> Dict[str, MetricsSummary]:
    return breakdown_by_field(trades, "session")


def breakdown_by_exit_reason(trades: List[ClosedTrade]) -> Dict[str, MetricsSummary]:
    return breakdown_by_field(trades, "exit_reason")


def breakdown_by_trap_evidence(
    trades: List[ClosedTrade],
) -> Dict[str, Dict[str, MetricsSummary]]:
    """For each trap evidence type, split trades into 'with' and 'without'.

    Returns {evidence_name: {"with": MetricsSummary, "without": MetricsSummary}}.
    """
    result = {}
    for ev in TrapEvidence:
        with_ev = [t for t in trades if ev in t.trap_evidence]
        without_ev = [t for t in trades if ev not in t.trap_evidence]
        result[ev.value] = {
            "with": compute_metrics(with_ev),
            "without": compute_metrics(without_ev),
        }
    return result


# ---------------------------------------------------------------------------
# Decision funnel
# ---------------------------------------------------------------------------

@dataclass
class FunnelStats:
    """Funnel statistics from decision log."""

    total_cycles: int = 0
    trades_opened: int = 0
    blocked_by: Dict[str, int] = field(default_factory=dict)
    conversion_rate: float = 0.0

    def compute_conversion(self) -> None:
        self.conversion_rate = (
            self.trades_opened / self.total_cycles
            if self.total_cycles > 0
            else 0.0
        )
