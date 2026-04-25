"""Tests for POST /tradelab/runs/<run_id>/unarchive."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_run(db: Path, run_id: str) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name) "
            "VALUES (?, ?, ?)",
            (run_id, "2026-04-25T00:00:00Z", "S2"),
        )
        conn.commit()
    finally:
        conn.close()


def test_unarchive_resurrects_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_run(db, "run-1")
    archive.archive_run("run-1", db_path=db)
    assert archive.is_archived("run-1", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/run-1/unarchive", b""
    )
    assert status == 204
    assert body == ""
    assert not archive.is_archived("run-1", db_path=db)


def test_unarchive_idempotent_when_not_archived(tmp_path: Path, monkeypatch) -> None:
    """Calling unarchive on a run that was never archived is a no-op success."""
    db = tmp_path / "history.db"
    _seed_run(db, "run-1")
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/run-1/unarchive", b""
    )
    assert status == 204
    assert not archive.is_archived("run-1", db_path=db)


def test_unarchive_runs_table_unchanged(tmp_path: Path, monkeypatch) -> None:
    """Audit DB runs row stays untouched — unarchive only deletes the sidecar entry."""
    db = tmp_path / "history.db"
    _seed_run(db, "run-1")
    archive.archive_run("run-1", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    handlers.handle_post_with_status("/tradelab/runs/run-1/unarchive", b"")

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT run_id, strategy_name FROM runs WHERE run_id = ?", ("run-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row == ("run-1", "S2")


def test_unarchive_double_call_idempotent(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_run(db, "run-1")
    archive.archive_run("run-1", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    _, s1 = handlers.handle_post_with_status("/tradelab/runs/run-1/unarchive", b"")
    _, s2 = handlers.handle_post_with_status("/tradelab/runs/run-1/unarchive", b"")
    assert s1 == 204
    assert s2 == 204
