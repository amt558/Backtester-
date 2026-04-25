"""Derive Live-Trading-tab view fields from cards.json + alerts.jsonl.

Pure functions — no I/O beyond reading files. Caller passes paths in
so tests can use tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional


def _iter_alerts(log_path: Path) -> Iterable[dict]:
    """Yield each parseable JSON object from alerts.jsonl. Malformed lines
    are silently skipped — alerts.jsonl is append-only and partial writes
    on crash are possible."""
    if not log_path.exists():
        return
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def derive_last_status(card_ids: Iterable[str], log_path: Path) -> dict[str, Optional[str]]:
    """For each card_id, return the most recent alert's status, or None
    if no alert has ever been logged for that card.

    "Most recent" = last occurrence in the file (we trust append-order).
    """
    wanted = set(card_ids)
    last: dict[str, Optional[str]] = {cid: None for cid in wanted}
    for entry in _iter_alerts(log_path):
        cid = entry.get("card_id")
        if cid in wanted:
            last[cid] = entry.get("status")
    return last


def derive_fire_counts(
    card_ids: Iterable[str],
    log_path: Path,
    hours: int = 24,
) -> dict[str, int]:
    """Count `order_submitted` alerts per card_id in the last `hours` hours.

    Other statuses (order_failed, guardrail_blocked, etc.) are NOT counted —
    a "fire" means an order actually went to Alpaca.
    """
    wanted = set(card_ids)
    counts: dict[str, int] = {cid: 0 for cid in wanted}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for entry in _iter_alerts(log_path):
        cid = entry.get("card_id")
        if cid not in wanted:
            continue
        if entry.get("status") != "order_submitted":
            continue
        ts_str = entry.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts >= cutoff:
            counts[cid] += 1
    return counts
