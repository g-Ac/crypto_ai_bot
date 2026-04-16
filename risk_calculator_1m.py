"""Risk Calculator for 1-minute trading system (Motor 0).

Before any trade, answers: "Is this trade viable?
If yes, with what size and leverage?"

All P&L calculations include fees. This is the guardian
that prevents unviable trades from entering.
"""
from dataclasses import dataclass
from config_1m import VALID_LEVERAGES, get_max_leverage, get_min_notional


@dataclass
class TradeViability:
    viable: bool
    reason: str
    position_size_usd: float
    leverage: int
    notional_usd: float
    fee_cost_usd: float
    fee_impact_pct: float
    min_profit_to_breakeven: float
    expected_profit_usd: float
    expected_loss_usd: float
    risk_reward_net: float
    actual_max_loss_usd: float


def calculate_viability(
    symbol: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    max_risk_per_trade_usd: float = 2.0,
    preferred_leverage: int | None = None,
    maker_fee_pct: float = 0.02,
    taker_fee_pct: float = 0.04,
    use_maker: bool = False,
    min_rr_net: float = 1.5,
    max_fee_impact_pct: float = 30.0,
    min_sl_distance_pct: float = 0.05,
    max_sl_distance_pct: float = 1.0,
) -> TradeViability:
    """Calculate trade viability with full fee accounting.

    Core logic:
    1. sl_distance_pct = abs(entry - sl) / entry * 100
    2. tp_distance_pct = abs(tp - entry) / entry * 100
    3. fee_roundtrip_pct = fee_per_side * 2
    4. notional = max_risk_per_trade_usd / (sl_distance_pct / 100)
    5. Check notional >= BINANCE_MIN_NOTIONAL
    6. Leverage: use preferred or maximize (125x) to minimize margin
    7. position_size = notional / leverage
    8. fee_cost = notional * fee_roundtrip_pct / 100
    9. expected_profit = (tp_distance_pct - fee_roundtrip_pct) / 100 * notional
    10. expected_loss = (sl_distance_pct + fee_roundtrip_pct) / 100 * notional
    11. risk_reward_net = expected_profit / expected_loss
    12. fee_impact_pct = fee_cost / expected_profit * 100
    13. Viable if: rr >= 1.5, fee_impact < 30%, notional >= min, sl in [0.05%, 1.0%]
    """

    _not_viable = lambda reason: TradeViability(
        viable=False, reason=reason,
        position_size_usd=0, leverage=0, notional_usd=0,
        fee_cost_usd=0, fee_impact_pct=0, min_profit_to_breakeven=0,
        expected_profit_usd=0, expected_loss_usd=0, risk_reward_net=0,
        actual_max_loss_usd=0,
    )

    if entry_price <= 0:
        return _not_viable("Entry price invalido")
    if sl_price <= 0:
        return _not_viable("SL price invalido")
    if tp_price <= 0:
        return _not_viable("TP price invalido")
    if max_risk_per_trade_usd <= 0:
        return _not_viable("Max risk per trade deve ser > 0")

    sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
    tp_distance_pct = abs(tp_price - entry_price) / entry_price * 100

    if sl_distance_pct == 0:
        return _not_viable("SL igual ao entry — distancia zero")
    if tp_distance_pct == 0:
        return _not_viable("TP igual ao entry — distancia zero")

    if sl_distance_pct < min_sl_distance_pct:
        return _not_viable(f"Stop muito curto: {sl_distance_pct:.3f}% < minimo {min_sl_distance_pct}%")
    if sl_distance_pct > max_sl_distance_pct:
        return _not_viable(f"Stop muito largo: {sl_distance_pct:.3f}% > maximo {max_sl_distance_pct}%")

    fee_per_side = maker_fee_pct if use_maker else taker_fee_pct
    fee_roundtrip_pct = fee_per_side * 2

    notional = max_risk_per_trade_usd / (sl_distance_pct / 100)

    min_notional = get_min_notional(symbol)
    if notional < min_notional:
        return _not_viable(f"Notional ${notional:.2f} abaixo do minimo ${min_notional} para {symbol}")

    max_lev = get_max_leverage(symbol)
    if preferred_leverage is not None:
        leverage = min(preferred_leverage, max_lev)
    else:
        leverage = max_lev

    position_size_usd = notional / leverage
    fee_cost_usd = notional * fee_roundtrip_pct / 100

    expected_profit_usd = (tp_distance_pct - fee_roundtrip_pct) / 100 * notional
    expected_loss_usd = (sl_distance_pct + fee_roundtrip_pct) / 100 * notional

    if expected_loss_usd <= 0:
        return _not_viable("Expected loss <= 0 — calculo invalido")
    risk_reward_net = expected_profit_usd / expected_loss_usd

    if expected_profit_usd <= 0:
        return _not_viable("Lucro esperado negativo apos fees")
    fee_impact_pct = fee_cost_usd / expected_profit_usd * 100

    min_profit_to_breakeven = fee_roundtrip_pct

    if risk_reward_net < min_rr_net:
        return _not_viable(f"R:R liquido {risk_reward_net:.2f} < minimo {min_rr_net}")
    if fee_impact_pct > max_fee_impact_pct:
        return _not_viable(f"Fee impact {fee_impact_pct:.1f}% > maximo {max_fee_impact_pct}%")

    return TradeViability(
        viable=True, reason="Trade viavel",
        position_size_usd=position_size_usd, leverage=leverage,
        notional_usd=notional, fee_cost_usd=fee_cost_usd,
        fee_impact_pct=fee_impact_pct,
        min_profit_to_breakeven=min_profit_to_breakeven,
        expected_profit_usd=expected_profit_usd,
        expected_loss_usd=expected_loss_usd,
        risk_reward_net=risk_reward_net,
        actual_max_loss_usd=expected_loss_usd,
    )
