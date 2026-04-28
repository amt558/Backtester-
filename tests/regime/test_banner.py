"""Test regime banner classification (independent of alpaca client)."""
from __future__ import annotations
import pytest
from tradelab.regime.banner import classify_regime, RegimeResult


def test_low_vol_trending_narrow():
    result = classify_regime(
        vix=14.8, realized_vol_30d=0.112,
        spx_above_50ma=True, spx_above_200ma=True, adx=26,
        breadth_pct_above_50d=44,
    )
    assert result.vol == "LOW"
    assert result.trend == "TRENDING"
    assert result.breadth == "NARROW"


def test_high_vol_choppy_broad():
    result = classify_regime(
        vix=28.5, realized_vol_30d=0.24,
        spx_above_50ma=False, spx_above_200ma=True, adx=14,
        breadth_pct_above_50d=72,
    )
    assert result.vol == "HIGH"
    assert result.trend == "CHOPPY"
    assert result.breadth == "BROAD"


def test_medium_vol_unclear_trend():
    """SPX above 50 but below 200 → trend is UNCLEAR (not TRENDING, not CHOPPY)."""
    result = classify_regime(
        vix=20.0, realized_vol_30d=0.18,
        spx_above_50ma=True, spx_above_200ma=False, adx=18,
        breadth_pct_above_50d=55,
    )
    assert result.vol == "MED"
    assert result.trend == "UNCLEAR"  # was: assert result.trend in ("UNCLEAR", "TRENDING", "CHOPPY")
    assert result.breadth == "MIXED"


def test_breadth_thresholds():
    # 60+ = BROAD; 50-59 = MIXED; <50 = NARROW
    r1 = classify_regime(vix=14.0, realized_vol_30d=0.10, spx_above_50ma=True, spx_above_200ma=True, adx=22, breadth_pct_above_50d=65)
    assert r1.breadth == "BROAD"
    r2 = classify_regime(vix=14.0, realized_vol_30d=0.10, spx_above_50ma=True, spx_above_200ma=True, adx=22, breadth_pct_above_50d=50)
    assert r2.breadth == "MIXED"
    r3 = classify_regime(vix=14.0, realized_vol_30d=0.10, spx_above_50ma=True, spx_above_200ma=True, adx=22, breadth_pct_above_50d=49)
    assert r3.breadth == "NARROW"
