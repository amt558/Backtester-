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

    def _persist(self) -> None:
        # caller must hold self._lock
        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in self._jobs.values()],
            "queue": list(self._queue),
            "running_id": self._running_id,
        }
        _atomic_write_json(self._state_path(), data)


# ─── Module helpers ──────────────────────────────────────────────────


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
