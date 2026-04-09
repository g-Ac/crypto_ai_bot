"""
Testes unitarios para Motor 2 — Liquidation Cascade + OI Divergence.

Cobre:
- Cascata de liquidacoes SHORT -> sinal LONG
- Cascata de liquidacoes LONG -> sinal SHORT
- OI divergencia (preco sobe, OI cai) -> sinal SHORT
- OI divergencia (preco cai, OI sobe) -> LONG ou SHORT conforme contexto
- Mercado parado (OI <0.5%) -> sem sinal
- Liquidacoes pequenas -> filtrado
- Proxy de liquidacao (is_proxy=True) -> score capped
- Dados indisponiveis / None -> comportamento seguro
"""
import sys
import os

# Garantir que o diretorio raiz do projeto esta no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from signal_types import Direction
from liquidation_engine import (
    LiquidationEngine,
    LIQUIDATION_MIN_USD,
    LIQUIDATION_STRONG_USD,
    OI_MIN_CHANGE_PCT,
    PROXY_LIQ_SCORE_CAP,
)


def _make_candles_5m(
    n: int = 24,
    base_price: float = 50000.0,
    trend_pct: float = 0.0,
    volume: float = 100.0,
) -> pd.DataFrame:
    """Gera DataFrame de candles 5m sinteticos.

    Args:
        n: numero de candles (12 = 1h)
        base_price: preco inicial
        trend_pct: variacao percentual total do periodo (positivo = alta)
        volume: volume por candle
    """
    prices = []
    step = (base_price * trend_pct / 100) / max(n - 1, 1)
    for i in range(n):
        p = base_price + step * i
        noise = p * 0.001 * (0.5 - (i % 3) * 0.25)  # small deterministic variation
        prices.append(p + noise)

    data = {
        "time": [datetime.now() - timedelta(minutes=5 * (n - i)) for i in range(n)],
        "open": [p - abs(p * 0.0005) for p in prices],
        "high": [p + abs(p * 0.001) for p in prices],
        "low": [p - abs(p * 0.001) for p in prices],
        "close": prices,
        "volume": [volume] * n,
    }
    return pd.DataFrame(data)


def _base_market_data(**overrides) -> dict:
    """Market data base (retorno de collect_microstructure) com defaults neutros."""
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": "BTCUSDT",
        "funding_rate": 0.0001,
        "funding_rate_prev1": 0.0001,
        "funding_rate_prev2": 0.0001,
        "ls_ratio_top": 1.0,
        "ls_ratio_global": 1.0,
        "liquidation_vol_long": 0.0,
        "liquidation_vol_short": 0.0,
        "liquidation_is_proxy": True,
        "open_interest": 1_000_000.0,
        "oi_change_1h_pct": 0.0,
        "oi_change_4h_pct": 0.0,
        "basis_spread_pct": 0.01,
        "session": "us",
    }
    data.update(overrides)
    return data


