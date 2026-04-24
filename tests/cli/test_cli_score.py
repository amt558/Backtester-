"""End-to-end CliRunner test for `tradelab score-from-trades`."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tradelab.cli import app


FIXTURE = Path(__file__).parent.parent / "io" / "fixtures" / "tv_export_amzn_smoke.csv"


def test_score_from_trades_produces_report_folder(tmp_path, monkeypatch):
    # Run the CLI from a clean cwd so reports/ lands under tmp_path.
    monkeypatch.chdir(tmp_path)
    csv_dst = tmp_path / "amzn.csv"
    shutil.copy(FIXTURE, csv_dst)

    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", str(csv_dst),
        "--symbol", "AMZN",
        "--name", "viprasol-amzn-v1",
        "--no-open",
        "--no-audit",
    ])
    assert result.exit_code == 0, result.output

    reports_dir = tmp_path / "reports"
    folders = [p for p in reports_dir.iterdir() if p.is_dir()
               and p.name.startswith("viprasol-amzn-v1_")]
    assert len(folders) == 1
    folder = folders[0]
    assert (folder / "executive_report.md").exists()
    assert (folder / "backtest_result.json").exists()
    assert (folder / "tv_trades.csv").exists()


def test_score_from_trades_missing_csv_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", "no-such-file.csv",
        "--symbol", "AMZN", "--name", "x",
        "--no-open", "--no-audit",
    ])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "no such" in result.output.lower()


def test_score_from_trades_bad_csv_reports_parse_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", str(bad),
        "--symbol", "AMZN", "--name", "x",
        "--no-open", "--no-audit",
    ])
    assert result.exit_code != 0
    assert "missing column" in result.output.lower()
