"""Position guardrails — pure check functions + composer.

Every check returns Optional[BlockReason]. None == pass; a value == reject.

Composer evaluate_guardrails() runs them in cheapest-first order and
short-circuits on first failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo


_NY = ZoneInfo("America/New_York")
_RTH_OPEN = time(9, 30)


@dataclass
class BlockReason:
    """Returned by a guardrail when an order must be rejected."""
    code: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class CardRuntimeState:
    """In-memory per-card runtime state held by the receiver."""
    last_attempted_at: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None
    fires_today: int = 0
    fire_window_start: Optional[datetime] = None


def get_rth_window_start(now: datetime) -> datetime:
    """Most recent 9:30 America/New_York <= now, returned in `now`'s tz.

    If `now` is before 9:30 ET on a weekday (or any time on Sat/Sun),
    walks back to the previous business day's 9:30 ET. US holidays are
    not special-cased in v1 — fires don't happen on closed markets so
    the previous-business-day window is harmless when one applies.
    """
    now_ny = now.astimezone(_NY)
    candidate = datetime.combine(now_ny.date(), _RTH_OPEN, tzinfo=_NY)
    while candidate > now_ny or candidate.weekday() >= 5:  # Sat=5, Sun=6
        candidate -= timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    return candidate.astimezone(now.tzinfo or timezone.utc)


def check_cooldown(card: dict, state: CardRuntimeState, now: datetime) -> Optional[BlockReason]:
    cooldown = int(card.get("cooldown_seconds", 30))
    if cooldown <= 0 or state.last_attempted_at is None:
        return None
    elapsed = (now - state.last_attempted_at).total_seconds()
    if elapsed >= cooldown:
        return None
    return BlockReason(
        code="cooldown_active",
        message=f"cooldown active: {cooldown - elapsed:.1f}s remaining",
        details={"cooldown_seconds": cooldown, "seconds_remaining": cooldown - elapsed},
    )
