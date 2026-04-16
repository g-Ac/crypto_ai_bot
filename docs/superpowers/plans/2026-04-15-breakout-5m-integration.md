# Breakout Engine 5-min — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar um Breakout Engine de 5 minutos no main.py, rodando lado a lado com o Momentum Pullback existente, com capital compartilhado e position router para evitar duplicatas.

**Architecture:** Novo diretório `engines_5m/` com base class e breakout engine adaptado do `engines_1m/breakout.py`. Executor paper dedicado (`breakout/paper_executor.py`) segue o mesmo padrão do `momentum/paper_executor.py`. Integração no loop do `main.py` ao lado do bloco Momentum Pullback. Position router simples: se já existe posição aberta num par (por qualquer engine), ninguém abre outra.

**Tech Stack:** Python 3.13, pandas, numpy, ta (indicators), SQLite WAL (bot.db), Binance Spot Klines API

---

## Contexto

O capítulo 1-min foi encerrado — 3 padrões testados, nenhum produziu edge. O Breakout Engine é o candidato mais promissor para 5-min porque:
- Consolidation ranges no 5-min são ~5-10x maiores que no 1-min (ATR/price ~0.3% vs ~0.06%)
- SL/TP têm espaço para absorver fees (roundtrip 0.08% taker)
- O padrão é stateless (simples de integrar e debugar)

Parâmetros ajustados para 5-min:
- `RANGE_THRESHOLD_PCT`: 0.3% → **1.5%** (ranges maiores no 5-min)
- `BB_BANDWIDTH_MAX`: 1.5% → **3.0%** (BB mais larga no 5-min)
- `VOLUME_MULTIPLE_MIN`: 2.0 → **1.8** (volume spikes menos extremos no 5-min)
- `BODY_RATIO_MIN`: 0.55 → **0.50** (candles 5-min têm mais wick)
- `LOOKBACK_MIN/MAX`: 10/20 → **8/15** (consolidação de 40-75 min)
- `TP1_PROJECTION`: 1.0 → **1.0** (mantém)
- `TP2_PROJECTION`: 1.5 → **2.0** (mais espaço para correr no 5-min)

Fee: **taker 0.04% × 2 = 0.08% roundtrip** (taker orders, como na produção).

GO/NO-GO: **PF ≥ 1.2** e **trades ≥ 10** em 30 dias = edge confirmado.

---

## File Structure

| Ação   | Arquivo | Responsabilidade |
|--------|---------|-----------------|
| Create | `engines_5m/__init__.py` | Package init |
| Create | `engines_5m/base.py` | Base class `Engine5m` (cópia adaptada de `engines_1m/base.py`) |
| Create | `engines_5m/breakout.py` | `BreakoutEngine5m` — detector de consolidation breakout para 5-min |
| Create | `indicators_5m.py` | `add_indicators_5m()` — indicadores técnicos para candles 5-min |
| Create | `breakout/__init__.py` | Package init |
| Create | `breakout/paper_executor.py` | `process_breakout_cycle()` — executor paper (padrão do momentum) |
| Modify | `config.py:175-177` | Adicionar `BREAKOUT_TRADER_ENABLED`, `BREAKOUT_SYMBOLS`, `BREAKOUT_MAX_POSITIONS`, `BREAKOUT_INITIAL_CAPITAL` |
| Modify | `runtime_config.py` | Adicionar `BREAKOUT_STATE_FILE` |
| Modify | `database.py` | Adicionar tabelas `breakout_trades` e `breakout_decisions` |
| Modify | `main.py:201-226` | Adicionar bloco Breakout 5-min + position router |
| Create | `scripts/backtest_breakout_5m.py` | Backtest 30d em BTC/ETH/SOL com taker fees |
| Create | `tests/test_breakout_5m.py` | Testes unitários do engine + executor |

---

### Task 1: Base class e indicadores 5-min

**Files:**
- Create: `engines_5m/__init__.py`
- Create: `engines_5m/base.py`
- Create: `indicators_5m.py`
- Test: `tests/test_breakout_5m.py`

- [ ] **Step 1: Criar `engines_5m/__init__.py`**

```python
# empty init
```

- [ ] **Step 2: Criar `engines_5m/base.py`**

Cópia de `engines_1m/base.py` com classe renomeada para `Engine5m`:

```python
"""Base class for 5-minute trading engines."""
from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd

from signal_types import Signal


class Engine5m(ABC):
    """Interface for pluggable 5-minute engines."""

    name: str = "base"
    version: str = "0.0.0"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name == "base":
            raise TypeError(
                f"{cls.__name__} must define a 'name' class attribute "
                f"different from 'base'"
            )

    @abstractmethod
    def analyze(
        self,
        symbol: str,
        df_5m: pd.DataFrame,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        ...

    @abstractmethod
    def required_indicators(self) -> List[str]:
        ...
```

- [ ] **Step 3: Criar `indicators_5m.py`**

Mesmos indicadores que `indicators_1m.py`, com janelas ajustadas para 5-min:

