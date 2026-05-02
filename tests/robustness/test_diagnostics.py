"""Tests for robustness diagnostic helpers (wf_decay, trade_efficiency)."""
from __future__ import annotations

from tradelab.results import (
    BacktestMetrics, BacktestResult, Trade,
    WalkForwardResult, WalkForwardWindow,
)
from tradelab.robustness.diagnostics import compute_wf_decay


def _window(idx: int, gp: float, gl: float) -> WalkForwardWindow:
    """Build a minimal WF window with the given gross profit/loss in test_metrics."""
    pf = (gp / gl) if gl > 0 else 0.0
    metrics = BacktestMetrics(
        total_trades=20, wins=12, losses=8, win_rate=60.0,
        profit_factor=pf, gross_profit=gp, gross_loss=gl,
    )
    return WalkForwardWindow(
        index=idx,
        train_start="2022-01-01", train_end="2022-06-30",
        test_start="2022-07-01", test_end="2022-12-31",
        train_metrics=None, test_metrics=metrics, best_params={},
    )


def _wf(windows: list[WalkForwardWindow]) -> WalkForwardResult:
    return WalkForwardResult(
        strategy="x", n_windows=len(windows), windows=windows,
        wfe_ratio=0.8,
    )


def test_wf_decay_decay_pattern():
    """Late-half PF lower than early-half should give ratio < 1.0."""
    # 6 windows; first 3 strong, last 3 weak.
    # Early aggregate PF = 300/100 = 3.0; Late aggregate PF = 90/100 = 0.9
    # Ratio = 0.9 / 3.0 = 0.30
    windows = [
        _window(0, 100, 33), _window(1, 100, 33), _window(2, 100, 34),
        _window(3, 30, 33),  _window(4, 30, 33),  _window(5, 30, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 0.30) < 0.01


def test_wf_decay_stable_pattern():
    """Equal PFs across windows should give ratio ~ 1.0."""
    windows = [_window(i, 100, 50) for i in range(6)]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 1.0) < 0.01


def test_wf_decay_improving_pattern():
    """Late-half PF higher than early-half should give ratio > 1.0."""
    # Early: 60/100 = 0.6 PF aggregate; Late: 200/100 = 2.0 PF aggregate.
    # Ratio = 2.0 / 0.6 = 3.33
    windows = [
        _window(0, 20, 33), _window(1, 20, 33), _window(2, 20, 34),
        _window(3, 65, 33), _window(4, 65, 33), _window(5, 70, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert result > 2.0


def test_wf_decay_insufficient_windows_returns_none():
    """N < 4 valid windows should return None."""
    windows = [_window(i, 100, 50) for i in range(3)]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_skips_windows_with_no_test_metrics():
    """Windows where test_metrics is None should be filtered out, not crash."""
    valid = [_window(i, 100, 50) for i in range(4)]
    # Add a window with no test_metrics
    no_metrics = WalkForwardWindow(
        index=4,
        train_start="2024-01-01", train_end="2024-06-30",
        test_start="2024-07-01", test_end="2024-12-31",
        train_metrics=None, test_metrics=None, best_params={},
    )
    result = compute_wf_decay(_wf(valid + [no_metrics]))
    assert result is not None  # 4 valid windows is enough
    assert abs(result - 1.0) < 0.01


def test_wf_decay_zero_gross_loss_returns_none():
    """If either half has zero gross_loss, PF undefined → return None."""
    # Late half has zero gross_loss in every window
    windows = [
        _window(0, 100, 50), _window(1, 100, 50),
        _window(2, 100, 0),  _window(3, 100, 0),
    ]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_all_zero_metrics_returns_none():
    """Windows with all-zero metrics should produce None (no PF computable)."""
    windows = [_window(i, 0, 0) for i in range(6)]
    assert compute_wf_decay(_wf(windows)) is None
