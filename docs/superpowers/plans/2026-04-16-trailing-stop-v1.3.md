# Trailing Stop v1.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fixed percentage trailing stop to momentum pullback, capturing profit when trades move in our favor.

**Architecture:** Extend `check_exit()` pure function with 3 new keyword args (default 0.0 = disabled). Trailing SL trails `candle_high * (1 - pct)` for LONG, activates after MFE threshold. State propagated via `new_trailing_sl` field in return dict, persisted in paper executor JSON and research DB.

**Tech Stack:** Python 3.13, SQLite, pytest, dataclasses

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `momentum/config.py` | Modify | Add `trailing_pct`, `trailing_trigger_pct` to MomentumConfig |
| `momentum/research_runner.py` | Modify | Trailing logic in `check_exit()`, propagate in `_manage_positions()` |
| `momentum/research_db.py` | Modify | Add `trailing_sl_price` column to DDL + update function |
| `momentum/paper_executor.py` | Modify | Pass/receive trailing state in `manage_positions()` |
| `scripts/tuning_matrix.py` | Modify | Add D1-D4 trailing variants |
| `tests/test_check_exit_trailing.py` | Create | Unit tests for trailing logic in `check_exit()` |

---

### Task 1: Add config parameters

**Files:**
- Modify: `momentum/config.py:67-72`

- [ ] **Step 1: Add trailing params to MomentumConfig**

```python
# In momentum/config.py, replace lines 67-72:

    # Exit tuning (v1.3 — trailing stop added)
    tp1_factor: float = 1.0  # TP1 = entry + factor * (impulse_end - entry). 1.0 = v1
    breakeven_trigger_pct: float = 0.5  # move SL to entry after MFE reaches 50% of TP1 distance
    trailing_pct: float = 0.0  # 0 = disabled. trail X% below highest high
    trailing_trigger_pct: float = 0.5  # activate trailing after MFE reaches this fraction of TP1 distance

    # Versioning
    param_version: str = "momentum-pullback-v1.3"
```

- [ ] **Step 2: Verify tests pass**

Hook pytest runs automatically. All existing tests use `MomentumConfig()` without these params — keyword defaults keep them working.

- [ ] **Step 3: Commit**

```bash
git add momentum/config.py
git commit -m "feat(momentum): add trailing_pct and trailing_trigger_pct to MomentumConfig v1.3"
```

---

### Task 2: Write failing tests for trailing stop

**Files:**
- Create: `tests/test_check_exit_trailing.py`

- [ ] **Step 1: Create test file with all trailing stop tests**

