"""Tests for the /tradelab/jobs HTTP handlers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tradelab.web import handlers, get_job_manager


@pytest.fixture(autouse=True)
def fresh_job_manager(tmp_path, monkeypatch):
    """Replace the module singleton with a tmp-rooted JobManager per test."""
    from tradelab.web import jobs
    cache = tmp_path / ".cache"
    cache.mkdir()
    jm = jobs.JobManager(cache_root=cache)

    # Patch the singleton reference
    import tradelab.web as web_pkg
    monkeypatch.setattr(web_pkg, "_job_manager", jm)
    # Also wire to the broadcaster
    bc = web_pkg.get_broadcaster()
    jm._on_state_change = lambda jid, ev: bc.broadcast({"job_id": jid, "event": ev})
    yield jm


def _fake_argv():
    return [sys.executable, str(Path(__file__).parent / "_fake_cli.py"), "--script", "happy_short"]


def test_post_jobs_creates_job_returns_201(fresh_job_manager, monkeypatch):
    # Patch the argv builder used by handlers
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda strategy, command: _fake_argv())

    body = json.dumps({"strategy": "momo", "command": "run --robustness"}).encode()
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 201
    payload = json.loads(body_str)
    assert payload["error"] is None
    assert "job_id" in payload["data"]
    assert payload["data"]["status"] in ("running", "queued")
    fresh_job_manager.wait_for_terminal(payload["data"]["job_id"], timeout=10)


def test_post_jobs_invalid_command_returns_400(fresh_job_manager):
    body = json.dumps({"strategy": "momo", "command": "rm -rf /"}).encode()
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 400
    payload = json.loads(body_str)
    assert "invalid command" in payload["error"].lower()


def test_post_jobs_missing_fields_returns_400(fresh_job_manager):
    body = json.dumps({"strategy": "momo"}).encode()  # missing command
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 400


def test_post_jobs_duplicate_returns_409(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    body = json.dumps({"strategy": "momo", "command": "run --robustness"}).encode()
    _, status1 = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status1 == 201

    body_str2, status2 = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status2 == 409
    payload = json.loads(body_str2)
    assert "existing_job_id" in payload["data"]

    # Cleanup
    fresh_job_manager.cancel(payload["data"]["existing_job_id"])


def test_get_jobs_returns_active_and_recent(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda s, c: _fake_argv())
    # Submit one job, let it finish
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    fresh_job_manager.wait_for_terminal(job_id, timeout=10)

    body_str, status = handlers.handle_get_with_status("/tradelab/jobs")
    assert status == 200
    payload = json.loads(body_str)
    jobs_list = payload["data"]["jobs"]
    assert any(j["id"] == job_id for j in jobs_list)


def test_post_cancel_running_job_returns_200(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    import time; time.sleep(0.3)

    body_str, status = handlers.handle_post_with_status(f"/tradelab/jobs/{job_id}/cancel", b"")
    assert status == 200
    fresh_job_manager.wait_for_terminal(job_id, timeout=5)
    assert fresh_job_manager.get(job_id).status.value == "cancelled"


def test_post_cancel_done_job_returns_410(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda s, c: _fake_argv())
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    fresh_job_manager.wait_for_terminal(job_id, timeout=10)

    body_str, status = handlers.handle_post_with_status(f"/tradelab/jobs/{job_id}/cancel", b"")
    assert status == 410


def test_post_cancel_unknown_job_returns_404(fresh_job_manager):
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs/does-not-exist/cancel", b"")
    assert status == 404


def test_handle_sse_writes_retry_hint_and_initial_state(fresh_job_manager, monkeypatch):
    """Sanity: subscribing to SSE writes the retry hint and replays state."""
    import io, threading
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    # Submit one job so initial_state is non-empty
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    handlers.handle_post_with_status("/tradelab/jobs", body)
    import time; time.sleep(0.2)

    # Use a buffered wfile substitute. handle_sse blocks, so run in a thread
    # and "disconnect" by removing the subscription.
    class W:
        def __init__(self): self.buf = io.BytesIO(); self.writes = 0
        def write(self, b): self.writes += 1; return self.buf.write(b)
        def flush(self): pass

    wf = W()
    t = threading.Thread(target=handlers.handle_sse, args=(wf,), daemon=True)
    t.start()
    time.sleep(0.3)  # let subscribe + initial-state writes happen

    out = wf.buf.getvalue().decode()
    assert "retry: 3000" in out
    assert "data: " in out  # at least the one running job

    # Force unsubscribe by clearing all clients
    from tradelab.web import get_broadcaster
    get_broadcaster()._clients.clear()
    t.join(timeout=2)

    # Cleanup the long_running job
    for j in fresh_job_manager.list_jobs():
        if j.status.value == "running":
            fresh_job_manager.cancel(j.id)
            fresh_job_manager.wait_for_terminal(j.id, timeout=5)


def test_post_jobs_returns_503_if_progress_log_unsupported(fresh_job_manager, monkeypatch):
    import tradelab.web as web_pkg
    monkeypatch.setattr(web_pkg, "supports_progress_log", lambda: False)
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    _, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 503


def test_failed_job_to_dict_includes_failure_hint():
    from tradelab.web.jobs import Job, JobStatus
    job = Job(
        id="test-abc123",
        strategy="momo",
        command="run --full",
        argv=["run", "momo", "--full"],
        status=JobStatus.FAILED,
        exit_code=1,
    )
    d = job.to_dict()
    assert "failure_hint" in d
    # failure_hint should be the exit-code fallback string (no progress log present)
    assert d["failure_hint"] is not None
    assert "Python exception" in d["failure_hint"]


def test_running_job_to_dict_omits_failure_hint():
    from tradelab.web.jobs import Job, JobStatus
    job = Job(
        id="test-def456",
        strategy="momo",
        command="run --full",
        argv=["run", "momo", "--full"],
        status=JobStatus.RUNNING,
    )
    d = job.to_dict()
    assert "failure_hint" not in d
