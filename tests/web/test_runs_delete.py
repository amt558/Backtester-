"""Tests for DELETE /tradelab/runs/<run_id>.

As of Research v3 (2026-04-30) this route is HARD-DELETE: the runs row is
removed, the report folder (if present) is rmtree'd, and a JSONL line is
appended to data/deletions.log. The prior soft-archive flow (insert into
archived_runs, keep the runs row) was retired. The /unarchive route and
archive primitives are still present for legacy archived rows; nothing new
lands there.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tradelab.web import handlers


def _seed_run(db: Path, run_id: str, report_folder: str) -> None:
    """Insert a runs row pointing at report_folder."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                report_card_html_path TEXT
            );
        """)
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, report_card_html_path) "
            "VALUES (?, ?, ?, ?)",
            (run_id, "2026-04-25T00:00:00Z", "S2", report_folder),
        )
        conn.commit()
    finally:
        conn.close()


def test_delete_unknown_returns_204_idempotent(tmp_path: Path, monkeypatch) -> None:
    """A DELETE on an unknown run_id returns 204, not 404. The FE/bulk-delete
    flow may legitimately ask to delete already-deleted rows from a stale
    view; treating that as success keeps the contract simple."""
    db = tmp_path / "history.db"
    _seed_run(db, "run-known", str(tmp_path / "reports" / "known"))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    # Avoid polluting the cwd-relative deletions.log default location.
    monkeypatch.chdir(tmp_path)

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-unknown")
    assert status == 204
    assert body == ""


def test_delete_success_removes_row_folder_and_appends_audit(
    tmp_path: Path, monkeypatch,
) -> None:
    """Hard-delete: DB row gone, folder rmtree'd, deletions.log gains a line."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    (folder / "dashboard.html").write_text("<html></html>")
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.chdir(tmp_path)  # default deletions.log is cwd-relative

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status == 204

    # DB row gone
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?", ("run-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row is None

    # Folder gone
    assert not folder.exists()

    # JSONL audit appended
    log_path = tmp_path / "data" / "deletions.log"
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["run_id"] == "run-1"
    assert entry["strategy"] == "S2"


def test_delete_idempotent_on_second_call(tmp_path: Path, monkeypatch) -> None:
    """Two DELETEs on the same run id both return 204. The first hard-deletes
    the row + folder + audit entry; the second (now finding nothing) is a
    no-op success because RunNotFound is caught and returned as 204."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    reports_root = tmp_path / "reports"
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.chdir(tmp_path)

    body1, status1 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    body2, status2 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status1 == 204
    assert status2 == 204  # idempotent

    # Parent reports/ dir survives — second delete must NOT walk up and rmtree it.
    assert reports_root.exists()

    # Audit log got exactly one entry (the first delete; second was a no-op).
    log_path = tmp_path / "data" / "deletions.log"
    assert log_path.exists()
    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
