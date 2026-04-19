"""CLI run command tests — orchestration mocked, verifies wiring."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import typer

from tradelab.results import (
    BacktestMetrics, BacktestResult, Trade,
)


def _minimal_bt():
    m = BacktestMetrics(
        total_trades=5, wins=3, losses=2, win_rate=60.0,
        profit_factor=1.4, gross_profit=50.0, gross_loss=35.0,
        net_pnl=15.0, pct_return=1.5, annual_return=5.0,
        final_equity=1015.0, avg_win_pct=1.0, avg_loss_pct=-0.5,
        avg_bars_held=3.0, max_drawdown_pct=-3.0, sharpe_ratio=0.9,
    )
    return BacktestResult(
        strategy="s2_pocket_pivot",
        start_date="2024-01-01", end_date="2024-03-31",
        params={"foo": 1.0}, metrics=m,
        trades=[], equity_curve=[],
    )


def _mock_data():
    return {"AAPL": pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=50, freq="B"),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
    })}


def test_cli_run_orchestrates_download_backtest_report(monkeypatch, tmp_path):
    """The run command should call download, backtest, report, dashboard in order."""
    from tradelab import cli_run

    monkeypatch.chdir(tmp_path)

    with patch("tradelab.cli_run.download_symbols", return_value=_mock_data()) as dl_mock, \
         patch("tradelab.cli_run.run_backtest", return_value=_minimal_bt()) as bt_mock, \
         patch("tradelab.cli_run.instantiate_strategy", return_value=MagicMock(name="strat")) as strat_mock, \
         patch("tradelab.cli_run.generate_executive_report") as rep_mock, \
         patch("tradelab.cli_run.build_dashboard") as dash_mock, \
         patch("tradelab.cli_run.typer.launch") as launch_mock:
        rep_mock.return_value = tmp_path / "r.md"
        dash_mock.return_value = tmp_path / "d.html"

        cli_run.run(
            strategy="s2_pocket_pivot",
            symbols="AAPL",
            start="2024-01-01",
            end="2024-03-31",
            optimize=False,
            walkforward=False,
            n_trials=100,
            cost_sweep=False,
            robustness=False,
            full=False,
            mc_simulations=500,
            noise_seeds=50,
            noise_sigma_bp=5.0,
            loso_trials_per_fold=0,
            allow_yfinance_fallback=False,
            open_dashboard=False,
            universe="",
        )

    assert dl_mock.called
    assert strat_mock.called
    assert bt_mock.called
    assert rep_mock.called
    assert dash_mock.called
    assert not launch_mock.called   # --no-open-dashboard


def test_cli_run_exits_on_no_symbols(tmp_path, monkeypatch):
    from tradelab import cli_run
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        cli_run.run(
            strategy="foo", symbols="", start="2024-01-01", end="2024-12-31",
            optimize=False, walkforward=False, n_trials=100, open_dashboard=False,
            universe="", cost_sweep=False, robustness=False, full=False,
            mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False,
        )


def test_cli_run_resolves_symbol_file(tmp_path, monkeypatch):
    from tradelab import cli_run
    monkeypatch.chdir(tmp_path)
    syms_file = tmp_path / "syms.txt"
    syms_file.write_text("AAPL\nMSFT\n")

    # Make download return empty dict so we exit at the "no data retrieved" step
    # — enough to verify the symbol file was parsed correctly.
    with patch("tradelab.cli_run.download_symbols", return_value={}) as dl_mock, \
         pytest.raises(typer.Exit):
        cli_run.run(
            strategy="foo", symbols=f"@{syms_file}",
            start="2024-01-01", end="2024-12-31",
            optimize=False, walkforward=False, n_trials=100, open_dashboard=False,
            universe="", cost_sweep=False, robustness=False, full=False,
            mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False,
        )
    args, _ = dl_mock.call_args
    assert args[0] == ["AAPL", "MSFT"]


def test_cli_run_missing_symbol_file_exits(tmp_path, monkeypatch):
    from tradelab import cli_run
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        cli_run.run(
            strategy="foo", symbols="@nonexistent.txt",
            start="2024-01-01", end="2024-12-31",
            optimize=False, walkforward=False, n_trials=100, open_dashboard=False,
            universe="", cost_sweep=False, robustness=False, full=False,
            mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False,
        )


def test_cli_run_exits_on_unknown_strategy(tmp_path, monkeypatch):
    from tradelab import cli_run
    from tradelab.registry import StrategyNotRegistered
    monkeypatch.chdir(tmp_path)
    with patch("tradelab.cli_run.download_symbols", return_value=_mock_data()), \
         patch("tradelab.cli_run.instantiate_strategy",
               side_effect=StrategyNotRegistered("not found")), \
         pytest.raises(typer.Exit):
        cli_run.run(
            strategy="nonexistent", symbols="AAPL",
            start="2024-01-01", end="2024-12-31",
            optimize=False, walkforward=False, n_trials=100, open_dashboard=False,
            universe="", cost_sweep=False, robustness=False, full=False,
            mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False,
        )