```python
"""Tests for trailing stop logic in check_exit()."""

import pytest
from momentum.research_runner import check_exit


# Shared fixtures: LONG trade with entry=100, SL=95, TP1=110, TP2=115
LONG_BASE = dict(
    direction="LONG", entry_price=100.0,
    sl_price=95.0, tp1_price=110.0, tp2_price=115.0,
    duration_candles=5, timeout_candles=16,
)

SHORT_BASE = dict(
    direction="SHORT", entry_price=100.0,
    sl_price=105.0, tp1_price=90.0, tp2_price=85.0,
    duration_candles=5, timeout_candles=16,
)


class TestTrailingNotActivated:
    """Trailing should not activate before MFE reaches trigger threshold."""

    def test_trailing_disabled_when_pct_zero(self):
        """trailing_pct=0.0 means no trailing — same as v1.2 behavior."""
        r = check_exit(
            **LONG_BASE,
            candle_high=108.0, candle_low=99.0, candle_close=107.0,
            current_mfe=7.0, current_mae=-1.0,
            trailing_pct=0.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0

    def test_trailing_not_active_before_threshold(self):
        """MFE below trigger threshold — trailing should not activate."""
        # TP1 distance = 10. Trigger = 50% = 5.0 in price.
        # MFE = 3% on entry=100 = $3 in price < $5 trigger.
        r = check_exit(
            **LONG_BASE,
            candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=2.0, current_mae=-1.0,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0


class TestTrailingActivation:
    """Trailing activates when MFE reaches trigger threshold."""

    def test_trailing_activates_long(self):
        """LONG: MFE reaches trigger, trailing_sl = high * (1 - pct/100)."""
        # TP1 distance = 10. Trigger = 50% = 5.0 in price.
        # candle_high=106 -> MFE = 6% -> 6.0 in price >= 5.0 trigger.
        # trailing_sl = 106 * (1 - 1.0/100) = 106 * 0.99 = 104.94
        r = check_exit(
            **LONG_BASE,
            candle_high=106.0, candle_low=101.0, candle_close=105.0,
            current_mfe=4.0, current_mae=-1.0,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(104.94)

    def test_trailing_activates_short(self):
        """SHORT: MFE reaches trigger, trailing_sl = low * (1 + pct/100)."""
        # TP1 distance = 10. Trigger = 50% = 5.0 in price.
        # candle_low=94 -> MFE = 6% -> 6.0 in price >= 5.0 trigger.
        # trailing_sl = 94 * (1 + 1.0/100) = 94 * 1.01 = 94.94
        r = check_exit(
            **SHORT_BASE,
            candle_high=99.0, candle_low=94.0, candle_close=95.0,
            current_mfe=4.0, current_mae=-0.5,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(94.94)


class TestTrailingAdvances:
    """Trailing SL only moves in favorable direction."""

    def test_trailing_advances_on_new_high(self):
        """LONG: new high -> trailing_sl advances."""
        # Previous trailing_sl = 104.94 (from high=106)
        # New candle_high=108 -> candidate = 108 * 0.99 = 106.92
        # 106.92 > 104.94 -> advances
        r = check_exit(
            **LONG_BASE,
            candle_high=108.0, candle_low=105.0, candle_close=107.0,
            current_mfe=6.0, current_mae=-1.0,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=104.94,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(106.92)

    def test_trailing_does_not_recede(self):
        """LONG: lower high -> trailing_sl stays put."""
        # Previous trailing_sl = 106.92 (from high=108)
        # New candle_high=105 -> candidate = 105 * 0.99 = 103.95
        # 103.95 < 106.92 -> stays at 106.92
        r = check_exit(
            **LONG_BASE,
            candle_high=105.0, candle_low=103.0, candle_close=104.0,
            current_mfe=8.0, current_mae=-1.0,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=106.92,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(106.92)

    def test_short_trailing_advances_on_new_low(self):
        """SHORT: new low -> trailing_sl moves down (tighter)."""
        # Previous trailing_sl = 94.94 (from low=94)
        # New candle_low=92 -> candidate = 92 * 1.01 = 92.92
        # 92.92 < 94.94 -> advances (for short, lower is better)
        r = check_exit(
            **SHORT_BASE,
            candle_high=95.0, candle_low=92.0, candle_close=93.0,
            current_mfe=6.0, current_mae=-0.5,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=94.94,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(92.92)


class TestTrailingStopHit:
    """Trailing stop triggers exit with correct reason and price."""

    def test_trailing_stop_hit_long(self):
        """LONG: candle_low touches trailing_sl -> exit trailing_stop."""
        # trailing_sl = 106.92, candle_low = 106.0 <= 106.92 -> hit
        r = check_exit(
            **LONG_BASE,
            candle_high=107.5, candle_low=106.0, candle_close=106.5,
            current_mfe=8.0, current_mae=-1.0,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=106.92,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "trailing_stop"
        assert r["exit_price"] == pytest.approx(106.92)
        assert r["pnl_pct"] == pytest.approx(6.92)

    def test_trailing_stop_hit_short(self):
        """SHORT: candle_high touches trailing_sl -> exit trailing_stop."""
        # trailing_sl = 92.92, candle_high = 93.5 >= 92.92 -> hit
        r = check_exit(
            **SHORT_BASE,
            candle_high=93.5, candle_low=91.0, candle_close=93.0,
            current_mfe=8.0, current_mae=-0.5,
            trailing_pct=1.0, trailing_trigger_pct=0.5,
            current_trailing_sl=92.92,
        )
        assert r["closed"] is True
        assert r["exit_reason"] == "trailing_stop"
        assert r["exit_price"] == pytest.approx(92.92)
        assert r["pnl_pct"] == pytest.approx(7.08)


class TestTrailingBreakevenInteraction:
    """Trailing must not go below breakeven level."""

    def test_trailing_respects_breakeven_floor(self):
        """LONG: trailing candidate below entry -> clamped to entry (breakeven)."""
        # breakeven active (trigger 0.5, MFE >= 50% of TP1 dist)
        # trailing_pct=2.0, candle_high=106 -> candidate = 106 * 0.98 = 103.88
        # But breakeven = entry = 100.0
        # effective_sl should be max(103.88, 100.0) = 103.88 (trailing wins here)
        # Let's test case where trailing is BELOW breakeven:
        # candle_high=101 -> candidate = 101 * 0.98 = 98.98
        # breakeven = entry = 100.0
        # new_trailing_sl = max(98.98, 100.0) = 100.0 (breakeven wins)
        r = check_exit(
            **LONG_BASE,
            candle_high=101.0, candle_low=99.5, candle_close=100.5,
            current_mfe=5.5, current_mae=-0.5,
            breakeven_trigger_pct=0.5,
            trailing_pct=2.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(100.0)

    def test_trailing_above_breakeven_takes_precedence(self):
        """LONG: trailing candidate above entry -> trailing wins."""
        # candle_high=108 -> candidate = 108 * 0.98 = 105.84
        # breakeven = entry = 100.0
        # new_trailing_sl = max(105.84, 100.0) = 105.84
        r = check_exit(
            **LONG_BASE,
            candle_high=108.0, candle_low=105.0, candle_close=107.0,
            current_mfe=6.0, current_mae=-0.5,
            breakeven_trigger_pct=0.5,
            trailing_pct=2.0, trailing_trigger_pct=0.5,
            current_trailing_sl=0.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == pytest.approx(105.84)


class TestTrailingBackwardCompat:
    """Existing callers without trailing params work unchanged."""

    def test_no_trailing_params_same_as_v12(self):
        """Calling without trailing params -> no trailing, no new_trailing_sl issues."""
        r = check_exit(
            **LONG_BASE,
            candle_high=103.0, candle_low=99.0, candle_close=102.0,
            current_mfe=2.0, current_mae=-1.0,
        )
        assert r["closed"] is False
        assert r["new_trailing_sl"] == 0.0
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
cd ~/crypto_ai_bot && python -m pytest tests/test_check_exit_trailing.py -v
```

