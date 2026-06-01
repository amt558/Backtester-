"""Task D: the New Strategy robustness run is tracked + queryable, not a
fire-and-forget DEVNULL Popen into a black hole.
"""
from __future__ import annotations

import json
from pathlib import Path

from tradelab.web import handlers
from tradelab.web.jobs import Job, JobStatus


class _FakeJM:
    def __init__(self, jobs):
        self._jobs = jobs

    def list_jobs(self):
        return self._jobs


class _RecorderJM:
    def __init__(self):
        self.calls = []

    def submit(self, strategy, command, argv, log_path=None):
        self.calls.append((strategy, command, argv, log_path))
        return ("jid-123", JobStatus.RUNNING)


def test_new_strategy_job_endpoint_reports_failed_with_log_tail(tmp_path: Path, monkeypatch):
    log = tmp_path / "demo.log"
    log.write_text("OUT line\nTraceback: boom happened\n", encoding="utf-8")
    job = Job(
        id="j1",
        strategy="demo",
        command="run --robustness",
        argv=[],
        status=JobStatus.FAILED,
        started_at="2026-06-01T00:00:00Z",
        ended_at="2026-06-01T00:01:00Z",
        exit_code=1,
        error_tail="Traceback: boom happened",
        log_path=str(log),
    )
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _FakeJM([job]))

    body, status = handlers.handle_get_with_status("/tradelab/new-strategy/job/demo")
    assert status == 200, body
    data = json.loads(body)["data"]
    assert data["state"] == "failed"
    assert data["job_id"] == "j1"
    assert "boom happened" in data["log_tail"]
    assert data["error"]


def test_new_strategy_job_endpoint_404_when_no_job(monkeypatch):
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _FakeJM([]))
    body, status = handlers.handle_get_with_status("/tradelab/new-strategy/job/nope")
    assert status == 404
    # Distinct message (not the generic dispatcher 404) proves the route exists.
    assert "no robustness job" in (json.loads(body).get("error") or "").lower()


def test_register_routes_robustness_through_job_manager(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        handlers.new_strategy,
        "register_strategy",
        lambda **kw: {"error": None, "final_path": str(tmp_path / "demo_test.py")},
    )
    rec = _RecorderJM()
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: rec)

    # Fire-and-forget raw Popen must be gone — fail loudly if it's used.
    def _boom(*a, **k):
        raise AssertionError("raw subprocess.Popen used instead of the job manager")

    monkeypatch.setattr(handlers.subprocess, "Popen", _boom)

    body = handlers.handle_post(
        "/tradelab/new-strategy",
        json.dumps({"action": "register", "name": "demo_test", "class_name": "DemoTest"}).encode(),
    )
    data = json.loads(body)["data"]
    assert data["robustness_started"] is True
    assert data["job_id"] == "jid-123"

    assert len(rec.calls) == 1
    strat, cmd, _argv, log_path = rec.calls[0]
    assert strat == "demo_test"
    assert cmd == "run --robustness"
    assert log_path and log_path.replace("\\", "/").endswith("demo_test.log")
