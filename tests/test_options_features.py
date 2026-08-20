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


def _chain(spot, now, items):
    """items: list of (kind, strike, iv, oi, days_to_exp)."""
    out = []
    for kind, strike, iv, oi, days in items:
        out.append({"kind": kind, "strike": strike, "iv": iv, "oi": oi,
                    "expiry_ts": now + int(days * 86400)})
    return out, spot, now


def test_compute_gex_sign_convention():
    chain, spot, now = _chain(100.0, 1_700_000_000, [
        ("call", 100.0, 0.5, 10.0, 30),   # dealer short call -> negativo
        ("put",  100.0, 0.5, 10.0, 30),    # dealer long put  -> positivo
    ])
    gex_signed, gex_abs = of.compute_gex(chain, spot, now)
    assert abs(gex_signed) < 1e-9          # call e put de mesmo strike/oi se cancelam
    assert gex_abs > 0                       # magnitude soma


def test_compute_gex_put_heavy_positive():
    chain, spot, now = _chain(100.0, 1_700_000_000, [
        ("put", 100.0, 0.5, 50.0, 30),
        ("call", 100.0, 0.5, 10.0, 30),
    ])
    gex_signed, _ = of.compute_gex(chain, spot, now)
    assert gex_signed > 0                    # puts dominam -> dealer long gamma


def test_compute_iv_atm_picks_nearest_strike():
    chain, spot, now = _chain(100.0, 1_700_000_000, [
        ("call", 95.0, 0.40, 5, 30), ("call", 100.0, 0.55, 5, 30),
        ("put", 105.0, 0.60, 5, 30),
    ])
    assert of.compute_iv_atm(chain, spot, now) == pytest.approx(0.55, abs=1e-9)


def test_compute_skew_25d_sign():
    # puts mais caras que calls -> skew positivo (medo)
    chain, spot, now = _chain(100.0, 1_700_000_000, [
        ("call", 90, 0.40, 5, 30), ("call", 100, 0.45, 5, 30), ("call", 130, 0.50, 5, 30),
        ("put", 70, 0.80, 5, 30), ("put", 100, 0.55, 5, 30), ("put", 110, 0.50, 5, 30),
    ])
    skew = of.compute_skew_25d(chain, spot, now)
    assert skew is not None and skew > 0


def test_features_empty_chain_return_none():
    assert of.compute_iv_atm([], 100.0, 1) is None
    assert of.compute_skew_25d([], 100.0, 1) is None
    assert of.compute_gamma_flip([], 100.0, 1) is None


def test_realized_vol_constant_returns_zero():
    assert of.realized_vol([100.0, 100.0, 100.0]) == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_positive_and_annualized():
    closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
    rv = of.realized_vol(closes)
    assert rv is not None and rv > 0


def test_realized_vol_insufficient():
    assert of.realized_vol([100.0]) is None
    assert of.realized_vol([]) is None


def test_compute_vrp():
    assert of.compute_vrp(0.60, 0.45) == pytest.approx(0.15, abs=1e-9)
    assert of.compute_vrp(None, 0.45) is None
    assert of.compute_vrp(0.60, None) is None