```python
"""Technical indicators for 5-minute engines."""
import numpy as np
import pandas as pd
import ta


def add_indicators_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicators for 5-minute engines.

    Same indicators as 1-min but window sizes adjusted:
    - VWAP window: 200 candles = ~16.7h (vs ~3.3h no 1-min)
    """
    # Moving averages
    df["ema8"] = ta.trend.ema_indicator(df["close"], window=8)
    df["ema21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["sma20"] = ta.trend.sma_indicator(df["close"], window=20)

    # Volatility
    if len(df) >= 14:
        atr_raw = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=14
        )
        df["atr14"] = atr_raw.replace(0, np.nan)
    else:
        df["atr14"] = np.nan
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_bandwidth"] = bb.bollinger_wband()

    # Momentum
    df["rsi14"] = ta.momentum.rsi(df["close"], window=14)

    # Volume
    df["vol_avg20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]

    # Rolling VWAP (200 candles ~16.7h for 5-min)
    typical = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical * df["volume"]
    df["vwap"] = tp_vol.rolling(200).sum() / df["volume"].rolling(200).sum()

    # Candle properties
    df["body"] = (df["close"] - df["open"]).abs()
    candle_range = df["high"] - df["low"]
    df["range"] = candle_range
    df["body_ratio"] = df["body"] / candle_range.replace(0, np.nan)
    df["upper_shadow"] = df["high"] - df[["close", "open"]].max(axis=1)
    df["lower_shadow"] = df[["close", "open"]].min(axis=1) - df["low"]
    df["is_green"] = df["close"] > df["open"]

    return df
```

- [ ] **Step 4: Escrever teste básico para base class e indicadores**

```python
# tests/test_breakout_5m.py
import numpy as np
import pandas as pd
import pytest

from engines_5m.base import Engine5m
from indicators_5m import add_indicators_5m
from signal_types import Signal


class TestEngine5mBase:
    def test_must_define_name(self):
        with pytest.raises(TypeError):
            class BadEngine(Engine5m):
                pass

    def test_subclass_with_name_works(self):
        class GoodEngine(Engine5m):
            name = "test_engine"
            version = "1.0.0"
            def analyze(self, symbol, df_5m, market_data=None):
                return None
            def required_indicators(self):
                return []
        engine = GoodEngine()
        assert engine.name == "test_engine"


class TestIndicators5m:
    def _make_df(self, n=50):
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        return pd.DataFrame({
            "open": close - np.random.rand(n) * 0.3,
            "high": close + np.random.rand(n) * 0.5,
            "low": close - np.random.rand(n) * 0.5,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 100,
        })

    def test_adds_all_required_columns(self):
        df = add_indicators_5m(self._make_df())
        required = [
            "ema8", "ema21", "sma20", "atr14",
            "bb_upper", "bb_lower", "bb_middle", "bb_bandwidth",
            "rsi14", "vol_avg20", "vol_ratio", "vwap",
            "body", "range", "body_ratio",
            "upper_shadow", "lower_shadow", "is_green",
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_atr14_not_all_nan(self):
        df = add_indicators_5m(self._make_df(50))
        assert not df["atr14"].isna().all()
```

- [ ] **Step 5: Rodar testes**

Run: `python -m pytest tests/test_breakout_5m.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add engines_5m/__init__.py engines_5m/base.py indicators_5m.py tests/test_breakout_5m.py
git commit -m "feat: add engines_5m base class and 5-min indicators"
```

---

### Task 2: Breakout Engine 5-min

**Files:**
- Create: `engines_5m/breakout.py`
- Modify: `tests/test_breakout_5m.py`

- [ ] **Step 1: Escrever teste para BreakoutEngine5m**

Adicionar ao `tests/test_breakout_5m.py`:

```python
from engines_5m.breakout import BreakoutEngine5m
from signal_types import Direction


class TestBreakoutEngine5m:
    def _make_consolidation_then_breakout(self, direction="LONG"):
        """Create 40 candles: 15 consolidation + 1 breakout."""
        np.random.seed(42)
        n = 40
        # 24 warmup candles + 15 consolidation + 1 breakout
        prices = []
        base = 100.0

        # Warmup: gentle uptrend
        for i in range(24):
            prices.append(base + i * 0.05)

        # Consolidation: tight range around 101.2
        cons_center = 101.2
        for i in range(15):
            prices.append(cons_center + np.random.uniform(-0.2, 0.2))

        # Breakout candle
        if direction == "LONG":
            prices.append(cons_center + 2.0)  # strong breakout up
        else:
            prices.append(cons_center - 2.0)  # strong breakout down

        close = np.array(prices)
        high = close + np.random.rand(n) * 0.3
        low = close - np.random.rand(n) * 0.3

        # Make breakout candle have strong body
        if direction == "LONG":
            high[-1] = close[-1] + 0.1
            low[-1] = close[-1] - 1.5
            open_prices = close.copy()
            open_prices[-1] = low[-1] + 0.1  # green candle, big body
        else:
            low[-1] = close[-1] - 0.1
            high[-1] = close[-1] + 1.5
            open_prices = close.copy()
            open_prices[-1] = high[-1] - 0.1  # red candle, big body

        volume = np.ones(n) * 100
        volume[-1] = 500  # 5x average → vol_ratio > 1.8

        df = pd.DataFrame({
            "open": open_prices,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min"),
        })
        return add_indicators_5m(df)

    def test_engine_name(self):
        engine = BreakoutEngine5m()
        assert engine.name == "breakout_5m"

    def test_returns_none_insufficient_candles(self):
        engine = BreakoutEngine5m()
        df = pd.DataFrame({
            "open": [1], "high": [2], "low": [0.5],
            "close": [1.5], "volume": [100],
        })
        df = add_indicators_5m(df)
        assert engine.analyze("BTCUSDT", df) is None

    def test_required_indicators(self):
        engine = BreakoutEngine5m()
        required = engine.required_indicators()
        assert "atr14" in required
        assert "vol_ratio" in required
        assert "bb_bandwidth" in required
```

- [ ] **Step 2: Rodar teste para confirmar que falha**

