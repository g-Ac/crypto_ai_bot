---
name: Scalping Realism Gaps (2026-04-01)
description: Scalping system has tight SLs (0.3-0.8%) where fees represent 10-27% of SL distance; leverage amplifies the gap; backtest_scalping.py is the most realistic backtest
type: project
---

Scalping SL distances in ScalpingConfig (signal_types.py):
- max_sl_rsi_bb: 0.6%
- max_sl_ema_crossover: 0.7%
- max_sl_volume_breakout: 0.8%

At 0.08% round-trip fee, fees represent:
- 0.8% SL -> fees = 10% of SL
- 0.6% SL -> fees = 13.3% of SL
- 0.3% SL -> fees = 26.7% of SL

With leverage 3-5x, effective fee impact on margin:
- 3x leverage: 0.24% additional loss on SL
- 5x leverage: 0.40% additional loss on SL

Slippage model in scalping_trader.py:
- CONFIG.slippage_pct = 0.05% applied to SL/TP fill prices (good)
- But NO fee subtracted from final PnL (bad)

backtest_scalping.py is the most realistic: fees 0.08%, extra slippage 0.04%, SL-first pessimistic exit logic, no look-ahead.

**Why:** Scalping is the highest-risk system for fee distortion because of tight SLs.

**How to apply:** When auditing scalping results, verify that profit factor > 1.0 AFTER applying fees. RR minimums of 1.5-2.0 in config may need upward adjustment after fees.
