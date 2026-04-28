"""Regime banner: classify market regime from SPY/VIX/breadth signals.

classify_regime() is pure logic — no I/O, testable without credentials.
fetch_regime() pulls SPY 250 daily bars from Alpaca, computes
realized vol / 50d-200d MAs / Wilder ADX(14), then delegates to
classify_regime(). VIX and breadth are currently stubbed (see TODOs).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

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
    if vix < 17 and realized_vol_30d < 0.13:
        vol = "LOW"
    elif vix > 25 or realized_vol_30d > 0.22:
        vol = "HIGH"
    else:
        vol = "MED"

    # --- Trend ---
    # Both MAs + ADX >= 20 = TRENDING; neither MA + ADX < 18 = CHOPPY; else UNCLEAR
    if spx_above_50ma and spx_above_200ma and adx >= 20:
        trend = "TRENDING"
    elif not spx_above_50ma and adx < 18:
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


# --- helpers (pure functions, separately testable) ---------------------------


def _realized_vol_30d(closes: Sequence[float]) -> float:
    """Annualized stdev of last 30 daily log returns (sqrt(252) scaling)."""
    if len(closes) < 31:
        raise ValueError(f"need >= 31 closes for 30d vol, got {len(closes)}")
    rets: List[float] = []
    tail = list(closes[-31:])
    for prev, curr in zip(tail[:-1], tail[1:]):
        if prev <= 0 or curr <= 0:
            raise ValueError("non-positive close encountered in vol calc")
        rets.append(math.log(curr / prev))
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252.0)


def _simple_moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"need >= {window} values for SMA{window}, got {len(values)}")
    tail = values[-window:]
    return sum(tail) / float(window)


def _wilder_adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float:
    """Compute the latest Wilder's ADX(period).

    Standard formulation:
      +DM_i = max(high_i - high_{i-1}, 0) if that move > (low_{i-1} - low_i) else 0
      -DM_i = max(low_{i-1} - low_i, 0)   if that move > (high_i - high_{i-1}) else 0
      TR_i  = max(high_i - low_i, |high_i - close_{i-1}|, |low_i - close_{i-1}|)
    Wilder smoothing (period=14):
      first smoothed value = simple sum of first 14 raw values
      thereafter: smoothed_today = smoothed_yesterday - (smoothed_yesterday/14) + today
    +DI = 100 * smoothed(+DM) / smoothed(TR); -DI similarly.
    DX  = 100 * |+DI - -DI| / (+DI + -DI).
    ADX = Wilder smoothing of DX (same period).

    Need at least 2*period bars to produce one ADX value (period for DI warmup
    + period for ADX smoothing). Conventionally 2*period+1 bars is the minimum
    we accept here for robustness.
    """
    n = len(closes)
    if not (len(highs) == len(lows) == n):
        raise ValueError("highs/lows/closes must be equal length")
    if n < 2 * period + 1:
        raise ValueError(
            f"need >= {2 * period + 1} bars for ADX({period}), got {n}"
        )

    plus_dm: List[float] = []
    minus_dm: List[float] = []
    tr: List[float] = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    # Wilder-smooth each series. First smoothed value = simple sum of first
    # `period` raw values; subsequent values use the recursion below.
    def _wilder_smooth(values: Sequence[float]) -> List[float]:
        out: List[float] = []
        first = sum(values[:period])
        out.append(first)
        prev = first
        for v in values[period:]:
            prev = prev - (prev / period) + v
            out.append(prev)
        return out

    sm_plus = _wilder_smooth(plus_dm)
    sm_minus = _wilder_smooth(minus_dm)
    sm_tr = _wilder_smooth(tr)

    dx_series: List[float] = []
    for sp, sm, st in zip(sm_plus, sm_minus, sm_tr):
        if st == 0:
            dx_series.append(0.0)
            continue
        plus_di = 100.0 * sp / st
        minus_di = 100.0 * sm / st
        denom = plus_di + minus_di
        dx_series.append(100.0 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0)

    if len(dx_series) < period:
        raise ValueError(
            f"insufficient DX history for ADX smoothing: have {len(dx_series)} need {period}"
        )

    # Wilder-smooth DX with the same period to get ADX. First ADX value =
    # mean of first `period` DX values (equivalent to sum/period scaled — we
    # follow the canonical formulation: first ADX = average of first 14 DX).
    adx = sum(dx_series[:period]) / period
    for v in dx_series[period:]:
        adx = (adx * (period - 1) + v) / period
    return adx


# --- alpaca client -----------------------------------------------------------

_ALPACA_CONFIG_PATH = Path("C:/TradingScripts/alpaca_config.json")
_data_client = None  # cached StockHistoricalDataClient


def _ensure_data_client():
    """Lazy singleton for the Alpaca market-data client.

    Mirrors the pattern in tradelab.live.receiver._ensure_data_client(): reads
    alpaca_config.json once with utf-8-sig (PowerShell-written JSON has BOM).
    """
    global _data_client
    if _data_client is not None:
        return _data_client
    from alpaca.data.historical import StockHistoricalDataClient
    cfg = json.loads(_ALPACA_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    _data_client = StockHistoricalDataClient(
        cfg["alpaca"]["api_key"], cfg["alpaca"]["secret_key"],
    )
    return _data_client


def _bars_to_ohlc(bars) -> tuple[list[float], list[float], list[float]]:
    """Extract (highs, lows, closes) from a list of alpaca-py Bar objects."""
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    closes = [float(b.close) for b in bars]
    return highs, lows, closes


def _fetch_spy_daily_bars(client, *, days: int = 260) -> list:
    """Fetch SPY daily bars going back ~260 calendar days (~250 trading days).

    Returns a chronologically-sorted list of Bar objects (oldest first).
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    start = datetime.now(timezone.utc) - timedelta(days=days)
    req = StockBarsRequest(
        symbol_or_symbols="SPY",
        timeframe=TimeFrame.Day,
        start=start,
    )
    barset = client.get_stock_bars(req)
    # alpaca-py BarSet exposes .data as Dict[str, List[Bar]].
    data = getattr(barset, "data", None) or {}
    bars = list(data.get("SPY", []) or [])
    # Sort defensively by timestamp (API normally returns oldest-first already).
    bars.sort(key=lambda b: getattr(b, "timestamp"))
    return bars


