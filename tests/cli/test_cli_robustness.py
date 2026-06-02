"""`tradelab robustness <strategy>` — exit-code/message contract + offline guarantee.

Exit codes:  0 = verdict produced (and matched --expect if given)
             2 = VERDICT MISMATCH (engine clean, label != --expect)        [Q-B]
             1 = ENGINE DID NOT PRODUCE A VERDICT (crash/0-trades/empty)    [Q-A]

Streams: Click >= 8.2 (this repo: 8.3.1) removed CliRunner(mix_stderr=...) and
keeps stdout/stderr SEPARATE by default; result.output aliases stdout. So
content/mutual-exclusion checks use _text(r) (stdout+stderr combined, stream-
agnostic); the dedicated routing test asserts r.stdout vs r.stderr.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import typer
from typer.testing import CliRunner

from tradelab.cli import app
from tradelab.results import BacktestMetrics, BacktestResult
from tradelab.robustness import RobustnessInputError
from tradelab.robustness.suite import RobustnessSuiteResult
from tradelab.robustness.verdict import VerdictResult

STRATEGY = "viprasol_v83"     # real registered strategy -> _check_strategy_exists passes
runner = CliRunner()


def _text(r):
    """Combined stdout+stderr — stream-agnostic content assertions."""
    return (r.stdout or "") + (r.stderr or "")


def _bt():
    m = BacktestMetrics(
        total_trades=242, wins=120, losses=122, win_rate=49.6,
        profit_factor=0.888, gross_profit=80.0, gross_loss=90.0,
        net_pnl=-10.0, pct_return=-1.0, annual_return=-2.0,
        final_equity=990.0, avg_win_pct=1.0, avg_loss_pct=-1.1,
        avg_bars_held=4.0, max_drawdown_pct=-8.0, sharpe_ratio=0.1,
    )
    return BacktestResult(strategy=STRATEGY, start_date="2020-01-01",
                          end_date="2024-12-31", params={}, metrics=m,
                          trades=[], equity_curve=[])


def _suite(verdict_label):
    return RobustnessSuiteResult(
        strategy=STRATEGY,
        verdict=VerdictResult(verdict=verdict_label, signals=[], diagnostics={}),
    )


def _patch_pipeline(verdict_label=None, suite_side_effect=None):
    """Patch offline-load + backtest + suite so no data/compute is needed.
    Returns three patch context managers to be entered together."""
    data = {"AAPL": pd.DataFrame({"Date": pd.date_range("2020-01-01", periods=3)})}
    p_load = patch("tradelab.cli._load_data_offline",
                   return_value=(MagicMock(name="strat"), data, MagicMock(name="spy")))
    p_bt = patch("tradelab.engines.run_backtest", return_value=_bt())
    if suite_side_effect is not None:
        p_suite = patch("tradelab.robustness.run_robustness_suite",
                        side_effect=suite_side_effect)
    else:
        p_suite = patch("tradelab.robustness.run_robustness_suite",
                        return_value=_suite(verdict_label))
    return p_load, p_bt, p_suite


# 1. --expect match -> exit 0
def test_expect_match_exits_zero():
    pl = _patch_pipeline("FRAGILE")
    with pl[0], pl[1], pl[2]:
        r = runner.invoke(app, ["robustness", STRATEGY, "--expect", "FRAGILE"])
    assert r.exit_code == 0, _text(r)
    assert "VERDICT MISMATCH" not in _text(r)


# 2. --expect mismatch -> exit 2, MISMATCH text, NOT engine text   [Q-B]
def test_expect_mismatch_exits_two_with_distinct_message():
    pl = _patch_pipeline("ROBUST")
    with pl[0], pl[1], pl[2]:
        r = runner.invoke(app, ["robustness", STRATEGY, "--expect", "FRAGILE"])
    assert r.exit_code == 2, _text(r)
    assert "VERDICT MISMATCH: expected FRAGILE, got ROBUST" in _text(r)
    assert "ENGINE DID NOT PRODUCE" not in _text(r)   # not mistaken for corruption


# 3. engine raises / no verdict -> exit 1, engine text, NOT mismatch text  [Q-A]
def test_engine_error_exits_one_with_distinct_message():
    pl = _patch_pipeline(suite_side_effect=RuntimeError("boom"))
    with pl[0], pl[1], pl[2]:
        r = runner.invoke(app, ["robustness", STRATEGY, "--expect", "FRAGILE"])
    assert r.exit_code == 1, _text(r)
    assert "ENGINE DID NOT PRODUCE A VERDICT" in _text(r)
    assert "VERDICT MISMATCH" not in _text(r)


# 4. 0 trades (RobustnessInputError) -> exit 1, loud
def test_zero_trades_exits_one_loud():
    err = RobustnessInputError("0 trades — nothing to test: strategy produced no trades")
    pl = _patch_pipeline(suite_side_effect=err)
    with pl[0], pl[1], pl[2]:
        r = runner.invoke(app, ["robustness", STRATEGY])
    assert r.exit_code == 1, _text(r)
    assert "ENGINE DID NOT PRODUCE A VERDICT" in _text(r)
    assert "0 trades" in _text(r)


# 5. empty cache -> exit 1, "populate cache first", and NETWORK NEVER TOUCHED
def test_empty_cache_exits_one_without_network(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(tmp_path)            # empty cwd -> .cache/ohlcv/1D/ absent
    # config is cwd-discovered (config.find_config_file walks up from cwd); an
    # empty tmp_path would die on FileNotFoundError before the cache check, so
    # point the loader's env override at the repo's real yaml (config.py reads
    # TRADELAB_CONFIG first). Empty cwd still isolates the cache variable.
    monkeypatch.setenv("TRADELAB_CONFIG",
                       str(Path(__file__).resolve().parents[2] / "tradelab.yaml"))
    boom = MagicMock(side_effect=AssertionError("NETWORK TOUCHED on empty-cache path"))
    with patch("tradelab.marketdata.downloader.download_symbols", boom), \
         patch("tradelab.marketdata.sources.twelvedata.download", boom), \
         patch("tradelab.marketdata.sources.yfinance.download", boom):
        r = runner.invoke(app, ["robustness", STRATEGY])
    assert r.exit_code == 1, _text(r)
    assert "populate cache first" in _text(r).lower()
    assert not boom.called


# 6. bare command (no --expect), verdict produced -> exit 0
def test_bare_command_produces_verdict_exits_zero():
    pl = _patch_pipeline("FRAGILE")
    with pl[0], pl[1], pl[2]:
        r = runner.invoke(app, ["robustness", STRATEGY])
    assert r.exit_code == 0, _text(r)
    assert "FRAGILE" in _text(r)


# 7 (identity). CLI references the EXACT engine VALID_VERDICTS object, not a copy
def test_cli_imports_engine_valid_verdicts_object():
    import tradelab.cli as cli_mod
    import tradelab.robustness.verdict as v
    assert cli_mod.VALID_VERDICTS is v.VALID_VERDICTS


# 8 (strengthened offline guarantee). _load_data_offline CANNOT reach network,
#    any cache state. is_available() is a LOCAL key check -> NOT in the boom set.
@pytest.mark.parametrize("populate", ["happy", "partial", "empty"])
def test_load_data_offline_never_touches_network(tmp_path, monkeypatch, populate):
    from tradelab import cli as cli_mod
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / ".cache" / "ohlcv" / "1D"
    cache_dir.mkdir(parents=True)

    def _bar(sym):
        pd.DataFrame({
            "Date": pd.date_range("2020-01-01", periods=60, freq="B"),
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }).to_parquet(cache_dir / f"{sym}.parquet", index=False)

    if populate in ("happy", "partial"):
        _bar("AAPL"); _bar("SPY")
    if populate == "partial":
        _bar("MSFT")

    boom = MagicMock(side_effect=AssertionError("NETWORK TOUCHED — offline guarantee broken"))
    with patch("tradelab.marketdata.downloader.download_symbols", boom), \
         patch("tradelab.marketdata.sources.twelvedata.download", boom), \
         patch("tradelab.marketdata.sources.yfinance.download", boom), \
         patch("tradelab.cli.instantiate_strategy", return_value=MagicMock(name="strat")), \
         patch("tradelab.cli.get_config",
               return_value=MagicMock(
                   benchmarks=MagicMock(primary="SPY"),
                   defaults=MagicMock(data_start="2020-01-01", data_end="2020-12-31"))), \
         patch("tradelab.marketdata.enrich_universe",
               side_effect=lambda raw, benchmark=None: raw):
        if populate == "empty":
            for p in cache_dir.glob("*.parquet"):
                p.unlink()
            with pytest.raises(typer.Exit) as ei:
                cli_mod._load_data_offline(STRATEGY)
            assert ei.value.exit_code == 1
        else:
            strat, data, spy = cli_mod._load_data_offline(STRATEGY)
            assert data            # built purely from parquet cache
        assert not boom.called     # MissingTwelveDataKey path never even reached


# 9 (stream separation). Errors on STDERR, verdict report on STDOUT.
def test_streams_errors_to_stderr_report_to_stdout():
    # exit 2 (mismatch) -> stderr, not stdout
    pl = _patch_pipeline("ROBUST")
    with pl[0], pl[1], pl[2]:
        r2 = runner.invoke(app, ["robustness", STRATEGY, "--expect", "FRAGILE"])
    assert r2.exit_code == 2
    assert "VERDICT MISMATCH" in r2.stderr
    assert "VERDICT MISMATCH" not in r2.stdout

    # exit 1 (engine error) -> stderr, not stdout
    pl = _patch_pipeline(suite_side_effect=RuntimeError("boom"))
    with pl[0], pl[1], pl[2]:
        r1 = runner.invoke(app, ["robustness", STRATEGY])
    assert r1.exit_code == 1
    assert "ENGINE DID NOT PRODUCE A VERDICT" in r1.stderr
    assert "ENGINE DID NOT PRODUCE A VERDICT" not in r1.stdout

    # exit 0 (verdict report) -> stdout
    pl = _patch_pipeline("FRAGILE")
    with pl[0], pl[1], pl[2]:
        r0 = runner.invoke(app, ["robustness", STRATEGY])
    assert r0.exit_code == 0
    assert "FRAGILE" in r0.stdout


# 10. loader applies the config window -> ALIGNED panel (regression guard for
#     the ragged-span bug: full parquet spans gave per-symbol end dates, which
#     can distort the verdict, not just the trade count).
def test_load_data_offline_slices_to_config_window(tmp_path, monkeypatch):
    from tradelab import cli as cli_mod
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / ".cache" / "ohlcv" / "1D"
    cache_dir.mkdir(parents=True)
    # Wide 2020..2026 span; the config window is a narrow slice inside it.
    for sym in ("AAPL", "SPY"):
        pd.DataFrame({
            "Date": pd.date_range("2020-01-01", "2026-12-31", freq="B"),
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
        }).to_parquet(cache_dir / f"{sym}.parquet", index=False)

    WIN_START, WIN_END = "2024-04-08", "2025-04-14"
    with patch("tradelab.cli.instantiate_strategy", return_value=MagicMock(name="strat")), \
         patch("tradelab.cli.get_config",
               return_value=MagicMock(
                   benchmarks=MagicMock(primary="SPY"),
                   defaults=MagicMock(data_start=WIN_START, data_end=WIN_END))), \
         patch("tradelab.marketdata.enrich_universe",
               side_effect=lambda raw, benchmark=None: raw):
        _strat, data, _spy = cli_mod._load_data_offline("viprasol_v83")

    # every symbol trimmed to the window — no bars outside [WIN_START, WIN_END]
    for sym, df in data.items():
        assert df["Date"].min() >= pd.Timestamp(WIN_START), sym
        assert df["Date"].max() <= pd.Timestamp(WIN_END), sym
    # ...and the panel is ALIGNED: identical span across every symbol
    spans = {(df["Date"].min(), df["Date"].max()) for df in data.values()}
    assert len(spans) == 1, f"panel not aligned across symbols: {spans}"
