from __future__ import annotations
import math, sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import options_features as of  # noqa: E402
import pytest  # noqa: E402


def test_norm_pdf_cdf_reference():
    assert of.norm_pdf(0.0) == pytest.approx(0.39894228, rel=1e-6)
    assert of.norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert of.norm_cdf(1.96) == pytest.approx(0.9750, abs=1e-3)


def test_parse_instrument_name_call():
    p = of.parse_instrument_name("BTC-26MAR27-105000-C")
    assert p["currency"] == "BTC"
    assert p["strike"] == 105000.0
    assert p["kind"] == "call"
    # 26 Mar 2027 08:00 UTC (expiry Deribit é sempre 08:00 UTC)
    assert p["expiry_ts"] == 1806048000


def test_parse_instrument_name_put_and_garbage():
    assert of.parse_instrument_name("ETH-1AUG25-3000-P")["kind"] == "put"
    assert of.parse_instrument_name("BTC-PERPETUAL") is None
    assert of.parse_instrument_name("garbage") is None


def test_bs_gamma_delta_reference():
    # S=K=100, sigma=0.5, T=1.0, r=0 -> d1=0.25
    g = of.bs_gamma(100.0, 100.0, 0.5, 1.0)
    assert g == pytest.approx(0.0077334, rel=1e-3)
    dc = of.bs_delta(100.0, 100.0, 0.5, 1.0, "call")
    assert dc == pytest.approx(0.5987, abs=1e-3)
    dp = of.bs_delta(100.0, 100.0, 0.5, 1.0, "put")
    assert dp == pytest.approx(0.5987 - 1.0, abs=1e-3)


def test_bs_gamma_degenerate_returns_zero():
    assert of.bs_gamma(100.0, 100.0, 0.5, 0.0) == 0.0   # expirado
    assert of.bs_gamma(100.0, 100.0, 0.0, 1.0) == 0.0   # vol zero
