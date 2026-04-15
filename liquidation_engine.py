"""
Motor 2 — Liquidation Cascade + OI Divergence.

Detecta cascatas de liquidacao forcada e divergencias entre preco e open interest.
Quando liquidacoes em massa ocorrem, geram momentum forcado na direcao oposta.
Quando OI diverge do preco, o movimento e fraco e tende a reverter.

Score (0-100):
- Magnitude de liquidacoes: 0-40 pontos (normalizado pelo volume diario)
  NOTA: quando dados de liquidacao vem via proxy (aggTrades), o score
  de liquidacao e capeado em 20/40 max. Dados reais requerem WebSocket
  forceOrder@{symbol} (nao implementado).
- OI divergencia magnitude: 0-30 pontos (dados publicos, totalmente validos)
- Velocidade da divergencia: 0-20 pontos (divergiu em 5min vs 1h)
- Direcao alinhada com regime: 0-10 pontos

Dependencias:
- market_data.collect_microstructure() para funding, OI, liquidacoes, basis
- candles_5m (DataFrame OHLCV) para VWAP e price range — sem candles,
  os filtros de range e VWAP sao ignorados (sinal ainda pode ser gerado
  via OI divergencia + liquidacoes, mas sem confirmacao de preco).
"""
import logging
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from signal_types import Direction, Signal

logger = logging.getLogger("engine.liquidation")

# ── Thresholds (calibrar via backtest) ───────────────────────────────────────
# Liquidation volume minimo em USD para considerar relevante
LIQUIDATION_MIN_USD = 50_000       # small-cap filter
LIQUIDATION_STRONG_USD = 500_000   # cascata forte
LIQUIDATION_EXTREME_USD = 2_000_000  # cascata extrema

# OI change thresholds
OI_MIN_CHANGE_PCT = 0.5   # abaixo disso = mercado parado
OI_STRONG_CHANGE_PCT = 2.0  # divergencia significativa
OI_EXTREME_CHANGE_PCT = 5.0  # divergencia extrema

# Price range filter
PRICE_RANGE_MIN_PCT = 0.3  # range minimo na ultima hora para considerar setup

# Proxy score cap: quando dados de liquidacao vem via aggTrades (proxy),
# a precisao e ~70%, entao limitamos o score de liquidacao a metade do max.
PROXY_LIQ_SCORE_CAP = 20  # max 20/40 pontos com dados proxy


