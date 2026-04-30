"""Tests for QS sub-grid math. Pure functions, no I/O."""
import numpy as np
import pandas as pd
import pytest

from tradelab.web.qs_metrics import (
    sharpe, sortino, cagr, max_drawdown,
    monthly_returns_matrix, rolling_sharpe, drawdown_series,
)


@pytest.fixture
def daily_returns_3y():
    """3 years of synthetic daily returns, deterministic."""
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2023-01-01", periods=756, freq="B")
    returns = pd.Series(rng.normal(0.0005, 0.01, 756), index=dates)
    return returns


def test_sharpe_ratio_known_series(daily_returns_3y):
    # Actual computed value for seed=42, mean=0.0005, std=0.01, n=756: ~0.159
    assert sharpe(daily_returns_3y) == pytest.approx(0.159, abs=0.05)


def test_sortino_ratio_known_series(daily_returns_3y):
    # Actual computed value for seed=42 fixture: ~0.266
    assert sortino(daily_returns_3y) == pytest.approx(0.266, abs=0.05)


def test_cagr_known_series(daily_returns_3y):
    # Actual computed value for seed=42 fixture: ~0.0127 (~1.3% annualised)
    assert cagr(daily_returns_3y) == pytest.approx(0.013, abs=0.01)


def test_max_drawdown_known_series(daily_returns_3y):
    dd = max_drawdown(daily_returns_3y)
    assert -0.30 < dd < -0.02
    assert isinstance(dd, float)


def test_monthly_returns_matrix_shape(daily_returns_3y):
    m = monthly_returns_matrix(daily_returns_3y)
    # 3 years × 12 months (Dec-2025 is NaN — data ends Nov-2025)
    assert m.shape == (3, 12)
    # Use nansum so the single NaN cell (Dec-2025) does not poison the assertion
    import numpy as np
    assert -1.0 < np.nansum(m.values) < 5.0


def test_rolling_sharpe_30d_length(daily_returns_3y):
    rs = rolling_sharpe(daily_returns_3y, window=30)
    assert len(rs) == len(daily_returns_3y)
    # First 29 should be NaN; remainder finite
    assert rs.iloc[:29].isna().all()
    assert rs.iloc[29:].notna().all()


def test_empty_series_returns_zero():
    empty = pd.Series([], dtype=float)
    assert sharpe(empty) == 0.0
    assert sortino(empty) == 0.0
    assert cagr(empty) == 0.0
    assert max_drawdown(empty) == 0.0


def test_drawdown_series_aligns_with_input(daily_returns_3y):
    dd = drawdown_series(daily_returns_3y)
    assert len(dd) == len(daily_returns_3y)
    # Drawdown is always 0 (at a fresh peak) or negative
    assert (dd <= 1e-12).all()
    # Min should match scalar max_drawdown
    assert float(dd.min()) == pytest.approx(max_drawdown(daily_returns_3y), abs=1e-9)


def test_drawdown_series_starts_at_zero(daily_returns_3y):
    dd = drawdown_series(daily_returns_3y)
    # First bar is always at peak (no prior history) -> 0 drawdown
    assert dd.iloc[0] == pytest.approx(0.0, abs=1e-12)


def test_drawdown_series_empty_returns_empty():
    empty = pd.Series([], dtype=float)
    dd = drawdown_series(empty)
    assert len(dd) == 0
    assert isinstance(dd, pd.Series)
