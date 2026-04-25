"""Unit tests for archived_runs sidecar.

The audit DB runs table is append-only (per audit/history.py docstring).
This sidecar is the user-archive layer that consumers filter against at
query time. It does NOT modify the runs table.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive


def test_archive_run_creates_table_and_inserts_row(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT run_id, reason FROM archived_runs").fetchall()
    finally:
        conn.close()

    assert rows == [("run-abc", None)]


def test_archive_run_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)
    archive.archive_run("run-abc", db_path=db)  # second call is a no-op

    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute("SELECT COUNT(*) FROM archived_runs").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_archive_run_records_reason(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", reason="user_delete", db_path=db)
    assert archive.is_archived("run-abc", db_path=db)


def test_is_archived_false_when_db_missing(tmp_path: Path) -> None:
    db = tmp_path / "missing.db"
    assert archive.is_archived("anything", db_path=db) is False


def test_is_archived_false_for_unknown_run_id(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)
    assert archive.is_archived("run-xyz", db_path=db) is False


def test_list_archived_run_ids_returns_set(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-1", db_path=db)
    archive.archive_run("run-2", db_path=db)
    archive.archive_run("run-3", db_path=db)

    ids = archive.list_archived_run_ids(db_path=db)
    assert ids == {"run-1", "run-2", "run-3"}


def test_list_archived_run_ids_empty_when_db_missing(tmp_path: Path) -> None:
    db = tmp_path / "missing.db"
    assert archive.list_archived_run_ids(db_path=db) == set()
