"""Shared JSONL helpers for daily_summary.render() data sources.

read_today_lines: read a jsonl file, filter to entries whose `ts` (ISO 8601
UTC) corresponds to the given date in America/New_York. Skips corrupt lines
silently. Returns list of dicts in original file order.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — Windows may need tzdata
    import pytz
    _ET = pytz.timezone("America/New_York")


def _parse_ts_to_et_date(ts_value: Any) -> date | None:
    """Parse an ISO 8601 timestamp (with or without offset) and return its date in ET.
    Returns None on any parse failure or unsupported type."""
    if not isinstance(ts_value, str):
        return None
    try:
        # fromisoformat handles "2026-04-27T13:30:00+00:00" natively in Py3.11
        # Fallback for trailing "Z" form
        ts = ts_value.replace("Z", "+00:00") if ts_value.endswith("Z") else ts_value
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(_ET).date()


def read_today_lines(path: Path, today_et: date) -> list[dict]:
    """Read jsonl at `path`, return entries whose `ts` field falls on `today_et` in ET.

    Returns [] if file is missing, empty, or unreadable. Skips lines that
    don't parse as JSON, lack a `ts` field, or have an unparseable timestamp.
    Preserves original file order.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[_jsonl_helpers] read failed for {path}: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entry_date = _parse_ts_to_et_date(entry.get("ts"))
        if entry_date != today_et:
            continue
        out.append(entry)
    return out
