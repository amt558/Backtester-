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
