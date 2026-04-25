"""Derive Live-Trading-tab view fields from cards.json + alerts.jsonl.

Pure functions — no I/O beyond reading files. Caller passes paths in
so tests can use tmp_path.
"""
from __future__ import annotations

import copy
import json
import re
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


_VERSION_PATTERN = re.compile(r"^(?P<base>.+)-v(?P<n>\d+)$")


def _parse_card_id(card_id: str) -> tuple[str, Optional[int]]:
    """Split card_id into (base_name, version). version is None if no -vN suffix."""
    m = _VERSION_PATTERN.match(card_id)
    if not m:
        return card_id, None
    return m.group("base"), int(m.group("n"))


def group_by_base_name(cards: dict[str, dict]) -> list[dict]:
    """Group cards by their base_name (the part before -vN).

    Returns groups sorted by base_name asc. Within each group, cards are
    sorted enabled-first then version-desc, with disabled appended after.

    Each group dict shape:
        {
          "base_name": str,
          "enabled_count": int,
          "total_count": int,
          "multi_enabled_warning": bool,
          "cards": [hydrated card dicts in display order],
        }
    """
    by_base: dict[str, list[tuple[Optional[int], dict]]] = {}
    for cid, card in cards.items():
        base, version = _parse_card_id(cid)
        by_base.setdefault(base, []).append((version, card))

    groups = []
    for base_name in sorted(by_base.keys()):
        entries = by_base[base_name]
        enabled = [(v, c) for v, c in entries if c.get("status") == "enabled"]
        disabled = [(v, c) for v, c in entries if c.get("status") != "enabled"]

        def _sortkey(t: tuple[Optional[int], dict]) -> tuple[int, int]:
            v, _ = t
            return (-v if v is not None else 1, 0)

        enabled.sort(key=_sortkey)
        disabled.sort(key=_sortkey)
        ordered = [c for _, c in enabled] + [c for _, c in disabled]
        groups.append({
            "base_name": base_name,
            "enabled_count": len(enabled),
            "total_count": len(entries),
            "multi_enabled_warning": len(enabled) > 1,
            "cards": ordered,
        })
    return groups


def tail_alerts_for_card(
    card_id: str,
    log_path: Path,
    limit: int = 50,
) -> list[dict]:
    """Return up to `limit` most-recent alerts for a card_id, newest first.

    A non-positive `limit` returns an empty list.
    """
    if limit <= 0:
        return []
    matches = [e for e in _iter_alerts(log_path) if e.get("card_id") == card_id]
    return list(reversed(matches[-limit:]))


def list_cards_view(cards: dict[str, dict], alerts_log: Path) -> dict:
    """Top-level aggregator for GET /tradelab/cards.

    Caller is responsible for passing hydrated cards (typically via
    CardRegistry.all_hydrated()). This function only handles derivations
    and grouping — it does NOT mutate cards or read cards.json itself.
    """
    card_ids = list(cards.keys())
    last_status = derive_last_status(card_ids, alerts_log)
    fires_24h = derive_fire_counts(card_ids, alerts_log, hours=24)

    enriched: dict[str, dict] = {}
    for cid, card in cards.items():
        copied = copy.deepcopy(card)
        copied["last_status"] = last_status.get(cid)
        copied["fires_24h"] = fires_24h.get(cid, 0)
        enriched[cid] = copied

    groups = group_by_base_name(enriched)
    total_enabled = sum(g["enabled_count"] for g in groups)
    return {
        "groups": groups,
        "total_cards": len(cards),
        "total_enabled": total_enabled,
    }
