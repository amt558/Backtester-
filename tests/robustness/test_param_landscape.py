"""Parameter-landscape grid test."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.marketdata import enrich_universe
from tradelab.robustness.param_landscape import (
    ParamLandscapeResult,
    run_param_landscape,
)
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
    }
    return enrich_universe(raw, benchmark="SPY")


def test_landscape_returns_grid(enriched):
    strat = S2PocketPivot()
    r = run_param_landscape(strat, enriched,
                            start="2023-01-02", end="2024-06-30",
                            grid_size=3)
    assert isinstance(r, ParamLandscapeResult)
    assert len(r.top_params) == 2
    assert len(r.grid_values) == 2
    assert len(r.grid_values[0]) == 3
    assert len(r.fitness_grid) == 3
    assert len(r.fitness_grid[0]) == 3


def test_landscape_fitness_is_finite(enriched):
    strat = S2PocketPivot()
    r = run_param_landscape(strat, enriched,
                            start="2023-01-02", end="2024-06-30",
                            grid_size=3)
    arr = np.array(r.fitness_grid)
    assert np.isfinite(arr).all()


def test_landscape_smoothness_ratio_is_nonneg(enriched):
    strat = S2PocketPivot()
    r = run_param_landscape(strat, enriched,
                            start="2023-01-02", end="2024-06-30",
                            grid_size=3)
    assert r.smoothness_ratio >= 0


def test_landscape_restores_strategy_params(enriched):
    strat = S2PocketPivot()
    baseline = dict(strat.params)
    run_param_landscape(strat, enriched,
                        start="2023-01-02", end="2024-06-30",
                        grid_size=3)
    # After grid scan, strategy.params should be back to baseline
    assert strat.params == baseline
