"""Tests for the merged GET /tradelab/runs endpoint."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_audit_runs(db: Path, rows: list[tuple]) -> None:
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


def _fake_job_manager(jobs_payload: list[dict]):
    jm = MagicMock()
    jm.list_jobs.return_value = [_FakeJob(j) for j in jobs_payload]
    return jm


class _FakeJob:
    def __init__(self, d: dict):
        self._d = d

    def to_dict(self) -> dict:
        return self._d


def test_runs_excludes_archived_by_default(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    ids = [r.get("run_id") or r.get("id") for r in payload["runs"]]
    assert "r1" in ids
    assert "r2" not in ids


def test_runs_include_archived_with_query_param(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([]))

    body, status = handlers.handle_get_with_status(
        "/tradelab/runs?include_archived=true"
    )
    assert status == 200
    payload = json.loads(body)
    ids = [r.get("run_id") or r.get("id") for r in payload["runs"]]
    assert "r1" in ids
    assert "r2" in ids


def test_runs_merges_inflight_jobs_at_top(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-A", "strategy": "S4", "status": "running", "command": "robustness"},
        {"id": "job-B", "strategy": "S7", "status": "queued", "command": "run"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    sources = [r["source"] for r in payload["runs"]]
    # In-flight rows come first
    assert sources[:2] == ["job", "job"]
    assert sources[2] == "audit"


def test_runs_inflight_running_before_queued(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-Q", "strategy": "S4", "status": "queued", "command": "run"},
        {"id": "job-R", "strategy": "S7", "status": "running", "command": "robustness"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    statuses = [r["status"] for r in payload["runs"][:2]]
    assert statuses == ["running", "queued"]


def test_runs_inflight_excludes_terminal_jobs(tmp_path: Path, monkeypatch) -> None:
    """Done/failed/cancelled jobs come from the audit DB, not the job list.

    The JobManager retains terminal jobs for ~50 entries (RETENTION_TERMINAL_JOBS),
    but the merged /tradelab/runs view should NOT double-render them — the
    audit DB row is the durable record. Terminal jobs are skipped here.
    """
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-D", "strategy": "S2", "status": "done", "command": "run"},
        {"id": "job-F", "strategy": "S4", "status": "failed", "command": "run"},
        {"id": "job-R", "strategy": "S7", "status": "running", "command": "run"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    payload = json.loads(body)
    job_rows = [r for r in payload["runs"] if r["source"] == "job"]
    assert len(job_rows) == 1
    assert job_rows[0]["status"] == "running"
