"""Tests for fetch_regime() and its pure-function helpers.

Network is never hit: we monkeypatch _ensure_data_client to return a fake
client whose get_stock_bars returns a BarSet-like object backed by lists of
SimpleNamespace bars.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tradelab.regime import banner as banner_mod
from tradelab.regime.banner import (
    _realized_vol_30d,
    _simple_moving_average,
    _wilder_adx,
    fetch_regime,
)


# --- helpers for synthetic bars ----------------------------------------------


def _make_bar(ts: datetime, close: float, *, hi: float | None = None,
              lo: float | None = None) -> SimpleNamespace:
    """Build a duck-typed Bar with the attributes our code reads."""
    return SimpleNamespace(
        symbol="SPY",
        timestamp=ts,
        open=close,
        high=hi if hi is not None else close * 1.005,
        low=lo if lo is not None else close * 0.995,
        close=close,
        volume=1_000_000.0,
        trade_count=10000.0,
        vwap=close,
    )


class _FakeBarSet:
    def __init__(self, mapping):
        self.data = mapping


class _FakeClient:
    """Fake StockHistoricalDataClient.

    `responses` maps symbol -> list[Bar] (or an Exception to raise).
    """

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def get_stock_bars(self, req):
        self.calls.append(req)
        sym = req.symbol_or_symbols
        if sym in self._responses:
            payload = self._responses[sym]
            if isinstance(payload, Exception):
                raise payload
            return _FakeBarSet({sym: payload})
        # Unknown symbols -> empty BarSet (alpaca returns empty data, not error)
        return _FakeBarSet({})


def _build_calm_uptrend_bars(n: int = 250) -> list[SimpleNamespace]:
    """SPY-like series: slow steady uptrend, low realized vol.

    Slope ~0.05% per day. Highs/lows = +/-0.5% around close. The resulting
    realized vol will be near-zero (deterministic series) so the classifier
    sees LOW vol, the close ends well above both MAs (UP), ADX > 20.
    """
    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out: list[SimpleNamespace] = []
    for i in range(n):
        close = 100.0 * (1.0005 ** i)
        out.append(_make_bar(base_ts + timedelta(days=i), close))
    return out


# --- helper unit tests -------------------------------------------------------


def test_realized_vol_constant_series_is_zero():
    closes = [100.0] * 50
    rv = _realized_vol_30d(closes)
    assert rv == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_known_value():
    """Geometric series with constant +0.1% daily move -> stdev of log returns
    is zero (all returns equal), so annualized vol = 0."""
    closes = [100.0 * (1.001 ** i) for i in range(60)]
    assert _realized_vol_30d(closes) == pytest.approx(0.0, abs=1e-10)


def test_realized_vol_alternating_series():
    """Alternating +1% / -1% returns. Daily log-return stdev should equal
    |ln(1.01)| (since mean is ~0). Annualized = stdev * sqrt(252).
    """
    closes = [100.0]
    factor = 1.01
    for i in range(60):
        factor = 1.01 if i % 2 == 0 else (1 / 1.01)
        closes.append(closes[-1] * factor)
    rv = _realized_vol_30d(closes)
    # Each return is +/- ln(1.01); sample stdev of equal-magnitude alternating
    # values with mean 0 is sqrt(sum/(n-1)) ≈ ln(1.01) * sqrt(n/(n-1)).
    n = 30
    expected = math.log(1.01) * math.sqrt(n / (n - 1)) * math.sqrt(252.0)
    assert rv == pytest.approx(expected, rel=0.02)


def test_sma_basic():
    vals = [float(i) for i in range(1, 11)]  # 1..10
    assert _simple_moving_average(vals, 5) == pytest.approx(8.0)  # mean of 6..10
    assert _simple_moving_average(vals, 10) == pytest.approx(5.5)


def test_sma_insufficient_raises():
    with pytest.raises(ValueError):
        _simple_moving_average([1.0, 2.0], window=5)


def test_adx_strong_uptrend_is_high():
    """A monotonic uptrend with no pullbacks -> ADX should peg near 100."""
    closes = [100.0 + i for i in range(50)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    adx = _wilder_adx(highs, lows, closes, period=14)
    # Pure uptrend with -DM == 0 throughout -> DX = 100 every bar -> ADX = 100.
    assert adx == pytest.approx(100.0, abs=1e-9)


def test_adx_no_movement_is_zero():
    """Flat series (high=low=close=const) -> +DM = -DM = 0, TR = 0.
    DX is set to 0 when smoothed TR is 0; ADX = 0.
    """
    closes = [100.0] * 50
    highs = [100.0] * 50
    lows = [100.0] * 50
    adx = _wilder_adx(highs, lows, closes, period=14)
    assert adx == pytest.approx(0.0, abs=1e-9)


def test_adx_insufficient_bars_raises():
    closes = [100.0 + i for i in range(20)]  # < 2*14+1 = 29
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    with pytest.raises(ValueError, match="need >= 29"):
        _wilder_adx(highs, lows, closes, period=14)


# --- fetch_regime tests ------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_data_client_singleton():
    """Each test starts with a fresh _data_client cache."""
    banner_mod._data_client = None
    yield
    banner_mod._data_client = None


def test_fetch_regime_happy_path_calm_up(monkeypatch):
    """Synthetic SPY = slow steady uptrend, no VIX response -> fallback used.
    Expect: classifier sees LOW-or-MED vol, TRENDING/UNCLEAR trend, BROAD breadth.
    """
    spy_bars = _build_calm_uptrend_bars(250)
    fake = _FakeClient({"SPY": spy_bars, "^VIX": Exception("alpaca rejects ^VIX")})
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    result = fetch_regime()

    # last close is well above both MAs in a steady uptrend
    # realized vol on a deterministic geometric series is ~0
    # ADX on a pure uptrend pegs at 100
    # VIX falls back to 18.0 (medium); rv ~0 -> LOW kicks in only if vix < 17.
    # With vix=18 we land in MED (vix < 25 and rv < 0.22).
    assert result.vol in ("LOW", "MED")
    assert result.trend == "TRENDING"
    assert result.breadth == "BROAD"  # hardcoded 60.0 -> BROAD boundary
    assert result.vix == pytest.approx(18.0)
    assert result.realized_vol_30d == pytest.approx(0.0, abs=1e-3)
    assert result.adx == pytest.approx(100.0, abs=0.1)
    assert result.breadth_pct_above_50d == pytest.approx(60.0)


def test_fetch_regime_vix_fetch_failure_uses_fallback(monkeypatch):
    """When ^VIX fetch raises, fetch_regime falls back to vix=18.0."""
    spy_bars = _build_calm_uptrend_bars(250)

    class _RaisingClient:
        def get_stock_bars(self, req):
            if req.symbol_or_symbols == "SPY":
                return _FakeBarSet({"SPY": spy_bars})
            raise RuntimeError("no index data")

    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: _RaisingClient())

    result = fetch_regime()
    assert result.vix == pytest.approx(18.0)


def test_fetch_regime_vix_empty_response_uses_fallback(monkeypatch):
    """When ^VIX returns an empty dict (alpaca silently ignores indices),
    fetch_regime still falls back to vix=18.0 rather than crashing."""
    spy_bars = _build_calm_uptrend_bars(250)
    fake = _FakeClient({"SPY": spy_bars})  # ^VIX -> empty BarSet
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    result = fetch_regime()
    assert result.vix == pytest.approx(18.0)


def test_fetch_regime_insufficient_bars_raises(monkeypatch):
    """Less than 200 SPY bars -> we can't compute a 200d MA, raise."""
    spy_bars = _build_calm_uptrend_bars(150)
    fake = _FakeClient({"SPY": spy_bars})
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    with pytest.raises(ValueError, match="insufficient SPY history"):
        fetch_regime()