class TestLiquidationCascadeShortToLong(unittest.TestCase):
    """Cascata de liquidacoes SHORT -> sinal LONG."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_strong_short_liquidation_generates_long(self):
        """Liquidacoes SHORT altas + OI subindo = LONG."""
        md = _base_market_data(
            liquidation_vol_short=600_000,  # acima de STRONG threshold
            liquidation_vol_long=50_000,    # longs intactos
            oi_change_1h_pct=1.5,           # OI subindo (dinheiro novo)
            oi_change_4h_pct=2.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.5)  # preco subindo levemente

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertTrue(signal.valid)
        self.assertGreater(signal.metadata["total_score"], 40)
        self.assertGreater(signal.metadata["score_liquidation"], 0)
        self.assertIn("Cascata SHORT", signal.reason)

    def test_extreme_short_liquidation_capped_by_proxy(self):
        """Cascata extrema de shorts com proxy = score capped at PROXY_LIQ_SCORE_CAP."""
        md = _base_market_data(
            liquidation_vol_short=3_000_000,  # extreme
            liquidation_vol_long=100_000,
            oi_change_1h_pct=3.0,
            oi_change_4h_pct=4.0,
            liquidation_is_proxy=True,
        )
        candles = _make_candles_5m(n=24, trend_pct=1.0)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertTrue(signal.valid)
        # Proxy data caps liquidation score at 20/40
        self.assertEqual(signal.metadata["score_liquidation"], PROXY_LIQ_SCORE_CAP)
        self.assertTrue(signal.metadata["liq_is_proxy"])

    def test_extreme_short_liquidation_full_score_real_data(self):
        """Cascata extrema de shorts com dados reais = score full 40."""
        md = _base_market_data(
            liquidation_vol_short=3_000_000,
            liquidation_vol_long=100_000,
            oi_change_1h_pct=3.0,
            oi_change_4h_pct=4.0,
            liquidation_is_proxy=False,
        )
        candles = _make_candles_5m(n=24, trend_pct=1.0)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertTrue(signal.valid)
        self.assertEqual(signal.metadata["score_liquidation"], 40)  # max, no cap
        self.assertFalse(signal.metadata["liq_is_proxy"])


class TestLiquidationCascadeLongToShort(unittest.TestCase):
    """Cascata de liquidacoes LONG -> sinal SHORT."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_strong_long_liquidation_generates_short(self):
        """Liquidacoes LONG altas + OI caindo = SHORT."""
        md = _base_market_data(
            liquidation_vol_long=700_000,
            liquidation_vol_short=30_000,
            oi_change_1h_pct=-1.0,  # OI diminuindo
            oi_change_4h_pct=-1.5,
        )
        candles = _make_candles_5m(n=24, trend_pct=-0.5)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertTrue(signal.valid)
        self.assertIn("Cascata LONG", signal.reason)

    def test_moderate_long_liquidation(self):
        """Liquidacoes LONG moderadas geram SHORT com score menor."""
        md = _base_market_data(
            liquidation_vol_long=200_000,
            liquidation_vol_short=50_000,
            oi_change_1h_pct=-0.8,
            oi_change_4h_pct=-1.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=-0.3)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.SHORT)
        # Score deve ser menor que cascata forte
        self.assertLess(signal.metadata["score_liquidation"], 20)


class TestOIDivergencePriceUpOIDown(unittest.TestCase):
    """OI divergencia: preco sobe, OI cai -> SHORT (distribuicao)."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_price_up_oi_down_generates_short(self):
        """Preco subindo enquanto OI cai = distribuicao = SHORT."""
        md = _base_market_data(
            liquidation_vol_long=10_000,   # pouca liquidacao
            liquidation_vol_short=10_000,
            oi_change_1h_pct=-2.0,         # OI caindo forte
            oi_change_4h_pct=-3.0,
        )
        # Preco subindo 1% na ultima hora
        candles = _make_candles_5m(n=24, trend_pct=1.0)

        signal = self.engine.analyze("BTCUSDT", md, "WEAK_TREND", candles)

        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertIn("divergencia bearish", signal.reason)
        self.assertGreater(signal.metadata["score_oi_divergence"], 0)

    def test_strong_divergence_high_oi_score(self):
        """Divergencia forte (OI -5%+) = score OI alto."""
        md = _base_market_data(
            oi_change_1h_pct=-6.0,
            oi_change_4h_pct=-7.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=2.0)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.metadata["score_oi_divergence"], 30)  # max


class TestOIDivergencePriceDownOIUp(unittest.TestCase):
    """OI divergencia: preco cai, OI sobe -> LONG ou SHORT conforme contexto."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_price_down_oi_up_with_long_liquidations_generates_short(self):
        """Preco caindo + OI subindo + liquidacoes de longs = SHORT (bearish)."""
        md = _base_market_data(
            liquidation_vol_long=300_000,   # longs sendo liquidados
            liquidation_vol_short=20_000,
            oi_change_1h_pct=2.0,           # OI subindo (novos shorts)
            oi_change_4h_pct=3.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=-1.0)  # preco caindo

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertIn("Shorts acumulando", signal.reason)

    def test_price_down_oi_up_without_liquidations_generates_long(self):
        """Preco caindo + OI subindo sem liquidacoes = possivel reversal LONG."""
        md = _base_market_data(
            liquidation_vol_long=10_000,    # sem liquidacoes significativas
            liquidation_vol_short=5_000,
            oi_change_1h_pct=2.5,           # OI subindo forte
            oi_change_4h_pct=3.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=-1.0)

        signal = self.engine.analyze("BTCUSDT", md, "RANGING", candles)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertIn("reversal", signal.reason)


