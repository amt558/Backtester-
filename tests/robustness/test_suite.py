"""Integration test: full robustness suite end-to-end on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.backtest import run_backtest
from tradelab.marketdata import enrich_universe
from tradelab.robustness import RobustnessSuiteResult, run_robustness_suite
from tradelab.strategies.s2_pocket_pivot import S2PocketPivot


def _raw_ohlcv(n=250, seed=0, drift=0.001, vol=0.012):
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


def test_suite_end_to_end(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    bt = run_backtest(strat, enriched, spy_close=spy,
                      start="2023-01-02", end="2024-06-30")
    r = run_robustness_suite(
        strat, enriched, bt,
        spy_close=spy, start="2023-01-02", end="2024-06-30",
        mc_n_simulations=50, landscape_grid_size=3,
    )
    assert isinstance(r, RobustnessSuiteResult)
    assert r.verdict.verdict in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert r.monte_carlo is not None
    assert r.param_landscape is not None
    assert r.entry_delay is not None
    assert r.loso is not None


def test_suite_can_skip_tests(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    bt = run_backtest(strat, enriched, spy_close=spy,
                      start="2023-01-02", end="2024-06-30")
    r = run_robustness_suite(
        strat, enriched, bt,
        spy_close=spy, start="2023-01-02", end="2024-06-30",
        mc_n_simulations=20, landscape_grid_size=3,
        skip=["monte_carlo", "loso"],
    )
    assert r.monte_carlo is None
    assert r.loso is None
    assert r.param_landscape is not None
    assert r.entry_delay is not None
