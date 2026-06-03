"""Job manager for the Research tab Trigger-a-Run feature.

Spawns subprocess.Popen for each tradelab CLI invocation, manages a serial
FIFO queue (one job running at a time), persists state to .cache/jobs.json
with atomic writes, recovers from dashboard restarts by checking PID liveness.
"""
from __future__ import annotations

import enum
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, asdict, fields as dc_fields
from pathlib import Path
from typing import Optional

from .progress import ProgressTailer


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
    log_path: Optional[str] = None    # combined stdout+stderr sink (never DEVNULL)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        if self.status == JobStatus.FAILED:
            from tradelab.web.failure_hint import extract_failure_hint
            d["failure_hint"] = extract_failure_hint(self.id, exit_code=self.exit_code)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        # Drop unknown keys: to_dict() injects runtime-derived fields like
        # `failure_hint` for FAILED jobs which aren't dataclass attributes.
        # The persistence path round-trips through to_dict, so those keys
        # land in jobs.json and would fail cls(**d).
        known = {f.name for f in dc_fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
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
        self._tailers: dict[str, ProgressTailer] = {}
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

        # Liveness check: any RUNNING job whose PID is dead → INTERRUPTED.
        # Take the lock for invariant correctness; in __init__ we are
        # single-threaded but a future "reload from disk" admin path
        # would otherwise violate _persist's lock-required contract.
        with self._lock:
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
        terminal_states = {
            JobStatus.DONE, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.INTERRUPTED,
        }
        active = [j for j in self._jobs.values() if j.status not in terminal_states]
        terminal = [j for j in self._jobs.values() if j.status in terminal_states]
        # Stable sort with id tiebreaker — _ts() is 1-second resolution, so
        # collisions are common when many jobs finish quickly. id keeps the
        # drop order deterministic across dict-rebuild paths.
        terminal.sort(key=lambda j: (j.ended_at or "", j.id))
        if len(terminal) > RETENTION_TERMINAL_JOBS:
            drop = terminal[: len(terminal) - RETENTION_TERMINAL_JOBS]
            for j in drop:
                self._jobs.pop(j.id, None)
            terminal = terminal[len(terminal) - RETENTION_TERMINAL_JOBS:]

        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in (active + terminal)],
            "queue": list(self._queue),
            "running_id": self._running_id,
        }
        _atomic_write_json(self._state_path(), data)


    def submit(
        self,
        strategy: str,
        command: str,
        argv: list[str],
        log_path: Optional[str] = None,
    ) -> tuple[str, JobStatus]:
        """Submit a new job. Returns (job_id, status) where status is RUNNING or QUEUED.

        Raises DuplicateJobError if a job with the same (strategy, command)
        is already RUNNING or QUEUED.

        log_path: if given, the job's combined stdout+stderr is written there
        when the process exits (never DEVNULL). Default None preserves the
        original PIPE-only behaviour.
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

            if log_path:
                Path(log_path).parent.mkdir(parents=True, exist_ok=True)

            job = Job(
                id=job_id,
                strategy=strategy,
                command=command,
                argv=argv_with_log,
                progress_log=str(progress_path),
                log_path=str(log_path) if log_path else None,
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
        # tail progress.jsonl and route events to last_event_summary + sse
        if job.progress_log:
            tailer = ProgressTailer(
                Path(job.progress_log),
                on_event=lambda ev, jid=job_id: self._on_progress_event(jid, ev),
            )
            tailer.start()
            self._tailers[job_id] = tailer

    def _watch(self, job_id: str) -> None:
        """Block on subprocess exit, then update state."""
        proc = self._processes.get(job_id)
        if proc is None:
            return
        # log_path is immutable after submit, so reading it without the lock is safe.
        job0 = self._jobs.get(job_id)
        log_path = job0.log_path if job0 else None
        try:
            stdout_bytes, stderr_bytes = proc.communicate()
            stdout_bytes = stdout_bytes or b""
            stderr_bytes = stderr_bytes or b""
        except Exception:
            stdout_bytes, stderr_bytes = b"", b""
        # Persist the combined stream so a failed run leaves a trail (never DEVNULL).
        if log_path:
            try:
                with open(log_path, "wb") as f:
                    if stdout_bytes:
                        f.write(stdout_bytes)
                    if stderr_bytes:
                        f.write(stderr_bytes)
            except OSError:
                pass
        # Subprocess has exited. The tailer may be mid-poll-wait and could
        # miss the final emitted events (the 'done' line written microseconds
        # before exit). Stop the tailer now so its final drain pass reads
        # any remaining bytes synchronously before we flip status to DONE.
        # If we don't do this, callers using wait_for_terminal() can race
        # the tailer and observe a stale last_event_summary.
        tailer = self._tailers.get(job_id)
        if tailer is not None:
            tailer.stop()
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
            self._tailers.pop(job_id, None)  # already stopped above
            self._running_id = None
            # promote next queued job
            if self._queue:
                next_id = self._queue.pop(0)
                self._start(next_id)
            self._persist()

    def _on_progress_event(self, job_id: str, event: dict) -> None:
        """Callback fired by ProgressTailer for each parsed event."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            new_summary = _summarize_event(event)
            if new_summary != job.last_event_summary:
                job.last_event_summary = new_summary
                # Persist only on coarse stage transitions, not on every progress
                # tick — Optuna runs can fire 500+ progress events per stage and
                # we don't want a jobs.json rewrite per tick. Stage transitions
                # are rare (~10/job), so post-restart UI shows the most recent
                # stage milestone instead of stale data.
                if event.get("type") in ("start", "complete", "done", "error"):
                    self._persist()
        # call the SSE hook outside the lock
        if self._on_state_change:
            try:
                self._on_state_change(job_id, event)
            except Exception:
                pass

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
        # Release lock before signaling — kill is potentially slow.
        # Windows note: the child is spawned DETACHED_PROCESS (no console), so
        # console ctrl events (CTRL_BREAK/CTRL_C via GenerateConsoleCtrlEvent)
        # can never reach it — the old os.kill(pid, CTRL_BREAK_EVENT) here was
        # a silent no-op and cancel only worked via the 5s proc.kill()
        # escalation below. proc.terminate() (TerminateProcess on Windows,
        # SIGTERM on POSIX) is the only reliable direct mechanism; no grace
        # period is lost because none ever existed.
        try:
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