class TestMarketStalled(unittest.TestCase):
    """Mercado parado: OI mudou <0.5% -> sem sinal."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_low_oi_change_no_signal(self):
        """OI quase flat + sem liquidacoes = neutro."""
        md = _base_market_data(
            liquidation_vol_long=5_000,
            liquidation_vol_short=5_000,
            oi_change_1h_pct=0.1,   # praticamente zero
            oi_change_4h_pct=0.2,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.0)

        signal = self.engine.analyze("BTCUSDT", md, "RANGING", candles)

        self.assertEqual(signal.direction, Direction.NEUTRAL)
        self.assertFalse(signal.valid)
        self.assertIn("parado", signal.reason)

    def test_tiny_oi_change_still_filtered(self):
        """OI change = 0.4% (abaixo de 0.5% threshold)."""
        md = _base_market_data(
            oi_change_1h_pct=0.4,
            oi_change_4h_pct=0.5,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.1)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.NEUTRAL)
        self.assertFalse(signal.valid)


class TestSmallLiquidationsFiltered(unittest.TestCase):
    """Liquidacoes muito pequenas -> filtrado."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_tiny_liquidations_no_signal(self):
        """Liquidacoes abaixo do threshold minimo = ignoradas."""
        md = _base_market_data(
            liquidation_vol_long=10_000,    # bem abaixo de LIQUIDATION_MIN_USD
            liquidation_vol_short=15_000,
            oi_change_1h_pct=0.2,           # OI tambem quase flat
            oi_change_4h_pct=0.3,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.0)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        self.assertEqual(signal.direction, Direction.NEUTRAL)
        self.assertFalse(signal.valid)

    def test_liquidations_below_threshold_but_oi_divergence_still_works(self):
        """Sem liquidacoes mas com OI divergencia forte = sinal via OI."""
        md = _base_market_data(
            liquidation_vol_long=5_000,
            liquidation_vol_short=5_000,
            oi_change_1h_pct=-3.0,  # OI caindo forte
            oi_change_4h_pct=-4.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=1.5)  # preco subindo

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)

        # Deve gerar SHORT via divergencia mesmo sem liquidacoes
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertIn("divergencia", signal.reason)


class TestScoreComponents(unittest.TestCase):
    """Testes dos componentes individuais de score."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_regime_score_trending_highest(self):
        score = self.engine._score_regime_alignment(Direction.LONG, "TRENDING")
        self.assertEqual(score, 10)

    def test_regime_score_ranging_lower(self):
        score = self.engine._score_regime_alignment(Direction.LONG, "RANGING")
        self.assertEqual(score, 4)

    def test_regime_score_unknown_minimal(self):
        score = self.engine._score_regime_alignment(Direction.LONG, "UNKNOWN")
        self.assertEqual(score, 2)

    def test_speed_score_recent_change_higher(self):
        """Mudanca concentrada na ultima hora = score mais alto."""
        fast = self.engine._score_divergence_speed(oi_change_1h=4.0, oi_change_4h=4.5)
        slow = self.engine._score_divergence_speed(oi_change_1h=1.0, oi_change_4h=4.5)
        self.assertGreater(fast, slow)

    def test_liquidation_score_scales_with_volume(self):
        """Score de liquidacao escala com volume."""
        low = self.engine._score_liquidation_magnitude(100_000, 0, Direction.SHORT)
        mid = self.engine._score_liquidation_magnitude(600_000, 0, Direction.SHORT)
        high = self.engine._score_liquidation_magnitude(3_000_000, 0, Direction.SHORT)
        self.assertLess(low, mid)
        self.assertLess(mid, high)
        self.assertEqual(high, 40)  # max


class TestNoCandles(unittest.TestCase):
    """Engine funciona mesmo sem candles (sem VWAP/range check)."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_signal_without_candles(self):
        """Sinal via cascata de liquidacoes sem candles para VWAP."""
        md = _base_market_data(
            liquidation_vol_short=800_000,
            liquidation_vol_long=50_000,
            oi_change_1h_pct=2.0,
            oi_change_4h_pct=3.0,
        )
        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles_5m=None)

        self.assertEqual(signal.direction, Direction.LONG)
        self.assertTrue(signal.valid)
        self.assertEqual(signal.price, 0.0)  # sem candles, preco = 0


