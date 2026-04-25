"""Tests for DELETE /tradelab/runs/<run_id>.

Verifies soft-archive semantics: the runs table is never modified;
archived_runs receives the row; the report folder is removed.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
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


def test_delete_unknown_returns_404(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_run(db, "run-known", str(tmp_path / "reports" / "known"))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-unknown")
    assert status == 404
    assert "not found" in body.lower()


def test_delete_success_archives_and_removes_folder(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    (folder / "dashboard.html").write_text("<html></html>")
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status == 204
    assert not folder.exists()
    assert archive.is_archived("run-1", db_path=db)


def test_delete_runs_table_row_preserved(tmp_path: Path, monkeypatch) -> None:
    """Audit DB runs row must NOT be modified — only archived_runs gets the entry."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    handlers.handle_delete_with_status("/tradelab/runs/run-1")

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT run_id, strategy_name FROM runs WHERE run_id = ?", ("run-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row == ("run-1", "S2")  # row still there, untouched


def test_delete_idempotent_on_second_call(tmp_path: Path, monkeypatch) -> None:
    """Second delete returns 204 (folder already gone, archive row already there)."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body1, status1 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    body2, status2 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status1 == 204
    assert status2 == 204  # idempotent
