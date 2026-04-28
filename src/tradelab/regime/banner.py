"""Regime banner: classify market regime from SPY/VIX/breadth signals.

classify_regime() is pure logic — no I/O, testable without credentials.
fetch_regime() is the live data stub (Option B: deferred).
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class RegimeResult(BaseModel):
    vol: str          # LOW | MED | HIGH | UNKNOWN
    trend: str        # TRENDING | CHOPPY | UNCLEAR | UNKNOWN
    breadth: str      # BROAD | MIXED | NARROW | UNKNOWN

    vix: Optional[float] = None
    realized_vol_30d: Optional[float] = None
    adx: Optional[float] = None
    breadth_pct_above_50d: Optional[float] = None
    last_shift_date: Optional[str] = None
    days_stable: Optional[int] = None


def classify_regime(
    *,
    vix: float,
    realized_vol_30d: float,
    spx_above_50ma: bool,
    spx_above_200ma: bool,
    adx: float,
    breadth_pct_above_50d: float,
) -> RegimeResult:
    """Classify current market regime from raw signal inputs.

    Args:
        vix: VIX close (CBOE volatility index).
        realized_vol_30d: 30-day annualized realized volatility (e.g. 0.18 = 18%).
        spx_above_50ma: True if SPX/SPY close > 50-day MA.
        spx_above_200ma: True if SPX/SPY close > 200-day MA.
        adx: Average Directional Index (14-period Wilder's).
        breadth_pct_above_50d: % of S&P 500 components above their 50d MA (0-100).

    Returns:
        RegimeResult with vol / trend / breadth classifications.
    """
    # --- Volatility ---
    # Composite: VIX-primary, realized-vol secondary
    if vix < 18 and realized_vol_30d < 0.15:
        vol = "LOW"
    elif vix > 25 or realized_vol_30d > 0.22:
        vol = "HIGH"
    else:
        vol = "MED"

    # --- Trend ---
    # Both MAs + ADX >= 20 = TRENDING; neither MA + ADX < 20 = CHOPPY; else UNCLEAR
    if spx_above_50ma and spx_above_200ma and adx >= 20:
        trend = "TRENDING"
    elif not spx_above_50ma and adx < 20:
        trend = "CHOPPY"
    else:
        trend = "UNCLEAR"

    # --- Breadth ---
    # 60+ = BROAD (most stocks participating); <50 = NARROW; 50-59 = MIXED
    if breadth_pct_above_50d >= 60:
        breadth = "BROAD"
    elif breadth_pct_above_50d >= 50:
        breadth = "MIXED"
    else:
        breadth = "NARROW"

    return RegimeResult(
        vol=vol,
        trend=trend,
        breadth=breadth,
        vix=round(vix, 2),
        realized_vol_30d=round(realized_vol_30d, 4),
        adx=round(adx, 1),
        breadth_pct_above_50d=round(breadth_pct_above_50d, 1),
    )


def fetch_regime() -> RegimeResult:
    """Fetch live regime signals from Alpaca and classify.

    Option B stub — alpaca-py data feed wiring deferred.
    See Spec section 8 risk #1. The /tradelab/regime endpoint returns
    UNKNOWN stub values when this raises NotImplementedError.
    """
    raise NotImplementedError(
        "fetch_regime: alpaca-py wiring deferred — see Spec section 8 risk #1"
    )
