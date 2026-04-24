"""Unit tests for approve_strategy.score_csv and accept_scored."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.io.tv_csv import TVCSVParseError
from tradelab.web import approve_strategy


@pytest.fixture
def smoke_csv_text() -> str:
    return Path("tests/io/fixtures/tv_export_amzn_smoke.csv").read_text(encoding="utf-8-sig")


def test_score_csv_happy(tmp_path: Path, smoke_csv_text: str):
    """Happy-path: valid CSV scores, writes report folder + audit row."""
    db_path = tmp_path / "audit.db"
    result = approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source="// pine stub",
        symbol="AMZN",
        base_name="smoke-amzn",
        timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=db_path,
    )
    # Contract: returns a dict with the keys the frontend needs.
    for key in (
        "verdict", "metrics", "report_folder", "scoring_run_id",
        "dsr_probability", "n_trades", "start_date", "end_date",
    ):
        assert key in result, f"missing key {key!r} in score_csv result"

    assert result["verdict"] in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert isinstance(result["scoring_run_id"], str) and result["scoring_run_id"]
    assert Path(result["report_folder"]).exists()
    assert (Path(result["report_folder"]) / "strategy.pine").read_text() == "// pine stub"
    assert (Path(result["report_folder"]) / "tv_trades.csv").read_text(encoding="utf-8") == smoke_csv_text
    assert result["n_trades"] > 0


def test_score_csv_bad_csv_raises_tv_parse_error(tmp_path: Path):
    with pytest.raises(TVCSVParseError):
        approve_strategy.score_csv(
            csv_text="not a csv at all",
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )


def test_score_csv_zero_closed_trades_raises(tmp_path: Path):
    """CSV with only entry rows (no exits) -> zero closed trades."""
    # One entry-only trade (no matching exit row)
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-01-08 09:30,150.00,10,,,,,,,,\n"
    )
    with pytest.raises(ValueError, match="no closed trades"):
        approve_strategy.score_csv(
            csv_text=csv,
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )
