"""Tests for GET /tradelab/strategies/<name>/history."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_runs(db: Path, rows: list[tuple]) -> None:
    """rows: [(run_id, timestamp, strategy, verdict, dsr), ...]"""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                verdict TEXT,
                dsr_probability REAL
            );
        """)
        conn.executemany(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, verdict, dsr_probability) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_history_returns_strategy_runs_descending(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        ("r1", "2026-04-23T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "MODERATE", 0.3),
        ("r3", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.5),
        ("r4", "2026-04-25T00:00:00Z", "S4", "WEAK", 0.1),
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history?limit=10"
    )
    assert status == 200
    payload = json.loads(body)
    assert [r["run_id"] for r in payload["runs"]] == ["r3", "r2", "r1"]


def test_history_excludes_archived(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        ("r1", "2026-04-23T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history"
    )
    assert status == 200
    assert [r["run_id"] for r in json.loads(body)["runs"]] == ["r1"]


def test_history_limit_param_caps_results(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        (f"r{i}", f"2026-04-{20+i:02d}T00:00:00Z", "S2", "STRONG", 0.4)
        for i in range(8)
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history?limit=3"
    )
    assert status == 200
    assert len(json.loads(body)["runs"]) == 3


def test_history_unknown_strategy_returns_empty(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4)])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/UNKNOWN/history"
    )
    assert status == 200
    assert json.loads(body) == {"runs": []}
