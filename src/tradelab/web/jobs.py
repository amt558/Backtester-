"""Job manager for the Research tab Trigger-a-Run feature.

Spawns subprocess.Popen for each tradelab CLI invocation, manages a serial
FIFO queue (one job running at a time), persists state to .cache/jobs.json
with atomic writes, recovers from dashboard restarts by checking PID liveness.
"""
from __future__ import annotations

import enum
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = 1
RETENTION_TERMINAL_JOBS = 50


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass
class Job:
    id: str
    strategy: str
    command: str          # human-readable: "run --robustness"
    argv: list[str]       # the actual ["run", "momo", "--robustness"] passed to tradelab.cli
    status: JobStatus = JobStatus.QUEUED
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    progress_log: Optional[str] = None
    last_event_summary: Optional[str] = None
    error_tail: Optional[str] = None  # last 100 lines of stderr if failed

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d["status"] = JobStatus(d["status"])
        return cls(**d)


class JobManager:
    """Serial-queue job manager. Thread-safe via a single Lock."""

    def __init__(self, cache_root: Path | str):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queue: list[str] = []
        self._running_id: Optional[str] = None
        self._processes: dict[str, subprocess.Popen] = {}
        # event hook — wired by sse.py to push state changes
        self._on_state_change = None
        self._load_or_init()

    # ─── State persistence ──────────────────────────────────────────

    def _state_path(self) -> Path:
        return self.cache_root / "jobs.json"

    def _load_or_init(self) -> None:
        p = self._state_path()
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw.get("schema_version") != SCHEMA_VERSION:
                # forward-incompat — start fresh, don't lose old file
                _backup_corrupted(p, reason="schema_mismatch")
                return
            self._jobs = {j["id"]: Job.from_dict(j) for j in raw.get("jobs", [])}
            self._queue = list(raw.get("queue", []))
            self._running_id = raw.get("running_id")
        except (json.JSONDecodeError, KeyError, ValueError):
            _backup_corrupted(p, reason="parse_error")
            return

        # Liveness check: any RUNNING job whose PID is dead → INTERRUPTED
        if self._running_id:
            running = self._jobs.get(self._running_id)
            if running is None or running.pid is None:
                self._running_id = None
            elif not _pid_alive(running.pid):
                running.status = JobStatus.INTERRUPTED
                running.ended_at = _ts()
                self._running_id = None
                self._persist()

    def _persist(self) -> None:
        # caller must hold self._lock
        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in self._jobs.values()],
            "queue": list(self._queue),
            "running_id": self._running_id,
        }
        _atomic_write_json(self._state_path(), data)


    def submit(self, strategy: str, command: str, argv: list[str]) -> tuple[str, JobStatus]:
        """Submit a new job. Returns (job_id, status) where status is RUNNING or QUEUED.

        Raises DuplicateJobError if a job with the same (strategy, command)
        is already RUNNING or QUEUED.
        """
        with self._lock:
            # dedupe
            for jid, j in self._jobs.items():
                if (
                    j.strategy == strategy
                    and j.command == command
                    and j.status in (JobStatus.RUNNING, JobStatus.QUEUED)
                ):
                    raise DuplicateJobError(existing_job_id=jid)

            job_id = uuid.uuid4().hex
            progress_path = self.cache_root / "jobs" / job_id / "progress.jsonl"
            progress_path.parent.mkdir(parents=True, exist_ok=True)

            # rewrite argv to inject --progress-log if not already present
            argv_with_log = list(argv)
            if "--progress-log" not in argv_with_log:
                argv_with_log.extend(["--progress-log", str(progress_path)])

            job = Job(
                id=job_id,
                strategy=strategy,
                command=command,
                argv=argv_with_log,
                progress_log=str(progress_path),
            )
            self._jobs[job_id] = job

            if self._running_id is None:
                self._start(job_id)
                status = JobStatus.RUNNING
            else:
                self._queue.append(job_id)
                status = JobStatus.QUEUED

            self._persist()
            return job_id, status

    def _start(self, job_id: str) -> None:
        """Spawn subprocess. Caller must hold self._lock."""
        job = self._jobs[job_id]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        proc = subprocess.Popen(
            job.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            cwd=str(self.cache_root.parent) if self.cache_root.parent.name == "tradelab" else None,
        )
        self._processes[job_id] = proc
        job.pid = proc.pid
        job.started_at = _ts()
        job.status = JobStatus.RUNNING
        self._running_id = job_id
        # start a watcher thread that flips status when subprocess exits
        threading.Thread(target=self._watch, args=(job_id,), daemon=True).start()

    def _watch(self, job_id: str) -> None:
        """Block on subprocess exit, then update state."""
        proc = self._processes.get(job_id)
        if proc is None:
            return
        try:
            stderr_bytes = proc.communicate()[1] or b""
        except Exception:
            stderr_bytes = b""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.exit_code = proc.returncode
            job.ended_at = _ts()
            if job.status == JobStatus.CANCELLED:
                pass  # already set by cancel()
            elif proc.returncode == 0:
                job.status = JobStatus.DONE
            else:
                job.status = JobStatus.FAILED
                tail = stderr_bytes.decode(errors="replace").splitlines()[-100:]
                job.error_tail = "\n".join(tail)
            self._processes.pop(job_id, None)
            self._running_id = None
            # promote next queued job
            if self._queue:
                next_id = self._queue.pop(0)
                self._start(next_id)
            self._persist()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if cancellation was attempted, False if no-op."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status == JobStatus.QUEUED:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                job.status = JobStatus.CANCELLED
                job.ended_at = _ts()
                self._persist()
                return True
            if job.status != JobStatus.RUNNING:
                return False
            proc = self._processes.get(job_id)
            if proc is None:
                return False
            job.status = JobStatus.CANCELLED  # set before signaling so _watch sees it
            self._persist()
        # release lock before signaling — kill is potentially slow
        try:
            if sys.platform == "win32":
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        return True

    def wait_for_terminal(self, job_id: str, timeout: float = 30.0) -> bool:
        """Block until the job is in a terminal state (test helper). Returns True if reached."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return False
                if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                    return True
            time.sleep(0.05)
        return False


class DuplicateJobError(Exception):
    """Raised when a (strategy, command) pair is already running or queued."""
    def __init__(self, existing_job_id: str):
        super().__init__(f"job already in flight: {existing_job_id}")
        self.existing_job_id = existing_job_id


# ─── Module helpers ──────────────────────────────────────────────────


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            # On Windows, os.kill(pid, 0) raises if dead, returns None if alive
            os.kill(pid, 0)
            return True
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _atomic_write_json(target: Path, data: dict) -> None:
    """Write to target atomically: write .tmp, then os.replace."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _backup_corrupted(path: Path, reason: str) -> None:
    """Rename a corrupted state file out of the way; log loudly."""
    bak = path.with_suffix(f".broken-{reason}-{int(time.time())}.json")
    try:
        path.rename(bak)
        print(f"[jobs] corrupted state file backed up to {bak}", file=sys.stderr)
    except OSError:
        pass