Expected: FAIL — `check_exit()` does not accept `trailing_pct`, `trailing_trigger_pct`, `current_trailing_sl` params yet, and return dict has no `new_trailing_sl` key.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_check_exit_trailing.py
git commit -m "test(momentum): add failing tests for trailing stop in check_exit"
```

---

### Task 3: Implement trailing stop in check_exit

**Files:**
- Modify: `momentum/research_runner.py:177-313`

- [ ] **Step 1: Add trailing params to check_exit signature**

Replace lines 177-192:

```python
def check_exit(
    *,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp1_price: float,
    tp2_price: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    current_mfe: float,
    current_mae: float,
    duration_candles: int,
    timeout_candles: int,
    breakeven_trigger_pct: float = 0.0,
    trailing_pct: float = 0.0,
    trailing_trigger_pct: float = 0.0,
    current_trailing_sl: float = 0.0,
) -> Dict[str, Any]:
```

- [ ] **Step 2: Add trailing logic after breakeven block**

Insert after line 229 (after `effective_sl = entry_price`), before the hit checks:

```python
    # --- Trailing stop: trail X% below highest high (LONG) or above lowest low (SHORT) ---
    new_trailing_sl = current_trailing_sl
    if trailing_pct > 0:
        tp1_distance = abs(tp1_price - entry_price) if breakeven_trigger_pct <= 0 else tp1_distance
        trail_trigger = trailing_trigger_pct * abs(tp1_price - entry_price)
        mfe_price = mfe / 100 * entry_price
        if mfe_price >= trail_trigger:
            if is_long:
                candidate = candle_high * (1 - trailing_pct / 100)
                new_trailing_sl = max(current_trailing_sl, candidate) if current_trailing_sl > 0 else candidate
                new_trailing_sl = max(new_trailing_sl, effective_sl)
            else:
                candidate = candle_low * (1 + trailing_pct / 100)
                new_trailing_sl = min(current_trailing_sl, candidate) if current_trailing_sl > 0 else candidate
                new_trailing_sl = min(new_trailing_sl, effective_sl)
            effective_sl = new_trailing_sl
