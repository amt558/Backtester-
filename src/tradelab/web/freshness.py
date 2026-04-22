"""Parquet cache freshness — age of oldest/newest symbol file.

Reported values drive the color-coded banner at the top of the Research tab.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

_DEFAULT_CACHE = Path(".cache") / "ohlcv" / "1D"


def get_freshness(cache_root: Optional[Path] = None) -> dict:
    """Return age summary for parquet cache.

    Returned dict:
        symbol_count       -- number of *.parquet files found
        oldest_age_hours   -- age of the oldest file (None if empty)
        newest_age_hours   -- age of the newest file (None if empty)
        status             -- "fresh" (<24h) | "aging" (24-72h) | "stale" (>72h) | "unknown"
    """
    root = Path(cache_root) if cache_root else _DEFAULT_CACHE
    if not root.exists() or not root.is_dir():
        return {
            "symbol_count": 0,
            "oldest_age_hours": None,
            "newest_age_hours": None,
            "status": "unknown",
        }

    now = time.time()
    ages: list[float] = []
    for p in root.glob("*.parquet"):
        try:
            ages.append((now - p.stat().st_mtime) / 3600.0)
        except OSError:
            continue

    if not ages:
        return {
            "symbol_count": 0,
            "oldest_age_hours": None,
            "newest_age_hours": None,
            "status": "unknown",
        }

    oldest = max(ages)
    newest = min(ages)
    if oldest < 24.0:
        status = "fresh"
    elif oldest < 72.0:
        status = "aging"
    else:
        status = "stale"

    return {
        "symbol_count": len(ages),
        "oldest_age_hours": round(oldest, 2),
        "newest_age_hours": round(newest, 2),
        "status": status,
    }
