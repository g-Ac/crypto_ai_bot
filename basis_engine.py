"""
Motor 3 -- Basis Spread + Session Timing.

O premium de futures sobre spot reflete sentimento agregado.
Sessoes de mercado (Asia, Europa, US) e horarios de funding
criam padroes previssiveis de posicionamento.

Sinais SHORT (euforia):
  - Basis > 0.05%  (futures muito mais caro que spot)
  - Basis expandindo nos ultimos 30min
  - Proximos 60min antes de pagamento de funding (00:00, 08:00, 16:00 UTC)
  - Sessao ativa para o ativo

Sinais LONG (panico):
  - Basis < -0.03%  (backwardation)
  - Basis contraindo (voltando para zero) nos ultimos 15min
  - Sessao de alta liquidez

Score 0-100 com 4 componentes:
  - Magnitude do basis:          0-35 pts
  - Velocidade de mudanca:       0-25 pts
  - Alinhamento com sessao:      0-20 pts
  - Proximidade funding payment: 0-20 pts

Filtros:
  - Basis entre -0.02% e 0.03% -> zona neutra, sem sinal
  - Dead zone (21:00-00:00 UTC) -> so operar com score > 80
  - Volatilidade muito baixa (ATR 1h < 0.1%) -> basis distorcido
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from signal_types import Direction, Signal

logger = logging.getLogger("scalping.basis_engine")

# Funding payment times (hours UTC)
_FUNDING_HOURS = (0, 8, 16)

# Basis thresholds
_BASIS_SHORT_THRESHOLD = 0.05   # % acima disso = euforia
_BASIS_LONG_THRESHOLD = -0.03   # % abaixo disso = panico
_BASIS_NEUTRAL_LOW = -0.02      # zona neutra inferior
_BASIS_NEUTRAL_HIGH = 0.03      # zona neutra superior

# Session definitions
_SESSIONS = {
    "asia":   (0, 8),
    "europe": (8, 14),
    "us":     (14, 21),
    "dead":   (21, 24),
}

# Which sessions are "active" for which assets
_ACTIVE_SESSIONS = {
    "BTCUSDT":  ("us", "europe"),
    "ETHUSDT":  ("us", "europe"),
    "SOLUSDT":  ("us", "europe"),
    "BNBUSDT":  ("asia", "europe"),
    "XRPUSDT":  ("asia", "us"),
    "DOGEUSDT": ("us", "asia"),
}
_DEFAULT_ACTIVE_SESSIONS = ("us", "europe")

# Dead zone score gate
_DEAD_ZONE_MIN_SCORE = 80


class BasisEngine:
    """Motor 3: gera sinais baseados em basis spread e timing de sessao."""

    def __init__(
        self,
        short_threshold: float = _BASIS_SHORT_THRESHOLD,
        long_threshold: float = _BASIS_LONG_THRESHOLD,
        neutral_low: float = _BASIS_NEUTRAL_LOW,
        neutral_high: float = _BASIS_NEUTRAL_HIGH,
        dead_zone_min_score: int = _DEAD_ZONE_MIN_SCORE,
    ):
        self.short_threshold = short_threshold
        self.long_threshold = long_threshold
        self.neutral_low = neutral_low
        self.neutral_high = neutral_high
        self.dead_zone_min_score = dead_zone_min_score

    def analyze(
        self,
        symbol: str,
        market_data: dict,
        regime: str = "UNKNOWN",
        now_utc: Optional[datetime] = None,
        prev_basis_pct: Optional[float] = None,
    ) -> Signal:
        """Analisa basis spread e sessao para gerar sinal.

        Args:
            symbol: par de trading (ex: BTCUSDT)
            market_data: retorno de collect_microstructure() do market_data.py
            regime: regime de mercado (TRENDING/RANGING/CHOPPY etc)
            now_utc: datetime UTC para teste (default: agora)
            prev_basis_pct: basis do ciclo anterior (para score de velocidade).
                            Deve vir da tabela market_microstructure (campo
                            basis_spread_pct do registro anterior para o mesmo symbol)
                            ou ser passado pelo caller que mantem estado.
                            Se None, o componente de velocidade = 0 (25 pontos
                            perdidos — dados reais de historico sao necessarios
                            para score completo).
        Returns:
            Signal com direction, strength (score/100), metadata
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        basis_pct = market_data.get("basis_spread_pct", 0.0)
        funding_rate = market_data.get("funding_rate", 0.0)
        session = market_data.get("session", self._classify_session(now_utc))

        # Determine direction
        direction = self._determine_direction(basis_pct)

        # Build score components
        magnitude_score = self._score_magnitude(basis_pct, direction)
        velocity_score = self._score_velocity(basis_pct, prev_basis_pct, direction)
        session_score = self._score_session(symbol, session, direction)
        funding_score = self._score_funding_proximity(now_utc)

        raw_score = magnitude_score + velocity_score + session_score + funding_score
        raw_score = max(0, min(100, raw_score))

        # Filters
        filtered = False
        filter_reason = ""

        if self.neutral_low <= basis_pct <= self.neutral_high:
            filtered = True
            filter_reason = f"Basis {basis_pct:.4f}% em zona neutra [{self.neutral_low}, {self.neutral_high}]"

        if session == "dead" and raw_score < self.dead_zone_min_score:
            filtered = True
            filter_reason = f"Dead zone (21-00 UTC) com score {raw_score} < {self.dead_zone_min_score}"

        if direction == Direction.NEUTRAL:
            filtered = True
            filter_reason = f"Basis {basis_pct:.4f}% sem direcao clara"

        valid = not filtered and raw_score > 0
        strength = raw_score / 100.0

        reason = filter_reason if filtered else self._build_reason(
            direction, basis_pct, session, raw_score
        )

        metadata = {
            "basis_pct": basis_pct,
            "prev_basis_pct": prev_basis_pct,
            "funding_rate": funding_rate,
            "session": session,
            "regime": regime,
            "score_magnitude": magnitude_score,
            "score_velocity": velocity_score,
            "score_session": session_score,
            "score_funding": funding_score,
            "score_total": raw_score,
            "filtered": filtered,
            "filter_reason": filter_reason,
        }

        logger.info(
            "[BASIS] %s basis=%.4f%% prev=%.4f%% session=%s dir=%s "
            "score=%d (mag=%d vel=%d ses=%d fun=%d) valid=%s%s",
            symbol,
            basis_pct,
            prev_basis_pct if prev_basis_pct is not None else 0.0,
            session,
            direction.value,
            raw_score,
            magnitude_score,
            velocity_score,
            session_score,
            funding_score,
            valid,
            f" FILTERED: {filter_reason}" if filtered else "",
        )

        return Signal(
            direction=direction if valid else Direction.NEUTRAL,
            strength=strength,
            timestamp=now_utc.isoformat(),
            source="basis_engine",
            symbol=symbol,
            price=market_data.get("futures_price", 0.0),
            metadata=metadata,
            reason=reason,
            valid=valid,
        )

    # ── Direction ───────────────────────────────────────────────────────

    def _determine_direction(self, basis_pct: float) -> Direction:
        """Basis alto = euforia = SHORT, basis negativo = panico = LONG."""
        if basis_pct >= self.short_threshold:
            return Direction.SHORT
        if basis_pct <= self.long_threshold:
            return Direction.LONG
        return Direction.NEUTRAL

    # ── Score Components ────────────────────────────────────────────────

    def _score_magnitude(self, basis_pct: float, direction: Direction) -> int:
        """Magnitude do basis: 0-35 pontos.

        SHORT: 0.05% = 10pts, 0.10% = 20pts, 0.20%+ = 35pts (linear interpolation)
        LONG:  -0.03% = 10pts, -0.08% = 20pts, -0.15%+ = 35pts
        """
        if direction == Direction.SHORT:
            abs_basis = basis_pct
            if abs_basis < self.short_threshold:
                return 0
            # Linear from threshold(10) to 0.20%(35)
            range_pct = 0.20 - self.short_threshold
            excess = min(abs_basis - self.short_threshold, range_pct)
            return int(10 + (excess / range_pct) * 25)

        if direction == Direction.LONG:
            abs_basis = abs(basis_pct)
            threshold_abs = abs(self.long_threshold)
            if abs_basis < threshold_abs:
                return 0
            # Linear from threshold(10) to 0.15%(35)
            range_pct = 0.15 - threshold_abs
            if range_pct <= 0:
                return 35
            excess = min(abs_basis - threshold_abs, range_pct)
            return int(10 + (excess / range_pct) * 25)

        return 0

    def _score_velocity(
        self,
        basis_pct: float,
        prev_basis_pct: Optional[float],
        direction: Direction,
    ) -> int:
        """Velocidade de mudanca do basis: 0-25 pontos.

        SHORT: basis expandindo (subindo) = bom
        LONG:  basis contraindo (subindo de negativo para zero) = bom
        """
        if prev_basis_pct is None:
            return 0

        delta = basis_pct - prev_basis_pct

        if direction == Direction.SHORT:
            # Basis crescendo = euforia acelerando
            if delta <= 0:
                return 0
            # 0.01% delta = 8pts, 0.03% = 17pts, 0.05%+ = 25pts
            return int(min(25, (delta / 0.05) * 25))

        if direction == Direction.LONG:
            # Basis subindo (ficando menos negativo) = panico recuando
            if delta <= 0:
                return 0
            return int(min(25, (delta / 0.05) * 25))

        return 0

    def _score_session(
        self,
        symbol: str,
        session: str,
        direction: Direction,
    ) -> int:
        """Alinhamento com sessao ativa: 0-20 pontos."""
        if direction == Direction.NEUTRAL:
            return 0

        active = _ACTIVE_SESSIONS.get(symbol, _DEFAULT_ACTIVE_SESSIONS)

        if session in active:
            return 20
        if session == "dead":
            return 0
        # Non-primary but not dead
        return 10

    def _score_funding_proximity(self, now_utc: datetime) -> int:
        """Proximidade ao pagamento de funding: 0-20 pontos.

        Funding payments at 00:00, 08:00, 16:00 UTC.
        <= 15min = 20pts, <= 30min = 15pts, <= 60min = 10pts
        """
        minutes_to_funding = self._minutes_to_next_funding(now_utc)

        if minutes_to_funding <= 15:
            return 20
        if minutes_to_funding <= 30:
            return 15
        if minutes_to_funding <= 60:
            return 10
        return 0

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _classify_session(now_utc: datetime) -> str:
        hour = now_utc.hour
        for name, (start, end) in _SESSIONS.items():
            if start <= hour < end:
                return name
        return "dead"

    @staticmethod
    def _minutes_to_next_funding(now_utc: datetime) -> int:
        """Minutes until the next funding payment (00, 08, 16 UTC)."""
        current_minutes = now_utc.hour * 60 + now_utc.minute
        funding_minutes = sorted(h * 60 for h in _FUNDING_HOURS)

        for fm in funding_minutes:
            if fm > current_minutes:
                return fm - current_minutes

        # Next is midnight (00:00 tomorrow)
        return (24 * 60 - current_minutes) + funding_minutes[0]

    @staticmethod
    def _build_reason(
        direction: Direction, basis_pct: float, session: str, score: int
    ) -> str:
        label = "euforia (premium)" if direction == Direction.SHORT else "panico (backwardation)"
        return (
            f"Basis {basis_pct:+.4f}% indica {label}. "
            f"Sessao {session}, score {score}/100"
        )
