import os


def _optional_float_env(name):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


_DEFAULT_INITIAL_CAPITALS = {
    "paper": 10000.0,
    "agent": 10000.0,
    "pump": 5000.0,
    "scalping": 10000.0,
    "momentum": 1000.0,
}

_portfolio_target_capital = _optional_float_env("BOT_PORTFOLIO_TARGET_CAPITAL")
_resolved_initial_capitals = dict(_DEFAULT_INITIAL_CAPITALS)

if _portfolio_target_capital and _portfolio_target_capital > 0:
    _default_total = sum(_DEFAULT_INITIAL_CAPITALS.values())
    _scale = _portfolio_target_capital / _default_total if _default_total > 0 else 1.0
    _resolved_initial_capitals = {
        key: value * _scale
        for key, value in _DEFAULT_INITIAL_CAPITALS.items()
    }

for _system_key, _env_name in {
    "paper": "BOT_PAPER_INITIAL_CAPITAL",
    "agent": "BOT_AGENT_INITIAL_CAPITAL",
    "pump": "BOT_PUMP_INITIAL_CAPITAL",
    "scalping": "BOT_SCALPING_INITIAL_CAPITAL",
    "momentum": "BOT_MOMENTUM_INITIAL_CAPITAL",
}.items():
    _override = _optional_float_env(_env_name)
    if _override is not None and _override > 0:
        _resolved_initial_capitals[_system_key] = _override

# API Binance: Futures (fapi) vs Spot (api)
# True = usa fapi.binance.com (Futures USDT-M) — padrao para scalping
# False = usa api.binance.com (Spot) — fallback
USE_FUTURES_API = True

# ── Spot endpoints (api.binance.com) ──
BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_SPOT_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_SPOT_TICKER_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr"

# ── Futures endpoints (fapi.binance.com) ──
BINANCE_FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_FUTURES_BALANCE_URL = "https://fapi.binance.com/fapi/v2/balance"

# Endpoint derivado (scalping usa Futures, resto usa Spot)
BINANCE_KLINES_URL = (
    BINANCE_FUTURES_KLINES_URL if USE_FUTURES_API else BINANCE_SPOT_KLINES_URL
)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

# Simbolos para scalping (microestrutura): foco em BTC/ETH para maior
# densidade de liquidacoes e sinais. Override via env var (comma-separated).
_scalping_symbols_raw = os.environ.get("SCALPING_SYMBOLS", "").strip()
SCALPING_SYMBOLS = (
    [s.strip().upper() for s in _scalping_symbols_raw.split(",") if s.strip()]
    if _scalping_symbols_raw
    else ["BTCUSDT", "ETHUSDT"]
)

INTERVAL = "5m"
INTERVAL_HTF = "1h"
LIMIT = 100

# Janelas dos indicadores
SMA_SHORT = 9
VOLUME_WINDOW = 20
SMA_LONG = 21
RSI_WINDOW = 14
BREAKOUT_WINDOW = 10

# Thresholds do RSI
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_BUY_ZONE = (30, 45)
RSI_SELL_ZONE = (55, 70)

# Thresholds de score (M3 FIX: ajustados para novo scoring 0-5.5)
# Antes: 4/7 = 57% -> 3.0/5.5 = 55% (mantém proporcao)
# Grupo de tendencia vale ate 1.5pts + 4 criterios individuais de 1pt = 5.5 max
SIGNAL_SCORE_MIN = 3.0
PRE_SIGNAL_SCORE_MIN = 2.5
PRE_SIGNAL_DIFF_MIN = 1.5
OBSERVATION_SCORE_MIN = 1.5

# Threshold de alerta
ALERT_PRIORITY_MIN = 85

# Força mínima do candle para pontuar (body_ratio)
BODY_RATIO_MIN = 0.6

# Fees Binance Futures (taker)
SINGLE_SIDE_FEE_PCT = 0.04          # 0.04% por leg
ROUND_TRIP_FEE_PCT = 0.08           # 0.04% x 2

# Backtest
BACKTEST_DAYS = 180

# Paper Trading
PAPER_INITIAL_CAPITAL = _resolved_initial_capitals["paper"]
PAPER_MAX_POSITIONS = 3          # maximo de posicoes abertas simultaneas
PAPER_REWARD_RATIO = 2.0         # TP = SL_distance * reward_ratio

# Cooldown apos stop_loss
COOLDOWN_MINUTES = 30            # minutos de espera antes de reabrir posicao no mesmo ativo

# SL dinamico baseado em ATR
ATR_SL_MULTIPLIER = 1.5          # SL = ATR * 1.5
ATR_TP_MULTIPLIER = 2.0          # TP = ATR * 2.0
ATR_SL_FLOOR_PCT = 2.0           # SL minimo de 2% independente do ATR

# Multi-Agent Trading
AGENT_INITIAL_CAPITAL = _resolved_initial_capitals["agent"]

# Pump Trading capital
PUMP_INITIAL_CAPITAL = _resolved_initial_capitals["pump"]
SCALPING_INITIAL_CAPITAL = _resolved_initial_capitals["scalping"]
MOMENTUM_INITIAL_CAPITAL = _resolved_initial_capitals["momentum"]
PORTFOLIO_INITIAL_CAPITAL = sum(_resolved_initial_capitals.values())

