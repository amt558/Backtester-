"""Named-universes CLI + cli_run --universe wiring tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import typer

from tradelab import cli_run, cli_universes
from tradelab.results import BacktestMetrics, BacktestResult


def _yaml(extras: str = "") -> str:
    return f"""
paths:
  data_dir: "./_d"
  reports_dir: "./_r"
  cache_dir: "./_c"
strategies:
  s2_pocket_pivot:
    module: "x"
    class_name: "X"
    status: "ported"
universes:
  small:
    [SPY, AAPL]
  big_tech:
    [SPY, AAPL, MSFT, GOOGL, AMZN, NVDA, META]
{extras}
"""


@pytest.fixture(autouse=True)
def _clean_config(tmp_path, monkeypatch):
    (tmp_path / "tradelab.yaml").write_text(_yaml())
    monkeypatch.chdir(tmp_path)
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    yield


def test_universes_list_shows_all(capsys):
    cli_universes.list_cmd()
    out = capsys.readouterr().out
    assert "small" in out
    assert "big_tech" in out


def test_universes_show_prints_each_symbol(capsys):
    cli_universes.show_cmd(name="small")
    out = capsys.readouterr().out
    assert "SPY" in out
    assert "AAPL" in out


def test_universes_show_unknown_exits():
    with pytest.raises(typer.Exit):
        cli_universes.show_cmd(name="nonexistent_universe_xyz")


def test_universes_show_unknown_with_close_match_hints(capsys):
    with pytest.raises(typer.Exit):
        cli_universes.show_cmd(name="bigtech")   # no underscore
    out = capsys.readouterr().out
    assert "Did you mean" in out
    assert "big_tech" in out


def _minimal_bt():
    m = BacktestMetrics(total_trades=1, profit_factor=1.0)
    return BacktestResult(strategy="s2_pocket_pivot",
                           start_date="2024-01-01", end_date="2024-03-31",
                           params={}, metrics=m, trades=[], equity_curve=[])


def test_cli_run_universe_resolves_symbol_list(tmp_path, monkeypatch):
    """--universe big_tech should populate symbol_list from the named entry."""
    monkeypatch.chdir(tmp_path)
    # Re-write yaml in this tmp dir
    (tmp_path / "tradelab.yaml").write_text(_yaml())
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)

    mock_data = {"AAPL": pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=10, freq="B"),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
    })}

    with patch("tradelab.cli_run.download_symbols", return_value=mock_data) as dl_mock, \
         patch("tradelab.cli_run.run_backtest", return_value=_minimal_bt()), \
         patch("tradelab.cli_run.instantiate_strategy", return_value=MagicMock()), \
         patch("tradelab.cli_run.generate_executive_report", return_value=tmp_path/"r.md"), \
         patch("tradelab.cli_run.build_dashboard", return_value=tmp_path/"d.html"), \
         patch("tradelab.cli_run.record_run", return_value="abc123"), \
         patch("tradelab.cli_run.assert_pit_valid"):
        cli_run.run(
            strategy="s2_pocket_pivot",
            symbols="",
            universe="big_tech",
            start="2024-01-01", end="2024-03-31",
            optimize=False, walkforward=False, n_trials=100,
            cost_sweep=False, robustness=False, full=False, mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False, open_dashboard=False,
        )
    args, _ = dl_mock.call_args
    # Symbol list should equal the big_tech universe
    assert args[0] == ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"]


def test_cli_run_universe_unknown_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tradelab.yaml").write_text(_yaml())
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    with pytest.raises(typer.Exit):
        cli_run.run(
            strategy="s2_pocket_pivot",
            symbols="",
            universe="not_a_real_universe",
            start="2024-01-01", end="2024-03-31",
            optimize=False, walkforward=False, n_trials=100,
            cost_sweep=False, robustness=False, full=False, mc_simulations=500,
            noise_seeds=50, noise_sigma_bp=5.0, loso_trials_per_fold=0,
            allow_yfinance_fallback=False, open_dashboard=False,
        )
