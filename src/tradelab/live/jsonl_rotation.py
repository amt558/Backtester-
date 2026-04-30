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
from zoneinfo import ZoneInfo


_ET = ZoneInfo("America/New_York")

# Default paths — pointed to the live data dir. Tests monkeypatch these.
_LIVE_DIR = Path(__file__).resolve().parents[3] / "live"
ALERTS_PATH = _LIVE_DIR / "alerts.jsonl"
NOTIFY_PATH = _LIVE_DIR / "notify_events.jsonl"
PANIC_PATH = _LIVE_DIR / "panic_events.jsonl"


def _today_et_str() -> str:
    """Today's date as YYYY-MM-DD in America/New_York (ET).

    Spec §9.2: "Date is the rotation date in ET." Uses zoneinfo (matching
    panic.py) so behavior is correct regardless of server-local TZ (e.g.
    a UTC container would otherwise compute the wrong date around 00:00 ET).
    """
    return datetime.now(_ET).strftime("%Y-%m-%d")


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


def _cleanup_orphans(path: Path) -> None:
    """Best-effort cleanup of crash-leftover tmp files for ``path``.

    Removes:
      - ``<path>.tmp``       — orphaned empty-truncate tmp (pre-fix legacy)
      - ``<archive>.gz.tmp`` for any archive in the same dir whose ``.gz``
        sibling either does not exist or is older than the ``.gz.tmp``
        (i.e. the rename never happened OR the tmp is from a fresh attempt).

    Failures are swallowed: the cleanup is opportunistic and rotation
    must remain best-effort.
    """
    # Truncate-tmp orphan
    legacy_tmp = path.with_suffix(path.suffix + ".tmp")
    if legacy_tmp.exists():
        try:
            legacy_tmp.unlink()
        except OSError as e:
            print(f"[jsonl_rotation] failed to remove orphan tmp {legacy_tmp}: {e}", file=sys.stderr)

    # gz.tmp orphans (B2 crash-recovery)
    base = path.stem
    parent = path.parent
    for tmp in parent.glob(f"{base}.*.jsonl.gz.tmp"):
        try:
            tmp.unlink()
        except OSError as e:
            print(f"[jsonl_rotation] failed to remove orphan gz tmp {tmp}: {e}", file=sys.stderr)


def rotate_if_needed(
    path: Path,
    max_size_mb: int = 50,
    keep_archives: int = 5,
) -> Optional[Path]:
    """If path exceeds max_size_mb, rename to `<base>.YYYY-MM-DD.N.jsonl.gz` and start fresh.

    Returns the rotated archive Path on success, or None if no rotation occurred
    (file missing, under threshold, or OSError caught).

    Crash-safety (B2): The archive is written to ``<archive>.gz.tmp`` first,
    THEN the source is truncated, THEN the tmp is atomic-renamed to
    ``<archive>.gz``. A crash at any point leaves either:
      - the original source intact + an orphan ``.gz.tmp`` (cleaned on next call)
      - a truncated source + an orphan ``.gz.tmp`` (cleaned on next call;
        the truncate step ensures we never re-archive the same content)
      - the final ``.gz`` plus a truncated source (success state)
    No path leaves a duplicate archive visible to ops.
    """
    try:
        # Sweep crash-leftover tmp files BEFORE deciding whether to rotate.
        # This handles the orphan-tmp case (B2 issue #1) and ensures a fresh
        # rotation attempt doesn't trip over stale gz.tmp from a prior crash.
        _cleanup_orphans(path)

        if not path.exists():
            return None
        size_bytes = path.stat().st_size
        if size_bytes < max_size_mb * 1024 * 1024:
            return None

        today = _today_et_str()
        archive = _next_archive_path(path, today)
        archive_tmp = archive.with_suffix(archive.suffix + ".tmp")

        # 1) Stream-compress source → archive.gz.tmp (NOT the final .gz path).
        try:
            with open(path, "rb") as src, gzip.open(archive_tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)

            # 2) Truncate the source. If we crash here, next call sees the
            #    .gz.tmp orphan and cleans it; source is still original or
            #    already-truncated, but no duplicate archive is published.
            empty_tmp = path.with_suffix(path.suffix + ".tmp")
            empty_tmp.write_bytes(b"")
            os.replace(empty_tmp, path)

            # 3) Atomic-rename .gz.tmp → .gz. After this point the archive
            #    is visible to ops. A crash before this point publishes nothing.
            os.replace(archive_tmp, archive)
        except BaseException:
            # On ANY failure (incl. KeyboardInterrupt/SystemExit), do not leave
            # an orphan .gz.tmp around. The outer `except OSError` will still
            # handle OSError reporting; non-OSError re-raises after cleanup.
            try:
                if archive_tmp.exists():
                    archive_tmp.unlink()
            except OSError:
                pass
            raise

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
