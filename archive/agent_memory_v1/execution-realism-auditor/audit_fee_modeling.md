---
name: Fee Modeling Audit (2026-04-01)
description: Critical finding - paper_trader, trade_agents, pump_trader have ZERO fees; scalping_trader has slippage but no fees; backtests are more realistic than live paper trading
type: project
---

Paper trading systems have NO fee deduction in PnL calculations:
- paper_trader.py: zero fees, zero slippage
- trade_agents.py: zero fees, zero slippage
- pump_trader.py: zero fees, zero slippage (but backtest_pump.py has 0.08%)
- scalping_trader.py: 0.05% slippage on fills (CONFIG.slippage_pct in signal_types.py) but ZERO fee deduction

Backtests are more realistic:
- backtest.py: 0.2% round trip (Spot fee, should be 0.08% for Futures)
- backtest_scalping.py: 0.08% fee + 0.04% extra slippage
- backtest_pump.py: 0.08% round trip

**Why:** Paper results currently overstate performance vs backtests of the same systems. Any edge that appears only in paper results is suspect.

**How to apply:** When evaluating paper trading metrics, mentally subtract 0.08% per trade at minimum. Do not trust paper results as evidence of edge until fee deduction is implemented in all 4 paper traders.
