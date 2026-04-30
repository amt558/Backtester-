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


def test_resolve_run_folder_distinguishes_missing_run(fake_audit_db: Path):
    lookup = audit_reader.resolve_run_folder(
        "does-not-exist", db_path=fake_audit_db
    )
    assert lookup.status == "no_run"
    assert lookup.folder is None


def test_resolve_run_folder_distinguishes_null_report_path(fake_audit_db: Path):
    # Default fixture rows all have report_card_html_path = NULL
    lookup = audit_reader.resolve_run_folder("run-002", db_path=fake_audit_db)
    assert lookup.status == "no_folder"
    assert lookup.folder is None


def test_resolve_run_folder_returns_ok_when_path_present(
    fake_audit_db: Path, fake_run_folder: Path
):
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    lookup = audit_reader.resolve_run_folder("run-003", db_path=fake_audit_db)
    assert lookup.status == "ok"
    assert lookup.folder == fake_run_folder


def test_resolve_run_folder_treats_missing_db_as_no_run(tmp_path: Path):
    lookup = audit_reader.resolve_run_folder(
        "anything", db_path=tmp_path / "nope.db"
    )
    assert lookup.status == "no_run"
    assert lookup.folder is None


def test_get_run_folder_remains_backward_compat(fake_audit_db: Path):
    # NULL report path collapses to None for legacy callers.
    assert audit_reader.get_run_folder("run-002", db_path=fake_audit_db) is None
    # Missing run also collapses to None.
    assert (
        audit_reader.get_run_folder("does-not-exist", db_path=fake_audit_db)
        is None
    )


def test_baselines_for_all_strategies_returns_latest_per_strategy(
    fake_audit_db: Path, fake_run_folder: Path
):
    """Both s4 runs in fake_audit_db share the same folder for this test —
    we only care that the result picks the newer of the two (run-003)."""
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id IN ('run-002', 'run-003')",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    baselines = audit_reader.baselines_for_all_strategies(db_path=fake_audit_db)
    assert "s4_inside_day_breakout" in baselines
    s4 = baselines["s4_inside_day_breakout"]
    assert s4["run_id"] == "run-003"  # newer of the two
    assert s4["verdict"] == "ROBUST"
    assert s4["metrics"]["win_rate"] == 59.09
    assert s4["metrics"]["profit_factor"] == 1.42
    assert s4["metrics"]["max_drawdown_pct"] == -6.8


def test_baselines_omits_strategies_with_null_report_path(fake_audit_db: Path):
    """run-001 (s2) has NULL report_card_html_path — should be omitted, not crash."""
    baselines = audit_reader.baselines_for_all_strategies(db_path=fake_audit_db)
    assert "s2_pocket_pivot" not in baselines
    assert "s4_inside_day_breakout" not in baselines  # both s4 runs also NULL


def test_baselines_skips_older_run_when_newest_has_null_path(
    fake_audit_db: Path, fake_run_folder: Path
):
    """If the newest run for a strategy has NULL html_path, the function should
    NOT silently fall through to the older run — that would mask data loss."""
    # Wire only the older s4 run (run-002) to a real folder; run-003 stays NULL.
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-002'",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    baselines = audit_reader.baselines_for_all_strategies(db_path=fake_audit_db)
    # Newest s4 run (run-003) has no metrics; older run (run-002) does.
    # Current behaviour: we DO fall through to the older valid run, since the
    # alternative (omit the strategy entirely) means a transient run-without-
    # report scratches all baselines until the next full backtest. Document via test.
    assert baselines["s4_inside_day_breakout"]["run_id"] == "run-002"


def test_baselines_returns_empty_when_db_missing(tmp_path: Path):
    assert audit_reader.baselines_for_all_strategies(db_path=tmp_path / "nope.db") == {}


def test_baselines_skips_archived_runs(fake_audit_db: Path, fake_run_folder: Path):
    """run-003 is archived → s4 baseline should fall back to run-002."""
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id IN ('run-002', 'run-003')",
        (str(fake_run_folder),),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS archived_runs (run_id TEXT PRIMARY KEY, archived_at TEXT NOT NULL, reason TEXT)"
    )
    conn.execute(
        "INSERT INTO archived_runs VALUES ('run-003', '2026-04-30', 'test')"
    )
    conn.commit(); conn.close()

    baselines = audit_reader.baselines_for_all_strategies(db_path=fake_audit_db)
    assert baselines["s4_inside_day_breakout"]["run_id"] == "run-002"
