"""Task D: a job submitted with log_path must capture BOTH stdout and stderr
to that file (never DEVNULL), and a failing run must end FAILED with a
non-empty error_tail — no silent disappearance.
"""
from __future__ import annotations

import sys
from pathlib import Path

from tradelab.web.jobs import JobManager, JobStatus


def test_job_log_path_captures_stdout_and_stderr_on_failure(tmp_path: Path):
    jm = JobManager(tmp_path / ".cache" / "jobs_root")
    log_path = tmp_path / "new_strategy_jobs" / "teststrat.log"

    # Emit to both streams, then exit non-zero so the job lands FAILED.
    code = (
        "import sys;"
        "print('OUT-MARKER-STDOUT');"
        "print('ERR-MARKER-STDERR', file=sys.stderr);"
        "sys.exit(7)"
    )
    argv = [sys.executable, "-c", code]

    job_id, _status = jm.submit(
        "teststrat", "run --robustness", argv, log_path=str(log_path)
    )
    assert jm.wait_for_terminal(job_id, timeout=30), "job never reached terminal state"

    job = jm.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.exit_code == 7

    # Log file exists and holds BOTH streams (proves we did not DEVNULL stdout).
    assert log_path.exists(), "per-run log file was not written"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "OUT-MARKER-STDOUT" in text, "stdout was not captured to the log file"
    assert "ERR-MARKER-STDERR" in text, "stderr was not captured to the log file"

    # The failure is surfaced, not swallowed.
    assert job.error_tail and "ERR-MARKER-STDERR" in job.error_tail


def test_job_without_log_path_keeps_existing_behavior(tmp_path: Path):
    """Default (no log_path) path is unchanged: no file, stderr still tailed."""
    jm = JobManager(tmp_path / ".cache" / "jobs_root")
    code = "import sys; print('boom', file=sys.stderr); sys.exit(3)"
    argv = [sys.executable, "-c", code]
    job_id, _ = jm.submit("teststrat2", "run --robustness", argv)
    assert jm.wait_for_terminal(job_id, timeout=30)
    job = jm.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_tail and "boom" in job.error_tail