class LiquidationEngine:
    """Motor de deteccao de cascatas de liquidacao e divergencia OI/preco."""

    SOURCE = "liquidation_cascade"

    def analyze(
        self,
        symbol: str,
        market_data: Dict,
        regime: str,
        candles_5m: Optional[pd.DataFrame] = None,
    ) -> Signal:
        """Analisa condicoes de liquidacao cascade e OI divergence.

        Args:
            symbol: Par de trading (ex: BTCUSDT)
            market_data: Retorno de collect_microstructure()
            regime: Label do regime (TRENDING, WEAK_TREND, RANGING, UNKNOWN)
            candles_5m: DataFrame OHLCV 5m para VWAP e price range (opcional)

        Returns:
            Signal com direcao, forca e score em metadata.
        """
        now_str = datetime.now().isoformat()
        neutral = Signal(
            direction=Direction.NEUTRAL, strength=0.0, timestamp=now_str,
            source=self.SOURCE, symbol=symbol, price=0.0,
            valid=False, reason="Sem sinal",
        )

        # ── Extrair dados de microestrutura ──────────────────────────────
        liq_vol_long = market_data.get("liquidation_vol_long", 0.0)
        liq_vol_short = market_data.get("liquidation_vol_short", 0.0)
        liq_total = liq_vol_long + liq_vol_short
        liq_is_proxy = market_data.get("liquidation_is_proxy", market_data.get("is_proxy", False))
        oi_change_1h = market_data.get("oi_change_1h_pct", 0.0)
        oi_change_4h = market_data.get("oi_change_4h_pct", 0.0)
        open_interest = market_data.get("open_interest", 0.0)

        # ── Calcular preco e VWAP se candles disponiveis ─────────────────
        price = 0.0
        vwap = 0.0
        price_range_1h_pct = 0.0

        if candles_5m is not None and len(candles_5m) >= 12:
            price = float(candles_5m["close"].iloc[-1])
            neutral.price = price

            # VWAP das ultimas 12 candles (1h em 5m)
            recent = candles_5m.iloc[-12:]
            typical_price = (recent["high"] + recent["low"] + recent["close"]) / 3
            cum_tp_vol = (typical_price * recent["volume"]).sum()
            cum_vol = recent["volume"].sum()
            if cum_vol > 0:
                vwap = cum_tp_vol / cum_vol

            # Price range da ultima hora
            high_1h = recent["high"].max()
            low_1h = recent["low"].min()
            if low_1h > 0:
                price_range_1h_pct = (high_1h - low_1h) / low_1h * 100

            # Price direction (close now vs close 1h ago)
            price_1h_ago = float(recent["close"].iloc[0])
            price_change_1h_pct = ((price - price_1h_ago) / price_1h_ago * 100) if price_1h_ago > 0 else 0.0
        else:
            price_change_1h_pct = 0.0

        # ── FILTRO 1: Mercado parado (OI mudou <0.5% na ultima hora) ─────
        if abs(oi_change_1h) < OI_MIN_CHANGE_PCT and liq_total < LIQUIDATION_MIN_USD:
            neutral.reason = f"Mercado parado: OI change {oi_change_1h:.2f}%, liq ${liq_total:.0f}"
            logger.info("LIQ %s: %s", symbol, neutral.reason)
            return neutral

        # ── FILTRO 2: Liquidacoes muito pequenas ─────────────────────────
        if liq_total < LIQUIDATION_MIN_USD and abs(oi_change_1h) < OI_MIN_CHANGE_PCT:
            neutral.reason = f"Liquidacoes insuficientes: ${liq_total:.0f} < ${LIQUIDATION_MIN_USD}"
            logger.info("LIQ %s: %s", symbol, neutral.reason)
            return neutral

        # ── FILTRO 3: Range apertado com OI estavel ──────────────────────
        if candles_5m is not None and len(candles_5m) >= 12:
            if price_range_1h_pct < PRICE_RANGE_MIN_PCT and abs(oi_change_1h) < OI_MIN_CHANGE_PCT:
                neutral.reason = f"Range apertado: {price_range_1h_pct:.2f}% com OI estavel"
                logger.info("LIQ %s: %s", symbol, neutral.reason)
                return neutral

        # ── Determinar direcao do sinal ──────────────────────────────────
        direction = Direction.NEUTRAL
        signal_subtype = "unknown"
        signal_reasons = []

        # Cenario 1: Cascata de liquidacoes SHORT -> LONG
        # Shorts sendo liquidados = preco subindo forcado, momentum long
        # OI > 0 = dinheiro novo entrando, OU liq muito forte confirma cascata
        if liq_vol_short > LIQUIDATION_MIN_USD and liq_vol_short > liq_vol_long * 1.5:
            if oi_change_1h > 0 or liq_vol_short > 200_000:
                direction = Direction.LONG
                signal_subtype = "cascade"
                signal_reasons.append(
                    f"Cascata SHORT: ${liq_vol_short:.0f} liquidados, OI {oi_change_1h:+.2f}%"
                )

        # Cenario 2: Cascata de liquidacoes LONG -> SHORT
        # Longs sendo liquidados = preco caindo forcado, momentum short
        # OI <= 0 = posicoes fechando, OU liq muito forte confirma cascata
        if liq_vol_long > LIQUIDATION_MIN_USD and liq_vol_long > liq_vol_short * 1.5:
            if oi_change_1h <= 0 or liq_vol_long > 200_000:
                direction = Direction.SHORT
                signal_subtype = "cascade"
                signal_reasons.append(
                    f"Cascata LONG: ${liq_vol_long:.0f} liquidados, OI {oi_change_1h:+.2f}%"
                )

        # Cenario 3: OI Divergencia — preco sobe, OI cai (distribuicao)
        if price_change_1h_pct > 0.3 and oi_change_1h < -OI_MIN_CHANGE_PCT:
            direction = Direction.SHORT
            signal_subtype = "divergence"
            signal_reasons.append(
                f"OI divergencia bearish: preco +{price_change_1h_pct:.2f}%, OI {oi_change_1h:+.2f}%"
            )

        # Cenario 4: Preco cai E OI sobe (novos shorts entrando com forca)
        if price_change_1h_pct < -0.3 and oi_change_1h > OI_MIN_CHANGE_PCT:
            # Pode ser bearish continuation OU reversal setup
            # Se liquidacoes de longs sao altas, e bearish continuation
            if liq_vol_long > LIQUIDATION_MIN_USD:
                direction = Direction.SHORT
                signal_subtype = "continuation"
                signal_reasons.append(
                    f"Shorts acumulando: preco {price_change_1h_pct:+.2f}%, OI +{oi_change_1h:.2f}%"
                )
            else:
                # OI subindo com preco caindo mas sem liquidacoes = possivel reversal
                direction = Direction.LONG
                signal_subtype = "divergence"
                signal_reasons.append(
                    f"Possivel reversal: preco {price_change_1h_pct:+.2f}%, OI +{oi_change_1h:.2f}%, sem liq"
                )

        if direction == Direction.NEUTRAL:
            neutral.reason = "Nenhum cenario de liquidacao/divergencia detectado"
            logger.info("LIQ %s: %s", symbol, neutral.reason)
            return neutral

        # ── Calcular score por componentes ───────────────────────────────
        score_liq = self._score_liquidation_magnitude(liq_vol_long, liq_vol_short, direction)

        # Liquidation data via proxy (aggTrades heuristic) = cap score at 20/40
        # Dados reais de liquidacao requerem WebSocket forceOrder@{symbol}
        if liq_is_proxy and score_liq > PROXY_LIQ_SCORE_CAP:
            logger.info(
                "LIQ %s: score_liq %d capped to %d (proxy data)",
                symbol, score_liq, PROXY_LIQ_SCORE_CAP,
            )
            score_liq = PROXY_LIQ_SCORE_CAP

        score_oi = self._score_oi_divergence(oi_change_1h, oi_change_4h, price_change_1h_pct, direction)
        score_speed = self._score_divergence_speed(oi_change_1h, oi_change_4h)
        score_regime = self._score_regime_alignment(direction, regime)

        total_score = score_liq + score_oi + score_speed + score_regime

        logger.info(
            "Signal %s %s subtype=%s score=%d (liq=%d%s oi=%d speed=%d regime=%d) | %s",
            symbol, direction.value, signal_subtype, total_score,
            score_liq, " [PROXY]" if liq_is_proxy else "",
            score_oi, score_speed, score_regime,
            "; ".join(signal_reasons),
        )

        # ── VWAP filter (from spec: preco acima do VWAP para LONG) ───────
        vwap_aligned = True
        if vwap > 0 and price > 0:
            if direction == Direction.LONG and price < vwap:
                vwap_aligned = False
                logger.info("LIQ %s: LONG mas preco %.2f < VWAP %.2f (penalizado)", symbol, price, vwap)
                total_score = int(total_score * 0.7)  # penalize but don't discard
            elif direction == Direction.SHORT and price > vwap:
                # For shorts, price above VWAP can still be valid (distribution)
                pass

        # ── Construir Signal ─────────────────────────────────────────────
        strength = min(total_score / 100.0, 1.0)
        is_valid = total_score >= 40  # threshold minimo para sinal valido

        return Signal(
            direction=direction,
            strength=strength,
            timestamp=now_str,
            source=self.SOURCE,
            symbol=symbol,
            price=price,
            valid=is_valid,
            reason="; ".join(signal_reasons),
            metadata={
                "total_score": total_score,
                "signal_subtype": signal_subtype,
                "score_liquidation": score_liq,
                "score_oi_divergence": score_oi,
                "score_speed": score_speed,
                "score_regime": score_regime,
                "liq_vol_long": liq_vol_long,
                "liq_vol_short": liq_vol_short,
                "liq_is_proxy": liq_is_proxy,
                "oi_change_1h_pct": oi_change_1h,
                "oi_change_4h_pct": oi_change_4h,
                "price_change_1h_pct": round(price_change_1h_pct, 2),
                "vwap": round(vwap, 2),
                "vwap_aligned": vwap_aligned,
                "regime": regime,
            },
        )

    # ── Score component calculators ──────────────────────────────────────

    def _score_liquidation_magnitude(
        self,
        liq_vol_long: float,
        liq_vol_short: float,
        direction: Direction,
    ) -> int:
        """Magnitude de liquidacoes: 0-40 pontos."""
        # Usar volume relevante para a direcao
        if direction == Direction.LONG:
            relevant_vol = liq_vol_short  # shorts sendo liquidados
        elif direction == Direction.SHORT:
            relevant_vol = liq_vol_long   # longs sendo liquidados
        else:
            return 0

        if relevant_vol < LIQUIDATION_MIN_USD:
            return 0
        elif relevant_vol < LIQUIDATION_STRONG_USD:
            # Linear scale 0-20 entre min e strong
            ratio = (relevant_vol - LIQUIDATION_MIN_USD) / (LIQUIDATION_STRONG_USD - LIQUIDATION_MIN_USD)
            return int(ratio * 20)
        elif relevant_vol < LIQUIDATION_EXTREME_USD:
            # Linear scale 20-35 entre strong e extreme
            ratio = (relevant_vol - LIQUIDATION_STRONG_USD) / (LIQUIDATION_EXTREME_USD - LIQUIDATION_STRONG_USD)
            return 20 + int(ratio * 15)
        else:
            return 40

    def _score_oi_divergence(
        self,
        oi_change_1h: float,
        oi_change_4h: float,
        price_change_1h_pct: float,
        direction: Direction,
    ) -> int:
        """OI divergencia magnitude: 0-30 pontos."""
        # Detectar divergencia: preco e OI movendo em direcoes opostas
        # ou OI movendo fortemente na direcao que confirma o sinal

        oi_abs = abs(oi_change_1h)

        if oi_abs < OI_MIN_CHANGE_PCT:
            return 0

        # Verificar se ha divergencia real
        has_divergence = False

        if direction == Direction.SHORT:
            # Preco sobe + OI cai = distribuicao (bearish divergence)
            if price_change_1h_pct > 0 and oi_change_1h < 0:
                has_divergence = True
            # Preco cai + OI sobe = shorts acumulando
            if price_change_1h_pct < 0 and oi_change_1h > 0:
                has_divergence = True

        elif direction == Direction.LONG:
            # OI subindo com preco estavel/subindo = dinheiro novo entrando
            if oi_change_1h > 0 and price_change_1h_pct >= -0.1:
                has_divergence = True
            # Preco cai + OI sobe sem liq = possivel acumulacao
            if price_change_1h_pct < 0 and oi_change_1h > 0:
                has_divergence = True

        if not has_divergence:
            return 5  # small base score for OI movement without clear divergence

        if oi_abs < OI_STRONG_CHANGE_PCT:
            ratio = (oi_abs - OI_MIN_CHANGE_PCT) / (OI_STRONG_CHANGE_PCT - OI_MIN_CHANGE_PCT)
            return 5 + int(ratio * 10)  # 5-15
        elif oi_abs < OI_EXTREME_CHANGE_PCT:
            ratio = (oi_abs - OI_STRONG_CHANGE_PCT) / (OI_EXTREME_CHANGE_PCT - OI_STRONG_CHANGE_PCT)
            return 15 + int(ratio * 10)  # 15-25
        else:
            return 30

    def _score_divergence_speed(
        self,
        oi_change_1h: float,
        oi_change_4h: float,
    ) -> int:
        """Velocidade da divergencia: 0-20 pontos.

        Se a maior parte da mudanca de OI aconteceu na ultima hora (vs 4h),
        o sinal e mais urgente e forte.
        """
        if abs(oi_change_4h) < OI_MIN_CHANGE_PCT:
            # Sem historico de 4h para comparar, usar apenas 1h
            if abs(oi_change_1h) >= OI_STRONG_CHANGE_PCT:
                return 15  # mudanca recente e forte
            elif abs(oi_change_1h) >= OI_MIN_CHANGE_PCT:
                return 8
            return 0

        # Razao: quanto do movimento de 4h aconteceu na ultima hora
        if abs(oi_change_4h) > 0:
            speed_ratio = abs(oi_change_1h) / abs(oi_change_4h)
        else:
            speed_ratio = 0

        # speed_ratio > 0.5 = maioria do movimento e recente
        if speed_ratio > 0.8:
            return 20  # quase toda a mudanca foi na ultima hora
        elif speed_ratio > 0.5:
            return 14
        elif speed_ratio > 0.3:
            return 8
        else:
            return 3  # mudanca distribuida no tempo, menos urgente

    def _score_regime_alignment(
        self,
        direction: Direction,
        regime: str,
    ) -> int:
        """Direcao alinhada com regime: 0-10 pontos.

        Em TRENDING, sinais na direcao da tendencia sao mais confiaveis.
        Em RANGING, sinais de reversao de liquidacao sao mais confiaveis.
        """
        if regime == "TRENDING":
            return 10  # liquidacoes em tendencia forte amplificam o movimento
        elif regime == "WEAK_TREND":
            return 6
        elif regime == "RANGING":
            return 4  # em range, cascata pode ser noise
        else:
            return 2  # UNKNOWN
