"""Silence detection — flag cards that haven't fired within their cadence threshold.

Per spec §8.3: runs in dashboard launcher process (one consumer). Tick every
30 minutes during RTH. For each enabled card with cadence != 'manual', compute
elapsed (trading days for intraday/daily, calendar days for weekly) since
last_fired_at (or enabled_at if never fired). On transition into silent set,
emit notify(WARNING). Clearing on next fire is silent — no second notify.

In-memory state per spec §8.3 — restart resets transitions, will re-notify any
still-silent card on first post-restart tick.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradelab.live.trading_calendar import count_trading_days_between


def _compute_should_be_silent(
    card: dict, now_utc: datetime, multipliers: dict[str, int]
) -> bool:
    """Pure verdict: should this card currently be in the silent set?

    Returns False for manual cadence, disabled cards, missing reference time,
    unknown cadence, or non-positive multiplier.
    """
    cadence = card.get("cadence", "daily")
    if cadence == "manual":
        return False
    if card.get("status") != "enabled":
        return False
    ref_str = card.get("last_fired_at") or card.get("enabled_at")
    if ref_str is None:
        return False
    if not isinstance(ref_str, str):
        return False
    try:
        ref = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    multiplier = int(multipliers.get(cadence, 0))
    if multiplier <= 0:
        return False
    if cadence == "weekly":
        return (now_utc - ref).days >= multiplier
    # intraday / daily → trading-day arithmetic
    return count_trading_days_between(ref, now_utc) >= multiplier
