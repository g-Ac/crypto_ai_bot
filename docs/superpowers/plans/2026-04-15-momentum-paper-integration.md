# Momentum Pullback Paper Trading Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the existing Momentum Pullback v1.1 signal evaluator into the bot's main loop as a paper trading subsystem, with full audit trail, circuit breaker, and state management.

**Architecture:** The signal evaluator (`momentum_trader.py`) and exit checker (`research_runner.py:check_exit`) already exist and are frozen. This plan wraps them in a paper executor that manages capital, positions, and persistence — writing to `bot.db` via `database.py` for consistency with scalping/pump/paper systems. A JSON state file handles inter-cycle persistence.

**Tech Stack:** Python 3.13, SQLite (WAL mode), existing momentum module, existing bot infrastructure.

**Governance:** This implements the technical integration (Block B) authorized by the Paper Readiness Framework (`docs/superpowers/specs/2026-04-15-paper-readiness-framework.md`). The framework's governance rules (checkpoints, kill conditions, classes of change) apply. Paper does NOT start automatically — requires operator approval after smoke test.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `config.py` | Add `MOMENTUM_*` constants (capital, enabled, symbols, max positions) |
| Modify | `runtime_config.py` | Add `MOMENTUM_STATE_FILE` path |
| Modify | `database.py` | Add `momentum_trades` + `momentum_decisions` tables, insert functions, VALID_TABLES |
| Create | `momentum/paper_executor.py` | Paper trading executor: state mgmt, signal→position, exits, status |
| Modify | `daily_report.py` | Add `"momentum"` to circuit breaker table_map |
| Modify | `main.py` | Add momentum block to main loop |
| Create | `tests/test_momentum_paper_executor.py` | Tests for the paper executor |
| Create | `tests/test_momentum_integration.py` | Integration tests for DB + circuit breaker + main loop wiring |

---

### Task 1: Config and Runtime Config

**Files:**
- Modify: `config.py:14-41` (capital defaults + env overrides)
- Modify: `config.py:166-171` (enabled flags)
- Modify: `runtime_config.py:130-146` (state files)
- Modify: `runtime_config.py:160-167` (runtime_metadata initial_capitals)

- [ ] **Step 1: Add momentum to capital defaults in config.py**

In `config.py`, add `"momentum"` to `_DEFAULT_INITIAL_CAPITALS` and add the env override:

```python
_DEFAULT_INITIAL_CAPITALS = {
    "paper": 10000.0,
    "agent": 10000.0,
    "pump": 5000.0,
    "scalping": 10000.0,
    "momentum": 1000.0,
}
```

Add to the env override loop (around line 32):

```python
for _system_key, _env_name in {
    "paper": "BOT_PAPER_INITIAL_CAPITAL",
    "agent": "BOT_AGENT_INITIAL_CAPITAL",
    "pump": "BOT_PUMP_INITIAL_CAPITAL",
    "scalping": "BOT_SCALPING_INITIAL_CAPITAL",
    "momentum": "BOT_MOMENTUM_INITIAL_CAPITAL",
}.items():
```

After the existing `SCALPING_INITIAL_CAPITAL` line (find it via grep), add:

```python
MOMENTUM_INITIAL_CAPITAL = _resolved_initial_capitals["momentum"]
```

- [ ] **Step 2: Add MOMENTUM_TRADER_ENABLED and MOMENTUM_SYMBOLS in config.py**

After the `AGENT_TRADER_ENABLED` line (around line 171):

```python
MOMENTUM_TRADER_ENABLED = os.environ.get("MOMENTUM_TRADER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
MOMENTUM_SYMBOLS = [s.strip() for s in os.environ.get("MOMENTUM_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
MOMENTUM_MAX_POSITIONS = 1
```

- [ ] **Step 3: Add MOMENTUM_STATE_FILE in runtime_config.py**

After the `SCALPING_V2_1B_STATE_FILE` line (line 135):

```python
MOMENTUM_STATE_FILE = runtime_path("momentum_state.json")
```

- [ ] **Step 4: Add momentum to runtime_metadata in runtime_config.py**

In the `runtime_metadata()` function, add `"momentum"` to the `initial_capitals` dict (around line 165):

```python
"initial_capitals": {
    "paper": round(float(PAPER_INITIAL_CAPITAL), 2),
    "agent": round(float(AGENT_INITIAL_CAPITAL), 2),
    "pump": round(float(PUMP_INITIAL_CAPITAL), 2),
    "scalping": round(float(SCALPING_INITIAL_CAPITAL), 2),
    "momentum": round(float(MOMENTUM_INITIAL_CAPITAL), 2),
},
```

Add the import of `MOMENTUM_INITIAL_CAPITAL` at the top of `runtime_config.py`:

```python
from config import (
    AGENT_INITIAL_CAPITAL,
    MOMENTUM_INITIAL_CAPITAL,
    PAPER_INITIAL_CAPITAL,
    PORTFOLIO_INITIAL_CAPITAL,
    PUMP_INITIAL_CAPITAL,
    SCALPING_INITIAL_CAPITAL,
)
```