def _fetch_vix_close(client) -> Optional[float]:
    """Best-effort VIX close. Alpaca-py does not currently expose ^VIX as a
    stock symbol; this attempt is left in place so we light up automatically
    if/when alpaca adds index support. On any failure we return None and the
    caller falls back to a hardcoded value.
    """
    # TODO: wire VIX once alpaca-py supports indices or via yfinance fallback.
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        start = datetime.now(timezone.utc) - timedelta(days=10)
        req = StockBarsRequest(
            symbol_or_symbols="^VIX",
            timeframe=TimeFrame.Day,
            start=start,
        )
        barset = client.get_stock_bars(req)
        data = getattr(barset, "data", None) or {}
        bars = list(data.get("^VIX", []) or [])
        if not bars:
            return None
        bars.sort(key=lambda b: getattr(b, "timestamp"))
        return float(bars[-1].close)
    except Exception:
        return None


# --- public entry point ------------------------------------------------------


def fetch_regime() -> RegimeResult:
    """Fetch live regime signals from Alpaca and classify.

    Pulls SPY ~250 daily bars, computes 30d realized vol, 50d/200d MAs and
    Wilder ADX(14), and delegates to classify_regime(). VIX and breadth are
    placeholders for now (see TODOs in helpers).

    Raises ValueError when fewer than 200 SPY bars are available (we cannot
    compute a 200d MA). The /tradelab/regime endpoint maps this to a 500.
    """
    client = _ensure_data_client()
    bars = _fetch_spy_daily_bars(client)
    if len(bars) < 200:
        raise ValueError(
            f"insufficient SPY history for regime banner: {len(bars)} bars (need 200)"
        )

    highs, lows, closes = _bars_to_ohlc(bars)

    realized_vol = _realized_vol_30d(closes)
    ma_50 = _simple_moving_average(closes, 50)
    ma_200 = _simple_moving_average(closes, 200)
    last_close = closes[-1]
    adx = _wilder_adx(highs, lows, closes, period=14)

    vix = _fetch_vix_close(client)
    if vix is None:
        # Fallback: alpaca-py doesn't expose ^VIX as a stock symbol today.
        # 18.0 is a neutral mid-range VIX that won't tip the vol classifier
        # toward either LOW (<17) or HIGH (>25) on its own.
        vix = 18.0

    # TODO: wire breadth once we have an S&P 500 universe data source.
    # 60.0 is the BROAD/MIXED boundary — chosen to be neutral until wired.
    breadth_pct_above_50d = 60.0

    return classify_regime(
        vix=vix,
        realized_vol_30d=realized_vol,
        spx_above_50ma=last_close > ma_50,
        spx_above_200ma=last_close > ma_200,
        adx=adx,
        breadth_pct_above_50d=breadth_pct_above_50d,
    )