Run: `python -m pytest tests/test_breakout_5m.py::TestBreakoutEngine5m -v`
Expected: FAIL (import error — `BreakoutEngine5m` doesn't exist yet)

- [ ] **Step 3: Implementar `engines_5m/breakout.py`**

Adaptado de `engines_1m/breakout.py` com parâmetros ajustados para 5-min:

```python
"""Breakout Engine 5m — consolidation breakout on 5-min candles.

Stateless, 2-phase detection:
  Phase 1: Consolidation (tight range + BB squeeze) in last N candles
  Phase 2: Breakout candle (close beyond range, volume + body confirmation)

Entry on breakout close. SL at mid-range. TP by range projection.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from engines_5m.base import Engine5m
from signal_types import Direction, Signal


class BreakoutEngine5m(Engine5m):
    """Consolidation breakout detector for 5-min candles."""

    name = "breakout_5m"
    version = "1.0.0"

    # Consolidation params (adjusted for 5-min)
    LOOKBACK_MIN = 8             # 40 min minimum consolidation
    LOOKBACK_MAX = 15            # 75 min maximum consolidation
    RANGE_THRESHOLD_PCT = 1.5    # max range for consolidation (vs 0.3% on 1m)
    BB_BANDWIDTH_MAX = 3.0       # BB squeeze threshold (vs 1.5% on 1m)

    # Breakout params
    VOLUME_MULTIPLE_MIN = 1.8    # volume spike (vs 2.0 on 1m)
    BODY_RATIO_MIN = 0.50        # body ratio (vs 0.55 on 1m)

    # Exit params
    TP1_PROJECTION = 1.0         # 1:1 range projection
    TP2_PROJECTION = 2.0         # 2:1 range projection (vs 1.5 on 1m)

    _MIN_CANDLES = 30            # LOOKBACK_MAX + warmup

    def analyze(
        self,
        symbol: str,
        df_5m: pd.DataFrame,
        market_data: dict | None = None,
    ) -> Optional[Signal]:
        n = len(df_5m)
        if n < self._MIN_CANDLES:
            return None

        highs = df_5m["high"].values
        lows = df_5m["low"].values
        closes = df_5m["close"].values
        opens = df_5m["open"].values
        idx = n - 1

        vol_ratio = df_5m["vol_ratio"].values[idx]
        body_ratio = df_5m["body_ratio"].values[idx]
        bb_bw = df_5m["bb_bandwidth"].values[idx]
        atr = df_5m["atr14"].values[idx]

        if np.isnan(atr) or atr <= 0:
            return None
        if np.isnan(vol_ratio) or np.isnan(body_ratio) or np.isnan(bb_bw):
            return None

        # Phase 2 quick checks first (cheap filters)
        if vol_ratio < self.VOLUME_MULTIPLE_MIN:
            return None
        if body_ratio < self.BODY_RATIO_MIN:
            return None

        # Try consolidation windows from LOOKBACK_MAX down to LOOKBACK_MIN
        for lookback in range(self.LOOKBACK_MAX, self.LOOKBACK_MIN - 1, -1):
            if idx < lookback:
                continue

            cons_start = idx - lookback
            cons_end = idx  # exclusive

            cons_highs = highs[cons_start:cons_end]
            cons_lows = lows[cons_start:cons_end]
            max_high = float(np.max(cons_highs))
            min_low = float(np.min(cons_lows))

            if min_low <= 0:
                continue

            range_pct = (max_high - min_low) / min_low * 100
            if range_pct >= self.RANGE_THRESHOLD_PCT:
                continue

            bb_bw_pre = df_5m["bb_bandwidth"].values[idx - 1]
            if np.isnan(bb_bw_pre) or bb_bw_pre >= self.BB_BANDWIDTH_MAX:
                continue

            # Phase 1 passed — consolidation confirmed

            close_now = float(closes[idx])
            is_green = closes[idx] > opens[idx]

            if close_now > max_high and is_green:
                direction = Direction.LONG
            elif close_now < min_low and not is_green:
                direction = Direction.SHORT
            else:
                continue

            # Build signal
            consolidation_range = max_high - min_low
            entry_price = close_now
            sl_price = (max_high + min_low) / 2  # mid-range

            if direction == Direction.LONG:
                tp1_price = entry_price + consolidation_range * self.TP1_PROJECTION
                tp2_price = entry_price + consolidation_range * self.TP2_PROJECTION
            else:
                tp1_price = entry_price - consolidation_range * self.TP1_PROJECTION
                tp2_price = entry_price - consolidation_range * self.TP2_PROJECTION

            sl_distance_pct = abs(entry_price - sl_price) / entry_price * 100
            tp_distance_pct = abs(tp1_price - entry_price) / entry_price * 100
            rr_ratio = tp_distance_pct / sl_distance_pct if sl_distance_pct > 0 else 0

            from datetime import datetime, timezone
            if "timestamp" in df_5m.columns:
                timestamp = str(df_5m["timestamp"].iloc[-1])
            else:
                timestamp = datetime.now(timezone.utc).isoformat()

            return Signal(
                direction=direction,
                strength=min(1.0, vol_ratio / 4.0),
                timestamp=timestamp,
                source=self.name,
                symbol=symbol,
                price=entry_price,
                entry_price=entry_price,
                sl_price=sl_price,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                sl_distance_pct=sl_distance_pct,
                rr_ratio=rr_ratio,
                valid=True,
                reason="Consolidation breakout (5m)",
                metadata={
                    "lookback": lookback,
                    "range_pct": round(range_pct, 4),
                    "bb_bandwidth": round(float(bb_bw_pre), 4),
                    "vol_ratio": round(float(vol_ratio), 2),
                    "body_ratio": round(float(body_ratio), 3),
                    "max_high": round(max_high, 8),
                    "min_low": round(min_low, 8),
                    "consolidation_range": round(consolidation_range, 8),
                },
            )

        return None

    def required_indicators(self) -> List[str]:
        return [
            "atr14", "vol_ratio", "body_ratio",
            "bb_bandwidth", "is_green",
        ]
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/test_breakout_5m.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engines_5m/breakout.py tests/test_breakout_5m.py
git commit -m "feat: add BreakoutEngine5m for 5-min consolidation breakouts"
```

---

### Task 3: Config, runtime e database

**Files:**
- Modify: `config.py:175-177`
- Modify: `runtime_config.py`
- Modify: `database.py`
- Modify: `tests/test_breakout_5m.py`

- [ ] **Step 1: Adicionar configs do breakout em `config.py`**

Após a linha `MOMENTUM_MAX_POSITIONS = 1` (linha 177), adicionar:

```python
# Breakout 5m Strategy
BREAKOUT_TRADER_ENABLED = os.environ.get("BREAKOUT_TRADER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
BREAKOUT_SYMBOLS = [s.strip() for s in os.environ.get("BREAKOUT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
BREAKOUT_MAX_POSITIONS = 2
BREAKOUT_INITIAL_CAPITAL = float(os.environ.get("BOT_BREAKOUT_INITIAL_CAPITAL", "1000"))
```

- [ ] **Step 2: Adicionar `BREAKOUT_STATE_FILE` em `runtime_config.py`**

Buscar onde `MOMENTUM_STATE_FILE` é definido e adicionar `BREAKOUT_STATE_FILE` logo abaixo, seguindo o mesmo padrão:

```python
BREAKOUT_STATE_FILE = os.path.join(RUNTIME_DIR, "breakout_state.json")
```

- [ ] **Step 3: Adicionar tabelas `breakout_trades` e `breakout_decisions` em `database.py`**

Seguir o padrão das tabelas `momentum_trades` e `momentum_decisions`. Buscar a função `init_db()` e adicionar os CREATE TABLE. Adicionar funções `insert_breakout_trade()` e `insert_breakout_decision()`.

A tabela `breakout_trades` deve ter as mesmas colunas que `momentum_trades`:
```sql
CREATE TABLE IF NOT EXISTS breakout_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    symbol TEXT,
    direction TEXT,
    entry_price REAL,
    exit_price REAL,
    sl_price REAL,
    tp1_price REAL,
    tp2_price REAL,
    position_size_usd REAL,
    pnl_pct REAL,
    pnl_usd REAL,
    exit_reason TEXT,
    capital_after REAL,
    param_version TEXT,
    duration_candles INTEGER DEFAULT 0,
    mfe_pct REAL DEFAULT 0,
    mae_pct REAL DEFAULT 0
)
```

A tabela `breakout_decisions`:
```sql
CREATE TABLE IF NOT EXISTS breakout_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    cycle_id TEXT,
    symbol TEXT,
    direction TEXT,
    blocked_by TEXT,
    range_pct REAL,
    bb_bandwidth REAL,
    vol_ratio REAL,
    body_ratio REAL,
    lookback INTEGER,
    param_version TEXT
)
```

- [ ] **Step 4: Rodar testes**

Run: `python -m pytest tests/ --tb=short -q`
Expected: PASS (todos os testes existentes + novos)

- [ ] **Step 5: Commit**

```bash
git add config.py runtime_config.py database.py
git commit -m "feat: add breakout 5m config, state file, and database tables"
```

---

### Task 4: Paper executor do Breakout

**Files:**
- Create: `breakout/__init__.py`
- Create: `breakout/paper_executor.py`
- Modify: `tests/test_breakout_5m.py`

- [ ] **Step 1: Escrever testes para o executor**

Adicionar ao `tests/test_breakout_5m.py`:

```python
from breakout.paper_executor import process_breakout_cycle


class TestBreakoutExecutor:
    def test_process_cycle_no_signal(self, tmp_path, monkeypatch):
        """Cycle with no signal returns empty messages."""
        monkeypatch.setattr(
            "breakout.paper_executor.BREAKOUT_STATE_FILE",
            str(tmp_path / "state.json"),
        )
        # Mock candle_fn that returns flat data (no breakout)
        def flat_candles(symbol, interval, limit):
            n = 50
            df = pd.DataFrame({
                "open": [100.0] * n,
                "high": [100.5] * n,
                "low": [99.5] * n,
                "close": [100.0] * n,
                "volume": [100.0] * n,
                "time": pd.date_range("2026-01-01", periods=n, freq="5min"),
            })
            return df

        msgs = process_breakout_cycle(
            ["BTCUSDT"],
            open_new=True,
            candle_fn=flat_candles,
        )
        assert isinstance(msgs, list)
```

- [ ] **Step 2: Rodar teste para confirmar que falha**

Run: `python -m pytest tests/test_breakout_5m.py::TestBreakoutExecutor -v`
Expected: FAIL (import error)

- [ ] **Step 3: Criar `breakout/__init__.py`**

```python
# empty init
```

- [ ] **Step 4: Implementar `breakout/paper_executor.py`**

Segue o padrão do `momentum/paper_executor.py`:
- `load_state()` / `save_state()` com JSON
- `open_position()` com position sizing (2% risk)
- `manage_positions()` com check_exit simplificado (SL/TP1/TP2/timeout)
- `process_breakout_cycle()` como entry point

```python
"""Breakout 5m paper trading executor.

Same pattern as momentum/paper_executor.py:
- JSON state persistence
- 2% risk position sizing
- SL/TP management with partial close at TP1
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from config import BREAKOUT_INITIAL_CAPITAL, BREAKOUT_MAX_POSITIONS
from engines_5m.breakout import BreakoutEngine5m
from indicators_5m import add_indicators_5m
from signal_types import Signal
import database as db

logger = logging.getLogger("breakout.paper")

_state_lock = threading.Lock()

from runtime_config import BREAKOUT_STATE_FILE

_engine = BreakoutEngine5m()


def _default_state() -> dict:
    return {
        "capital": float(BREAKOUT_INITIAL_CAPITAL),
        "positions": {},
        "cooldowns": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl_usd": 0.0,
        "hwm": float(BREAKOUT_INITIAL_CAPITAL),
        "last_candle_ts": {},
    }


def load_state() -> dict:
    with _state_lock:
        if not os.path.exists(BREAKOUT_STATE_FILE):
            return _default_state()
        try:
            with open(BREAKOUT_STATE_FILE, "r") as f:
                state = json.load(f)
            if "hwm" not in state:
                state["hwm"] = max(state.get("capital", BREAKOUT_INITIAL_CAPITAL),
                                   BREAKOUT_INITIAL_CAPITAL)
            return state
        except (json.JSONDecodeError, ValueError):
            return _default_state()


def save_state(state: dict) -> None:
    state["hwm"] = max(state.get("hwm", state["capital"]), state["capital"])
    with _state_lock:
        dir_name = os.path.dirname(BREAKOUT_STATE_FILE) or "."
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, suffix=".tmp",
        ) as f:
            json.dump(state, f, indent=2)
            tmp = f.name
        os.replace(tmp, BREAKOUT_STATE_FILE)


def get_breakout_status() -> str:
    state = load_state()
    cap = state["capital"]
    w = state["wins"]
    l = state["losses"]
    total = state["total_trades"]
    pnl = state["total_pnl_usd"]
    wr = (w / total * 100) if total > 0 else 0
    n_pos = len(state.get("positions", {}))
    hwm = state.get("hwm", cap)
    dd_pct = ((hwm - cap) / hwm * 100) if hwm > 0 else 0

    lines = [
        f"BREAKOUT 5M | ${cap:.2f} | {total}t {w}W/{l}L WR={wr:.1f}% | PnL ${pnl:+.2f}",
        f"  HWM=${hwm:.2f} DD={dd_pct:.1f}% | Pos={n_pos}",
    ]
    for sym, pos in state.get("positions", {}).items():
        lines.append(f"  {sym} {pos['direction']} @ {pos['entry_price']:.2f}")
    return "\n".join(lines)


def _calculate_position_size(capital: float, entry: float, sl: float) -> float:
    sl_distance_pct = abs(entry - sl) / entry * 100
    if sl_distance_pct <= 0:
        return 0.0
    risk_amount = capital * 0.02
    position_size = risk_amount / (sl_distance_pct / 100)
    return min(position_size, capital)


def _check_position_conflict(symbol: str) -> bool:
    """Check if any other engine has an open position on this symbol."""
    try:
        from momentum.paper_executor import load_state as load_momentum_state
        momentum_state = load_momentum_state()
        if symbol in momentum_state.get("positions", {}):
            return True
    except Exception:
        pass
    return False


def open_position(state: dict, signal: Signal, cycle_id: str) -> list[str]:
    msgs: list[str] = []
    symbol = signal.symbol

    if symbol in state["positions"]:
        return msgs
    if len(state["positions"]) >= BREAKOUT_MAX_POSITIONS:
        return msgs
    if symbol in state.get("cooldowns", {}):
        return msgs
    if _check_position_conflict(symbol):
        logger.info("SKIP %s — momentum has open position", symbol)
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
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "candles_elapsed": 0,
        "tp1_hit": False,
    }

    sl_dist = abs(entry - sl) / entry * 100
    msg = (
        f"{symbol} {direction} @ {entry:.2f} | "
        f"SL={sl:.2f} ({sl_dist:.2f}%) TP1={tp1:.2f} TP2={tp2:.2f} | "
        f"Size=${size:.2f}"
    )
    msgs.append(msg)
    logger.info("OPEN %s", msg)
    return msgs


def manage_positions(state: dict, candles: dict[str, dict],
                     new_candle_symbols: set[str] | None = None) -> list[str]:
    msgs: list[str] = []
    closed_symbols: list[str] = []
    TIMEOUT_CANDLES = 60  # 5h timeout

    for symbol, pos in list(state["positions"].items()):
        candle = candles.get(symbol)
        if candle is None:
            continue

        high = candle["high"]
        low = candle["low"]
        close = candle["close"]
        entry = pos["entry_price"]
        direction = pos["direction"]

        # Update MFE/MAE
        if direction == "LONG":
            excursion = (high - entry) / entry * 100
            adverse = (entry - low) / entry * 100
        else:
            excursion = (entry - low) / entry * 100
            adverse = (high - entry) / entry * 100

        pos["mfe_pct"] = max(pos.get("mfe_pct", 0), excursion)
        pos["mae_pct"] = max(pos.get("mae_pct", 0), adverse)

        if new_candle_symbols is None or symbol in new_candle_symbols:
            pos["candles_elapsed"] = pos.get("candles_elapsed", 0) + 1

        # Check exit conditions
        exit_reason = None
        exit_price = close

        sl = pos["sl_price"]
        tp1 = pos["tp1_price"]
        tp2 = pos["tp2_price"]
        tp1_hit = pos.get("tp1_hit", False)

        if direction == "LONG":
            if low <= sl:
                exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                exit_price = sl
            elif not tp1_hit and high >= tp1:
                # TP1 hit: move SL to breakeven, continue for TP2
                pos["tp1_hit"] = True
                pos["tp1_exit_price"] = tp1
                pos["sl_price"] = entry  # breakeven
                # Check if TP2 also hit in same candle
                if high >= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * tp1 + 0.5 * tp2  # blended
            elif tp1_hit and high >= tp2:
                exit_reason = "tp2_hit"
                exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
            elif tp1_hit and low <= pos["sl_price"]:
                exit_reason = "sl_breakeven"
                exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry
        else:  # SHORT
            if high >= sl:
                exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                exit_price = sl
            elif not tp1_hit and low <= tp1:
                pos["tp1_hit"] = True
                pos["tp1_exit_price"] = tp1
                pos["sl_price"] = entry
                if low <= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * tp1 + 0.5 * tp2
            elif tp1_hit and low <= tp2:
                exit_reason = "tp2_hit"
                exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
            elif tp1_hit and high >= pos["sl_price"]:
                exit_reason = "sl_breakeven"
                exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry

        # Timeout
        if exit_reason is None and pos.get("candles_elapsed", 0) >= TIMEOUT_CANDLES:
            exit_reason = "timeout"
            exit_price = close

        if exit_reason:
            if direction == "LONG":
                pnl_pct = (exit_price - entry) / entry * 100
            else:
                pnl_pct = (entry - exit_price) / entry * 100

            # Subtract fees
            pnl_pct -= 0.08  # taker roundtrip

            pnl_usd = pos["position_size_usd"] * pnl_pct / 100
            state["capital"] += pnl_usd
            state["total_pnl_usd"] += pnl_usd
            state["total_trades"] += 1

            if pnl_pct > 0:
                state["wins"] += 1
            elif pnl_pct < 0:
                state["losses"] += 1
                state.setdefault("cooldowns", {})[symbol] = 2

            try:
                db.insert_breakout_trade({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": round(exit_price, 8),
                    "sl_price": pos["sl_price"],
                    "tp1_price": tp1,
                    "tp2_price": tp2,
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_usd": round(pnl_usd, 2),
                    "exit_reason": exit_reason,
                    "capital_after": round(state["capital"], 2),
                    "param_version": "breakout-5m-v1.0",
                    "duration_candles": pos.get("candles_elapsed", 0),
                    "mfe_pct": round(pos.get("mfe_pct", 0), 4),
                    "mae_pct": round(pos.get("mae_pct", 0), 4),
                })
            except Exception as e:
                logger.warning("Failed to log breakout trade: %s", e)

            msg = (
                f"CLOSE {symbol} {direction} | "
                f"{exit_reason} @ {exit_price:.2f} | "
                f"PnL {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | "
                f"Cap ${state['capital']:.2f}"
            )
            msgs.append(msg)
            logger.info(msg)
            closed_symbols.append(symbol)

    for sym in closed_symbols:
        del state["positions"][sym]

    return msgs


def _tick_cooldowns(state: dict) -> None:
    expired = []
    for symbol, remaining in state.get("cooldowns", {}).items():
        remaining -= 1
        if remaining <= 0:
            expired.append(symbol)
        else:
            state["cooldowns"][symbol] = remaining
    for sym in expired:
        del state["cooldowns"][sym]


def process_breakout_cycle(
    symbols: list[str],
    open_new: bool = True,
    *,
    candle_fn: Optional[Callable] = None,
) -> list[str]:
    """One full breakout cycle: evaluate signals + manage positions.

    Args:
        symbols: Symbols to evaluate.
        open_new: If False, only manage existing positions.
        candle_fn: Override for testing. (symbol, interval, limit) -> DataFrame.

    Returns:
        List of Telegram-ready messages.
    """
    if candle_fn is None:
        from market import get_candles
        candle_fn = get_candles

    state = load_state()
    msgs: list[str] = []
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candle_cache: dict[str, dict] = {}
    new_candle_symbols: set[str] = set()
    last_candle_ts = state.get("last_candle_ts", {})

    for symbol in symbols:
        candles = candle_fn(symbol, "5m", 100)
        if candles is None or len(candles) == 0:
            continue

        last = candles.iloc[-1]
        candle_ts = str(last.get("time", ""))
        candle_cache[symbol] = {
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "time": candle_ts,
        }

        if candle_ts != last_candle_ts.get(symbol, ""):
            new_candle_symbols.add(symbol)
            last_candle_ts[symbol] = candle_ts
        else:
            continue

        # Add indicators and run engine
        df = add_indicators_5m(candles)
        signal = _engine.analyze(symbol, df)

        if signal is not None and signal.valid and open_new:
            entry_msgs = open_position(state, signal, cycle_id)
            msgs.extend(entry_msgs)
            if not entry_msgs:
                try:
                    db.insert_breakout_decision({
                        "timestamp": signal.timestamp,
                        "cycle_id": cycle_id,
                        "symbol": symbol,
                        "direction": signal.direction.value,
                        "blocked_by": "max_positions" if len(state["positions"]) >= BREAKOUT_MAX_POSITIONS else "cooldown_or_conflict",
                        "range_pct": signal.metadata.get("range_pct", 0),
                        "bb_bandwidth": signal.metadata.get("bb_bandwidth", 0),
                        "vol_ratio": signal.metadata.get("vol_ratio", 0),
                        "body_ratio": signal.metadata.get("body_ratio", 0),
                        "lookback": signal.metadata.get("lookback", 0),
                        "param_version": "breakout-5m-v1.0",
                    })
                except Exception as e:
                    logger.warning("Failed to log breakout decision: %s", e)
        elif signal is not None and signal.valid and not open_new:
            try:
                db.insert_breakout_decision({
                    "timestamp": signal.timestamp,
                    "cycle_id": cycle_id,
                    "symbol": symbol,
                    "direction": signal.direction.value,
                    "blocked_by": "suspended",
                    "range_pct": signal.metadata.get("range_pct", 0),
                    "bb_bandwidth": signal.metadata.get("bb_bandwidth", 0),
                    "vol_ratio": signal.metadata.get("vol_ratio", 0),
                    "body_ratio": signal.metadata.get("body_ratio", 0),
                    "lookback": signal.metadata.get("lookback", 0),
                    "param_version": "breakout-5m-v1.0",
                })
            except Exception as e:
                logger.warning("Failed to log breakout decision: %s", e)

    if new_candle_symbols:
        _tick_cooldowns(state)

    # Manage existing positions
    exit_msgs = manage_positions(state, candle_cache, new_candle_symbols)
    msgs.extend(exit_msgs)

    state["last_candle_ts"] = last_candle_ts
    save_state(state)
    return msgs
```

- [ ] **Step 5: Rodar testes**

Run: `python -m pytest tests/test_breakout_5m.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add breakout/__init__.py breakout/paper_executor.py tests/test_breakout_5m.py
git commit -m "feat: add breakout 5m paper executor with position management"
```

---

### Task 5: Integração no main.py + position router

**Files:**
- Modify: `main.py:201-226`
- Modify: `tests/test_breakout_5m.py`

- [ ] **Step 1: Adicionar bloco Breakout 5m no main.py**

Após o bloco do Momentum Pullback (linha 226), adicionar:

```python
    # Breakout 5m Strategy
    if cfg.BREAKOUT_TRADER_ENABLED:
        print("\n========================================")
        print("BREAKOUT 5M STRATEGY\n")

        try:
            try:
                breakout_suspended = enforce_circuit_breaker("breakout") or is_paused()
            except Exception as e:
                print(f"  [ERRO] Falha ao verificar circuit breaker breakout: {e}")
                breakout_suspended = True
            if breakout_suspended:
                print("  Circuit breaker ativo ou bot pausado - gerenciando posicoes")
            from breakout.paper_executor import process_breakout_cycle, get_breakout_status
            breakout_msgs = process_breakout_cycle(
                cfg.BREAKOUT_SYMBOLS,
                open_new=not breakout_suspended,
            )
            for msg in breakout_msgs:
                print(f"  {msg}")
                send_telegram_message(f"\U0001f4ca <b>[BREAKOUT 5M]</b> {msg}")
            print(f"\n  {get_breakout_status()}")
        except Exception as e:
            print(f"  [ERRO] Falha no breakout 5m: {e}")
    else:
        print("\n========================================")
        print("BREAKOUT 5M: DESABILITADO (BREAKOUT_TRADER_ENABLED=false)\n")
```

- [ ] **Step 2: Adicionar position router reverso no momentum executor**

No `momentum/paper_executor.py`, na função `open_position()`, adicionar check se breakout já tem posição aberta neste par. Adicionar após o check de cooldown:

```python
    # Position router: check if breakout engine has position on this symbol
    try:
        from breakout.paper_executor import load_state as load_breakout_state
        breakout_state = load_breakout_state()
        if symbol in breakout_state.get("positions", {}):
            return msgs
    except Exception:
        pass
```

- [ ] **Step 3: Rodar testes**

Run: `python -m pytest tests/ --tb=short -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add main.py momentum/paper_executor.py
git commit -m "feat: integrate breakout 5m into main.py with position router"
```

---

### Task 6: Backtest 30d em BTC/ETH/SOL

**Files:**
- Create: `scripts/backtest_breakout_5m.py`

- [ ] **Step 1: Implementar backtest**

Script segue o padrão do `fase3_breakout_validation.py` mas adaptado para 5-min:
- Fetch 30d de candles 5-min via Binance API (8640 candles)
- Roda BreakoutEngine5m em cada candle
- Position management com partial close (TP1 50%, trailing, TP2)
- Fee: 0.08% roundtrip (taker)
- Output: trades, WR, PF, avg PnL, distribuição de exit reasons

```python
"""Backtest Breakout Engine 5m — 30d BTC/ETH/SOL with taker fees."""
import sys
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, ".")

from engines_5m.breakout import BreakoutEngine5m
from indicators_5m import add_indicators_5m


FEE_ROUNDTRIP_PCT = 0.08
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS = 30


def fetch_5m_candles(symbol: str, days: int) -> pd.DataFrame:
    """Fetch 5-min candles from Binance Spot Klines."""
    all_candles = []
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    limit = 1000

    current = start_time
    while current < end_time:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=5m&startTime={current}&limit={limit}"
        )
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data:
                        current = end_time
                        break
                    all_candles.extend(data)
                    current = data[-1][0] + 1
                    break
                elif resp.status_code == 429:
                    time.sleep(5)
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)
        else:
            break
        time.sleep(0.2)

    df = pd.DataFrame(all_candles, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore",
    ])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms")
    return df


def run_backtest(symbol: str):
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {symbol} — Breakout 5m — {DAYS}d")
    print(f"{'='*60}")

    df_full = fetch_5m_candles(symbol, DAYS)
    print(f"  Candles: {len(df_full)}")

    engine = BreakoutEngine5m()
    trades = []
    position = None
    signals_count = 0

    for i in range(engine._MIN_CANDLES, len(df_full)):
        visible = df_full.iloc[max(0, i - 120):i + 1].copy()
        visible = add_indicators_5m(visible)

        candle = df_full.iloc[i]
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        # Manage open position
        if position is not None:
            pos = position
            direction = pos["direction"]
            entry = pos["entry_price"]
            sl = pos["sl_price"]
            tp1 = pos["tp1_price"]
            tp2 = pos["tp2_price"]
            tp1_hit = pos.get("tp1_hit", False)
            pos["candles_elapsed"] += 1

            # MFE/MAE
            if direction == "LONG":
                pos["mfe_pct"] = max(pos["mfe_pct"], (high - entry) / entry * 100)
                pos["mae_pct"] = max(pos["mae_pct"], (entry - low) / entry * 100)
            else:
                pos["mfe_pct"] = max(pos["mfe_pct"], (entry - low) / entry * 100)
                pos["mae_pct"] = max(pos["mae_pct"], (high - entry) / entry * 100)

            exit_reason = None
            exit_price = close

            if direction == "LONG":
                if low <= sl:
                    exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                    exit_price = sl
                elif not tp1_hit and high >= tp1:
                    pos["tp1_hit"] = True
                    pos["tp1_exit_price"] = tp1
                    pos["sl_price"] = entry
                    if high >= tp2:
                        exit_reason = "tp2_hit"
                        exit_price = 0.5 * tp1 + 0.5 * tp2
                elif tp1_hit and high >= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
                elif tp1_hit and low <= pos["sl_price"]:
                    exit_reason = "sl_breakeven"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry
            else:
                if high >= sl:
                    exit_reason = "sl_hit" if not tp1_hit else "sl_breakeven"
                    exit_price = sl
                elif not tp1_hit and low <= tp1:
                    pos["tp1_hit"] = True
                    pos["tp1_exit_price"] = tp1
                    pos["sl_price"] = entry
                    if low <= tp2:
                        exit_reason = "tp2_hit"
                        exit_price = 0.5 * tp1 + 0.5 * tp2
                elif tp1_hit and low <= tp2:
                    exit_reason = "tp2_hit"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * tp2
                elif tp1_hit and high >= pos["sl_price"]:
                    exit_reason = "sl_breakeven"
                    exit_price = 0.5 * pos["tp1_exit_price"] + 0.5 * entry

            if exit_reason is None and pos["candles_elapsed"] >= 60:
                exit_reason = "timeout"
                exit_price = close

            if exit_reason:
                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100
                pnl_pct -= FEE_ROUNDTRIP_PCT

                trades.append({
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": exit_reason,
                    "duration": pos["candles_elapsed"],
                    "mfe_pct": round(pos["mfe_pct"], 4),
                    "mae_pct": round(pos["mae_pct"], 4),
                })
                position = None

        # Generate new signal if no position
        if position is None:
            signal = engine.analyze(symbol, visible)
            if signal is not None and signal.valid:
                signals_count += 1
                position = {
                    "direction": signal.direction.value,
                    "entry_price": signal.entry_price,
                    "sl_price": signal.sl_price,
                    "tp1_price": signal.tp1_price,
                    "tp2_price": signal.tp2_price,
                    "candles_elapsed": 0,
                    "mfe_pct": 0.0,
                    "mae_pct": 0.0,
                    "tp1_hit": False,
                }

    # Results
    print(f"\n  Signals: {signals_count}")
    print(f"  Trades: {len(trades)}")

    if not trades:
        print("  NO TRADES — skipping metrics")
        return trades

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    print(f"  Win Rate: {len(wins)}/{len(trades)} = {len(wins)/len(trades)*100:.1f}%")
    print(f"  Avg PnL: {np.mean(pnls):.4f}%")
    print(f"  Total PnL: {sum(pnls):.4f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Avg Duration: {np.mean([t['duration'] for t in trades]):.1f} candles")

    # Exit reason distribution
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        reasons[r] = reasons.get(r, 0) + 1
    print(f"\n  Exit Reasons:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r}: {c} ({c/len(trades)*100:.1f}%)")

    return trades


if __name__ == "__main__":
    all_trades = []
    for sym in SYMBOLS:
        trades = run_backtest(sym)
        all_trades.extend(trades)
        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"  COMBINED RESULTS — {len(all_trades)} trades")
    print(f"{'='*60}")

    if all_trades:
        pnls = [t["pnl_pct"] for t in all_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gp = sum(wins) if wins else 0
        gl = abs(sum(losses)) if losses else 0
        pf = gp / gl if gl > 0 else float("inf")

        print(f"  Total Trades: {len(all_trades)}")
        print(f"  Win Rate: {len(wins)}/{len(all_trades)} = {len(wins)/len(all_trades)*100:.1f}%")
        print(f"  Total PnL: {sum(pnls):.4f}%")
        print(f"  Profit Factor: {pf:.2f}")

        print(f"\n  GO/NO-GO:")
        go = pf >= 1.2 and len(all_trades) >= 10
        print(f"    PF >= 1.2: {'PASS' if pf >= 1.2 else 'FAIL'} ({pf:.2f})")
        print(f"    Trades >= 10: {'PASS' if len(all_trades) >= 10 else 'FAIL'} ({len(all_trades)})")
        print(f"    Verdict: {'GO' if go else 'NO-GO'}")
    else:
        print("  NO TRADES across all symbols")
        print(f"\n  GO/NO-GO: NO-GO (0 trades)")
```

- [ ] **Step 2: Rodar backtest**

Run: `cd ~/crypto_ai_bot && source .venv/bin/activate && python scripts/backtest_breakout_5m.py`
Expected: Results for each symbol + combined GO/NO-GO verdict

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_breakout_5m.py
git commit -m "feat: add breakout 5m backtest script (30d BTC/ETH/SOL)"
```

---

### Task 7: GO/NO-GO e próximos passos

- [ ] **Step 1: Analisar resultados do backtest**

Critérios:
- **GO**: PF ≥ 1.2 **E** trades ≥ 10 → habilitar `BREAKOUT_TRADER_ENABLED=true` no `.env`, restart cryptobot, monitorar 48h
- **NO-GO**: PF < 1.2 **OU** trades < 10 → documentar resultados, discutir pivô (Break & Retest 5-min? Outro timeframe?)

- [ ] **Step 2: Se GO, atualizar `.env` e restart**

```bash
# Adicionar ao .env
echo "BREAKOUT_TRADER_ENABLED=true" >> ~/crypto_ai_bot/.env
echo "BREAKOUT_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT" >> ~/crypto_ai_bot/.env
sudo systemctl restart cryptobot
curl -s http://localhost:5000/api/status | python3 -m json.tool
```

- [ ] **Step 3: Se NO-GO, documentar e decidir próximo passo**

Opções:
- A) Break & Retest no 5-min (retest geometry pode funcionar melhor com ranges maiores)
- B) Ajustar parâmetros do Breakout 5-min (relaxar/apertar thresholds)
- C) Pivotar para outro timeframe (15-min, 1h)
