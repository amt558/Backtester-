"""Executive report generator tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.reporting import generate_executive_report
from tradelab.results import (
    BacktestMetrics, BacktestResult,
    OptunaResult, OptunaTrial,
    WalkForwardResult, WalkForwardWindow,
    Trade,
)


@pytest.fixture
def minimal_backtest():
    metrics = BacktestMetrics(
        total_trades=100, wins=60, losses=40, win_rate=60.0,
        profit_factor=1.45, gross_profit=10000.0, gross_loss=6900.0,
        net_pnl=3100.0, pct_return=3.1, annual_return=12.4,
        final_equity=103100.0, avg_win_pct=1.2, avg_loss_pct=-0.9,
        avg_bars_held=3.5, max_drawdown_pct=-8.2, sharpe_ratio=1.1,
    )
    return BacktestResult(
        strategy="test_strat",
        start_date="2023-01-01", end_date="2023-12-31",
        params={"foo": 1.0}, metrics=metrics, trades=[], equity_curve=[],
    )


def test_report_generates_file(minimal_backtest, tmp_path):
    path = generate_executive_report(minimal_backtest, out_dir=tmp_path)
    assert path.exists()
    assert path.name == "executive_report.md"
    content = path.read_text()
    assert "test_strat" in content
    assert "Executive verdict" in content
    assert "1.45" in content  # PF


def test_report_handles_no_optuna_no_wf(minimal_backtest, tmp_path):
    path = generate_executive_report(minimal_backtest, out_dir=tmp_path)
    content = path.read_text()
    # DSR now live (not a stub). Robustness-suite stub remains for Phase 1.
    assert "Deflated Sharpe (DSR)" in content
    assert "Pending Phase 1" in content  # Robustness suite stub
    assert "No optimization" in content or "Parameter importance" in content


def test_report_includes_wf_when_provided(minimal_backtest, tmp_path):
    window = WalkForwardWindow(
        index=0,
        train_start="2023-01-01", train_end="2023-06-30",
        test_start="2023-07-01", test_end="2023-09-30",
        train_metrics=minimal_backtest.metrics,
        test_metrics=minimal_backtest.metrics,
        best_params={"foo": 1.0},
    )
    wf = WalkForwardResult(
        strategy="test_strat", n_windows=1, windows=[window],
        aggregate_oos=minimal_backtest.metrics, wfe_ratio=0.85,
        oos_trades=[], oos_equity_curve=[],
    )
    path = generate_executive_report(minimal_backtest, wf_result=wf, out_dir=tmp_path)
    content = path.read_text()
    assert "Per-window walk-forward" in content
    assert "0.85" in content  # WFE


def test_report_includes_optuna_when_provided(minimal_backtest, tmp_path):
    trial = OptunaTrial(number=0, fitness=1.5, params={"foo": 1.0}, metrics={})
    opt = OptunaResult(
        strategy="test_strat", n_trials=10,
        best_trial=trial, all_trials=[trial],
        param_importance={"foo": 0.65, "bar": 0.35},
        best_backtest=None,
    )
    path = generate_executive_report(minimal_backtest, optuna_result=opt, out_dir=tmp_path)
    content = path.read_text()
    assert "foo" in content
    assert "Parameter importance" in content


def test_report_observations_are_specific(minimal_backtest, tmp_path):
    """Observations section must contain concrete numbers, not vague language."""
    path = generate_executive_report(minimal_backtest, out_dir=tmp_path)
    content = path.read_text()
    # Any of these concrete values should appear somewhere in observations
    assert "100" in content or "60" in content or "3.5" in content
    # Must NOT contain prescriptive language
    for forbidden in ("should reduce", "we recommend", "suggest adding"):
        assert forbidden.lower() not in content.lower()
