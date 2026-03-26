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

# Thresholds de score
SIGNAL_SCORE_MIN = 4
PRE_SIGNAL_SCORE_MIN = 3
PRE_SIGNAL_DIFF_MIN = 2
OBSERVATION_SCORE_MIN = 2

# Threshold de alerta
ALERT_PRIORITY_MIN = 85

# Força mínima do candle para pontuar (body_ratio)
BODY_RATIO_MIN = 0.6

# Backtest
BACKTEST_DAYS = 30
STOP_LOSS_PCT = 1.5

# Stop Loss por ativo (otimizado via backtest)
STOP_LOSS_MAP = {
    "BTCUSDT": 3.0,
    "ETHUSDT": 3.0,
    "SOLUSDT": 1.0,
    "BNBUSDT": 2.5,
    "XRPUSDT": 2.5,
    "DOGEUSDT": 1.0,
}

# Paper Trading
PAPER_INITIAL_CAPITAL = 10000
PAPER_MAX_POSITIONS = 3          # maximo de posicoes abertas simultaneas
PAPER_REWARD_RATIO = 2.0         # TP = SL_distance * reward_ratio

# Cooldown apos stop_loss
COOLDOWN_MINUTES = 30            # minutos de espera antes de reabrir posicao no mesmo ativo

# SL dinamico baseado em ATR
ATR_SL_MULTIPLIER = 1.5          # SL = ATR * 1.5
ATR_TP_MULTIPLIER = 2.0          # TP = ATR * 2.0
ATR_SL_FLOOR_PCT = 2.0           # SL minimo de 2% independente do ATR

# Multi-Agent Trading
AGENT_INITIAL_CAPITAL = 10000

# Agent V2 (Claude como decisor principal)
AGENT_MODEL = "claude-haiku-4-5-20251001"
AGENT_MAX_TOKENS = 1024
AGENT_TEMPERATURE = 0.3
AGENT_RISK_PER_TRADE_PCT = 2.0      # % do capital por trade (baseado em risco no SL)
AGENT_MAX_RISK_PER_TRADE_PCT = 5.0  # teto absoluto de exposicao
AGENT_MIN_CONFIDENCE = 60           # confianca minima para abrir posicao (0-100)
AGENT_MIN_RR = 1.5                  # R/R minimo aceito (tp_pct / sl_pct)
AGENT_POSITION_TIMEOUT_MIN = 240    # fecha posicao automaticamente apos X minutos

# Pump Trading capital
PUMP_INITIAL_CAPITAL = 5000

# Pump Scanner
PUMP_VOLUME_MULTIPLIER = 5       # volume atual > 5x a media = anomalia
PUMP_PRICE_CHANGE_MIN = 2.0      # % minima de mudanca de preco para alertar
PUMP_SCAN_INTERVAL = 60          # segundos entre scans
PUMP_TOP_COINS = 50              # quantas moedas monitorar

# Circuit Breaker
DAILY_LOSS_LIMIT_PCT = 5.0       # para de operar se perder X% num dia
DAILY_MAX_TRADES = 20            # maximo de trades por dia

# Pump Trading
PUMP_TRAILING_STOP = 3.0         # % do trailing stop
PUMP_MAX_POSITION_TIME = 30      # minutos max em uma posicao
PUMP_POSITION_SIZE_PCT = 2.0     # % do capital por trade
PUMP_RSI_EXHAUSTION = 80         # RSI acima disso = pump exaurindo
PUMP_DUMP_RETRACE_PCT = 25       # % de retrace do pump para entrar short
PUMP_CAPITAL = 5000              # capital separado para pump trades