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


import threading
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from tradelab.live import notify as _notify
from tradelab.live.notify import Severity

ET = ZoneInfo("America/New_York")

_silent_cards: set[str] = set()
_silent_lock = threading.Lock()


def is_silent(card_id: str) -> bool:
    with _silent_lock:
        return card_id in _silent_cards


def silent_set() -> set[str]:
    """Snapshot copy of the silent set — safe to mutate."""
    with _silent_lock:
        return set(_silent_cards)


def is_rth(now_utc: datetime) -> bool:
    """Regular trading hours: 9:30am–4:00pm ET on a NYSE trading day.

    Imports trading_calendar lazily-by-module-load (top-of-file already).
    """
    from tradelab.live.trading_calendar import is_trading_day
    now_et = now_utc.astimezone(ET)
    if not is_trading_day(now_et.date()):
        return False
    open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now_et < close_t


def tick(
    *,
    now_utc: Optional[datetime] = None,
    cards: Optional[dict[str, dict]] = None,
    multipliers: Optional[dict[str, int]] = None,
    notify_fn: Optional[Callable] = None,
) -> None:
    """One cycle. Deps injectable for tests; defaults to live system on None.

    Outside RTH → return immediately, no state change. Inside RTH → diff the
    verdict against _silent_cards; fire notify(WARNING) for new entries; clear
    silently for cards that left.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if not is_rth(now_utc):
        return

    if cards is None:
        from tradelab.live.cards import CardRegistry
        from pathlib import Path
        path = Path(__file__).resolve().parents[3] / "live" / "cards.json"
        registry = CardRegistry(path)
        registry.reload()
        cards = registry.all_hydrated()
    if multipliers is None:
        from tradelab.live import live_config
        multipliers = live_config.get().get("silence", {}).get("multipliers", {})
    if notify_fn is None:
        notify_fn = _notify.notify

    transitioned: list[dict] = []
    with _silent_lock:
        for cid, card in cards.items():
            should_silent = _compute_should_be_silent(card, now_utc, multipliers)
            if should_silent and cid not in _silent_cards:
                _silent_cards.add(cid)
                transitioned.append(card)
            elif not should_silent and cid in _silent_cards:
                _silent_cards.discard(cid)

    for card in transitioned:
        cid = card.get("card_id", "?")
        symbol = card.get("symbol", "?")
        cadence = card.get("cadence", "daily")
        notify_fn(
            Severity.WARNING,
            "Card silent",
            f"{cid} ({symbol}) has not fired within its {cadence} cadence threshold.",
        )
