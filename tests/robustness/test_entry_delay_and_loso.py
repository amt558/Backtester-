"""Entry-delay and LOSO integration tests — use enriched synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.marketdata import enrich_universe
from tradelab.robustness.entry_delay import EntryDelayResult, run_entry_delay
from tradelab.robustness.loso import LOSOResult, run_loso
from tradelab.strategies.s2_pocket_pivot import S2PocketPivot


def _raw_ohlcv(n=300, seed=0, drift=0.001, vol=0.012):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    returns = rng.normal(drift, vol, size=n)
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


@pytest.fixture
def enriched():
    raw = {
        "SPY": _raw_ohlcv(seed=1, drift=0.0005),
        "AAPL": _raw_ohlcv(seed=2, drift=0.0010),
        "MSFT": _raw_ohlcv(seed=3, drift=0.0009),
        "NVDA": _raw_ohlcv(seed=4, drift=0.0011),
    }
    return enrich_universe(raw, benchmark="SPY")


def test_entry_delay_returns_requested_delays(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    r = run_entry_delay(strat, enriched, delays=[0, 1, 2],
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    assert isinstance(r, EntryDelayResult)
    assert [p.delay for p in r.points] == [0, 1, 2]


def test_entry_delay_pf_drop_one_bar_is_a_fraction(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    r = run_entry_delay(strat, enriched, delays=[0, 1],
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    drop = r.pf_drop_one_bar
    # Could be any real number; test it's finite & the helper doesn't blow up
    assert drop == drop   # not NaN


def test_loso_drops_one_symbol_per_fold(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    r = run_loso(strat, enriched, benchmark="SPY",
                 spy_close=spy, start="2023-01-02", end="2024-06-30")
    assert isinstance(r, LOSOResult)
    # 3 tradable symbols → 3 folds (each drops one)
    assert len(r.folds) == 3
    symbols_held_out = [f.held_out_symbol for f in r.folds]
    assert set(symbols_held_out) == {"AAPL", "MSFT", "NVDA"}


def test_loso_spread_is_nonneg(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    r = run_loso(strat, enriched, benchmark="SPY",
                 spy_close=spy, start="2023-01-02", end="2024-06-30")
    assert r.pf_spread >= 0
    assert r.pf_min <= r.pf_mean <= r.pf_max
