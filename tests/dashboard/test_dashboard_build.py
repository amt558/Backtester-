"""Dashboard build tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.dashboard import build_dashboard
from tradelab.results import (
    BacktestMetrics, BacktestResult,
    OptunaResult, OptunaTrial,
    WalkForwardResult, WalkForwardWindow,
    Trade,
)


@pytest.fixture
def simple_backtest():
    metrics = BacktestMetrics(
        total_trades=10, wins=6, losses=4, win_rate=60.0,
        profit_factor=1.5, gross_profit=100.0, gross_loss=66.0,
        net_pnl=34.0, pct_return=3.4, annual_return=10.0,
        final_equity=1034.0, avg_win_pct=1.0, avg_loss_pct=-0.8,
        avg_bars_held=2.0, max_drawdown_pct=-5.0, sharpe_ratio=1.2,
    )
    equity_curve = [{"date": f"2023-01-{i:02d}", "equity": 1000 + i * 3} for i in range(1, 11)]
    trades = [Trade(
        ticker="AAPL",
        entry_date="2023-01-01", exit_date="2023-01-05",
        entry_price=100.0, exit_price=101.0, shares=10, pnl=10.0,
        pnl_pct=1.0, bars_held=4, exit_reason="Trail Stop",
    )]
    return BacktestResult(
        strategy="dash_test",
        start_date="2023-01-01", end_date="2023-12-31",
        params={"foo": 1.0}, metrics=metrics,
        trades=trades, equity_curve=equity_curve,
    )


def test_dashboard_builds_file(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    assert path.exists()
    assert path.suffix == ".html"
    content = path.read_text()
    assert "<!DOCTYPE html>" in content
    assert "plotly-2" in content  # CDN reference
    assert "dash_test" in content


def test_dashboard_has_four_tabs(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    assert 'data-tab="performance"' in content
    assert 'data-tab="trades"' in content
    assert 'data-tab="robustness"' in content
    assert 'data-tab="parameters"' in content


def test_dashboard_trades_tab_renders_table(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    # Trade table + per-symbol chart
    assert "All trades" in content
    assert "AAPL" in content                   # ticker from fixture
    assert "Trail Stop" in content             # exit reason from fixture
    assert "Net P&L by symbol" in content


def test_dashboard_header_has_verdict_pill(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    assert 'class="verdict' in content   # the verdict pill class is rendered


def test_dashboard_performance_kpi_strip_present(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    assert "Net P&L" in content or "Net P&amp;L" in content
    assert "Profit factor" in content
    assert "Max drawdown" in content


def test_dashboard_shows_dsr_and_robustness_stub(simple_backtest, tmp_path):
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    # DSR live; robustness suite stub invites --robustness flag
    assert "Deflated Sharpe" in content or "insufficient return history" in content
    assert "--robustness" in content


def test_dashboard_handles_optuna(simple_backtest, tmp_path):
    trial = OptunaTrial(number=0, fitness=1.5, params={"foo": 1.0},
                        metrics={"pf": 1.5, "trades": 10})
    opt = OptunaResult(
        strategy="dash_test", n_trials=5,
        best_trial=trial, all_trials=[trial],
        param_importance={"foo": 0.7}, best_backtest=None,
    )
    path = build_dashboard(simple_backtest, optuna_result=opt, out_dir=tmp_path)
    content = path.read_text()
    assert "foo" in content
    assert "Top 20 trials" in content


def test_dashboard_handles_wf(simple_backtest, tmp_path):
    window = WalkForwardWindow(
        index=0,
        train_start="2023-01-01", train_end="2023-06-30",
        test_start="2023-07-01", test_end="2023-09-30",
        train_metrics=simple_backtest.metrics,
        test_metrics=simple_backtest.metrics,
        best_params={"foo": 1.0},
    )
    wf = WalkForwardResult(
        strategy="dash_test", n_windows=1, windows=[window],
        aggregate_oos=simple_backtest.metrics, wfe_ratio=0.85,
        oos_trades=simple_backtest.trades,
        oos_equity_curve=simple_backtest.equity_curve,
    )
    path = build_dashboard(simple_backtest, wf_result=wf, out_dir=tmp_path)
    content = path.read_text()
    assert "IS vs OOS Profit Factor" in content or "W0" in content


def test_dashboard_is_self_contained(simple_backtest, tmp_path):
    """HTML must work offline — contains Plotly CDN + inline JSON, no other external refs."""
    path = build_dashboard(simple_backtest, out_dir=tmp_path)
    content = path.read_text()
    # Only one external reference: Plotly CDN
    assert content.count("<script src=") == 1
    assert "cdn.plot.ly" in content
