"""
FundingFilter — veto de sinais quando funding rate indica crowd na mesma direcao.

Usado pelo fluxo V2.1b do confluence.py.
Se abs(funding_rate) >= threshold E a direcao do sinal = lado do crowd,
o sinal e vetado (direcao -> NEUTRAL).

Threshold padrao: 0.05% (0.0005 em decimal).
"""
import logging

logger = logging.getLogger("scalping.funding_filter")


class FundingFilter:
    """Veta sinais quando funding rate indica crowd na mesma direcao."""

    def should_veto(self, signal, market_data, threshold=0.05):
        """Retorna True se o sinal deve ser vetado.

        Args:
            signal: Signal com direction LONG/SHORT
            market_data: dict com 'funding_rate' (em decimal, ex: 0.0001 = 0.01%)
            threshold: funding rate threshold em % (0.05 = 0.05%)

        Returns:
            True se funding rate indica crowd na mesma direcao do sinal
        """
        funding = market_data.get("funding_rate", 0)
        threshold_decimal = threshold / 100

        if signal.direction.value == "LONG" and funding > threshold_decimal:
            logger.info(
                "FUNDING_FILTER: veto LONG — funding %.4f%% > %.4f%% (crowd long)",
                funding * 100, threshold_decimal * 100,
            )
            return True

        if signal.direction.value == "SHORT" and funding < -threshold_decimal:
            logger.info(
                "FUNDING_FILTER: veto SHORT — funding %.4f%% < -%.4f%% (crowd short)",
                funding * 100, threshold_decimal * 100,
            )
            return True

        return False