def test_fetch_regime_vix_success_used(monkeypatch):
    """If alpaca *does* return ^VIX bars, fetch_regime uses the real value."""
    spy_bars = _build_calm_uptrend_bars(250)
    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    vix_bars = [_make_bar(base_ts + timedelta(days=i), 22.5) for i in range(5)]
    fake = _FakeClient({"SPY": spy_bars, "^VIX": vix_bars})
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    result = fetch_regime()
    assert result.vix == pytest.approx(22.5)


def test_fetch_regime_breadth_is_stub(monkeypatch):
    """Until the breadth data source is wired, breadth is hardcoded at 60.0."""
    spy_bars = _build_calm_uptrend_bars(250)
    fake = _FakeClient({"SPY": spy_bars})
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    result = fetch_regime()
    assert result.breadth_pct_above_50d == pytest.approx(60.0)


def test_fetch_regime_passes_correct_request(monkeypatch):
    """Ensure we ask alpaca for SPY daily bars over a ~year-long window."""
    spy_bars = _build_calm_uptrend_bars(250)
    fake = _FakeClient({"SPY": spy_bars})
    monkeypatch.setattr(banner_mod, "_ensure_data_client", lambda: fake)

    fetch_regime()

    spy_calls = [c for c in fake.calls if c.symbol_or_symbols == "SPY"]
    assert len(spy_calls) == 1
    spy_req = spy_calls[0]
    # Should be the Day timeframe and a start ~260 days ago. (TimeFrame
    # in alpaca-py is a class with mutable instances; compare by repr.)
    from alpaca.data.timeframe import TimeFrame
    assert str(spy_req.timeframe) == str(TimeFrame.Day)
    assert spy_req.start is not None
    # alpaca-py may strip tzinfo on the StockBarsRequest model; normalize.
    start = spy_req.start
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - start).days
    # Allow some slack but it should be in the ~260d ballpark.
    assert 250 <= age_days <= 270
