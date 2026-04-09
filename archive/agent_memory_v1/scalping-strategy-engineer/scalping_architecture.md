---
name: Scalping Strategy Architecture
description: Architecture of the 3-engine scalping system with confluence, risk management, and integration points
type: project
---

Scalping strategy implemented with 5 core modules + 3 support modules.

**Core Modules:**
- `signal_types.py` — Shared dataclasses (Signal, ConfluenceResult, RiskDecision, ScalpingConfig) and Direction enum
- `volume_breakout.py` — Motor 1: Volume spike breakout detection (3m entry, 15m context)
- `rsi_bb_reversal.py` — Motor 2: RSI + Bollinger Bands mean reversion (5m entry, 15m context)
- `ema_crossover.py` — Motor 3: EMA9/21 crossover with retest confirmation (3m entry, 15m context)
- `confluence.py` — Combines 3 signals into score (0-3) + direction + size/leverage
- `risk_manager.py` — Position sizing (2% risk), cooldown (3 candles), funding rate, ATR/BB checks

**Support Modules:**
- `scalping_data.py` — OHLCV fetch with cache, indicator calculation, funding rate API
- `scalping_trader.py` — Main integrator: position management, TP1/TP2 partial exits, DB logging
- `scalping_logger.py` — Rotating file logger (5MB max, 3 backups) for Pi

**Integration:**
- Connected to `main.py` in the main loop, runs after Multi-Agent Trading section
- Uses `database.py` for trade logging (agent_trades table)
- Sends alerts via `telegram_notifier.py`
- Respects circuit breaker via `is_circuit_broken("scalping")`
- State persisted in `scalping_state.json`

**Why:** Strategy uses 3 independent signal engines because each alone has high error rate in scalping, but when 2+ confirm same direction, win rate improves significantly. Confluence score of 2/3 = 50% size at 3x leverage, 3/3 = 100% size at 5x leverage.

**How to apply:** When modifying any module, maintain the Signal dataclass interface. All motors return Signal objects. ScalpingConfig in signal_types.py centralizes all parameters.