- [ ] **Step 5: Verify config loads without errors**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python -c "from config import MOMENTUM_INITIAL_CAPITAL, MOMENTUM_TRADER_ENABLED, MOMENTUM_SYMBOLS; print(f'Capital={MOMENTUM_INITIAL_CAPITAL}, Enabled={MOMENTUM_TRADER_ENABLED}, Symbols={MOMENTUM_SYMBOLS}')"`

Expected: `Capital=1000.0, Enabled=False, Symbols=['BTCUSDT', 'ETHUSDT']`

Run: `python -c "from runtime_config import MOMENTUM_STATE_FILE; print(MOMENTUM_STATE_FILE)"`

Expected: path ending in `runtime/baseline/momentum_state.json`

- [ ] **Step 6: Commit**

```bash
git add config.py runtime_config.py
git commit -m "feat: add momentum paper trading config (capital, enabled, symbols, state file)"
```

---

### Task 2: Database Schema and Insert Functions

**Files:**
- Modify: `database.py:15-27` (VALID_TABLES)
- Modify: `database.py:48-319` (init_db schema)
- Modify: `database.py` (new insert functions, after existing inserts)
- Test: `tests/test_momentum_integration.py`

- [ ] **Step 1: Write failing test for momentum trade insert**

Create `tests/test_momentum_integration.py`:

```python
"""Integration tests for momentum paper trading DB + circuit breaker."""
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def tmp_db(monkeypatch):
    """Create a temp DB file and point database.py at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("database.DB_FILE", path)
    import database as db
    db.init_db()
    yield path
    os.unlink(path)


class TestMomentumTradeInsert:
    def test_insert_and_retrieve(self, tmp_db):
        import database as db

        trade = {
            "timestamp": "2026-04-15T12:00:00",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "regime": "TRENDING",
            "entry_price": 85000.0,
            "exit_price": 86000.0,
            "sl_price": 84500.0,
            "tp1_price": 85800.0,
            "tp2_price": 86500.0,
            "pnl_pct": 1.18,
            "pnl_usd": 11.80,
            "exit_reason": "tp1_hit",
            "capital_after": 1011.80,
            "param_version": "momentum-pullback-v1.1",
            "duration_candles": 8,
            "mfe_pct": 1.5,
            "mae_pct": -0.3,
        }
        db.insert_momentum_trade(trade)

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_trades").fetchone()
        conn.close()

        assert row is not None
        assert row["symbol"] == "BTCUSDT"
        assert row["direction"] == "LONG"
        assert row["pnl_pct"] == 1.18
        assert row["exit_reason"] == "tp1_hit"
        assert row["param_version"] == "momentum-pullback-v1.1"


class TestMomentumDecisionInsert:
    def test_insert_and_retrieve(self, tmp_db):
        import database as db

        decision = {
            "timestamp": "2026-04-15T12:00:00",
            "cycle_id": "20260415_120000",
            "symbol": "BTCUSDT",
            "regime": "TRENDING",
            "outcome": "trade",
            "direction": "LONG",
            "blocked_by": "none",
            "ema_fast_value": 85100.0,
            "ema_slow_value": 84800.0,
            "retracement_pct": 42.5,
            "param_version": "momentum-pullback-v1.1",
        }
        db.insert_momentum_decision(decision)

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM momentum_decisions").fetchone()
        conn.close()

        assert row is not None
        assert row["outcome"] == "trade"
        assert row["blocked_by"] == "none"
        assert row["retracement_pct"] == 42.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_momentum_integration.py -v`

Expected: FAIL — `momentum_trades` table doesn't exist, `insert_momentum_trade` not defined.

- [ ] **Step 3: Add momentum tables to database.py init_db**

Add to `VALID_TABLES`:

```python
VALID_TABLES = frozenset({
    "paper_trades",
    "agent_trades",
    "pump_trades",
    "scalping_trades",
    "momentum_trades",
    "momentum_decisions",
    "analysis_log",
    "alerts",
    "scalping_decisions",
    "scalping_audit_log",
    "scalping_outcome_labels",
    "ai_decisions",
    "market_microstructure",
})
```

Add the following SQL to `init_db()`, before the closing `""")` or in a separate `executescript` call after the existing one:

```python
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS momentum_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            symbol              TEXT,
            direction           TEXT,
            regime              TEXT,
            entry_price         REAL,
            exit_price          REAL,
            sl_price            REAL,
            tp1_price           REAL,
            tp2_price           REAL,
            position_size_usd   REAL,
            pnl_pct             REAL,
            pnl_usd             REAL,
            exit_reason         TEXT,
            capital_after       REAL,
            param_version       TEXT,
            duration_candles    INTEGER,
            mfe_pct             REAL DEFAULT 0,
            mae_pct             REAL DEFAULT 0,
            session_bucket      TEXT DEFAULT '',
            asset_bucket        TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS momentum_decisions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT,
            cycle_id            TEXT,
            symbol              TEXT,
            regime              TEXT,
            outcome             TEXT,
            direction           TEXT,
            blocked_by          TEXT DEFAULT 'none',
            ema_fast_value      REAL DEFAULT 0,
            ema_slow_value      REAL DEFAULT 0,
            ema_gap_pct         REAL DEFAULT 0,
            retracement_pct     REAL DEFAULT 0,
            impulse_start_price REAL DEFAULT 0,
            impulse_end_price   REAL DEFAULT 0,
            pullback_rejection  TEXT DEFAULT '',
            param_version       TEXT DEFAULT '',
            session_bucket      TEXT DEFAULT '',
            asset_bucket        TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_momentum_trades_ts ON momentum_trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_momentum_trades_symbol ON momentum_trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_ts ON momentum_decisions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_cycle ON momentum_decisions(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_momentum_decisions_outcome ON momentum_decisions(outcome);
    """)
```

- [ ] **Step 4: Add insert_momentum_trade function to database.py**

After the existing `insert_pump_trade` function:

```python
def insert_momentum_trade(trade: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO momentum_trades (
                timestamp, symbol, direction, regime,
                entry_price, exit_price, sl_price, tp1_price, tp2_price,
                position_size_usd, pnl_pct, pnl_usd,
                exit_reason, capital_after, param_version,
                duration_candles, mfe_pct, mae_pct,
                session_bucket, asset_bucket
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade["timestamp"],
            trade["symbol"],
            trade["direction"],
            trade.get("regime", ""),
            trade["entry_price"],
            trade.get("exit_price"),
            trade.get("sl_price"),
            trade.get("tp1_price"),
            trade.get("tp2_price"),
            trade.get("position_size_usd"),
            trade.get("pnl_pct"),
            round(trade.get("pnl_usd", 0), 2),
            trade.get("exit_reason", "open"),
            round(trade.get("capital_after", 0), 2),
            trade.get("param_version", "momentum-pullback-v1.1"),
            trade.get("duration_candles"),
            trade.get("mfe_pct", 0),
            trade.get("mae_pct", 0),
            trade.get("session_bucket", ""),
            trade.get("asset_bucket", ""),
        ))
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 5: Add insert_momentum_decision function to database.py**

Right after `insert_momentum_trade`:

```python
def insert_momentum_decision(decision: dict):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO momentum_decisions (
                timestamp, cycle_id, symbol, regime,
                outcome, direction, blocked_by,
                ema_fast_value, ema_slow_value, ema_gap_pct,
                retracement_pct, impulse_start_price, impulse_end_price,
                pullback_rejection, param_version,
                session_bucket, asset_bucket
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision["timestamp"],
            decision.get("cycle_id", ""),
            decision["symbol"],
            decision.get("regime", ""),
            decision["outcome"],
            decision.get("direction", ""),
            decision.get("blocked_by", "none"),
            decision.get("ema_fast_value", 0),
            decision.get("ema_slow_value", 0),
            decision.get("ema_gap_pct", 0),
            decision.get("retracement_pct", 0),
            decision.get("impulse_start_price", 0),
            decision.get("impulse_end_price", 0),
            decision.get("pullback_rejection", ""),
            decision.get("param_version", "momentum-pullback-v1.1"),
            decision.get("session_bucket", ""),
            decision.get("asset_bucket", ""),
        ))
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum_integration.py -v`

Expected: 2 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_momentum_integration.py
git commit -m "feat: add momentum_trades and momentum_decisions tables to bot.db"
```

---

### Task 3: Paper Executor — State Management

**Files:**
- Create: `momentum/paper_executor.py`
- Create: `tests/test_momentum_paper_executor.py`

- [ ] **Step 1: Write failing tests for state management**

Create `tests/test_momentum_paper_executor.py`:

```python
"""Tests for momentum paper executor."""
import json
import os
import tempfile

import pytest


@pytest.fixture
def state_file(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    # Remove so load_state creates fresh
    os.unlink(path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_STATE_FILE", path)
    monkeypatch.setattr("momentum.paper_executor.MOMENTUM_INITIAL_CAPITAL", 1000.0)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestStateManagement:
    def test_load_fresh_state(self, state_file):
        from momentum.paper_executor import load_state

        state = load_state()
        assert state["capital"] == 1000.0
        assert state["positions"] == {}
        assert state["cooldowns"] == {}
        assert state["total_trades"] == 0
        assert state["wins"] == 0
        assert state["losses"] == 0
        assert state["total_pnl_usd"] == 0.0
        assert state["hwm"] == 1000.0

    def test_save_and_reload(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        state["capital"] = 1050.0
        state["hwm"] = 1050.0
        state["total_trades"] = 3
        save_state(state)

        reloaded = load_state()
        assert reloaded["capital"] == 1050.0
        assert reloaded["hwm"] == 1050.0
        assert reloaded["total_trades"] == 3

    def test_save_is_atomic(self, state_file):
        from momentum.paper_executor import load_state, save_state

        state = load_state()
        save_state(state)

        # File exists and is valid JSON
        with open(state_file) as f:
            data = json.load(f)
        assert data["capital"] == 1000.0

    def test_get_status_no_positions(self, state_file):
        from momentum.paper_executor import load_state, get_momentum_status

        load_state()  # ensure state file exists
        status = get_momentum_status()
        assert "MOMENTUM" in status
        assert "$1000.00" in status
        assert "0W" in status
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum_paper_executor.py -v`

Expected: FAIL — `momentum.paper_executor` module doesn't exist.

- [ ] **Step 3: Create momentum/paper_executor.py with state management**

```python
"""Momentum Pullback paper trading executor.

Wraps the frozen v1.1 signal evaluator with capital management,
position tracking, and bot.db persistence. State persisted in
JSON file between cycles (same pattern as scalping_trader.py).

Governance: Paper Readiness Framework
  docs/superpowers/specs/2026-04-15-paper-readiness-framework.md
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone

from config import MOMENTUM_INITIAL_CAPITAL

logger = logging.getLogger("momentum.paper")

_state_lock = threading.Lock()

# Imported at module level but overridable in tests via monkeypatch
from runtime_config import MOMENTUM_STATE_FILE


def _default_state() -> dict:
    return {
        "capital": float(MOMENTUM_INITIAL_CAPITAL),
        "positions": {},
        "cooldowns": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_usd": 0.0,
        "hwm": float(MOMENTUM_INITIAL_CAPITAL),
    }


def load_state() -> dict:
    with _state_lock:
        if not os.path.exists(MOMENTUM_STATE_FILE):
            return _default_state()
        try:
            with open(MOMENTUM_STATE_FILE, "r") as f:
                state = json.load(f)
            # Ensure hwm exists (migration from older state files)
            if "hwm" not in state:
                state["hwm"] = max(state.get("capital", MOMENTUM_INITIAL_CAPITAL),
                                   MOMENTUM_INITIAL_CAPITAL)
            return state
        except (json.JSONDecodeError, ValueError):
            return _default_state()


def save_state(state: dict) -> None:
    # Update HWM before saving
    state["hwm"] = max(state.get("hwm", state["capital"]), state["capital"])
    with _state_lock:
        dir_name = os.path.dirname(MOMENTUM_STATE_FILE) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, suffix=".tmp",
        ) as f:
            json.dump(state, f, indent=2)
            tmp = f.name
        os.replace(tmp, MOMENTUM_STATE_FILE)


