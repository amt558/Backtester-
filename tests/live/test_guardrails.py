"""Position guardrails — pure functions returning Optional[BlockReason]."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradelab.live.guardrails import (
    BlockReason,
    CardRuntimeState,
    check_cooldown,
    get_rth_window_start,
)


# ── RTH window helper ────────────────────────────────────────────────

def test_rth_window_during_market_returns_today_930_et():
    # 2026-03-04 (Wed) 11:00 America/New_York == 16:00 UTC
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # 9:30 ET = 14:30 UTC on 2026-03-04
    assert start == datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc)


def test_rth_window_pre_market_returns_previous_business_day():
    # 2026-03-04 (Wed) 09:00 ET == 14:00 UTC (before 9:30)
    now = datetime(2026, 3, 4, 14, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # Previous business day = 2026-03-03 (Tue) 9:30 ET = 14:30 UTC
    assert start == datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)


def test_rth_window_monday_premarket_returns_friday():
    # 2026-03-09 (Mon) 06:00 ET == 11:00 UTC (before 9:30)
    now = datetime(2026, 3, 9, 11, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # Friday 2026-03-06 9:30 ET = 14:30 UTC
    assert start == datetime(2026, 3, 6, 14, 30, tzinfo=timezone.utc)


# ── Cooldown ─────────────────────────────────────────────────────────

def _card(cooldown_seconds=30, **overrides):
    base = {
        "card_id": "foo-v1", "symbol": "AAPL", "status": "enabled",
        "quantity": 1, "secret": "s" * 32,
        "cooldown_seconds": cooldown_seconds, "daily_limit": 5,
        "allow_collision": False, "allow_naked_short": False,
    }
    base.update(overrides)
    return base


def test_cooldown_no_prior_attempt_passes():
    state = CardRuntimeState()
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    assert check_cooldown(_card(), state, now) is None


def test_cooldown_within_window_blocks():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=10))
    reason = check_cooldown(_card(cooldown_seconds=30), state, now)
    assert reason is not None
    assert reason.code == "cooldown_active"


def test_cooldown_at_boundary_passes():
    """Exactly cooldown_seconds elapsed → allowed."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=30))
    assert check_cooldown(_card(cooldown_seconds=30), state, now) is None


def test_cooldown_zero_disables_check():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(milliseconds=1))
    assert check_cooldown(_card(cooldown_seconds=0), state, now) is None


def test_blockreason_carries_details():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=5))
    reason = check_cooldown(_card(cooldown_seconds=30), state, now)
    assert reason.details["seconds_remaining"] == pytest.approx(25, abs=0.5)