```

IMPORTANT: The `tp1_distance` variable is already computed in the breakeven block when `breakeven_trigger_pct > 0`. When breakeven is disabled but trailing is enabled, we need our own computation. The correct full block to insert is:

```python
    # --- Trailing stop: trail X% below highest high / above lowest low ---
    new_trailing_sl = current_trailing_sl
    if trailing_pct > 0:
        trail_trigger = trailing_trigger_pct * abs(tp1_price - entry_price)
        mfe_price = mfe / 100 * entry_price
        if mfe_price >= trail_trigger:
            if is_long:
                candidate = candle_high * (1 - trailing_pct / 100)
                new_trailing_sl = max(current_trailing_sl, candidate) if current_trailing_sl > 0 else candidate
                new_trailing_sl = max(new_trailing_sl, effective_sl)
            else:
                candidate = candle_low * (1 + trailing_pct / 100)
                new_trailing_sl = min(current_trailing_sl, candidate) if current_trailing_sl > 0 else candidate
                new_trailing_sl = min(new_trailing_sl, effective_sl)
            effective_sl = new_trailing_sl
```

- [ ] **Step 3: Update exit reason detection in SL hit block**

Replace lines 242-248:

```python
    if sl_hit:
        pnl = _pnl(is_long, entry_price, effective_sl)
        if new_trailing_sl > 0 and effective_sl == new_trailing_sl:
            reason = "trailing_stop"
        elif effective_sl == entry_price:
            reason = "breakeven"
        else:
            reason = "sl_hit"
        return _exit(
            effective_sl, reason, pnl, mfe, mae,
            retested=tp1_hit, lost=(reason == "sl_hit"),
            new_trailing_sl=new_trailing_sl,
        )
```

- [ ] **Step 4: Add new_trailing_sl to _exit helper and all return paths**

Replace `_exit` function (lines 294-313):

```python
def _exit(
    price: float,
    reason: str,
    pnl: float,
    mfe: float,
    mae: float,
    *,
    retested: bool,
    lost: bool,
    new_trailing_sl: float = 0.0,
) -> Dict[str, Any]:
    return {
        "closed": True,
        "exit_price": price,
        "exit_reason": reason,
        "pnl_pct": pnl,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "retested_impulse_end": retested,
        "lost_pullback_extreme": lost,
        "new_trailing_sl": new_trailing_sl,
    }
```

Add `new_trailing_sl=new_trailing_sl` to ALL `_exit()` calls (TP2, TP1, timeout):

```python
    if tp2_hit:
        pnl = _pnl(is_long, entry_price, tp2_price)
        return _exit(
            tp2_price, "tp2_hit", pnl, mfe, mae,
            retested=True, lost=False, new_trailing_sl=new_trailing_sl,
        )

    if tp1_hit:
        pnl = _pnl(is_long, entry_price, tp1_price)
        return _exit(
            tp1_price, "tp1_hit", pnl, mfe, mae,
            retested=True, lost=False, new_trailing_sl=new_trailing_sl,
        )

    if duration_candles >= timeout_candles:
        pnl = _pnl(is_long, entry_price, candle_close)
        return _exit(
            candle_close, "timeout", pnl, mfe, mae,
            retested=False, lost=False, new_trailing_sl=new_trailing_sl,
        )
```

Add `new_trailing_sl` to the no-exit return (line 272):

```python
    return {
        "closed": False,
        "exit_price": 0.0,
        "exit_reason": "",
        "pnl_pct": 0.0,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "retested_impulse_end": False,
        "lost_pullback_extreme": False,
        "new_trailing_sl": new_trailing_sl,
    }
```

- [ ] **Step 5: Run trailing tests — verify they PASS**

```bash
cd ~/crypto_ai_bot && python -m pytest tests/test_check_exit_trailing.py -v
```

Expected: ALL PASS.

- [ ] **Step 6: Run ALL existing tests — verify no regression**

```bash
cd ~/crypto_ai_bot && python -m pytest tests/test_research_runner.py -v
```

Expected: ALL PASS (existing callers don't pass trailing params, defaults kick in).

- [ ] **Step 7: Commit**

```bash
git add momentum/research_runner.py
git commit -m "feat(momentum): implement trailing stop logic in check_exit v1.3"
```

---

### Task 4: Add trailing_sl_price to research DB

**Files:**
- Modify: `momentum/research_db.py:51-84` (DDL), `momentum/research_db.py:218-226` (columns), `momentum/research_db.py:284-299` (update function)

- [ ] **Step 1: Add column to _TRADES_DDL**

In `research_db.py`, add after line 76 (`mae_pct` line):

```python
    trailing_sl_price   REAL NOT NULL DEFAULT 0,
```

So the DDL section becomes:

```python
    -- Performance (filled on exit or progressively)
    pnl_pct         REAL,
    duration_candles INTEGER,
    mfe_pct         REAL NOT NULL DEFAULT 0,
    mae_pct         REAL NOT NULL DEFAULT 0,
    trailing_sl_price REAL NOT NULL DEFAULT 0,
