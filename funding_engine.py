"""
Motor 1 -- Funding Rate + Long/Short Ratio.

Quando o mercado esta desequilibrado (muitos longs ou shorts) e pagando caro
para manter posicao, a reversao tem edge estatistico.

Sinais SHORT (funding extremo positivo):
  - Funding rate atual > 0.03%
  - L/S ratio top traders > 65% long (ratio > 1.86)
  - Funding subindo nos ultimos 3 periodos
  - Regime NAO e TRENDING forte (ADX > 35 na direcao do funding)

Sinais LONG (funding extremo negativo):
  - Funding rate atual < -0.02%
  - L/S ratio top traders > 60% short (ratio < 0.67)
  - Funding caindo nos ultimos 3 periodos

Score 0-100:
  - Funding magnitude:       0-40 pts
  - L/S ratio desequilibrio: 0-30 pts
  - Tendencia de crowding:   0-20 pts
  - Alinhamento com regime:  0-10 pts

Filtros:
  - Funding entre -0.01% e 0.02% (zona neutra)
  - Menos de 2h para proximo pagamento de funding
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from signal_types import Direction, Signal

logger = logging.getLogger("engine.funding")

# Thresholds
_FUNDING_SHORT_THRESHOLD = 0.0003   # 0.03%
_FUNDING_LONG_THRESHOLD = -0.0002   # -0.02%
_FUNDING_NEUTRAL_LOW = -0.0001      # -0.01%
_FUNDING_NEUTRAL_HIGH = 0.0002      # 0.02%

# L/S ratio thresholds (ratio > 1 = mais longs)
_LS_CROWDED_LONG = 1.86   # ~65% long
_LS_CROWDED_SHORT = 0.67  # ~60% short

# Funding hours (UTC)
_FUNDING_HOURS = (0, 8, 16)
_MIN_HOURS_TO_FUNDING = 2  # filter: nao operar < 2h antes do pagamento


class FundingEngine:
    """Motor 1: gera sinais baseados em funding rate e L/S ratio."""

    SOURCE = "funding_rate"

    def analyze(
        self,
        symbol: str,
        market_data: Dict,
        regime: str = "UNKNOWN",
        now_utc: Optional[datetime] = None,
    ) -> Signal:
        """Analisa funding rate e L/S ratio para gerar sinal.

        Args:
            symbol: par de trading (ex: BTCUSDT)
            market_data: retorno de collect_microstructure()
            regime: regime de mercado (TRENDING/WEAK_TREND/RANGING/etc)
            now_utc: datetime UTC para teste (default: agora)

        Returns:
            Signal com direction, strength (score/100), metadata
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        funding = market_data.get("funding_rate", 0.0)
        funding_prev1 = market_data.get("funding_rate_prev1", 0.0)
        funding_prev2 = market_data.get("funding_rate_prev2", 0.0)
        ls_ratio_top = market_data.get("ls_ratio_top", 1.0)
        ls_ratio_global = market_data.get("ls_ratio_global", 1.0)

        now_str = now_utc.isoformat()

        # ── FILTRO: Zona neutra de funding ───────────────────────────
        if _FUNDING_NEUTRAL_LOW <= funding <= _FUNDING_NEUTRAL_HIGH:
            return self._neutral(symbol, now_str, funding, ls_ratio_top,
                                 f"Funding {funding*100:.4f}% em zona neutra")

        # ── FILTRO: Proximo ao pagamento de funding ──────────────────
        mins_to_funding = self._minutes_to_next_funding(now_utc)
        if mins_to_funding < _MIN_HOURS_TO_FUNDING * 60:
            return self._neutral(symbol, now_str, funding, ls_ratio_top,
                                 f"Muito proximo ao pagamento ({mins_to_funding}min)")

        # ── Determinar direcao ───────────────────────────────────────
        direction = Direction.NEUTRAL

        if funding >= _FUNDING_SHORT_THRESHOLD:
            direction = Direction.SHORT
        elif funding <= _FUNDING_LONG_THRESHOLD:
            direction = Direction.LONG

        if direction == Direction.NEUTRAL:
            return self._neutral(symbol, now_str, funding, ls_ratio_top,
                                 f"Funding {funding*100:.4f}% sem extremo")

        # ── FILTRO: Regime trending forte na direcao do funding ──────
        # ADX > 35 com preco subindo + funding positivo = trend pode continuar
        if regime == "TRENDING":
            # In strong trend, funding extremes may persist — reduced but not filtered
            pass

        # ── Score components ─────────────────────────────────────────
        score_funding = self._score_funding_magnitude(funding, direction)
        score_ls = self._score_ls_ratio(ls_ratio_top, ls_ratio_global, direction)
        score_crowding = self._score_crowding_trend(funding, funding_prev1, funding_prev2, direction)
        score_regime = self._score_regime(regime, direction)

        total = score_funding + score_ls + score_crowding + score_regime
        total = max(0, min(100, total))

        valid = total >= 40
        strength = total / 100.0

        reason = self._build_reason(direction, funding, ls_ratio_top, total)

        logger.info(
            "[FUNDING] %s fund=%.4f%% ls_top=%.2f dir=%s "
            "score=%d (fund=%d ls=%d crowd=%d reg=%d) valid=%s",
            symbol, funding * 100, ls_ratio_top, direction.value,
            total, score_funding, score_ls, score_crowding, score_regime, valid,
        )

        return Signal(
            direction=direction,
            strength=strength,
            timestamp=now_str,
            source=self.SOURCE,
            symbol=symbol,
            price=market_data.get("futures_price", 0.0),
            valid=valid,
            reason=reason,
            metadata={
                "score_total": total,
                "score_funding": score_funding,
                "score_ls_ratio": score_ls,
                "score_crowding": score_crowding,
                "score_regime": score_regime,
                "funding_rate": funding,
                "funding_rate_prev1": funding_prev1,
                "funding_rate_prev2": funding_prev2,
                "ls_ratio_top": ls_ratio_top,
                "ls_ratio_global": ls_ratio_global,
                "minutes_to_funding": mins_to_funding,
                "regime": regime,
            },
        )

    # ── Score components ─────────────────────────────────────────────

    def _score_funding_magnitude(self, funding: float, direction: Direction) -> int:
        """Funding magnitude: 0-40 pontos."""
        abs_funding = abs(funding)

        if direction == Direction.SHORT:
            if abs_funding < _FUNDING_SHORT_THRESHOLD:
                return 0
            # 0.03% = 10pts, 0.06% = 25pts, 0.10%+ = 40pts
            excess = abs_funding - _FUNDING_SHORT_THRESHOLD
            return int(min(40, 10 + (excess / 0.0007) * 30))
        elif direction == Direction.LONG:
            threshold_abs = abs(_FUNDING_LONG_THRESHOLD)
            if abs_funding < threshold_abs:
                return 0
            excess = abs_funding - threshold_abs
            return int(min(40, 10 + (excess / 0.0008) * 30))
        return 0

    def _score_ls_ratio(self, ls_top: float, ls_global: float, direction: Direction) -> int:
        """L/S ratio desequilibrio: 0-30 pontos."""
        if direction == Direction.SHORT:
            # Alto L/S = muitos longs = bom para short
            if ls_top >= _LS_CROWDED_LONG:
                base = 15
            elif ls_top >= 1.3:
                base = 8
            elif ls_top >= 1.1:
                base = 3
            else:
                return 0
            # Bonus se global tambem confirma
            if ls_global >= 1.2:
                base += 10
            elif ls_global >= 1.05:
                base += 5
            return min(30, base)

        elif direction == Direction.LONG:
            # Baixo L/S = muitos shorts = bom para long
            if ls_top <= _LS_CROWDED_SHORT:
                base = 15
            elif ls_top <= 0.8:
                base = 8
            elif ls_top <= 0.95:
                base = 3
            else:
                return 0
            if ls_global <= 0.85:
                base += 10
            elif ls_global <= 0.95:
                base += 5
            return min(30, base)

        return 0

    def _score_crowding_trend(
        self, funding: float, prev1: float, prev2: float, direction: Direction,
    ) -> int:
        """Tendencia de crowding nos ultimos 3 periodos: 0-20 pontos."""
        rates = [prev2, prev1, funding]
        # Check if all rates are in the same direction and increasing
        if direction == Direction.SHORT:
            # Funding subindo = longs pagando mais = crowding crescente
            if rates[2] > rates[1] > rates[0] and all(r > 0 for r in rates):
                return 20  # 3 periodos crescentes
            elif rates[2] > rates[1] and rates[2] > 0 and rates[1] > 0:
                return 12  # 2 periodos crescentes
            elif rates[2] > 0:
                return 5   # funding positivo mas sem tendencia clara
            return 0

        elif direction == Direction.LONG:
            # Funding caindo = shorts pagando mais
            if rates[2] < rates[1] < rates[0] and all(r < 0 for r in rates):
                return 20
            elif rates[2] < rates[1] and rates[2] < 0 and rates[1] < 0:
                return 12
            elif rates[2] < 0:
                return 5
            return 0

        return 0

    def _score_regime(self, regime: str, direction: Direction) -> int:
        """Alinhamento com regime: 0-10 pontos."""
        # Funding reversals work best in RANGING/WEAK_TREND
        # In strong TRENDING, the trend can overpower funding signals
        if regime in ("RANGING", "VOLATILE"):
            return 10  # ideal for mean reversion
        elif regime == "WEAK_TREND":
            return 7
        elif regime == "TRENDING":
            return 3  # trend may overpower
        elif regime == "CHOPPY":
            return 0  # should not be called (regime gate)
        return 5  # UNKNOWN

    # ── Helpers ───────────────────────────────────────────────────────

    def _neutral(self, symbol: str, now_str: str, funding: float,
                 ls_top: float, reason: str) -> Signal:
        logger.info("[FUNDING] %s: %s", symbol, reason)
        return Signal(
            direction=Direction.NEUTRAL, strength=0.0, timestamp=now_str,
            source=self.SOURCE, symbol=symbol, price=0.0,
            valid=False, reason=reason,
            metadata={"funding_rate": funding, "ls_ratio_top": ls_top},
        )

    @staticmethod
    def _minutes_to_next_funding(now_utc: datetime) -> int:
        current_minutes = now_utc.hour * 60 + now_utc.minute
        funding_minutes = sorted(h * 60 for h in _FUNDING_HOURS)
        for fm in funding_minutes:
            if fm > current_minutes:
                return fm - current_minutes
        return (24 * 60 - current_minutes) + funding_minutes[0]

    @staticmethod
    def _build_reason(direction: Direction, funding: float, ls_top: float, score: int) -> str:
        label = "crowded long" if direction == Direction.SHORT else "crowded short"
        return (
            f"Funding {funding*100:+.4f}% ({label}), "
            f"L/S top {ls_top:.2f}, score {score}/100"
        )
