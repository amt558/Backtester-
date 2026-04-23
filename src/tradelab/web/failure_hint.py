"""Parse .cache/jobs/<job_id>/progress.jsonl to produce a one-line hint
for a FAILED job. Returns None for non-FAILED or unparseable logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


EXIT_CODE_LABELS = {
    0:  "success (but state=FAILED — possible orchestration bug)",
    1:  "Python exception (see log)",
    2:  "CLI arg error",
    3:  "timeout",
    -1073741510:   "cancelled (CTRL_BREAK)",
    3221225786:    "cancelled (CTRL_BREAK)",
}


def extract_failure_hint(job_id: str, exit_code: Optional[int],
                         cache_root: Path = Path(".cache")) -> Optional[str]:
    """Return a short hint string for a FAILED job, or None if no log found."""
    log = cache_root / "jobs" / job_id / "progress.jsonl"
    last_error: Optional[dict] = None
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "error" or ev.get("ok") is False:
                last_error = ev

    if last_error:
        et = last_error.get("error_type") or last_error.get("type") or "error"
        msg = (last_error.get("message") or last_error.get("error") or "")[:80]
        if et == "NoSymbolsProvided":
            return "universe not resolved — check preflight"
        return f"{et}: {msg}" if msg else et

    if exit_code is None:
        return None
    return EXIT_CODE_LABELS.get(exit_code, f"exit {exit_code}")
