"""Monte Carlo trade-resampling tests."""
from __future__ import annotations

import numpy as np
import pytest

from tradelab.results import BacktestResult, BacktestMetrics, Trade
from tradelab.robustness.monte_carlo import (
    MonteCarloResult,
    run_monte_carlo,
)


def _bt_with_pnls(pnls, strategy="x"):
    trades = [Trade(
        ticker="T", entry_date="2023-01-01", exit_date=f"2023-01-{i+2:02d}",
        entry_price=100.0, exit_price=100.0 + p/10, shares=10, pnl=float(p),
        pnl_pct=float(p) / 10.0, bars_held=1, exit_reason="TEST",
    ) for i, p in enumerate(pnls)]
    return BacktestResult(
        strategy=strategy, start_date="2023-01-01", end_date="2023-12-31",
        params={}, metrics=BacktestMetrics(total_trades=len(pnls)),
        trades=trades, equity_curve=[],
    )


def test_mc_runs_3x4_grid():
    rng = np.random.default_rng(0)
    pnls = rng.normal(50, 200, size=50).tolist()
    bt = _bt_with_pnls(pnls)
    mc = run_monte_carlo(bt, n_simulations=20, seed=42)
    assert isinstance(mc, MonteCarloResult)
    # 3 methods * 4 metrics = 12 distributions
    assert len(mc.distributions) == 12
    for d in mc.distributions:
        assert d.method in ("shuffle", "bootstrap", "block_bootstrap")
        assert d.metric in ("max_dd", "max_loss_streak", "time_underwater", "ulcer_index")
        assert len(d.samples) == 20


def test_mc_observed_values_are_scalar():
    pnls = [100, -50, 200, -80, 150, -30, 90]
    bt = _bt_with_pnls(pnls)
    mc = run_monte_carlo(bt, n_simulations=50, seed=1)
    for d in mc.distributions:
        assert isinstance(d.observed, float)


def test_mc_deterministic_with_seed():
    pnls = list(np.random.default_rng(0).normal(40, 150, 30))
    bt = _bt_with_pnls(pnls)
    a = run_monte_carlo(bt, n_simulations=30, seed=99)
    b = run_monte_carlo(bt, n_simulations=30, seed=99)
    # Same seed → same distributions
    for da, db in zip(a.distributions, b.distributions):
        assert da.samples == db.samples


def test_mc_handles_degenerate_empty_trades():
    bt = _bt_with_pnls([])
    mc = run_monte_carlo(bt, n_simulations=10, seed=1)
    assert mc.n_trades == 0
    assert mc.n_simulations == 0
    # Still returns empty distributions for all 12 cells
    assert len(mc.distributions) == 12


def test_mc_percentile_in_valid_range():
    pnls = list(np.random.default_rng(7).normal(30, 100, 80))
    bt = _bt_with_pnls(pnls)
    mc = run_monte_carlo(bt, n_simulations=200, seed=5)
    for d in mc.distributions:
        import math
        p = d.percentile_of_observed
        assert math.isnan(p) or 0.0 <= p <= 100.0


def test_mc_get_lookup_works():
    pnls = [1.0, -1.0, 2.0, -0.5]
    bt = _bt_with_pnls(pnls)
    mc = run_monte_carlo(bt, n_simulations=10, seed=1)
    d = mc.get("shuffle", "max_dd")
    assert d.method == "shuffle"
    assert d.metric == "max_dd"
    with pytest.raises(KeyError):
        mc.get("shuffle", "no_such_metric")


def test_mc_block_bootstrap_runs():
    pnls = list(np.random.default_rng(3).normal(20, 80, 64))
    bt = _bt_with_pnls(pnls)
    mc = run_monte_carlo(bt, n_simulations=20, methods=["block_bootstrap"],
                         metrics=["max_dd"], seed=1)
    d = mc.get("block_bootstrap", "max_dd")
    assert len(d.samples) == 20
