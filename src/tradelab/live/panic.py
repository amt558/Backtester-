"""Panic panel core logic — Slice 6.

L1: Disable all cards.
L2: L1 + cancel open tradelab orders (optionally all open orders).
L3: L2 + flatten all positions (whole-account).

Each Alpaca call is wrapped in try/except so partial failures don't abort
the panic. Failures are recorded as PanicAction(ok=False) entries and
included in the audit log + notification.

Per spec §10: lives in dashboard launcher process. Receiver picks up L1
via existing watchdog reload of cards.json. L2/L3 hit Alpaca directly.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PANIC_LOG_PATH = Path(__file__).resolve().parents[3] / "live" / "panic_events.jsonl"


# ─── Dataclasses ─────────────────────────────────────────────────────────

@dataclass
class CancelAction:
    ok: bool
    error: Optional[str]
    order_id: Optional[str]
    client_order_id: Optional[str]
    card_id: Optional[str]  # None if non-tradelab order


@dataclass
class FlattenAction:
    ok: bool
    error: Optional[str]
    symbol: str
    qty: str  # alpaca returns string; preserve precision
    side: str  # "buy" or "sell" — opposite of held position
    order_id: Optional[str]


@dataclass
class PanicResult:
    ts: str
    level: str  # "L1" | "L2" | "L3"
    before_state_snapshot: list[dict]
    cards_disabled: list[str]
    orders_cancelled: list[CancelAction]
    positions_flattened: list[FlattenAction]


# ─── Notification body helpers ───────────────────────────────────────────

_TRUNC_AT = 10


def _truncate_for_notification(ids: list[str]) -> str:
    """Render a list of IDs as a comma-separated string, truncated after 10
    items with a '… +N more' suffix. Returns '(none)' for empty."""
    if not ids:
        return "(none)"
    if len(ids) <= _TRUNC_AT:
        return ", ".join(ids)
    head = ", ".join(ids[:_TRUNC_AT])
    return f"{head}… +{len(ids) - _TRUNC_AT} more"


def _build_notification_body(result: PanicResult) -> str:
    """Build the multi-line CRITICAL notification body. Same string to all
    five channels (truncation per channel happens client-side).
    """
    ts_local = result.ts  # already includes TZ
    cancelled_ids = [a.client_order_id or "?" for a in result.orders_cancelled if a.ok]
    flattened_strs = [
        f"{a.symbol}({a.qty} {a.side})"
        for a in result.positions_flattened if a.ok
    ]
    cancel_failures = sum(1 for a in result.orders_cancelled if not a.ok)
    flatten_failures = sum(1 for a in result.positions_flattened if not a.ok)
    total_failures = cancel_failures + flatten_failures

    lines = [
        f"{result.level} panic at {ts_local}",
        "",
        f"Cards disabled ({len(result.cards_disabled)}): {_truncate_for_notification(result.cards_disabled)}",
        f"Orders cancelled ({sum(1 for a in result.orders_cancelled if a.ok)}): {_truncate_for_notification(cancelled_ids)}",
        f"Positions flattened: {_truncate_for_notification(flattened_strs)}",
    ]
    if total_failures > 0:
        lines.append(f"Errors: {total_failures} failed action(s) (see audit log).")
    return "\n".join(lines)