def get_momentum_status() -> str:
    state = load_state()
    cap = state["capital"]
    w = state["wins"]
    l = state["losses"]
    total = state["total_trades"]
    pnl = state["total_pnl_usd"]
    wr = (w / total * 100) if total > 0 else 0
    positions = state.get("positions", {})
    n_pos = len(positions)
    hwm = state.get("hwm", cap)
    dd_pct = ((hwm - cap) / hwm * 100) if hwm > 0 else 0

    lines = [
        f"MOMENTUM PULLBACK | ${cap:.2f} | {total}t {w}W/{l}L WR={wr:.1f}% | PnL ${pnl:+.2f}",
        f"  HWM=${hwm:.2f} DD={dd_pct:.1f}% | Pos={n_pos}",
    ]
    if positions:
        for sym, pos in positions.items():
            lines.append(
                f"  {sym} {pos['direction']} @ {pos['entry_price']:.2f}"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum_paper_executor.py -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum/paper_executor.py tests/test_momentum_paper_executor.py
git commit -m "feat: momentum paper executor — state management (load, save, status)"
```

---

### Task 4: Paper Executor — Signal Evaluation and Entry

**Files:**
- Modify: `momentum/paper_executor.py`
- Modify: `tests/test_momentum_paper_executor.py`

- [ ] **Step 1: Write failing tests for signal evaluation and position entry**

Add to `tests/test_momentum_paper_executor.py`:

```python
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pandas as pd
import numpy as np

from momentum.config import MomentumConfig, MomentumOutcome, MomentumDirection
from momentum.momentum_trader import MomentumSignal


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("database.DB_FILE", path)
    import database as db
    db.init_db()
    yield path
    os.unlink(path)


def _make_trade_signal(symbol="BTCUSDT", direction="LONG",
                       entry=85000.0, sl=84500.0,
                       tp1=85800.0, tp2=86500.0):
    return MomentumSignal(
        outcome=MomentumOutcome.TRADE,
        direction=MomentumDirection(direction),
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
        ema_fast_value=85100.0,
        ema_slow_value=84800.0,
        ema_gap_pct=0.35,
        retracement_pct=42.5,
        impulse_start_price=84000.0,
        impulse_end_price=86000.0,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


def _make_reject_signal(symbol="BTCUSDT", outcome=MomentumOutcome.NO_TREND):
    return MomentumSignal(
        outcome=outcome,
        direction=MomentumDirection.NEUTRAL,
        symbol=symbol,
        regime="TRENDING",
        timestamp="2026-04-15T12:00:00",
        param_version="momentum-pullback-v1.1",
    )


class TestOpenPosition:
    def test_opens_position_on_trade_signal(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        msgs = open_position(state, signal, "20260415_120000")
        save_state(state)

        assert "BTCUSDT" in state["positions"]
        pos = state["positions"]["BTCUSDT"]
        assert pos["direction"] == "LONG"
        assert pos["entry_price"] == 85000.0
        assert pos["sl_price"] == 84500.0
        assert pos["position_size_usd"] > 0
        assert len(msgs) > 0

    def test_respects_max_positions(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        # Fill the only slot
        signal1 = _make_trade_signal(symbol="BTCUSDT")
        open_position(state, signal1, "cycle1")

        # Try to open second — should be blocked
        signal2 = _make_trade_signal(symbol="ETHUSDT", entry=3200.0,
                                     sl=3150.0, tp1=3280.0, tp2=3350.0)
        msgs = open_position(state, signal2, "cycle1")
        save_state(state)

        assert "ETHUSDT" not in state["positions"]
        assert len(state["positions"]) == 1

    def test_skips_duplicate_symbol(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")
        msgs = open_position(state, signal, "cycle2")
        save_state(state)

        assert len(state["positions"]) == 1

    def test_position_size_within_capital(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, open_position

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        pos = state["positions"]["BTCUSDT"]
        assert pos["position_size_usd"] <= state["capital"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum_paper_executor.py::TestOpenPosition -v`

Expected: FAIL — `open_position` not defined.

- [ ] **Step 3: Implement open_position in paper_executor.py**

Add to `momentum/paper_executor.py`:

```python
from config import MOMENTUM_MAX_POSITIONS
import database as db


def _calculate_position_size(capital: float, entry: float, sl: float) -> float:
    """Size position so that a full SL hit loses ~2% of capital."""
    sl_distance_pct = abs(entry - sl) / entry * 100
    if sl_distance_pct <= 0:
        return 0.0
    risk_amount = capital * 0.02  # 2% risk per trade
    position_size = risk_amount / (sl_distance_pct / 100)
    # Cap at 100% of capital
    return min(position_size, capital)


def open_position(state: dict, signal: MomentumSignal, cycle_id: str) -> list[str]:
    """Open a paper position from a TRADE signal. Returns Telegram messages."""
    msgs: list[str] = []
    symbol = signal.symbol

    # Guard: already in position for this symbol
    if symbol in state["positions"]:
        return msgs

    # Guard: max positions reached
    if len(state["positions"]) >= MOMENTUM_MAX_POSITIONS:
        return msgs

    # Guard: in cooldown
    if symbol in state.get("cooldowns", {}):
        return msgs

    entry = signal.entry_price
    sl = signal.sl_price
    tp1 = signal.tp1_price
    tp2 = signal.tp2_price
    direction = signal.direction.value

    size = _calculate_position_size(state["capital"], entry, sl)
    if size <= 0:
        return msgs

    state["positions"][symbol] = {
        "direction": direction,
        "entry_price": entry,
        "sl_price": sl,
        "tp1_price": tp1,
        "tp2_price": tp2,
        "position_size_usd": round(size, 2),
        "open_time": signal.timestamp,
        "regime": signal.regime,
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "candles_elapsed": 0,
    }

    # Log decision as trade
    try:
        _log_decision(signal, cycle_id, blocked_by="none")
    except Exception as e:
        logger.warning("Failed to log momentum decision: %s", e)

    sl_dist = abs(entry - sl) / entry * 100
    msg = (
        f"{symbol} {direction} @ {entry:.2f} | "
        f"SL={sl:.2f} ({sl_dist:.2f}%) TP1={tp1:.2f} TP2={tp2:.2f} | "
        f"Size=${size:.2f}"
    )
    msgs.append(msg)
    logger.info("OPEN %s", msg)

    return msgs


def _log_decision(signal: MomentumSignal, cycle_id: str, blocked_by: str = "none"):
    """Log a momentum decision to bot.db."""
    try:
        from audit_helpers import get_session_bucket, get_asset_bucket
        ts_dt = datetime.fromisoformat(signal.timestamp) if signal.timestamp else None
        session = get_session_bucket(ts_dt) if ts_dt else ""
        asset = get_asset_bucket(signal.symbol)
    except Exception:
        session = ""
        asset = ""

    db.insert_momentum_decision({
        "timestamp": signal.timestamp or "",
        "cycle_id": cycle_id,
        "symbol": signal.symbol,
        "regime": signal.regime,
        "outcome": signal.outcome.value,
        "direction": signal.direction.value,
        "blocked_by": blocked_by,
        "ema_fast_value": signal.ema_fast_value,
        "ema_slow_value": signal.ema_slow_value,
        "ema_gap_pct": signal.ema_gap_pct,
        "retracement_pct": signal.retracement_pct,
        "impulse_start_price": signal.impulse_start_price,
        "impulse_end_price": signal.impulse_end_price,
        "pullback_rejection": (
            signal.pullback_rejection.value if signal.pullback_rejection else ""
        ),
        "param_version": signal.param_version,
        "session_bucket": session,
        "asset_bucket": asset,
    })
```

- [ ] **Step 4: Add missing import at top of paper_executor.py**

Make sure these imports are at the top:

```python
from momentum.momentum_trader import MomentumSignal
from momentum.config import MomentumOutcome
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum_paper_executor.py -v`

Expected: all tests PASS (both state management and open position).

- [ ] **Step 6: Commit**

```bash
git add momentum/paper_executor.py tests/test_momentum_paper_executor.py
git commit -m "feat: momentum paper executor — open_position with sizing and decision logging"
```

---

### Task 5: Paper Executor — Position Management and Exits

**Files:**
- Modify: `momentum/paper_executor.py`
- Modify: `tests/test_momentum_paper_executor.py`

- [ ] **Step 1: Write failing tests for position exits**

Add to `tests/test_momentum_paper_executor.py`:

```python
class TestClosePosition:
    def test_sl_hit_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()  # LONG @ 85000, SL 84500
        open_position(state, signal, "cycle1")

        # Simulate candle that hits SL
        candle = {"high": 85100.0, "low": 84400.0, "close": 84450.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["losses"] == 1
        assert state["total_trades"] == 1
        assert state["capital"] < 1000.0
        assert len(msgs) > 0

    def test_tp1_hit_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()  # LONG @ 85000, TP1 85800
        open_position(state, signal, "cycle1")

        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["wins"] == 1
        assert state["capital"] > 1000.0

    def test_timeout_closes_position(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        # Simulate 16 candles elapsed (timeout)
        state["positions"]["BTCUSDT"]["candles_elapsed"] = 16

        candle = {"high": 85100.0, "low": 84900.0, "close": 85050.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" not in state["positions"]
        assert state["total_trades"] == 1

    def test_no_exit_when_no_hit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        # Normal candle, no SL/TP hit
        candle = {"high": 85200.0, "low": 84900.0, "close": 85100.0}
        msgs = manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert "BTCUSDT" in state["positions"]
        assert state["total_trades"] == 0
        # Candle counter should increment
        assert state["positions"]["BTCUSDT"]["candles_elapsed"] == 1

    def test_hwm_updates_on_profit(self, state_file, tmp_db):
        from momentum.paper_executor import load_state, save_state, open_position, manage_positions

        state = load_state()
        signal = _make_trade_signal()
        open_position(state, signal, "cycle1")

        candle = {"high": 85900.0, "low": 85000.0, "close": 85850.0}
        manage_positions(state, {"BTCUSDT": candle})
        save_state(state)

        assert state["hwm"] >= state["capital"]
        assert state["hwm"] > 1000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_momentum_paper_executor.py::TestClosePosition -v`

Expected: FAIL — `manage_positions` not defined.

- [ ] **Step 3: Implement manage_positions in paper_executor.py**

Add to `momentum/paper_executor.py`:

```python
from momentum.research_runner import check_exit
from momentum.config import MomentumConfig


def manage_positions(state: dict, candles: dict[str, dict]) -> list[str]:
    """Check all open positions against current candles. Returns messages."""
    msgs: list[str] = []
    config = MomentumConfig()
    closed_symbols: list[str] = []

    for symbol, pos in list(state["positions"].items()):
        candle = candles.get(symbol)
        if candle is None:
            continue

        result = check_exit(
            direction=pos["direction"],
            entry_price=pos["entry_price"],
            sl_price=pos["sl_price"],
            tp1_price=pos["tp1_price"],
            tp2_price=pos["tp2_price"],
            candle_high=candle["high"],
            candle_low=candle["low"],
            candle_close=candle["close"],
            current_mfe=pos.get("mfe_pct", 0),
            current_mae=pos.get("mae_pct", 0),
            duration_candles=pos.get("candles_elapsed", 0),
            timeout_candles=config.timeout_candles,
            breakeven_trigger_pct=config.breakeven_trigger_pct,
        )

        if result["closed"]:
            pnl_pct = result["pnl_pct"]
            pnl_usd = pos["position_size_usd"] * pnl_pct / 100
            state["capital"] += pnl_usd
            state["total_pnl_usd"] += pnl_usd
            state["total_trades"] += 1

            if pnl_pct > 0:
                state["wins"] += 1
            else:
                state["losses"] += 1
                # Cooldown after loss: skip 2 candles (30 min)
                state.setdefault("cooldowns", {})[symbol] = 2

            # Log trade to bot.db
            try:
                db.insert_momentum_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "direction": pos["direction"],
                    "regime": pos.get("regime", ""),
                    "entry_price": pos["entry_price"],
                    "exit_price": result["exit_price"],
                    "sl_price": pos["sl_price"],
                    "tp1_price": pos["tp1_price"],
                    "tp2_price": pos["tp2_price"],
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 2),
                    "exit_reason": result["exit_reason"],
                    "capital_after": round(state["capital"], 2),
                    "param_version": "momentum-pullback-v1.1",
                    "duration_candles": pos.get("candles_elapsed", 0),
                    "mfe_pct": round(result["mfe_pct"], 4),
                    "mae_pct": round(result["mae_pct"], 4),
                })
            except Exception as e:
                logger.warning("Failed to log momentum trade: %s", e)

            msg = (
                f"CLOSE {symbol} {pos['direction']} | "
                f"{result['exit_reason']} @ {result['exit_price']:.2f} | "
                f"PnL {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | "
                f"Cap ${state['capital']:.2f}"
            )
            msgs.append(msg)
            logger.info(msg)
            closed_symbols.append(symbol)
        else:
            # Update MFE/MAE and candle counter
            pos["mfe_pct"] = result["mfe_pct"]
            pos["mae_pct"] = result["mae_pct"]
            pos["candles_elapsed"] = pos.get("candles_elapsed", 0) + 1

    for sym in closed_symbols:
        del state["positions"][sym]

    return msgs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum_paper_executor.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum/paper_executor.py tests/test_momentum_paper_executor.py
git commit -m "feat: momentum paper executor — manage_positions with exits and trade logging"
```

---

### Task 6: Paper Executor — Main Cycle Orchestrator

**Files:**
- Modify: `momentum/paper_executor.py`
- Modify: `tests/test_momentum_paper_executor.py`

- [ ] **Step 1: Write failing test for process_momentum_cycle**

Add to `tests/test_momentum_paper_executor.py`:

```python
class TestProcessCycle:
    def test_logs_reject_decision(self, state_file, tmp_db):
        from momentum.paper_executor import process_momentum_cycle

        def mock_candle_fn(symbol, interval, limit):
            # Return a DataFrame with enough candles but no valid signal
            n = 100
            data = {
                "time": pd.date_range("2026-01-01", periods=n, freq="15min"),
                "open": np.full(n, 85000.0),
                "high": np.full(n, 85100.0),
                "low": np.full(n, 84900.0),
                "close": np.full(n, 85000.0),
                "volume": np.full(n, 100.0),
            }
            return pd.DataFrame(data)

        def mock_regime_fn(symbol):
            return {"regime_label": "TRENDING"}

        msgs = process_momentum_cycle(
            symbols=["BTCUSDT"],
            open_new=True,
            candle_fn=mock_candle_fn,
            regime_fn=mock_regime_fn,
        )

        # Should have logged a decision (rejection) to the DB
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM momentum_decisions").fetchall()
        conn.close()
        assert len(rows) >= 1
        # The flat candles should produce a reject (no trend)
        assert rows[0]["outcome"] != "trade" or rows[0]["blocked_by"] != "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_momentum_paper_executor.py::TestProcessCycle -v`

Expected: FAIL — `process_momentum_cycle` not defined.

- [ ] **Step 3: Implement process_momentum_cycle**

Add to `momentum/paper_executor.py`:

```python
from typing import Callable, Optional


def _tick_cooldowns(state: dict) -> None:
    """Decrement cooldown counters. Remove expired ones."""
    expired = []
    for symbol, remaining in state.get("cooldowns", {}).items():
        remaining -= 1
        if remaining <= 0:
            expired.append(symbol)
        else:
            state["cooldowns"][symbol] = remaining
    for sym in expired:
        del state["cooldowns"][sym]


def process_momentum_cycle(
    symbols: list[str],
    open_new: bool = True,
    *,
    candle_fn: Optional[Callable] = None,
    regime_fn: Optional[Callable] = None,
) -> list[str]:
    """One full momentum cycle: evaluate signals + manage positions.

    Args:
        symbols: Symbols to evaluate.
        open_new: If False, only manage existing positions (circuit breaker).
        candle_fn: Override for testing. (symbol, interval, limit) -> DataFrame.
        regime_fn: Override for testing. (symbol) -> dict with regime_label.

    Returns:
        List of Telegram-ready messages.
    """
    if candle_fn is None:
        from market import get_candles
        candle_fn = get_candles
    if regime_fn is None:
        from htf import get_htf_regime
        regime_fn = regime_fn_default

    state = load_state()
    msgs: list[str] = []
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candle_cache: dict[str, dict] = {}

    _tick_cooldowns(state)

    # Phase 1: evaluate signals per symbol
    for symbol in symbols:
        candles = candle_fn(symbol, "15m", 100)
        if candles is None or len(candles) == 0:
            continue

        last = candles.iloc[-1]
        candle_cache[symbol] = {
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
        }

        regime_data = regime_fn(symbol)
        regime = (
            regime_data.get("regime_label", "UNKNOWN")
            if isinstance(regime_data, dict)
            else str(regime_data)
        )

        signal = evaluate_momentum_pullback(
            candles, regime, MomentumConfig(),
            symbol=symbol,
            timestamp=str(last.get("time", "")),
        )

        if signal.outcome == MomentumOutcome.TRADE and open_new:
            entry_msgs = open_position(state, signal, cycle_id)
            msgs.extend(entry_msgs)
            if not entry_msgs:
                # Blocked by max positions or cooldown
                blocked = "max_positions" if len(state["positions"]) >= MOMENTUM_MAX_POSITIONS else "cooldown"
                _log_decision(signal, cycle_id, blocked_by=blocked)
        else:
            # Log rejection decision
            blocked = signal.outcome.value if signal.outcome != MomentumOutcome.TRADE else "suspended"
            _log_decision(signal, cycle_id, blocked_by=blocked)

    # Phase 2: manage existing positions
    exit_msgs = manage_positions(state, candle_cache)
    msgs.extend(exit_msgs)

    save_state(state)
    return msgs


def regime_fn_default(symbol: str) -> dict:
    from htf import get_htf_regime
    return get_htf_regime(symbol)
```

Add the import for `evaluate_momentum_pullback` at the top if not already present:

```python
from momentum.momentum_trader import MomentumSignal, evaluate_momentum_pullback
from momentum.config import MomentumConfig, MomentumOutcome
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_momentum_paper_executor.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add momentum/paper_executor.py tests/test_momentum_paper_executor.py
git commit -m "feat: momentum paper executor — process_momentum_cycle orchestrator"
```

---

### Task 7: Circuit Breaker and Main Loop Integration

**Files:**
- Modify: `daily_report.py:336-418` (circuit breaker table_map)
- Modify: `main.py:1-28` (imports)
- Modify: `main.py:291-311` (add momentum block after scalping)
- Modify: `tests/test_momentum_integration.py`

- [ ] **Step 1: Write failing test for circuit breaker support**

Add to `tests/test_momentum_integration.py`:

```python
class TestCircuitBreakerMomentum:
    def test_momentum_in_table_map(self):
        """Circuit breaker functions should recognize 'momentum' system."""
        from daily_report import check_circuit_breaker
        # Should not crash — just return False (no trades today)
        result = check_circuit_breaker("momentum")
        assert result is False or result is True  # no crash

    def test_momentum_not_unknown(self):
        """'momentum' should be a known system, not silently ignored."""
        from daily_report import check_circuit_breaker
        # If momentum is not in table_map, it returns False silently
        # We want it to actually check the table
        # This test verifies the table_map contains momentum
        import daily_report
        # Access the internal table_map via source inspection
        import inspect
        source = inspect.getsource(daily_report.check_circuit_breaker)
        assert "momentum" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_momentum_integration.py::TestCircuitBreakerMomentum -v`

Expected: FAIL on the second test (momentum not in source).

- [ ] **Step 3: Add momentum to circuit breaker in daily_report.py**

In `check_circuit_breaker` (line 338) and `enforce_circuit_breaker` (line 379), add `"momentum"` to the `table_map`:

```python
    table_map = {
        "agent": "agent_trades",
        "pump": "pump_trades",
        "paper": "paper_trades",
        "scalping": "scalping_trades",
        "momentum": "momentum_trades",
    }
```

Also in `enforce_circuit_breaker`, add the initial capital reference (around line 397):

```python
    initial_capitals = {
        "paper": PAPER_INITIAL_CAPITAL,
        "agent": AGENT_INITIAL_CAPITAL,
        "pump": PUMP_INITIAL_CAPITAL,
        "scalping": SCALPING_INITIAL_CAPITAL,
        "momentum": MOMENTUM_INITIAL_CAPITAL,
    }
```

Add the import at the top of `daily_report.py`:

```python
from config import (
    ...existing imports...,
    MOMENTUM_INITIAL_CAPITAL,
)
```

And add the state file to `_get_current_capital`:

```python
    state_files = {
        "paper": PAPER_STATE_FILE,
        "agent": AGENT_STATE_FILE,
        "scalping": SCALPING_STATE_FILE,
        "momentum": MOMENTUM_STATE_FILE,
    }
```

With the import:

```python
from runtime_config import ..., MOMENTUM_STATE_FILE
```

- [ ] **Step 4: Run circuit breaker tests to verify they pass**

Run: `python -m pytest tests/test_momentum_integration.py::TestCircuitBreakerMomentum -v`

Expected: PASS.

- [ ] **Step 5: Add momentum block to main.py**

Add import at top of `main.py` (after the scalping imports):

```python
from momentum.paper_executor import process_momentum_cycle, get_momentum_status
```

Add the following block after the scalping V2.1b block (after line 311) and before the outcome labeler (line 313):

```python
    # Momentum Pullback Strategy
    if cfg.MOMENTUM_TRADER_ENABLED:
        print("\n========================================")
        print("MOMENTUM PULLBACK STRATEGY\n")

        try:
            try:
                momentum_suspended = enforce_circuit_breaker("momentum") or is_paused()
            except Exception as e:
                print(f"  [ERRO] Falha ao verificar circuit breaker momentum: {e}")
                momentum_suspended = True
            if momentum_suspended:
                print("  Circuit breaker ativo ou bot pausado - gerenciando posicoes")
            momentum_msgs = process_momentum_cycle(
                cfg.MOMENTUM_SYMBOLS,
                open_new=not momentum_suspended,
            )
            for msg in momentum_msgs:
                print(f"  {msg}")
                send_telegram_message(f"\U0001f4c8 <b>[MOMENTUM]</b> {msg}")
            print(f"\n  {get_momentum_status()}")
        except Exception as e:
            print(f"  [ERRO] Falha no momentum pullback: {e}")
    else:
        print("\n========================================")
        print("MOMENTUM PULLBACK: DESABILITADO (MOMENTUM_TRADER_ENABLED=false)\n")
```

- [ ] **Step 6: Verify main.py imports cleanly**

Run: `python -c "import main; print('OK')"`

Expected: `OK` (may print warnings about missing API keys, but no ImportError).

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/test_momentum_paper_executor.py tests/test_momentum_integration.py -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add daily_report.py main.py tests/test_momentum_integration.py
git commit -m "feat: integrate momentum paper trading into main loop with circuit breaker"
```

---

### Task 8: Final Verification and Cleanup

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ --tb=short -q`

Expected: all tests pass, no regressions.

- [ ] **Step 2: Verify momentum is disabled by default**

Run: `python -c "from config import MOMENTUM_TRADER_ENABLED; print(f'Enabled={MOMENTUM_TRADER_ENABLED}')"`

Expected: `Enabled=False`

This confirms momentum won't activate unless explicitly enabled via `MOMENTUM_TRADER_ENABLED=true` in `.env`.

- [ ] **Step 3: Verify health check passes**

Run: `python -c "import main; import supervisor; import dashboard_server; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit if any cleanup was needed**

Only if fixes were made in previous steps:

```bash
git add -A
git commit -m "fix: cleanup from momentum integration verification"
```

---

## Post-Implementation Notes

**What this plan does NOT do (by design):**
- Does not enable momentum trading (stays `MOMENTUM_TRADER_ENABLED=false`)
- Does not start paper trading (requires smoke test + operator approval per governance framework)
- Does not modify any momentum strategy parameters (v1.1 frozen)
- Does not add dashboard routes for momentum (can be done later, not a paper blocker)

**To activate paper trading (when ready):**
1. Add `MOMENTUM_TRADER_ENABLED=true` to `.env`
2. `sudo systemctl restart cryptobot`
3. Run smoke test for 24-48h
4. Verify smoke test checklist from the Paper Readiness Framework
5. Get operator approval to start official paper
