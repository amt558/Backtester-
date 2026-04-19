"""Indicator enrichment tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.marketdata import enrich_universe, enrich_with_indicators


def _raw_ohlcv(n=250, seed=0, drift=0.0005, vol=0.015, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=n, freq="B")
    returns = rng.normal(loc=drift, scale=vol, size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, n)))
    openp = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(800_000, 5_000_000, n)
    return pd.DataFrame({
        "Date": dates, "Open": openp,
        "High": np.maximum.reduce([openp, close, high]),
        "Low":  np.minimum.reduce([openp, close, low]),
        "Close": close, "Volume": volume,
    })


S2_REQUIRED = {
    "ATR", "ATR_pct", "RSI",
    "EMA10", "EMA21",
    "SMA10", "SMA21", "SMA50", "SMA200",
    "Vol_MA20", "Vol_Ratio", "Vol_OK",
    "Trend_OK", "Above50", "Above200",
    "Pocket_Pivot", "RS_21d",
}


def test_enrich_adds_all_s2_columns():
    df = _raw_ohlcv()
    enriched = enrich_with_indicators(df)
    missing = S2_REQUIRED - set(enriched.columns)
    assert not missing, f"missing required indicator columns: {missing}"


def test_enrich_preserves_original_columns():
    df = _raw_ohlcv()
    enriched = enrich_with_indicators(df)
    for col in ("Date", "Open", "High", "Low", "Close", "Volume"):
        assert col in enriched.columns
        assert len(enriched) == len(df)


def test_enrich_does_not_mutate_input():
    df = _raw_ohlcv()
    before_cols = set(df.columns)
    enrich_with_indicators(df)
    assert set(df.columns) == before_cols


def test_enrich_universe_uses_benchmark_for_rs():
    data = {
        "SPY": _raw_ohlcv(seed=1),
        "AAPL": _raw_ohlcv(seed=2),
    }
    out = enrich_universe(data, benchmark="SPY")
    assert "SPY" in out and "AAPL" in out
    # SPY's RS_21d should be all 0; AAPL's should have real values after 21 bars
    assert (out["SPY"]["RS_21d"] == 0).all()
    aapl_rs = out["AAPL"]["RS_21d"].dropna()
    assert len(aapl_rs) > 0
    # RS values should not all be identically zero (that would mean fallback)
    assert aapl_rs.abs().sum() > 0


def test_enrich_universe_handles_missing_benchmark():
    data = {"AAPL": _raw_ohlcv(seed=3)}  # no SPY
    out = enrich_universe(data, benchmark="SPY")
    # Should still return AAPL enriched, RS_21d filled with 0
    assert "AAPL" in out
    assert (out["AAPL"]["RS_21d"] == 0).all()


def test_enriched_data_is_sufficient_for_s2_signals():
    """End-to-end: run S2PocketPivot.generate_signals on enriched data."""
    from tradelab.strategies.s2_pocket_pivot import S2PocketPivot
    data = {
        "SPY": _raw_ohlcv(seed=11, n=300),
        "AAPL": _raw_ohlcv(seed=12, n=300),
    }
    enriched = enrich_universe(data, benchmark="SPY")
    spy_close = enriched["SPY"].set_index("Date")["Close"]
    signals = S2PocketPivot().generate_signals(
        {"AAPL": enriched["AAPL"]}, spy_close=spy_close
    )
    # buy_signal column must be present and boolean
    assert "buy_signal" in signals["AAPL"].columns
    assert signals["AAPL"]["buy_signal"].dtype == bool
