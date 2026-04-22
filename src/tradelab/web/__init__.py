"""tradelab.web — web dashboard backend modules."""
from __future__ import annotations

from pathlib import Path

from . import audit_reader, freshness, handlers, new_strategy, ranges, whatif  # noqa: F401
from .jobs import JobManager
from .sse import Broadcaster

# Module-level singletons used by handlers.py.
# Cache root is .cache/ relative to current working directory; launch_dashboard.py
# chdirs to the tradelab repo root before importing handlers, so this resolves to
# tradelab/.cache/.
_broadcaster = Broadcaster()
_job_manager: JobManager | None = None


def get_broadcaster() -> Broadcaster:
    return _broadcaster


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager(cache_root=Path(".cache"))
        # wire JobManager → Broadcaster on every event
        def _broadcast_event(job_id: str, event: dict) -> None:
            _broadcaster.broadcast({"job_id": job_id, "event": event})
        _job_manager._on_state_change = _broadcast_event
    return _job_manager
