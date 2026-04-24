"""csv_scoring orchestrator tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.audit import list_runs
from tradelab.csv_scoring import build_backtest_result_from_trades, score_trades
from tradelab.io.tv_csv import parse_tv_trades_csv


FIXTURE = Path(__file__).parent / "io" / "fixtures" / "tv_export_amzn_smoke.csv"


@pytest.fixture
def parsed_amzn():
    return parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")


def test_build_backtest_result_populates_window_and_strategy_name(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn,
        strategy_name="viprasol-amzn-v1",
        symbol="AMZN",
        timeframe="1H",
        starting_equity=100_000.0,
    )
    assert bt.strategy == "viprasol-amzn-v1"
    assert bt.symbol == "AMZN"
    assert bt.timeframe == "1H"
    assert bt.start_date == "2024-01-08"
    assert bt.end_date == "2024-03-22"
    assert len(bt.trades) == 6
    assert bt.metrics.total_trades == 6


def test_build_backtest_result_emits_equity_curve_per_trade(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    # One equity point per closed trade, dated by exit_date, equity is cumulative.
    assert len(bt.equity_curve) == 6
    assert bt.equity_curve[0] == {"date": "2024-01-12", "equity": 100_060.0}
    assert bt.equity_curve[-1]["equity"] == round(100_000.0 + 240.0, 2)


def test_build_backtest_result_fills_annual_return_from_window(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    # 73-day window, +0.24% net (240 / 100k) → annualized ≈ 1.2%.
    # Tight bounds catch annualization-formula regressions.
    assert 0.8 < bt.metrics.annual_return < 1.8


def test_build_backtest_result_includes_monthly_pnl(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    months = {row["month"] for row in bt.monthly_pnl}
    assert months == {"2024-01", "2024-02", "2024-03"}


def test_score_trades_returns_verdict_and_dsr(parsed_amzn):
    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    assert out.verdict.verdict in {"ROBUST", "INCONCLUSIVE", "FRAGILE"}
    # 6 trades is too few for a meaningful DSR — should be NaN-handled, not crash.
    assert out.dsr_probability is None or 0.0 <= out.dsr_probability <= 1.0
    assert out.backtest_result.metrics.total_trades == 6
    assert out.monte_carlo is not None
    assert out.monte_carlo.n_trades == 6


def test_write_report_folder_creates_executive_dashboard_and_json(parsed_amzn, tmp_path):
    from tradelab.csv_scoring import score_trades, write_report_folder

    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    folder = write_report_folder(
        out,
        base_name="viprasol-amzn-v1",
        out_root=tmp_path,
        pine_source="// dummy pine\nstrategy('x')",
        csv_text="dummy,csv\n",
        record_audit=False,
    )

    assert folder.exists() and folder.is_dir()
    assert folder.name.startswith("viprasol-amzn-v1_")
    assert (folder / "executive_report.md").exists()
    assert (folder / "dashboard.html").exists()
    assert (folder / "backtest_result.json").exists()
    assert (folder / "tv_trades.csv").exists()
    assert (folder / "strategy.pine").exists()

    # Round-trip the JSON to confirm BacktestResult survives pydantic dump+load.
    data = json.loads((folder / "backtest_result.json").read_text(encoding="utf-8"))
    assert data["strategy"] == "viprasol-amzn-v1"
    assert data["symbol"] == "AMZN"
    assert len(data["trades"]) == 6


def test_write_report_folder_records_audit_row_when_enabled(parsed_amzn, tmp_path):
    from tradelab.csv_scoring import score_trades, write_report_folder

    db_path = tmp_path / "history.db"
    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    write_report_folder(
        out,
        base_name="viprasol-amzn-v1",
        out_root=tmp_path,
        pine_source=None,
        csv_text="x\n",
        record_audit=True,
        db_path=db_path,
    )

    rows = list_runs(strategy="viprasol-amzn-v1", db_path=db_path)
    assert len(rows) == 1
    assert rows[0].verdict in {"ROBUST", "INCONCLUSIVE", "FRAGILE"}
    assert rows[0].report_card_html_path is not None
