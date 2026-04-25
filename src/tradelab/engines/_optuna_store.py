"""Shared Optuna persistence helpers.

All tradelab engines that create Optuna studies write to a single SQLite file
under the configured cache dir. This enables post-hoc inspection via
``optuna-dashboard sqlite:///<cache>/optuna_studies.db``.

Study naming convention (chronologically sortable in the dashboard UI):
    {strategy}_opt_{YYYYMMDD_HHMMSS_ffffff}            # single optimize call
    {strategy}_wf_{YYYYMMDD_HHMMSS_ffffff}_w{NN}       # walkforward per-window

Microsecond resolution is needed because LOSO and other batch flows create
studies in tight succession; second-resolution timestamps collide and
optuna.create_study(load_if_exists=False) raises DuplicatedStudyError.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import get_config


# Process-wide monotonically increasing counter, used as a tiebreaker when
# two calls land in the same microsecond (rare but possible on fast hardware).
_counter_lock = threading.Lock()
_counter = 0


def _next_counter() -> int:
    global _counter
    with _counter_lock:
        _counter += 1
        return _counter


def optuna_storage_url() -> str:
    """SQLite URL for the shared Optuna studies DB. Ensures the dir exists."""
    cfg = get_config()
    cache_dir = Path(cfg.paths.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = (cache_dir / "optuna_studies.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


def make_study_name(
    strategy_name: str,
    kind: str,
    timestamp: Optional[str] = None,
    window_idx: Optional[int] = None,
) -> str:
    """Build a unique, sortable study name. `timestamp` lets callers share a
    prefix across related studies (e.g., all WF windows of one run)."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    name = f"{strategy_name}_{kind}_{ts}_n{_next_counter():06d}"
    if window_idx is not None:
        name = f"{name}_w{window_idx:02d}"
    return name
