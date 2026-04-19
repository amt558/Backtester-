"""Noise injection tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.backtest import run_backtest
from tradelab.marketdata import enrich_universe
from tradelab.robustness.noise_injection import (
    NoiseInjectionResult,
    _add_noise_to_bar,
    run_noise_injection,
)
from tradelab.strategies.s2_pocket_pivot import S2PocketPivot


def _raw_ohlcv(n=200, seed=0, drift=0.001, vol=0.012):
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


def test_noise_preserves_ohlc_inequalities():
    rng = np.random.default_rng(7)
    df = _raw_ohlcv(n=100, seed=0)
    noisy = _add_noise_to_bar(df, sigma_bp=10.0, rng=rng)
    # H >= max(O, C) and L <= min(O, C) must hold bar-by-bar
    assert (noisy["High"] >= np.maximum(noisy["Open"], noisy["Close"]) - 1e-9).all()
    assert (noisy["Low"] <= np.minimum(noisy["Open"], noisy["Close"]) + 1e-9).all()


def test_noise_injection_returns_correct_seed_count(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    baseline = run_backtest(strat, enriched, spy_close=spy,
                            start="2023-01-02", end="2024-06-30")
    r = run_noise_injection(
        strat, enriched, baseline.metrics,
        n_seeds=5, noise_sigma_bp=5.0,
        spy_close=spy, start="2023-01-02", end="2024-06-30",
    )
    assert isinstance(r, NoiseInjectionResult)
    assert r.n_seeds == 5
    assert len(r.points) == 5


def test_noise_injection_records_baseline(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    baseline = run_backtest(strat, enriched, spy_close=spy,
                            start="2023-01-02", end="2024-06-30")
    r = run_noise_injection(
        strat, enriched, baseline.metrics,
        n_seeds=3, noise_sigma_bp=5.0,
        spy_close=spy, start="2023-01-02", end="2024-06-30",
    )
    assert r.baseline_pf == baseline.metrics.profit_factor
    assert r.baseline_sharpe == baseline.metrics.sharpe_ratio


def test_noise_injection_deterministic_per_seed_base(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    baseline = run_backtest(strat, enriched, spy_close=spy,
                            start="2023-01-02", end="2024-06-30")
    a = run_noise_injection(strat, enriched, baseline.metrics,
                             n_seeds=3, seed_base=999,
                             spy_close=spy, start="2023-01-02", end="2024-06-30")
    b = run_noise_injection(strat, enriched, baseline.metrics,
                             n_seeds=3, seed_base=999,
                             spy_close=spy, start="2023-01-02", end="2024-06-30")
    # Same seed_base → same sequence of per-seed results
    assert [p.metrics.profit_factor for p in a.points] == [p.metrics.profit_factor for p in b.points]


def test_noise_injection_pf_drop_is_fraction(enriched):
    strat = S2PocketPivot()
    spy = enriched["SPY"].set_index("Date")["Close"]
    baseline = run_backtest(strat, enriched, spy_close=spy,
                            start="2023-01-02", end="2024-06-30")
    r = run_noise_injection(strat, enriched, baseline.metrics,
                             n_seeds=5, noise_sigma_bp=5.0,
                             spy_close=spy, start="2023-01-02", end="2024-06-30")
    drop = r.pf_drop_p5_from_baseline
    assert isinstance(drop, float)
