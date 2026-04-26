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

from tradelab.live import live_config


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


def check_daily_limit(card: dict, state: CardRuntimeState, now: datetime) -> Optional[BlockReason]:
    limit = int(card.get("daily_limit", 5))
    current_window = get_rth_window_start(now)
    # Stale or absent window means the count cannot be attributed to today
    fires_today = (
        state.fires_today
        if state.fire_window_start is not None
        and state.fire_window_start >= current_window
        else 0
    )
    if fires_today < limit:
        return None
    return BlockReason(
        code="daily_limit_exceeded",
        message=f"daily limit reached: {fires_today}/{limit}",
        details={"fires_today": fires_today, "daily_limit": limit},
    )


_COLLISION_WINDOW_SECONDS = 30


def check_symbol_collision(
    card: dict,
    registry: dict[str, dict],
    states: dict[str, CardRuntimeState],
    now: datetime,
) -> Optional[BlockReason]:
    if card.get("allow_collision"):
        return None
    my_id = card["card_id"]
    my_symbol = str(card.get("symbol", "")).upper()
    cutoff = now - timedelta(seconds=_COLLISION_WINDOW_SECONDS)
    for other_id, other_card in registry.items():
        if other_id == my_id:
            continue
        if other_card.get("status") != "enabled":
            continue
        if str(other_card.get("symbol", "")).upper() != my_symbol:
            continue
        other_state = states.get(other_id)
        if other_state is None or other_state.last_fired_at is None:
            continue
        if other_state.last_fired_at < cutoff:
            continue
        return BlockReason(
            code="symbol_collision",
            message=f"another card ({other_id}) fired {my_symbol} within {_COLLISION_WINDOW_SECONDS}s",
            details={
                "other_card_id": other_id,
                "symbol": my_symbol,
                "window_seconds": _COLLISION_WINDOW_SECONDS,
            },
        )
    return None


def check_naked_short(card: dict, action: str, alpaca_state) -> Optional[BlockReason]:
    if action != "sell":
        return None
    if card.get("allow_naked_short"):
        return None
    target = str(card.get("symbol", "")).upper()
    for pos in alpaca_state.positions():
        if str(getattr(pos, "symbol", "")).upper() != target:
            continue
        try:
            qty = float(getattr(pos, "qty", 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty > 0:
            return None
    return BlockReason(
        code="no_position_to_sell",
        message=f"sell rejected: no open position in {target}",
        details={"symbol": target},
    )


def _coerce_float(v) -> float:
    """Coerce a value to float, handling None and non-numeric types gracefully."""
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def check_buying_power(
    card: dict,
    alpaca_state,
    qty: float,
    last_price: float,
    max_exposure_pct: Optional[float] = None,
) -> Optional[BlockReason]:
    """Check if (working_orders_notional + new_order_notional) exceeds buying_power cap.

    Working notional is the sum of each open order's qty × (limit_price or filled_avg_price or 0).
    New order's notional is qty × last_price. Both are checked against buying_power × max_exposure_pct.

    max_exposure_pct: when None (default), reads from live_config["guardrails"]["max_exposure_pct"].
    Pass an explicit float to override (used in tests that predate live_config).
    """
    if max_exposure_pct is None:
        max_exposure_pct = live_config.get()["guardrails"]["max_exposure_pct"]
    bp = _coerce_float(alpaca_state.account().buying_power)
    cap = bp * max_exposure_pct
    working = 0.0
    for o in alpaca_state.open_orders():
        o_qty = _coerce_float(getattr(o, "qty", 0))
        o_price = _coerce_float(getattr(o, "limit_price", None)) \
            or _coerce_float(getattr(o, "filled_avg_price", None))
        working += o_qty * o_price
    new_notional = qty * last_price
    if working + new_notional <= cap:
        return None
    return BlockReason(
        code="insufficient_buying_power",
        message=f"buying-power cap exceeded: working ${working:.0f} + new ${new_notional:.0f} > cap ${cap:.0f}",
        details={
            "buying_power": bp,
            "max_exposure_pct": max_exposure_pct,
            "cap": cap,
            "working_notional": working,
            "new_notional": new_notional,
        },
    )


def evaluate_guardrails(
    *,
    card: dict,
    action: str,
    qty: float,
    last_price: float,
    registry: dict[str, dict],
    states: dict[str, CardRuntimeState],
    alpaca_state,
    now: datetime,
    max_exposure_pct: Optional[float] = None,
) -> Optional[BlockReason]:
    """Run the 5 checks in fixed cheapest-first order. First failure wins.

    Order matters:
      1. cooldown      — cheap, in-memory
      2. daily_limit   — cheap, in-memory
      3. collision     — in-memory scan over <=50 cards
      4. naked_short   — Alpaca positions (cached)
      5. buying_power  — Alpaca account+orders (cached)

    max_exposure_pct: when None (default), check_buying_power reads from live_config.
    """
    state = states.get(card["card_id"], CardRuntimeState())

    if (br := check_cooldown(card, state, now)) is not None:
        return br
    if (br := check_daily_limit(card, state, now)) is not None:
        return br
    if (br := check_symbol_collision(card, registry, states, now)) is not None:
        return br
    if (br := check_naked_short(card, action, alpaca_state)) is not None:
        return br
    if (br := check_buying_power(card, alpaca_state, qty, last_price, max_exposure_pct)) is not None:
        return br
    return None