# Pump Scanner
PUMP_VOLUME_MULTIPLIER = 5       # volume atual > 5x a media = anomalia
PUMP_PRICE_CHANGE_MIN = 2.0      # % minima de mudanca de preco para alertar
PUMP_SCAN_INTERVAL = 30          # segundos entre scans (acelerando coleta de dados)
PUMP_TOP_COINS = 100             # quantas moedas monitorar (acelerando coleta de dados)

# Agent Execution Policy
AGENT_REAL_EXECUTION_ENABLED = os.environ.get("AGENT_REAL_EXECUTION_ENABLED", "").strip().lower() in ("true", "1", "yes")
AGENT_REAL_MIN_CONFIDENCE = 80
AGENT_REAL_MIN_SETUP_QUALITY = {"A", "B"}
AGENT_REAL_BLOCKED_ENTRY_QUALITY = {"late", "poor"}
AGENT_REAL_BLOCKED_INVALIDATION_QUALITY = {"unclear", "missing"}

# Circuit Breaker
DAILY_LOSS_LIMIT_PCT = 5.0       # para de operar se perder X% num dia
DAILY_MAX_TRADES = 9999          # sem limite (paper trading, acelerando coleta de dados)

# Pump Trading
PUMP_MAX_POSITIONS = 5           # maximo de posicoes simultaneas
PUMP_TRAILING_STOP = 3.0         # % do trailing stop
PUMP_MAX_POSITION_TIME = 30      # minutos max em uma posicao
PUMP_POSITION_SIZE_PCT = 2.0     # % do capital por trade
PUMP_RSI_EXHAUSTION = 80         # RSI acima disso = pump exaurindo
PUMP_DUMP_RETRACE_PCT = 4.5      # % de retrace para detectar dump (PUMP_TRAILING_STOP * 1.5)
PUMP_DUMP_SPEED_PCT = 2.0        # % de queda em PUMP_DUMP_SPEED_CANDLES candles = dump por velocidade
PUMP_DUMP_SPEED_CANDLES = 3      # janela de candles para medir velocidade de queda
PUMP_CAPITAL = PUMP_INITIAL_CAPITAL  # capital separado para pump trades

# V2.1b Confluence: motor primario OI + FundingFilter veto + BasisConfidenceAdjuster
# Mudar para True apos paper test validar OOS
V2_1B_ENABLED = False

# V2.1b Paper side-by-side: roda V2.1b em paralelo com V2 para comparacao
# Quando True, ambos V2 e V2.1b rodam a cada ciclo com estado/DB separados
V2_1B_PAPER_ENABLED = os.environ.get("V2_1B_PAPER_ENABLED", "true").strip().lower() in ("true", "1", "yes")

# Paper/Agent Trader: desligar para focar em microestrutura
# False = desativa paper_trader e trade_agents no loop principal
PAPER_TRADER_ENABLED = os.environ.get("PAPER_TRADER_ENABLED", "true").strip().lower() in ("true", "1", "yes")
AGENT_TRADER_ENABLED = os.environ.get("AGENT_TRADER_ENABLED", "true").strip().lower() in ("true", "1", "yes")
MOMENTUM_TRADER_ENABLED = os.environ.get("MOMENTUM_TRADER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
MOMENTUM_SYMBOLS = [s.strip() for s in os.environ.get("MOMENTUM_SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
MOMENTUM_MAX_POSITIONS = 1

# Custo de execucao do momentum paper (gross -> net). So MEDE/debita custo —
# nao altera a logica nem os params congelados da v1.1.
# Default = taker REAL Binance USDT-M Futures VIP 0 = 0.05%/lado (round-trip
# 0.10%), confirmado 2026 (FAQ oficial). NAO usamos SINGLE_SIDE_FEE_PCT (0.04):
# e a taxa taker ANTIGA da Binance e subestima o custo real para capital real.
# MOMENTUM_PAPER_FEE_RATE seta ambos os lados; entry/exit podem ser individuais.
_MOMENTUM_TAKER_FEE_PCT = 0.05
_momentum_fee_default = os.environ.get("MOMENTUM_PAPER_FEE_RATE", str(_MOMENTUM_TAKER_FEE_PCT))
MOMENTUM_PAPER_ENTRY_FEE_RATE = float(os.environ.get("MOMENTUM_PAPER_ENTRY_FEE_RATE", _momentum_fee_default))
MOMENTUM_PAPER_EXIT_FEE_RATE = float(os.environ.get("MOMENTUM_PAPER_EXIT_FEE_RATE", _momentum_fee_default))
MOMENTUM_PAPER_LIQUIDITY = os.environ.get("MOMENTUM_PAPER_LIQUIDITY", "taker").strip().lower()
MOMENTUM_PAPER_FEE_MODEL = os.environ.get("MOMENTUM_PAPER_FEE_MODEL", f"flat_{MOMENTUM_PAPER_LIQUIDITY}")

# Breakout 5m Strategy
BREAKOUT_TRADER_ENABLED = os.environ.get("BREAKOUT_TRADER_ENABLED", "false").strip().lower() in ("true", "1", "yes")
BREAKOUT_SYMBOLS = [s.strip() for s in os.environ.get("BREAKOUT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()]
BREAKOUT_MAX_POSITIONS = 2
BREAKOUT_INITIAL_CAPITAL = float(os.environ.get("BOT_BREAKOUT_INITIAL_CAPITAL", "1000"))

# Dashboard Auth (HTTP Basic Auth para rotas POST)
# Defina via env vars DASHBOARD_USER / DASHBOARD_PASS no Pi.
# Se ambas estiverem vazias, auth fica desabilitada (apenas rede local confiavel).
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "").strip()
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "").strip()
