"""Cost sensitivity sweep tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.cost_sweep import (
    CostSweepResult,
    format_cost_sweep_markdown,
    run_cost_sweep,
)
from tradelab.marketdata import enrich_universe
from tradelab.strategies.s2_pocket_pivot import S2PocketPivot


def _raw_ohlcv(n=300, seed=0, drift=0.001, vol=0.012):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
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


@pytest.fixture
def enriched_universe():
    raw = {
        "SPY": _raw_ohlcv(seed=1, drift=0.0005),
        "AAPL": _raw_ohlcv(seed=2, drift=0.0010),
        "MSFT": _raw_ohlcv(seed=3, drift=0.0009),
    }
    return enrich_universe(raw, benchmark="SPY")


def test_sweep_returns_one_point_per_multiplier(enriched_universe):
    strat = S2PocketPivot()
    spy = enriched_universe["SPY"].set_index("Date")["Close"]
    result = run_cost_sweep(
        strat, enriched_universe,
        multipliers=[0.0, 1.0, 4.0],
        spy_close=spy,
        start="2023-01-02", end="2024-12-31",
    )
    assert isinstance(result, CostSweepResult)
    assert len(result.points) == 3
    assert [p.multiplier for p in result.points] == [0.0, 1.0, 4.0]


def test_sweep_commission_scales_with_multiplier(enriched_universe):
    strat = S2PocketPivot()
    spy = enriched_universe["SPY"].set_index("Date")["Close"]
    result = run_cost_sweep(
        strat, enriched_universe,
        multipliers=[0.0, 0.5, 1.0, 2.0],
        spy_close=spy,
        start="2023-01-02", end="2024-12-31",
    )
    commissions = [p.commission_per_trade for p in result.points]
    # Should be 0, 0.5*base, base, 2*base
    assert commissions[0] == 0.0
    assert commissions[2] == result.baseline_commission
    assert commissions[3] == 2 * result.baseline_commission


def test_sweep_higher_cost_lowers_final_equity(enriched_universe):
    """Monotone: higher commission → lower final equity (for strategies with any trades)."""
    strat = S2PocketPivot()
    spy = enriched_universe["SPY"].set_index("Date")["Close"]
    result = run_cost_sweep(
        strat, enriched_universe,
        multipliers=[0.0, 4.0],
        spy_close=spy,
        start="2023-01-02", end="2024-12-31",
    )
    zero_cost = result.points[0].metrics
    high_cost = result.points[1].metrics
    # Only check if there were actual trades
    if zero_cost.total_trades > 0:
        assert high_cost.final_equity <= zero_cost.final_equity, (
            f"expected higher cost to not exceed zero cost; got {high_cost.final_equity} vs {zero_cost.final_equity}"
        )


def test_format_cost_sweep_markdown_smoke(enriched_universe):
    strat = S2PocketPivot()
    spy = enriched_universe["SPY"].set_index("Date")["Close"]
    result = run_cost_sweep(
        strat, enriched_universe,
        multipliers=[0.0, 1.0, 4.0],
        spy_close=spy,
        start="2023-01-02", end="2024-12-31",
    )
    md = format_cost_sweep_markdown(result)
    assert "Cost sensitivity sweep" in md
    assert "0x" in md
    assert "1x" in md
    assert "4x" in md


def test_to_table_shape(enriched_universe):
    strat = S2PocketPivot()
    spy = enriched_universe["SPY"].set_index("Date")["Close"]
    result = run_cost_sweep(
        strat, enriched_universe,
        multipliers=[0.0, 1.0],
        spy_close=spy,
        start="2023-01-02", end="2024-12-31",
    )
    df = result.to_table()
    assert list(df.columns) == [
        "multiplier", "commission_per_trade", "total_trades", "profit_factor",
        "sharpe_ratio", "pct_return", "max_drawdown_pct", "final_equity",
    ]
    assert len(df) == 2