def _summarize_event(event: dict) -> str:
    """Compact human-readable summary like 'MC 320/500'."""
    t = event.get("type", "")
    stage = event.get("stage", "")
    if t == "progress" and "i" in event and "total" in event:
        return f"{stage} {event['i']}/{event['total']}"
    if t == "start":
        return f"{stage} starting"
    if t == "complete":
        return f"{stage} done"
    if t == "done":
        return "done"
    if t == "error":
        return "error"
    return ""


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check.

    WARNING (Windows): never use os.kill(pid, 0) here. signal.CTRL_C_EVENT == 0
    on Windows, so os.kill(pid, 0) calls GenerateConsoleCtrlEvent — it is NOT a
    liveness probe, it BROADCASTS Ctrl+C to the caller's own console process
    group. This asynchronously killed the test runner / dashboard console
    (root cause of the 2026-06-03 "terminal crashes", see
    SESSION_2026-06-03b_step3-5-LANDED_crash-root-cause.md §3).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True  # process exists but is owned by another user
    except (OSError, ProcessLookupError):
        return False


def _win_pid_alive(pid: int) -> bool:
    """Windows liveness check via OpenProcess + WaitForSingleObject. No signals.

    WaitForSingleObject(handle, 0) == WAIT_TIMEOUT means the process is still
    running. This is correct even when another process holds an open handle to
    an already-exited process (where a bare OpenProcess success would lie).
    """
    import ctypes

    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        # ACCESS_DENIED → process exists but isn't ours → alive.
        # Anything else (e.g. ERROR_INVALID_PARAMETER) → no such process.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


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
