"""
Rotulador forward para os eventos auditados do scalping.

Objetivo:
- olhar o que aconteceu apos cada observacao/execucao do scalping
- marcar se teria batido TP/SL primeiro
- medir MFE/MAE e retorno forward em 5m, 15m, 30m e 60m
- persistir isso como dataset para evolucao da estrategia/IA
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import database as db
from scalping_data import fetch_candles_range

logger = logging.getLogger("scalping.outcomes")

HORIZONS_MINUTES = (5, 15, 30, 60)
MAX_HORIZON_MINUTES = max(HORIZONS_MINUTES)
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round_or_none(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _parse_audit_timestamp(raw_value: str) -> Optional[datetime]:
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    except ValueError:
        return None


def _age_minutes(event_dt: Optional[datetime]) -> float:
    if event_dt is None:
        return 0.0
    now_local = datetime.now(LOCAL_TZ)
    return max((now_local - event_dt).total_seconds() / 60.0, 0.0)


def _resolve_best_signal(details: dict) -> dict:
    confluence = details.get("confluence") or {}
    best_signal = confluence.get("best_signal") or {}
    signals = confluence.get("signals") or []

    if best_signal and best_signal.get("direction") not in (None, "", "NEUTRAL"):
        return best_signal

    valid_signals = [item for item in signals if item.get("valid")]
    if not valid_signals:
        return best_signal

    valid_signals.sort(
        key=lambda item: (
            _safe_float(item.get("rr_ratio"), 0.0) or 0.0,
            _safe_float(item.get("strength"), 0.0) or 0.0,
        ),
        reverse=True,
    )
    return valid_signals[0]


def _resolve_setup(audit: dict) -> dict:
    details = audit.get("details") or {}
    confluence = details.get("confluence") or {}
    risk = details.get("risk") or {}
    market = details.get("market") or {}
    best_signal = _resolve_best_signal(details)

    market_1m = market.get("tf_1m") or {}
    market_3m = market.get("tf_3m") or {}
    market_5m = market.get("tf_5m") or {}

    direction = str(best_signal.get("direction") or confluence.get("direction") or "NEUTRAL").upper()
    reference_price = (
        _safe_float(best_signal.get("entry_price"))
        or _safe_float(best_signal.get("price"))
        or _safe_float(market_1m.get("close"))
        or _safe_float(market_3m.get("close"))
        or _safe_float(market_5m.get("close"))
    )
    entry_price = _safe_float(best_signal.get("entry_price")) or reference_price
    sl_price = _safe_float(risk.get("sl_price")) or _safe_float(best_signal.get("sl_price"))
    tp1_price = _safe_float(risk.get("tp1_price")) or _safe_float(best_signal.get("tp1_price"))
    tp2_price = _safe_float(risk.get("tp2_price")) or _safe_float(best_signal.get("tp2_price"))

    has_direction = direction in {"LONG", "SHORT"}
    has_entry = bool(entry_price and entry_price > 0)
    has_trade_plan = all(
        value is not None and value > 0
        for value in (entry_price, sl_price, tp1_price, tp2_price)
    )

    return {
        "direction": direction,
        "reference_price": reference_price,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "best_signal": best_signal,
        "has_direction": has_direction,
        "has_entry": has_entry,
        "has_trade_plan": has_trade_plan,
        "is_actionable": has_direction and has_entry,
    }


def _scenario_type(audit: dict) -> str:
    outcome = str(audit.get("outcome") or "")
    if audit.get("force_entry_applied"):
        return "forced"
    if outcome == "opened" or outcome == "tp1_partial" or outcome.startswith("closed_"):
        return "executed"
    if outcome == "ai_rejected":
        return "rejected"
    if "block" in outcome or outcome in {"cooldown", "in_position"}:
        return "blocked"
    return "observed"


def _directional_close_return(direction: str, entry_price: Optional[float], close_price: float) -> Optional[float]:
    if not entry_price or entry_price <= 0:
        return None
    if direction == "SHORT":
        return (entry_price / close_price - 1.0) * 100.0
    return (close_price / entry_price - 1.0) * 100.0


def _directional_mfe(direction: str, entry_price: Optional[float], high_price: float, low_price: float) -> tuple[Optional[float], Optional[float]]:
    if not entry_price or entry_price <= 0:
        return None, None
    if direction == "SHORT":
        mfe = (entry_price / low_price - 1.0) * 100.0
        mae = (entry_price / high_price - 1.0) * 100.0
    else:
        mfe = (high_price / entry_price - 1.0) * 100.0
        mae = (low_price / entry_price - 1.0) * 100.0
    return mfe, mae


def _scan_touches(df, direction: str, sl_price: Optional[float], tp1_price: Optional[float], tp2_price: Optional[float]) -> dict:
    result = {
        "first_touch": "none",
        "first_touch_minutes": None,
        "time_to_tp1_minutes": None,
        "time_to_tp2_minutes": None,
        "time_to_sl_minutes": None,
        "tp1_hit": False,
        "tp2_hit": False,
        "sl_hit": False,
        "touch_assumption": "worst_case_same_candle_hits_stop_first",
    }

    if df is None or df.empty:
        return result
    if not sl_price or not tp1_price or not tp2_price:
        result["first_touch"] = "no_trade_plan"
        return result

    for idx, row in enumerate(df.itertuples(index=False), start=1):
        if direction == "SHORT":
            sl_hit = row.high >= sl_price
            tp1_hit = row.low <= tp1_price
            tp2_hit = row.low <= tp2_price
        else:
            sl_hit = row.low <= sl_price
            tp1_hit = row.high >= tp1_price
            tp2_hit = row.high >= tp2_price

        if tp1_hit and result["time_to_tp1_minutes"] is None:
            result["time_to_tp1_minutes"] = idx
            result["tp1_hit"] = True
        if tp2_hit and result["time_to_tp2_minutes"] is None:
            result["time_to_tp2_minutes"] = idx
            result["tp2_hit"] = True
        if sl_hit and result["time_to_sl_minutes"] is None:
            result["time_to_sl_minutes"] = idx
            result["sl_hit"] = True

        if result["first_touch"] != "none":
            continue

        if sl_hit and (tp1_hit or tp2_hit):
            result["first_touch"] = "sl"
            result["first_touch_minutes"] = idx
        elif sl_hit:
            result["first_touch"] = "sl"
            result["first_touch_minutes"] = idx
        elif tp1_hit and tp2_hit:
            result["first_touch"] = "tp1"
            result["first_touch_minutes"] = idx
        elif tp1_hit:
            result["first_touch"] = "tp1"
            result["first_touch_minutes"] = idx
        elif tp2_hit:
            result["first_touch"] = "tp2"
            result["first_touch_minutes"] = idx

    return result


def _verdict_for_label(first_touch: str, is_actionable: bool, close_return_60m: Optional[float], label_status: str) -> tuple[str, bool, bool]:
    if not is_actionable:
        return "no_setup", False, False
    if first_touch in {"tp1", "tp2"}:
        return "winner", True, False
    if first_touch == "sl":
        return "loser", False, True
    if label_status != "complete":
        return "partial", False, False
    if close_return_60m is None:
        return "unresolved", False, False
    if close_return_60m > 0:
        return "open_positive", False, False
    if close_return_60m < 0:
        return "open_negative", False, False
    return "flat", False, False


def _compute_horizon_metrics(df, setup: dict, available_horizons: list[int]) -> dict:
    metrics = {}
    direction = setup["direction"]
    entry_price = setup["entry_price"] or setup["reference_price"]
    reference_price = setup["reference_price"] or entry_price

    for horizon in available_horizons:
        subset = df.iloc[:horizon].copy()
        if subset.empty:
            continue
        last_row = subset.iloc[-1]
        high_price = float(subset["high"].max())
        low_price = float(subset["low"].min())
        close_price = float(last_row["close"])

        if setup["has_direction"]:
            close_ret = _directional_close_return(direction, entry_price, close_price)
            mfe_pct, mae_pct = _directional_mfe(direction, entry_price, high_price, low_price)
            metrics[str(horizon)] = {
                "close_return_pct": _round_or_none(close_ret, 4),
                "mfe_pct": _round_or_none(mfe_pct, 4),
                "mae_pct": _round_or_none(mae_pct, 4),
                "close_price": _round_or_none(close_price, 6),
                "high_price": _round_or_none(high_price, 6),
                "low_price": _round_or_none(low_price, 6),
                "candles": int(len(subset)),
            }
        else:
            close_ret = ((close_price / reference_price) - 1.0) * 100.0 if reference_price else None
            up_move = ((high_price / reference_price) - 1.0) * 100.0 if reference_price else None
            down_move = ((low_price / reference_price) - 1.0) * 100.0 if reference_price else None
            metrics[str(horizon)] = {
                "close_return_pct": _round_or_none(close_ret, 4),
                "spot_up_pct": _round_or_none(up_move, 4),
                "spot_down_pct": _round_or_none(down_move, 4),
                "close_price": _round_or_none(close_price, 6),
                "high_price": _round_or_none(high_price, 6),
                "low_price": _round_or_none(low_price, 6),
                "candles": int(len(subset)),
            }

    return metrics


def _build_label_payload(audit: dict, df_future, available_horizons: list[int]) -> Optional[dict]:
    setup = _resolve_setup(audit)
    max_horizon = max(available_horizons) if available_horizons else 0
    if max_horizon <= 0:
        return None

    df_eval = df_future.iloc[:max_horizon].copy()
    if df_eval.empty:
        return None

    touch = _scan_touches(
        df_eval,
        setup["direction"],
        setup["sl_price"],
        setup["tp1_price"],
        setup["tp2_price"],
    ) if setup["is_actionable"] else {
        "first_touch": "not_applicable",
        "first_touch_minutes": None,
        "time_to_tp1_minutes": None,
        "time_to_tp2_minutes": None,
        "time_to_sl_minutes": None,
        "tp1_hit": False,
        "tp2_hit": False,
        "sl_hit": False,
        "touch_assumption": "not_actionable",
    }

    horizon_metrics = _compute_horizon_metrics(df_future, setup, available_horizons)
    close_return_60m = None
    if "60" in horizon_metrics:
        close_return_60m = horizon_metrics["60"].get("close_return_pct")
    elif str(max_horizon) in horizon_metrics:
        close_return_60m = horizon_metrics[str(max_horizon)].get("close_return_pct")

    label_status = "complete" if max_horizon >= MAX_HORIZON_MINUTES else "partial"
    verdict, winner_flag, loser_flag = _verdict_for_label(
        touch["first_touch"],
        setup["is_actionable"],
        close_return_60m,
        label_status,
    )

    start_time = df_future.iloc[0]["time"] if not df_future.empty else None
    end_time = df_future.iloc[max_horizon - 1]["time"] if len(df_future) >= max_horizon else None

    details = {
        "setup": {
            "direction": setup["direction"],
            "reference_price": _round_or_none(setup["reference_price"], 6),
            "entry_price": _round_or_none(setup["entry_price"], 6),
            "sl_price": _round_or_none(setup["sl_price"], 6),
            "tp1_price": _round_or_none(setup["tp1_price"], 6),
            "tp2_price": _round_or_none(setup["tp2_price"], 6),
            "is_actionable": setup["is_actionable"],
            "has_trade_plan": setup["has_trade_plan"],
            "best_signal_source": (setup["best_signal"] or {}).get("source"),
        },
        "touch": touch,
        "available_horizons": available_horizons,
        "horizons": horizon_metrics,
        "evaluation_window": {
            "start_time_utc": start_time.isoformat() if hasattr(start_time, "isoformat") else None,
            "end_time_utc": end_time.isoformat() if hasattr(end_time, "isoformat") else None,
            "candles_fetched": int(len(df_future)),
        },
    }

    return {
        "audit_id": audit["id"],
        "labeled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "audit_timestamp": audit.get("timestamp", ""),
        "symbol": audit.get("symbol", ""),
        "scenario_type": _scenario_type(audit),
        "event_outcome": audit.get("outcome", ""),
        "verdict": verdict,
        "reason": audit.get("reason", ""),
        "force_entry_applied": bool(audit.get("force_entry_applied", False)),
        "is_actionable": setup["is_actionable"],
        "direction": setup["direction"],
        "reference_price": _round_or_none(setup["reference_price"], 6),
        "entry_price": _round_or_none(setup["entry_price"], 6),
        "sl_price": _round_or_none(setup["sl_price"], 6),
        "tp1_price": _round_or_none(setup["tp1_price"], 6),
        "tp2_price": _round_or_none(setup["tp2_price"], 6),
        "first_touch": touch["first_touch"],
        "first_touch_minutes": touch["first_touch_minutes"],
        "time_to_tp1_minutes": touch["time_to_tp1_minutes"],
        "time_to_tp2_minutes": touch["time_to_tp2_minutes"],
        "time_to_sl_minutes": touch["time_to_sl_minutes"],
        "winner_flag": winner_flag,
        "loser_flag": loser_flag,
        "max_labeled_horizon": max_horizon,
        "label_status": label_status,
        "details_json": details,
    }


def label_scalping_outcomes(batch_size: int = 50, days: int = 7) -> dict:
    """Rotula auditorias com desfecho forward em janelas futuras."""
    audits = db.get_scalping_audits_for_outcome_labeling(limit=batch_size, days=days)
    processed = 0
    updated = 0
    skipped = 0
    errors = 0

    for audit in audits:
        processed += 1
        event_dt = _parse_audit_timestamp(audit.get("timestamp", ""))
        if event_dt is None:
            skipped += 1
            continue

        age = _age_minutes(event_dt)
        available_horizons = [h for h in HORIZONS_MINUTES if h <= age + 0.25]
        current_max = int(audit.get("current_max_labeled_horizon") or 0)
        if not available_horizons or max(available_horizons) <= current_max:
            skipped += 1
            continue

        highest_available = max(available_horizons)
        start_dt_utc = event_dt.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        fetch_limit = highest_available + 3
        df_future = fetch_candles_range(
            audit.get("symbol", ""),
            "1m",
            limit=fetch_limit,
            start_time_ms=int(start_dt_utc.timestamp() * 1000),
        )
        if df_future is None or df_future.empty:
            skipped += 1
            continue

        final_horizons = [h for h in available_horizons if len(df_future) >= h]
        if not final_horizons:
            skipped += 1
            continue

        try:
            payload = _build_label_payload(audit, df_future, final_horizons)
            if payload is None:
                skipped += 1
                continue
            db.upsert_scalping_outcome_label(payload)
            updated += 1
        except Exception as exc:
            errors += 1
            logger.warning("Falha ao rotular auditoria %s %s: %s", audit.get("id"), audit.get("symbol"), exc)

    result = {
        "processed": processed,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    if updated:
        logger.info("Outcome labeler processou %d e atualizou %d eventos", processed, updated)
    return result
