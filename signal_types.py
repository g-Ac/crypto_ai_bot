"""
Tipos compartilhados para o sistema de scalping.

Define as dataclasses usadas por todos os motores de sinal,
confluencia e risk manager para manter consistencia na interface.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Direction(Enum):
    """Direcao do sinal de trading."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class Signal:
    """Sinal padronizado retornado por cada motor de estrategia."""
    direction: Direction
    strength: float          # 0.0 a 1.0
    timestamp: str           # ISO format
    source: str              # nome do motor (ex: "volume_breakout")
    symbol: str
    price: float
    # Niveis calculados pelo motor
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    sl_distance_pct: float = 0.0
    rr_ratio: float = 0.0
    # Metadados extras do motor
    metadata: dict = field(default_factory=dict)
    # Motivo do sinal ou bloqueio
    reason: str = ""
    # Se o sinal passou todos os filtros
    valid: bool = False


@dataclass
class ConfluenceResult:
    """Resultado da analise de confluencia entre os 3 motores."""
    direction: Direction
    score: int                  # 0 a 3
    meets_threshold: bool       # True se score >= 2
    signals: list = field(default_factory=list)  # lista de Signal
    position_size_pct: float = 0.0   # % do tamanho maximo (0, 50, 100)
    leverage: int = 0                # 0, 3 ou 5
    reason: str = ""
    # Melhor sinal para SL/TP (o motor com melhor RR)
    best_signal: Optional[Signal] = None


@dataclass
class RiskDecision:
    """Decisao do risk manager sobre se o trade pode ser executado."""
    approved: bool
    reason: str
    position_size_usd: float = 0.0
    sl_price: float = 0.0
    tp1_price: float = 0.0
    tp2_price: float = 0.0
    leverage: int = 1
    risk_amount_usd: float = 0.0
    # Metadados de risco
    funding_rate: float = 0.0
    atr_elevated: bool = False
    bb_bandwidth_low: bool = False
    in_cooldown: bool = False
    near_news_event: bool = False


@dataclass
class ScalpingConfig:
    """Configuracao centralizada da estrategia de scalping."""
    # Modo de operacao
    paper_mode: bool = True            # True = paper trading, False = real trading

    # Capital e risco
    initial_capital: float = 10000.0
    min_capital: float = 100.0         # capital minimo para operar ($)
    max_risk_pct: float = 2.0         # % do capital por trade
    max_positions: int = 3

    # Slippage
    slippage_pct: float = 0.05         # 0.05% buffer de slippage em SL/TP

    # Cooldown
    cooldown_candles: int = 3          # candles no TF de entrada

    # Funding rate
    funding_rate_threshold: float = 0.05  # |funding| > 0.05% = cuidado
    funding_rate_reduce_pct: float = 50.0 # reduzir size em 50%

    # ATR check
    atr_elevation_threshold: float = 50.0  # ATR subiu > 50% vs media

    # BB bandwidth global (15m)
    bb_bandwidth_min_15m: float = 1.2  # % - abaixo disso, nao operar

    # SL maximo por abordagem
    max_sl_volume_breakout: float = 0.8
    max_sl_rsi_bb: float = 0.6
    max_sl_ema_crossover: float = 0.7

    # RR minimo por abordagem
    min_rr_volume_breakout: float = 1.8
    min_rr_rsi_bb: float = 1.5
    min_rr_ema_crossover: float = 2.0

    # News filter
    news_filter_enabled: bool = True
    news_minutes_before: int = 15     # bloquear N min antes do evento
    news_minutes_after: int = 10      # bloquear N min apos o evento

    # Confluence
    min_confluence_score: int = 2

    # Volume Breakout
    vb_volume_multiplier: float = 2.5
    vb_volume_period: int = 20
    vb_breakout_period: int = 5
    vb_body_ratio_min: float = 0.6
    vb_ema_period: int = 20
    vb_wick_max_pct: float = 0.4
    vb_atr_min_pct: float = 0.15
    vb_spread_max_pct: float = 0.05
    vb_max_consecutive_spikes: int = 2
    vb_sl_atr_mult: float = 0.5
    vb_tp1_atr_mult: float = 1.0
    vb_tp2_atr_mult: float = 2.2

    # RSI + BB Reversal
    rsi_oversold: float = 32.0
    rsi_overbought: float = 68.0
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_bb_vol_multiplier: float = 1.5
    rsi_bb_vol_period: int = 20
    rsi_max_extreme_candles: int = 6
    rsi_bb_bandwidth_min: float = 0.8
    rsi_bb_max_touches: int = 2
    rsi_bb_atr_min_pct: float = 0.10
    rsi_bb_sl_atr_mult: float = 0.3
    rsi_bb_sl_lookback: int = 3

    # EMA Crossover
    ema_fast: int = 9
    ema_slow: int = 21
    ema_context: int = 50
    ema_slope_lookback: int = 3
    ema_max_gap_pct: float = 0.3
    ema_max_retest_candles: int = 5
    ema_htf_entangle_pct: float = 0.1
    ema_max_crosses_15: int = 3
    ema_sl_atr_mult: float = 0.2
    ema_tp1_atr_mult: float = 1.5
    ema_tp2_atr_mult: float = 2.5
    ema_tp2_high_lookback: int = 20
