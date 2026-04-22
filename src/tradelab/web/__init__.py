"""tradelab.web — web dashboard backend modules."""
from __future__ import annotations

from pathlib import Path

from . import audit_reader, freshness, handlers, new_strategy, ranges, whatif  # noqa: F401
from .jobs import JobManager
from .sse import Broadcaster

# Module-level singletons used by handlers.py.
# Cache root is .cache/ relative to current working directory; launch_dashboard.py
# chdirs to the tradelab repo root before importing handlers, so this resolves to
# tradelab/.cache/. Both eagerly constructed at import time — JobManager.__init__
# does mkdir(parents=True, exist_ok=True), so cold-start is safe and the eager
# pattern removes the cold-start race that double-checked locking would invite.
_broadcaster = Broadcaster()
_job_manager = JobManager(cache_root=Path(".cache"))


def _broadcast_event(job_id: str, event: dict) -> None:
    _broadcaster.broadcast({"job_id": job_id, "event": event})


# Wire JobManager → Broadcaster on every state change.
_job_manager._on_state_change = _broadcast_event


def get_broadcaster() -> Broadcaster:
    return _broadcaster


def get_job_manager() -> JobManager:
    return _job_manager


def supports_progress_log() -> bool:
    """Return True if the installed tradelab CLI knows the --progress-log flag.

    Cached on first call. Used by handlers to short-circuit POST /tradelab/jobs
    with 503 if the local tradelab is too old.

    Cache staleness: if the dashboard was started against an old tradelab and
    the user later upgrades, the False result sticks until the dashboard is
    restarted. Workaround is to restart launch_dashboard.py after a tradelab
    upgrade. v1.5 doesn't expose a cache-invalidation hook.
    """
    global _supports_pl
    try:
        return _supports_pl  # type: ignore[name-defined]
    except NameError:
        pass
    import subprocess as _sp
    import sys as _sys
    try:
        # text=True without explicit encoding uses the locale (cp1252 on US
        # Windows), which crashes if the CLI's --help output contains the
        # Unicode chars Rich/Typer emit for table borders. Force UTF-8 with
        # error replacement so the probe never crashes on encoding alone.
        out = _sp.run(
            [_sys.executable, "-m", "tradelab.cli", "run", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        _supports_pl = "--progress-log" in (out.stdout + out.stderr)
    except Exception:
        _supports_pl = False
    return _supports_pl
