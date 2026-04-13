"""
BasisConfidenceAdjuster — ajusta strength do sinal baseado em basis spread.

Usado pelo fluxo V2.1b do confluence.py.
Nao bloqueia sinais, apenas ajusta o multiplicador de confianca:
- Basis confirma direcao: bonus (+10%)
- Basis contradiz direcao: penalty (-15%)
- Basis neutro (< 0.02%): sem ajuste (1.0)

Logica de confirmacao:
  LONG  + basis negativo (futures < spot = desconto)    → bonus  (mercado pessimista, bom para reversal long)
  LONG  + basis positivo (futures > spot = premium)     → penalty (mercado ja otimista, crowd long)
  SHORT + basis positivo (futures > spot = premium)     → bonus  (mercado euforico, bom para reversal short)
  SHORT + basis negativo (futures < spot = desconto)    → penalty (mercado ja pessimista, crowd short)
"""
import logging

logger = logging.getLogger("scalping.basis_confidence")


class BasisConfidenceAdjuster:
    """Ajusta strength do sinal baseado em basis spread."""

    def adjust(self, signal, market_data, bonus=0.1, penalty=0.15, neutral=0.02):
        """Retorna multiplicador de confianca (>1.0 = bonus, <1.0 = penalty).

        Args:
            signal: Signal com direction LONG/SHORT
            market_data: dict com 'basis_pct' (em %, ex: 0.05 = 0.05%)
            bonus: bonus quando basis confirma direcao
            penalty: penalty quando basis contradiz direcao
            neutral: threshold de basis neutro (abaixo disso = sem ajuste)

        Returns:
            float multiplicador (ex: 1.1, 0.85, 1.0)
        """
        basis = market_data.get("basis_spread_pct", market_data.get("basis_pct", 0))

        if abs(basis) < neutral:
            return 1.0

        direction = signal.direction.value

        if direction == "LONG":
            # Basis negativo (futures < spot) = desconto = bom para LONG (reversal)
            # Basis positivo (futures > spot) = premium = ruim para LONG (crowd)
            mult = 1.0 + bonus if basis < -neutral else 1.0 - penalty
        elif direction == "SHORT":
            # Basis positivo (futures > spot) = premium = bom para SHORT (euforia)
            # Basis negativo (futures < spot) = desconto = ruim para SHORT (crowd)
            mult = 1.0 + bonus if basis > neutral else 1.0 - penalty
        else:
            return 1.0

        logger.info(
            "BASIS_CONFIDENCE: %s basis=%.4f%% -> mult=%.2f",
            direction, basis, mult,
        )
        return mult
