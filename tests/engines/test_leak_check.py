"""Look-ahead bias detector tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.canaries import LeakCanary, RandCanary
from tradelab.engines.leak_check import (
    LeakCheckResult,
    dynamic_shift_check,
    run_leak_check,
    static_scan,
)
from tradelab.marketdata import enrich_universe


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
        "SPY":  _raw_ohlcv(seed=1, drift=0.0005),
        "AAPL": _raw_ohlcv(seed=2, drift=0.001),
        "MSFT": _raw_ohlcv(seed=3, drift=0.0007),
    }
    return enrich_universe(raw, benchmark="SPY")


def test_static_scan_flags_leak_canary():
    """LeakCanary uses .shift(-lookahead) — static scan must flag it."""
    res = static_scan(LeakCanary())
    assert res.n_findings > 0
    found_patterns = " ".join(f.line for f in res.findings)
    assert "shift" in found_patterns.lower()


def test_static_scan_clean_for_rand_canary():
    """RandCanary has no lookahead — static scan should be clean."""
    res = static_scan(RandCanary())
    # RandCanary may have benign matches (e.g., comments) but no actual
    # lookahead patterns. Tolerance: <= 1 finding.
    assert res.n_findings <= 1


def test_dynamic_shift_flags_leak_canary(enriched):
    """LeakCanary's PF should drop dramatically when shifted +1 bar."""
    res = dynamic_shift_check(LeakCanary(), enriched,
                                start="2023-01-02", end="2024-12-31")
    # The canary cheats on bar T using close[T+1]; shift by +1 should kill it
    assert res.flag in ("suspect", "fragile"), (
        f"expected leak detection on LeakCanary, got flag={res.flag} "
        f"(baseline PF {res.baseline_pf}, shifted PF {res.shifted_pf})"
    )


def test_dynamic_shift_runs_for_rand_canary(enriched):
    """RandCanary has no real edge; shift test runs cleanly. Flag may be
    anything because random-entry P&L on a small synthetic universe is noise."""
    res = dynamic_shift_check(RandCanary(), enriched,
                                start="2023-01-02", end="2024-12-31")
    assert res.flag in ("ok", "suspect", "fragile")
    assert isinstance(res.baseline_pf, float)
    assert isinstance(res.shifted_pf, float)


def test_run_leak_check_aggregates(enriched):
    res = run_leak_check(LeakCanary(), enriched,
                          start="2023-01-02", end="2024-12-31")
    assert isinstance(res, LeakCheckResult)
    assert res.strategy == "leak_canary"
    # Static OR dynamic should flag
    assert res.overall_flag in ("suspect", "fragile")


def test_run_leak_check_static_only_when_no_data():
    """Without ticker_data, only the static scan runs."""
    res = run_leak_check(LeakCanary(), ticker_data=None)
    assert res.dynamic is None
    # Static still flags (LeakCanary has the .shift(-N) pattern)
    assert res.overall_flag in ("suspect", "fragile")
