"""
Sistema de Confluencia -- combina os 3 motores de sinal.

Cada motor que confirma a mesma direcao = +1 ponto.
- 1/3: nao operar
- 2/3: 50% do tamanho maximo, alavancagem 3x
- 3/3: 100% do tamanho maximo, alavancagem 5x

Sinais opostos entre motores = nao operar (mercado indeciso).
Verificar a cada candle fechado no timeframe de entrada.
"""
import logging
from datetime import datetime
from typing import Optional, List

import pandas as pd

from signal_types import Direction, Signal, ConfluenceResult, ScalpingConfig
from scalping_data import fetch_candles, add_scalping_indicators, clear_cache
import volume_breakout
import rsi_bb_reversal
import ema_crossover

logger = logging.getLogger("scalping.confluence")


def _select_best_signal(signals: List[Signal]) -> Optional[Signal]:
    """
    Seleciona o melhor sinal entre os validos para usar seus niveis de SL/TP.

    Criterios: melhor RR ratio, depois maior forca.
    """
    valid = [s for s in signals if s.valid]
    if not valid:
        return None

    # Ordenar por RR (maior primeiro), depois por forca (maior primeiro)
    valid.sort(key=lambda s: (s.rr_ratio, s.strength), reverse=True)
    return valid[0]


def analyze(
    symbol: str,
    config: ScalpingConfig,
    df_3m: Optional[pd.DataFrame] = None,
    df_5m: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
) -> ConfluenceResult:
    """
    Executa os 3 motores de sinal e calcula a confluencia.

    Parametros:
        symbol: par de trading
        config: configuracao da estrategia
        df_3m: DataFrame 3m (opcional, sera buscado se None)
        df_5m: DataFrame 5m (opcional, sera buscado se None)
        df_15m: DataFrame 15m (opcional, sera buscado se None)

    Retorna:
        ConfluenceResult com score, direcao e decisao de operacao
    """
    now_str = datetime.now().isoformat()

    # Resultado padrao
    no_trade = ConfluenceResult(
        direction=Direction.NEUTRAL,
        score=0,
        meets_threshold=False,
        reason="Confluencia insuficiente"
    )

    # ============================================================
    # BUSCAR DADOS OHLCV (com cache)
    # ============================================================
    if df_3m is None:
        df_3m = fetch_candles(symbol, "3m", 100)
        if df_3m is not None:
            df_3m = add_scalping_indicators(df_3m)

    if df_5m is None:
        df_5m = fetch_candles(symbol, "5m", 100)
        if df_5m is not None:
            df_5m = add_scalping_indicators(df_5m)

    if df_15m is None:
        df_15m = fetch_candles(symbol, "15m", 100)
        if df_15m is not None:
            df_15m = add_scalping_indicators(df_15m)

    if df_3m is None or df_5m is None:
        no_trade.reason = "Dados OHLCV indisponiveis"
        logger.warning("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # ============================================================
    # EXECUTAR OS 3 MOTORES
    # ============================================================
    logger.info("CONFLUENCE %s: Executando 3 motores...", symbol)

    sig_vb = volume_breakout.analyze(symbol, config, df_3m=df_3m, df_5m=df_5m)
    sig_rsi = rsi_bb_reversal.analyze(symbol, config, df_5m=df_5m, df_15m=df_15m)
    sig_ema = ema_crossover.analyze(symbol, config, df_3m=df_3m, df_15m=df_15m)

    all_signals = [sig_vb, sig_rsi, sig_ema]
    valid_signals = [s for s in all_signals if s.valid]

    logger.info(
        "CONFLUENCE %s: VB=%s(%s) | RSI_BB=%s(%s) | EMA=%s(%s)",
        symbol,
        sig_vb.direction.value, "OK" if sig_vb.valid else sig_vb.reason[:30],
        sig_rsi.direction.value, "OK" if sig_rsi.valid else sig_rsi.reason[:30],
        sig_ema.direction.value, "OK" if sig_ema.valid else sig_ema.reason[:30],
    )

    if not valid_signals:
        no_trade.signals = all_signals
        no_trade.reason = "Nenhum motor gerou sinal valido"
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # ============================================================
    # CONTAR SINAIS POR DIRECAO
    # ============================================================
    long_count = sum(1 for s in valid_signals if s.direction == Direction.LONG)
    short_count = sum(1 for s in valid_signals if s.direction == Direction.SHORT)

    # Verificar sinais opostos
    if long_count > 0 and short_count > 0:
        no_trade.signals = all_signals
        no_trade.reason = f"Sinais opostos: {long_count} LONG vs {short_count} SHORT (mercado indeciso)"
        logger.warning("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    # Determinar direcao dominante
    if long_count > short_count:
        direction = Direction.LONG
        score = long_count
    elif short_count > long_count:
        direction = Direction.SHORT
        score = short_count
    else:
        no_trade.signals = all_signals
        no_trade.reason = "Sem direcao dominante"
        return no_trade

    # ============================================================
    # AVALIAR CONFLUENCIA
    # ============================================================
    same_dir_signals = [s for s in valid_signals if s.direction == direction]
    best_signal = _select_best_signal(same_dir_signals)

    # Score -> tamanho e alavancagem
    if score >= 3:
        position_size_pct = 100.0
        leverage = 5
        classification = "ALTO"
    elif score >= 2:
        position_size_pct = 50.0
        leverage = 3
        classification = "MEDIO"
    else:
        # score == 1: nao operar
        no_trade.signals = all_signals
        no_trade.score = score
        no_trade.reason = f"Confluencia {score}/3 - insuficiente (minimo 2)"
        logger.info("CONFLUENCE %s: %s", symbol, no_trade.reason)
        return no_trade

    meets_threshold = score >= config.min_confluence_score

    reason = (
        f"Confluencia {classification} ({score}/3 {direction.value}) | "
        f"VB={'OK' if sig_vb.valid and sig_vb.direction == direction else 'X'} "
        f"RSI={'OK' if sig_rsi.valid and sig_rsi.direction == direction else 'X'} "
        f"EMA={'OK' if sig_ema.valid and sig_ema.direction == direction else 'X'} | "
        f"Size: {position_size_pct:.0f}% | Leverage: {leverage}x"
    )

    logger.info("CONFLUENCE %s: %s", symbol, reason)

    return ConfluenceResult(
        direction=direction,
        score=score,
        meets_threshold=meets_threshold,
        signals=all_signals,
        position_size_pct=position_size_pct,
        leverage=leverage,
        reason=reason,
        best_signal=best_signal,
    )


def run_cycle(symbols: list, config: ScalpingConfig) -> list:
    """
    Executa um ciclo completo de analise de confluencia para todos os pares.

    Limpa o cache no inicio do ciclo para dados frescos.
    Retorna lista de ConfluenceResult para cada simbolo.
    """
    clear_cache()
    results = []

    for symbol in symbols:
        try:
            result = analyze(symbol, config)
            results.append((symbol, result))
        except Exception as e:
            logger.error("Erro ao analisar %s: %s", symbol, e, exc_info=True)
            results.append((symbol, ConfluenceResult(
                direction=Direction.NEUTRAL,
                score=0,
                meets_threshold=False,
                reason=f"Erro: {e}"
            )))

    return results
