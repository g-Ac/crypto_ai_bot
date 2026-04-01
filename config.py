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
}.items():
    _override = _optional_float_env(_env_name)
    if _override is not None and _override > 0:
        _resolved_initial_capitals[_system_key] = _override

# API Binance: Futures (fapi) vs Spot (api)
# True = usa fapi.binance.com (Futures USDT-M) — padrao para scalping
# False = usa api.binance.com (Spot) — fallback
USE_FUTURES_API = True

# Endpoints derivados
BINANCE_KLINES_URL = (
    "https://fapi.binance.com/fapi/v1/klines"
    if USE_FUTURES_API
    else "https://api.binance.com/api/v3/klines"
)
BINANCE_FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]

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
PORTFOLIO_INITIAL_CAPITAL = sum(_resolved_initial_capitals.values())

# Pump Scanner
PUMP_VOLUME_MULTIPLIER = 5       # volume atual > 5x a media = anomalia
PUMP_PRICE_CHANGE_MIN = 2.0      # % minima de mudanca de preco para alertar
PUMP_SCAN_INTERVAL = 60          # segundos entre scans
PUMP_TOP_COINS = 50              # quantas moedas monitorar

# Circuit Breaker
DAILY_LOSS_LIMIT_PCT = 5.0       # para de operar se perder X% num dia
DAILY_MAX_TRADES = 20            # maximo de trades por dia

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

# Dashboard Auth (HTTP Basic Auth para rotas POST)
# Defina via env vars DASHBOARD_USER / DASHBOARD_PASS no Pi.
# Se ambas estiverem vazias, auth fica desabilitada (apenas rede local confiavel).
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "").strip()
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "").strip()