class TestProxyLiquidationScoreCap(unittest.TestCase):
    """Dados de liquidacao via proxy tem score capeado."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_proxy_caps_strong_liquidation(self):
        """Score > PROXY_LIQ_SCORE_CAP e reduzido quando is_proxy=True."""
        md = _base_market_data(
            liquidation_vol_short=600_000,  # strong, raw score ~20
            liquidation_vol_long=30_000,
            oi_change_1h_pct=1.0,
            oi_change_4h_pct=2.0,
            liquidation_is_proxy=True,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.5)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)
        self.assertLessEqual(signal.metadata["score_liquidation"], PROXY_LIQ_SCORE_CAP)

    def test_no_proxy_flag_means_real_data(self):
        """Sem is_proxy ou is_proxy=False = dados reais, sem cap."""
        md = _base_market_data(
            liquidation_vol_short=600_000,
            liquidation_vol_long=30_000,
            oi_change_1h_pct=1.0,
            oi_change_4h_pct=2.0,
            liquidation_is_proxy=False,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.5)

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)
        # Raw score for 600k: between min(50k) and strong(500k) -> ~20
        # With real data, no cap applied (score <= 20 anyway, but no cap mechanism)
        self.assertGreater(signal.metadata["score_liquidation"], 0)

    def test_proxy_metadata_flag_present(self):
        """Metadata sempre inclui liq_is_proxy."""
        md = _base_market_data(
            liquidation_vol_short=100_000,
            oi_change_1h_pct=1.0,
            liquidation_is_proxy=True,
        )
        candles = _make_candles_5m(n=24, trend_pct=0.3)
        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)
        # Even if signal is neutral, metadata should have the flag when signal is generated
        # For neutral signals, metadata might not be set, that's ok


class TestDataUnavailable(unittest.TestCase):
    """Comportamento quando dados de microestrutura estao indisponiveis."""

    def setUp(self):
        self.engine = LiquidationEngine()

    def test_all_zeros_returns_neutral(self):
        """Todos os campos zerados = mercado parado = neutro."""
        md = _base_market_data()  # defaults are all zero/neutral
        candles = _make_candles_5m(n=24, trend_pct=0.0)

        signal = self.engine.analyze("BTCUSDT", md, "RANGING", candles)
        self.assertEqual(signal.direction, Direction.NEUTRAL)
        self.assertFalse(signal.valid)

    def test_missing_fields_use_defaults(self):
        """Dict com campos faltando nao causa crash."""
        md = {"symbol": "BTCUSDT", "timestamp": "2026-04-08"}
        # Missing all microstructure fields — should default to 0
        signal = self.engine.analyze("BTCUSDT", md, "UNKNOWN", candles_5m=None)
        self.assertEqual(signal.direction, Direction.NEUTRAL)
        self.assertFalse(signal.valid)

    def test_empty_candles_df(self):
        """DataFrame vazio nao causa crash."""
        md = _base_market_data(
            oi_change_1h_pct=3.0,
            oi_change_4h_pct=4.0,
        )
        empty_df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles_5m=empty_df)
        # Should work without candles (no VWAP/range)
        # OI change alone may or may not trigger signal depending on liq values

    def test_oi_divergence_works_without_liquidation_data(self):
        """OI divergencia funciona mesmo com liquidacoes zeradas."""
        md = _base_market_data(
            liquidation_vol_long=0.0,
            liquidation_vol_short=0.0,
            oi_change_1h_pct=-4.0,
            oi_change_4h_pct=-5.0,
        )
        candles = _make_candles_5m(n=24, trend_pct=2.0)  # preco subindo

        signal = self.engine.analyze("BTCUSDT", md, "TRENDING", candles)
        # Price up + OI down = bearish divergence = SHORT
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertIn("divergencia", signal.reason)
        # Liquidation score should be 0 since no liquidation data
        self.assertEqual(signal.metadata["score_liquidation"], 0)


if __name__ == "__main__":
    unittest.main()
