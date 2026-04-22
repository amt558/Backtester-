"""Tests for audit DB reader."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.web import audit_reader


def test_list_runs_returns_all_rows(fake_audit_db: Path):
    rows = audit_reader.list_runs(db_path=fake_audit_db)
    assert len(rows) == 3
    # Newest first
    assert rows[0]["run_id"] == "run-003"
    assert rows[-1]["run_id"] == "run-001"


def test_list_runs_filters_by_strategy(fake_audit_db: Path):
    rows = audit_reader.list_runs(strategy="s4_inside_day_breakout", db_path=fake_audit_db)
    assert len(rows) == 2
    assert all(r["strategy_name"] == "s4_inside_day_breakout" for r in rows)


def test_list_runs_filters_by_verdict(fake_audit_db: Path):
    rows = audit_reader.list_runs(verdicts=["FRAGILE"], db_path=fake_audit_db)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "FRAGILE"


def test_list_runs_limit_and_offset(fake_audit_db: Path):
    rows = audit_reader.list_runs(limit=2, db_path=fake_audit_db)
    assert len(rows) == 2
    rows_page2 = audit_reader.list_runs(limit=2, offset=2, db_path=fake_audit_db)
    assert len(rows_page2) == 1


def test_list_runs_returns_empty_when_db_missing(tmp_path: Path):
    missing = tmp_path / "nope.db"
    rows = audit_reader.list_runs(db_path=missing)
    assert rows == []


def test_get_run_metrics_joins_backtest_json(fake_audit_db: Path, fake_run_folder: Path):
    # Point the audit row to the fake run folder
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit()
    conn.close()

    metrics = audit_reader.get_run_metrics(
        "run-003", db_path=fake_audit_db
    )
    assert metrics["profit_factor"] == 1.42
    assert metrics["total_trades"] == 44
    assert metrics["max_drawdown_pct"] == -6.8


def test_get_run_metrics_returns_empty_when_run_missing(fake_audit_db: Path):
    metrics = audit_reader.get_run_metrics(
        "does-not-exist", db_path=fake_audit_db
    )
    assert metrics == {}
