"""JSONL log rotation utility — gzip-based, size-triggered, archive-capped.

Used by daily_summary.tick() to rotate the three append-only logs once per
trading day after a successful digest send. Best-effort: catches OSError,
logs to stderr, never raises.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Default paths — pointed to the live data dir. Tests monkeypatch these.
_LIVE_DIR = Path(__file__).resolve().parents[3] / "live"
ALERTS_PATH = _LIVE_DIR / "alerts.jsonl"
NOTIFY_PATH = _LIVE_DIR / "notify_events.jsonl"
PANIC_PATH = _LIVE_DIR / "panic_events.jsonl"


def _today_et_str() -> str:
    """Today's date as YYYY-MM-DD in local server time. Plan picks local; ET conversion
    not strictly required here because rotation timing is "after digest send" which is
    already ET-gated. Keeps this helper dependency-free of pytz/zoneinfo."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _next_archive_path(path: Path, today: str) -> Path:
    """Compute next available `<base>.YYYY-MM-DD.N.jsonl.gz` for today.

    Looks at existing archives in the same dir; picks N = max(existing_N) + 1
    for today's date, or 0 if no archive exists for today.
    """
    base = path.stem  # e.g. "alerts" from "alerts.jsonl"
    parent = path.parent
    pattern = f"{base}.{today}.*.jsonl.gz"
    existing = list(parent.glob(pattern))
    used_n = []
    for p in existing:
        # p.name like "alerts.2026-04-27.3.jsonl.gz" → extract the "3"
        try:
            n_str = p.name.removeprefix(f"{base}.{today}.").removesuffix(".jsonl.gz")
            used_n.append(int(n_str))
        except (ValueError, AttributeError):
            continue
    next_n = (max(used_n) + 1) if used_n else 0
    return parent / f"{base}.{today}.{next_n}.jsonl.gz"


def _enforce_archive_cap(path: Path, keep_archives: int) -> None:
    """Delete oldest <base>.*.jsonl.gz files until count <= keep_archives.

    Best-effort. Sorts by mtime ascending; oldest deleted first.
    """
    base = path.stem
    parent = path.parent
    archives = sorted(parent.glob(f"{base}.*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    while len(archives) > keep_archives:
        victim = archives.pop(0)
        try:
            victim.unlink()
        except OSError as e:
            print(f"[jsonl_rotation] failed to delete archive {victim}: {e}", file=sys.stderr)
            break  # don't loop on persistent failure


def rotate_if_needed(
    path: Path,
    max_size_mb: int = 50,
    keep_archives: int = 5,
) -> Optional[Path]:
    """If path exceeds max_size_mb, rename to `<base>.YYYY-MM-DD.N.jsonl.gz` and start fresh.

    Returns the rotated archive Path on success, or None if no rotation occurred
    (file missing, under threshold, or OSError caught).
    """
    try:
        if not path.exists():
            return None
        size_bytes = path.stat().st_size
        if size_bytes < max_size_mb * 1024 * 1024:
            return None

        today = _today_et_str()
        archive = _next_archive_path(path, today)

        # Stream-compress: read source, write gz; then truncate source.
        with open(path, "rb") as src, gzip.open(archive, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Atomic-ish truncate: replace with empty file
        empty_tmp = path.with_suffix(path.suffix + ".tmp")
        empty_tmp.write_bytes(b"")
        os.replace(empty_tmp, path)

        _enforce_archive_cap(path, keep_archives)
        return archive
    except OSError as e:
        print(f"[jsonl_rotation] rotate failed for {path}: {e}", file=sys.stderr)
        return None


def rotate_all() -> dict[str, Optional[Path]]:
    """Rotate alerts.jsonl, notify_events.jsonl, panic_events.jsonl with default thresholds.

    Returns map of name → rotation result for caller logging.
    """
    return {
        "alerts": rotate_if_needed(ALERTS_PATH),
        "notify_events": rotate_if_needed(NOTIFY_PATH),
        "panic_events": rotate_if_needed(PANIC_PATH),
    }
