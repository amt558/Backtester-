"""Shared progress event schema for CLI emitters and web tail consumers.

The CLI side imports `ProgressEmitter` from here when --progress-log is set.
The web side imports `parse_event` from here in progress.py to validate lines.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

# Allowed event types
EVENT_START = "start"
EVENT_PROGRESS = "progress"
EVENT_COMPLETE = "complete"
EVENT_DONE = "done"
EVENT_ERROR = "error"

# Allowed stage names
STAGES = {
    "backtest", "optuna", "walk_forward", "monte_carlo",
    "loso", "regime", "cost_sweep", "tearsheet",
}


class ProgressEmitter:
    """Append-only JSON-line writer for a single subprocess job.

    Line-buffered so events are visible to a tail reader immediately.
    Safe to call when path is empty/None — becomes a no-op (backward compat).
    """

    def __init__(self, path: str | os.PathLike | None):
        self.path: Optional[Path] = Path(path) if path else None
        self._fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Line-buffered text mode so the tail loop sees each line immediately
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    def emit(self, type_: str, **fields: Any) -> None:
        if not self._fh:
            return
        event = {"ts": _ts(), "type": type_, **fields}
        self._fh.write(json.dumps(event) + "\n")

    def start(self, stage: str) -> None:
        self.emit(EVENT_START, stage=stage)

    def complete(self, stage: str, duration_s: float | None = None) -> None:
        if duration_s is None:
            self.emit(EVENT_COMPLETE, stage=stage)
        else:
            self.emit(EVENT_COMPLETE, stage=stage, duration_s=round(duration_s, 2))

    def progress(self, stage: str, i: int, total: int) -> None:
        self.emit(EVENT_PROGRESS, stage=stage, i=i, total=total)

    def done(self, exit_code: int = 0) -> None:
        self.emit(EVENT_DONE, exit=exit_code)

    def error(self, message: str) -> None:
        self.emit(EVENT_ERROR, message=message)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def parse_event(line: str) -> Optional[dict]:
    """Parse one JSONL line into an event dict, or None if invalid.

    Tolerant: returns None on JSONDecodeError or missing 'type' field.
    Tolerant of unknown event types and unknown extra fields (forward-compat).
    """
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(ev, dict) or "type" not in ev:
        return None
    return ev


def _ts() -> str:
    """ISO-8601 UTC timestamp with second precision."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