```

- [ ] **Step 2: Add to _TRADE_COLUMNS list**

Add `"trailing_sl_price"` after `"mae_pct"` in line 223:

```python
_TRADE_COLUMNS = [
    "decision_id", "timestamp", "symbol", "direction", "regime",
    "session_bucket",
    "entry_price", "sl_price", "tp1_price", "tp2_price",
    "exit_price", "exit_reason", "exit_timestamp",
    "pnl_pct", "duration_candles", "mfe_pct", "mae_pct",
    "trailing_sl_price",
    "retested_impulse_end", "lost_pullback_extreme",
    "param_version",
]
```

- [ ] **Step 3: Add update_trade_trailing_sl function**

Add after `update_trade_mfe_mae` (after line 299):

```python
def update_trade_mfe_mae_trailing(
    db_path: str | Path,
    trade_id: int,
    mfe_pct: float,
    mae_pct: float,
    trailing_sl_price: float,
) -> None:
    """Update running MFE/MAE and trailing SL on an open trade."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE momentum_trades SET mfe_pct = ?, mae_pct = ?, trailing_sl_price = ? WHERE id = ?",
            (mfe_pct, mae_pct, trailing_sl_price, trade_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Verify tests pass**

Hook pytest runs automatically.

- [ ] **Step 5: Commit**

```bash
git add momentum/research_db.py
git commit -m "feat(momentum): add trailing_sl_price column to research DB schema"
```

---

### Task 5: Propagate trailing state in research runner _manage_positions

**Files:**
- Modify: `momentum/research_runner.py:109-170`

- [ ] **Step 1: Update import to include new function**

Replace line 24:

```python
from momentum.research_db import (
    close_trade,
    get_open_trades,
    insert_decision,
    insert_trade,
    update_trade_mfe_mae,
    update_trade_mfe_mae_trailing,
)
```

- [ ] **Step 2: Update _manage_positions to pass and persist trailing state**

Replace lines 134-168:

```python
        result = check_exit(
            direction=trade["direction"],
            entry_price=trade["entry_price"],
            sl_price=trade["sl_price"],
            tp1_price=trade["tp1_price"],
            tp2_price=trade["tp2_price"],
            candle_high=high,
            candle_low=low,
            candle_close=close_price,
            current_mfe=trade["mfe_pct"],
            current_mae=trade["mae_pct"],
            duration_candles=duration,
            timeout_candles=config.timeout_candles,
            breakeven_trigger_pct=config.breakeven_trigger_pct,
            trailing_pct=config.trailing_pct,
            trailing_trigger_pct=config.trailing_trigger_pct,
            current_trailing_sl=trade.get("trailing_sl_price", 0.0),
        )

        if result["closed"]:
            close_trade(
                db_path,
                trade["id"],
                exit_price=result["exit_price"],
                exit_reason=result["exit_reason"],
                exit_timestamp=ts,
                pnl_pct=result["pnl_pct"],
                duration_candles=duration,
                mfe_pct=result["mfe_pct"],
                mae_pct=result["mae_pct"],
                retested_impulse_end=result["retested_impulse_end"],
                lost_pullback_extreme=result["lost_pullback_extreme"],
            )
            closed += 1
        else:
            update_trade_mfe_mae_trailing(
                db_path, trade["id"],
                result["mfe_pct"], result["mae_pct"],
                result.get("new_trailing_sl", 0.0),
            )
```

- [ ] **Step 3: Verify tests pass**

Hook pytest runs automatically.

- [ ] **Step 4: Commit**

```bash
git add momentum/research_runner.py
git commit -m "feat(momentum): propagate trailing state in research runner _manage_positions"
```

---

### Task 6: Wire trailing into paper executor (live)

**Files:**
- Modify: `momentum/paper_executor.py:142-258`

- [ ] **Step 1: Add trailing_sl_price to position dict in open_position**

In `open_position()`, add field to the position dict (line 142-154). Replace:

```python
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
```

With:

```python
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
        "trailing_sl_price": 0.0,
    }
```

- [ ] **Step 2: Pass trailing params to check_exit in manage_positions**

Replace lines 190-204:

```python
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
            trailing_pct=config.trailing_pct,
            trailing_trigger_pct=config.trailing_trigger_pct,
            current_trailing_sl=pos.get("trailing_sl_price", 0.0),
        )
```

- [ ] **Step 3: Update trailing state on no-exit path**

Replace lines 253-258:

```python
        else:
            pos["mfe_pct"] = result["mfe_pct"]
            pos["mae_pct"] = result["mae_pct"]
            pos["trailing_sl_price"] = result.get("new_trailing_sl", 0.0)
            # Only count candle if a new 15m candle has closed
            if new_candle_symbols is None or symbol in new_candle_symbols:
                pos["candles_elapsed"] = pos.get("candles_elapsed", 0) + 1
```

- [ ] **Step 4: Update param_version in trade log**

Replace line 236 (`"param_version": "momentum-pullback-v1.1"`) with:

```python
                    "param_version": config.param_version,
```

- [ ] **Step 5: Verify tests pass**

Hook pytest runs automatically.

- [ ] **Step 6: Commit**

```bash
git add momentum/paper_executor.py
git commit -m "feat(momentum): wire trailing stop into paper executor for live trading"
```

---

### Task 7: Add tuning matrix variants

**Files:**
- Modify: `scripts/tuning_matrix.py:46-53`

- [ ] **Step 1: Add D1-D4 trailing variants**

Replace the VARIANTS dict:

```python
VARIANTS = {
    "v1_baseline": MomentumConfig(sl_floor_pct=0.3, breakeven_trigger_pct=0.0, trailing_pct=0.0, param_version="momentum-pullback-v1"),
    "A1_timeout12": MomentumConfig(sl_floor_pct=0.3, timeout_candles=12, trailing_pct=0.0, param_version="momentum-pullback-v1"),
    "A2_breakeven": MomentumConfig(sl_floor_pct=0.3, breakeven_trigger_pct=0.5, trailing_pct=0.0, param_version="momentum-pullback-v1"),
    "B1_floor05": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.0, trailing_pct=0.0, param_version="momentum-pullback-v1.1"),
    "B2_floor08": MomentumConfig(sl_floor_pct=0.8, breakeven_trigger_pct=0.0, trailing_pct=0.0, param_version="momentum-pullback-v1"),
    "B3_floor05_be": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.5, trailing_pct=0.0, param_version="momentum-pullback-v1.2"),
    "C1_tp1_half": MomentumConfig(sl_floor_pct=0.3, tp1_factor=0.5, trailing_pct=0.0, param_version="momentum-pullback-v1"),
    "D1_trail05": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.5, trailing_pct=0.5, param_version="momentum-pullback-v1.3"),
    "D2_trail10": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.5, trailing_pct=1.0, param_version="momentum-pullback-v1.3"),
    "D3_trail15": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.5, trailing_pct=1.5, param_version="momentum-pullback-v1.3"),
    "D4_trail20": MomentumConfig(sl_floor_pct=0.5, breakeven_trigger_pct=0.5, trailing_pct=2.0, param_version="momentum-pullback-v1.3"),
}
```

- [ ] **Step 2: Update config print to show trailing_pct**

Replace line 328-331:

```python
        print(f"  Config: timeout={config.timeout_candles}, "
              f"sl_floor={config.sl_floor_pct}%, "
              f"tp1_factor={config.tp1_factor}, "
              f"breakeven={config.breakeven_trigger_pct}, "
              f"trailing={config.trailing_pct}%")
```

- [ ] **Step 3: Verify tests pass**

Hook pytest runs automatically.

- [ ] **Step 4: Commit**

```bash
git add scripts/tuning_matrix.py
git commit -m "feat(momentum): add D1-D4 trailing stop variants to tuning matrix"
```

---

### Task 8: Restart bot and validate

- [ ] **Step 1: Restart cryptobot service**

```bash
sudo systemctl restart cryptobot
```

- [ ] **Step 2: Verify service is running**

```bash
sudo systemctl status cryptobot --no-pager
```

Expected: active (running), 3 processes.

- [ ] **Step 3: Check dashboard API**

```bash
curl -s http://localhost:5000/api/status | python3 -m json.tool | head -20
```

Expected: responds with valid JSON, no errors.

- [ ] **Step 4: Check logs for trailing config**

```bash
journalctl -u cryptobot --since "1 minute ago" --no-pager | tail -20
```

Expected: no errors, bot starts normally with v1.3 config.

- [ ] **Step 5: Final commit with all changes**

```bash
git add -A
git status
```

Verify only expected files changed. If clean, no additional commit needed.
