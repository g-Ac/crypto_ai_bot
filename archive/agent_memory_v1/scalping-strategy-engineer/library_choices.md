---
name: Library Choices
description: Confirmed library choices for the trading bot - ta (not ta-lib), requests (not ccxt), pandas
type: project
---

Libraries used in the project (confirmed from pip list and existing code):

- **ta 0.11.0** — Technical Analysis library (pure Python, not ta-lib which requires C compilation)
- **pandas 3.0.1** — Data manipulation
- **numpy 2.4.3** — Numerical operations
- **requests 2.32.5** — HTTP client for Binance REST API (not ccxt)
- **anthropic** — Claude API client (used in trade_agents.py)

**Why:** The bot uses direct Binance REST API calls via requests (not ccxt). The `market.py` module fetches from `api.binance.com/api/v3/klines`. Futures funding rate uses `fapi.binance.com/fapi/v1/fundingRate`.

**How to apply:** When adding new features, use `ta` library for indicators and `requests` for API calls. Do not introduce ccxt or ta-lib without asking first.
