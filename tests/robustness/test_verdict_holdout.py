"""Hold-out OOS gate (S4) — verdict signal #10.

Tests the `hold_out_oos` signal contributed to compute_verdict's signals
list when wf.holdout_result is populated. Mirrors the fixture style of
test_verdict.py — small synthetic BacktestResult + WalkForwardResult.
"""
from __future__ import annotations

from tradelab.results import (
    BacktestMetrics,
    BacktestResult,
    WalkForwardResult,
    WalkForwardWindow,
)
from tradelab.robustness.verdict import compute_verdict


def _bt(pf: float = 1.3, trades: int = 100):
    m = BacktestMetrics(
        total_trades=trades, wins=int(trades * 0.6), losses=int(trades * 0.4),
        win_rate=60.0, profit_factor=pf, sharpe_ratio=1.0, max_drawdown_pct=-10.0,
    )
    return BacktestResult(
        strategy="x", start_date="2023-01-01", end_date="2024-01-01",
        params={}, metrics=m, trades=[], equity_curve=[],
    )


def _wf_with_holdout(holdout_pf: float | None, n_windows: int = 4,
                     wfe: float = 0.85, holdout_months: int = 6):
    """Build a WalkForwardResult with a populated holdout_result.

    n_windows>0 + a non-zero wfe is enough to make the WFE block in
    compute_verdict fire too — that's fine, the test asserts on the
    hold_out_oos signal in particular.
    """
    holdout_metrics = None
    if holdout_pf is not None:
        holdout_metrics = BacktestMetrics(
            total_trades=30, wins=18, losses=12,
            win_rate=60.0, profit_factor=holdout_pf, max_drawdown_pct=-8.0,
        )
    return WalkForwardResult(
        strategy="x",
        n_windows=n_windows,
        windows=[
            WalkForwardWindow(
                index=i, train_start="2023-01-01", train_end="2023-06-30",
                test_start="2023-07-01", test_end="2023-08-31",
                train_metrics=BacktestMetrics(profit_factor=1.4, total_trades=20),
                test_metrics=BacktestMetrics(profit_factor=1.2, total_trades=10),
                best_params={},
            )
            for i in range(n_windows)
        ],
        aggregate_oos=BacktestMetrics(profit_factor=1.2, total_trades=40),
        wfe_ratio=wfe,
        holdout_result=holdout_metrics,
        holdout_window_months=holdout_months if holdout_metrics is not None else None,
    )


def _find(verdict, signal_name):
    for s in verdict.signals:
        if s.name == signal_name:
            return s
    return None


def test_holdout_pf_above_threshold_is_robust():
    """PF >= hold_out_robust_pf (1.50) → outcome 'robust'."""
    bt = _bt(pf=1.3)
    wf = _wf_with_holdout(holdout_pf=1.78)
    v = compute_verdict(bt, wf=wf)
    sig = _find(v, "hold_out_oos")
    assert sig is not None, "hold_out_oos signal missing from verdict"
    assert sig.outcome == "robust", f"expected robust, got {sig.outcome}: {sig.reason}"
    assert "1.78" in sig.reason
    assert "6mo" in sig.reason


def test_holdout_pf_below_fragile_marks_fragile():
    """PF < hold_out_fragile_pf (1.00) → outcome 'fragile'."""
    bt = _bt(pf=1.3)
    wf = _wf_with_holdout(holdout_pf=0.85)
    v = compute_verdict(bt, wf=wf)
    sig = _find(v, "hold_out_oos")
    assert sig is not None, "hold_out_oos signal missing from verdict"
    assert sig.outcome == "fragile", f"expected fragile, got {sig.outcome}: {sig.reason}"
    assert "0.85" in sig.reason


def test_holdout_pf_in_between_inconclusive():
    """Fragile <= PF < Robust → outcome 'inconclusive'."""
    bt = _bt(pf=1.3)
    wf = _wf_with_holdout(holdout_pf=1.20)
    v = compute_verdict(bt, wf=wf)
    sig = _find(v, "hold_out_oos")
    assert sig is not None, "hold_out_oos signal missing from verdict"
    assert sig.outcome == "inconclusive", (
        f"expected inconclusive, got {sig.outcome}: {sig.reason}"
    )
    assert "1.20" in sig.reason


def test_no_holdout_skips_signal():
    """wf.holdout_result is None → no hold_out_oos signal at all."""
    bt = _bt(pf=1.3)
    wf = _wf_with_holdout(holdout_pf=None)
    v = compute_verdict(bt, wf=wf)
    sig = _find(v, "hold_out_oos")
    assert sig is None, (
        f"expected no hold_out_oos signal when holdout_result=None, "
        f"got {sig}"
    )


def test_no_wf_passed_skips_signal():
    """wf=None (no walk-forward run) → no hold_out_oos signal."""
    bt = _bt(pf=1.3)
    v = compute_verdict(bt)  # no wf at all
    sig = _find(v, "hold_out_oos")
    assert sig is None
