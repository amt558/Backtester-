"""Tests for atomic run deletion (DB row + on-disk folder + audit log)."""
import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.web.run_deletion import RunNotFound, delete_run_atomic


@pytest.fixture
def workspace(tmp_path: Path):
    """Build a workspace with one fake run on disk + in DB."""
    reports = tmp_path / "reports" / "virpo-mu-v1_2026-04-29-1432"
    reports.mkdir(parents=True)
    (reports / "robustness_result.json").write_text("{}")
    (reports / "quantstats_tearsheet.html").write_text("<html></html>")
    dashboard = reports / "dashboard.html"
    dashboard.write_text("<html></html>")

    db = tmp_path / "tradelab_history.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs ("
        "  run_id TEXT PRIMARY KEY, "
        "  strategy_name TEXT, "
        "  verdict TEXT, "
        "  timestamp_utc TEXT, "
        "  report_card_html_path TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?)",
        ("r1", "virpo-mu-v1", "ROBUST", "2026-04-29T14:32:00", str(dashboard)),
    )
    conn.commit()
    conn.close()

    deletions_log = tmp_path / "data" / "deletions.log"
    deletions_log.parent.mkdir(parents=True, exist_ok=True)

    return {"root": tmp_path, "db": db, "log": deletions_log, "reports": reports}


def test_atomic_delete_removes_db_row_and_folder(workspace):
    delete_run_atomic("r1", db_path=workspace["db"], log_path=workspace["log"])

    conn = sqlite3.connect(workspace["db"])
    rows = conn.execute("SELECT * FROM runs WHERE run_id = 'r1'").fetchall()
    conn.close()
    assert rows == []

    assert not workspace["reports"].exists()


def test_atomic_delete_appends_audit_log(workspace):
    delete_run_atomic("r1", db_path=workspace["db"], log_path=workspace["log"])

    line = workspace["log"].read_text().strip()
    entry = json.loads(line)
    assert entry["run_id"] == "r1"
    assert entry["strategy"] == "virpo-mu-v1"
    assert entry["deleted_by"] == "ui"
    assert "ts" in entry
    assert any("robustness_result.json" in p for p in entry["paths_removed"])


def test_atomic_delete_returns_manifest(workspace):
    manifest = delete_run_atomic(
        "r1", db_path=workspace["db"], log_path=workspace["log"]
    )
    assert manifest["run_id"] == "r1"
    assert manifest["strategy"] == "virpo-mu-v1"
    assert "paths_removed" in manifest


def test_unknown_run_raises_RunNotFound(workspace):
    with pytest.raises(RunNotFound):
        delete_run_atomic(
            "does-not-exist",
            db_path=workspace["db"],
            log_path=workspace["log"],
        )

    assert not workspace["log"].exists() or workspace["log"].read_text() == ""


def test_run_with_null_report_path_still_deletes_db_row(tmp_path: Path):
    """Run exists in DB but report_card_html_path is NULL (CLI run without --report).
    DB row is removed; no folder to remove; audit log still appended."""
    db = tmp_path / "tradelab_history.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs ("
        "  run_id TEXT PRIMARY KEY, strategy_name TEXT, "
        "  verdict TEXT, timestamp_utc TEXT, report_card_html_path TEXT)"
    )
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?)",
        ("r2", "no-report-strategy", "ROBUST", "2026-04-29T15:00:00", None),
    )
    conn.commit()
    conn.close()

    log = tmp_path / "data" / "deletions.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    manifest = delete_run_atomic("r2", db_path=db, log_path=log)
    assert manifest["paths_removed"] == []

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT * FROM runs WHERE run_id='r2'").fetchall() == []
    conn.close()


def test_default_log_path_used_when_unspecified(workspace, monkeypatch):
    """With no log_path, helper uses _default_log_path() which is overridable."""
    custom_log = workspace["root"] / "alt-log.jsonl"
    monkeypatch.setattr(
        "tradelab.web.run_deletion._default_log_path", lambda: custom_log
    )
    delete_run_atomic("r1", db_path=workspace["db"])
    assert custom_log.exists()


def test_atomic_delete_records_cascaded_card_ids(workspace):
    """Phase 1 (audit slice C): the cards the FE actually disabled are recorded
    on the run's deletions.log entry as cascaded_card_ids (record-only, 1B)."""
    delete_run_atomic(
        "r1",
        db_path=workspace["db"],
        log_path=workspace["log"],
        cascaded_card_ids=["card-aaa", "card-bbb"],
    )

    entry = json.loads(workspace["log"].read_text().strip())
    assert entry["cascaded_card_ids"] == ["card-aaa", "card-bbb"]


def test_atomic_delete_defaults_cascaded_card_ids_empty(workspace):
    """Back-compat (1A always-present): omitting cascaded_card_ids writes [],
    and the five existing fields stay byte-stable (no rename/reshape)."""
    delete_run_atomic("r1", db_path=workspace["db"], log_path=workspace["log"])

    entry = json.loads(workspace["log"].read_text().strip())
    # New field present and defaulted.
    assert entry["cascaded_card_ids"] == []
    # Existing five fields unchanged.
    assert entry["run_id"] == "r1"
    assert entry["strategy"] == "virpo-mu-v1"
    assert entry["deleted_by"] == "ui"
    assert "ts" in entry
    assert "paths_removed" in entry
    # Nothing else added or renamed.
    assert set(entry) == {
        "ts", "run_id", "strategy", "deleted_by", "paths_removed",
        "cascaded_card_ids",
    }
