"""Tests for tradelab.web.jobs — job manager."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tradelab.web import jobs


@pytest.fixture
def jm(tmp_path, monkeypatch):
    """Fresh JobManager with state under tmp_path/.cache."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    return jobs.JobManager(cache_root=cache)


def test_job_dataclass_has_expected_fields():
    j = jobs.Job(
        id="abc",
        strategy="momo",
        command="run --robustness",
        argv=["run", "momo", "--robustness"],
        status=jobs.JobStatus.QUEUED,
    )
    assert j.id == "abc"
    assert j.status == jobs.JobStatus.QUEUED
    assert j.pid is None
    assert j.exit_code is None
    assert j.started_at is None
    assert j.ended_at is None


def test_atomic_write_creates_then_replaces(tmp_path):
    target = tmp_path / "jobs.json"
    jobs._atomic_write_json(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text())["hello"] == "world"
    # second write replaces
    jobs._atomic_write_json(target, {"hello": "again"})
    assert json.loads(target.read_text())["hello"] == "again"
    # tmp file should not be left behind
    assert not (tmp_path / "jobs.json.tmp").exists()


def test_submit_first_job_promotes_to_running(jm):
    job_id, status = jm.submit("momo", "run --robustness", _fake_argv())
    assert status == jobs.JobStatus.RUNNING
    assert jm.get(job_id).status == jobs.JobStatus.RUNNING
    assert jm._running_id == job_id
    jm.cancel(job_id); jm.wait_for_terminal(job_id, timeout=5)


def test_submit_second_job_stays_queued(jm):
    a_id, _ = jm.submit("momo", "run --robustness", _fake_argv("long_running"))
    b_id, b_status = jm.submit("mean_rev", "run --robustness", _fake_argv())
    assert b_status == jobs.JobStatus.QUEUED
    assert jm._running_id == a_id
    assert b_id in jm._queue
    jm.cancel(a_id); jm.cancel(b_id)


def test_duplicate_strategy_command_returns_existing_409(jm):
    a_id, _ = jm.submit("momo", "run --robustness", _fake_argv("long_running"))
    with pytest.raises(jobs.DuplicateJobError) as exc:
        jm.submit("momo", "run --robustness", _fake_argv())
    assert exc.value.existing_job_id == a_id
    jm.cancel(a_id)


def test_restart_recovery_pid_alive_reattaches(tmp_path, monkeypatch):
    """If the dashboard restarts but the subprocess is still alive,
    JobManager should re-load the running job and treat it as still in flight."""
    cache = tmp_path / ".cache"
    cache.mkdir()

    # Manually craft jobs.json as if a prior dashboard left a running job
    # Use os.getpid() — guaranteed to be alive
    own_pid = os.getpid()
    state = {
        "schema_version": jobs.SCHEMA_VERSION,
        "jobs": [{
            "id": "abc",
            "strategy": "momo",
            "command": "run",
            "argv": ["echo"],
            "status": "running",
            "started_at": "2026-04-22T10:00:00Z",
            "ended_at": None,
            "pid": own_pid,
            "exit_code": None,
            "progress_log": str(cache / "jobs/abc/progress.jsonl"),
            "last_event_summary": None,
            "error_tail": None,
        }],
        "queue": [],
        "running_id": "abc",
    }
    (cache / "jobs.json").write_text(json.dumps(state))

    jm = jobs.JobManager(cache_root=cache)
    # Re-loaded job should be present and still RUNNING because PID is alive
    assert jm.get("abc").status == jobs.JobStatus.RUNNING
    assert jm._running_id == "abc"


def test_restart_recovery_pid_dead_marks_interrupted(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    # PID 999999 is overwhelmingly likely to not exist
    state = {
        "schema_version": jobs.SCHEMA_VERSION,
        "jobs": [{
            "id": "abc", "strategy": "momo", "command": "run",
            "argv": ["echo"], "status": "running",
            "started_at": "2026-04-22T10:00:00Z", "ended_at": None,
            "pid": 999999, "exit_code": None,
            "progress_log": None, "last_event_summary": None, "error_tail": None,
        }],
        "queue": [], "running_id": "abc",
    }
    (cache / "jobs.json").write_text(json.dumps(state))

    jm = jobs.JobManager(cache_root=cache)
    j = jm.get("abc")
    assert j.status == jobs.JobStatus.INTERRUPTED
    assert j.ended_at is not None
    assert jm._running_id is None


def test_corrupted_jobs_json_is_renamed_and_fresh_state_starts(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "jobs.json").write_text("{not valid json")

    jm = jobs.JobManager(cache_root=cache)
    assert jm.list_jobs() == []
    # backup file with .broken- prefix should exist
    backups = list(cache.glob("jobs.broken-*.json"))
    assert len(backups) == 1


def test_queue_promotes_next_on_exit(jm):
    a_id, _ = jm.submit("momo", "run", _fake_argv("happy_short"))
    b_id, b_status = jm.submit("mean_rev", "run", _fake_argv("happy_short"))
    assert b_status == jobs.JobStatus.QUEUED

    # wait for A to exit and B to be promoted + finish
    assert jm.wait_for_terminal(a_id, timeout=10)
    assert jm.wait_for_terminal(b_id, timeout=10)
    assert jm.get(a_id).status == jobs.JobStatus.DONE
    assert jm.get(b_id).status == jobs.JobStatus.DONE
    assert jm._running_id is None
    assert jm._queue == []


def test_bounded_retention_only_keeps_last_50_terminal(jm):
    # Spam 60 short jobs
    for i in range(60):
        jid, _ = jm.submit(f"strat_{i}", "run", _fake_argv())
        assert jm.wait_for_terminal(jid, timeout=10)

    # All 60 finished, but only the last 50 should remain
    assert len(jm.list_jobs()) == jobs.RETENTION_TERMINAL_JOBS  # 50


def _fake_argv(script: str = "happy_short") -> list[str]:
    """Build argv that points at the fake CLI."""
    return [
        sys.executable,
        str(Path(__file__).parent / "_fake_cli.py"),
        "--script", script,
    ]
