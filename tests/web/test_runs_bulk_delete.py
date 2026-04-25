"""Tests for POST /tradelab/runs/bulk-delete."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_run(db: Path, run_id: str, report_folder: str) -> None:
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


def test_bulk_delete_all_success(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    folders = []
    for i in range(3):
        f = tmp_path / "reports" / f"r{i}"
        f.mkdir(parents=True)
        folders.append(f)
        _seed_run(db, f"run-{i}", str(f))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": ["run-0", "run-1", "run-2"]}).encode(),
    )
    assert status == 200
    payload = json.loads(body)
    assert sorted(payload["deleted"]) == ["run-0", "run-1", "run-2"]
    assert payload["failed"] == []
    for f in folders:
        assert not f.exists()


def test_bulk_delete_unknown_id_lands_in_failed(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    f = tmp_path / "reports" / "r0"
    f.mkdir(parents=True)
    _seed_run(db, "run-0", str(f))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": ["run-0", "run-missing"]}).encode(),
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["deleted"] == ["run-0"]
    assert payload["failed"] == [{"id": "run-missing", "reason": "run not found"}]


def test_bulk_delete_empty_request(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": []}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"deleted": [], "failed": []}


def test_bulk_delete_missing_run_ids_field_returns_400(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({}).encode(),
    )
    assert status == 400
