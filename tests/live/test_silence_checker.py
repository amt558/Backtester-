"""Pure verdict logic — no thread, no notify, no IO."""
from datetime import datetime, timezone

from tradelab.live.silence_checker import _compute_should_be_silent


MULTS = {"intraday": 2, "daily": 5, "weekly": 21}


def _utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def _card(**overrides) -> dict:
    base = {
        "card_id": "foo-v1",
        "status": "enabled",
        "cadence": "daily",
        "last_fired_at": _utc(2026, 4, 22).isoformat(),
        "enabled_at": _utc(2026, 4, 1).isoformat(),
    }
    base.update(overrides)
    return base


def test_manual_cadence_never_silent():
    card = _card(cadence="manual", last_fired_at=_utc(2020, 1, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 26), MULTS) is False


def test_disabled_card_never_silent():
    card = _card(status="disabled", last_fired_at=_utc(2020, 1, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 26), MULTS) is False


def test_daily_card_just_fired_not_silent():
    card = _card(cadence="daily", last_fired_at=_utc(2026, 4, 22).isoformat())
    # Apr 22 → Apr 23 = 1 trading day elapsed; threshold = 5; not silent
    assert _compute_should_be_silent(card, _utc(2026, 4, 23), MULTS) is False


def test_daily_card_at_threshold_is_silent():
    # Last fired Wed Apr 22; now Wed Apr 29 = 5 trading days elapsed; threshold met
    card = _card(cadence="daily", last_fired_at=_utc(2026, 4, 22).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is True


def test_intraday_card_two_trading_days_silent():
    # intraday threshold = 2 trading days
    card = _card(cadence="intraday", last_fired_at=_utc(2026, 4, 22).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 24), MULTS) is True


def test_weekly_card_uses_calendar_days():
    # weekly threshold = 21 calendar days; 22 days later → silent
    card = _card(cadence="weekly", last_fired_at=_utc(2026, 4, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 23), MULTS) is True


def test_weekly_card_under_threshold_not_silent():
    card = _card(cadence="weekly", last_fired_at=_utc(2026, 4, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 15), MULTS) is False


def test_never_fired_falls_back_to_enabled_at():
    # last_fired_at None; use enabled_at instead
    card = _card(cadence="daily", last_fired_at=None, enabled_at=_utc(2026, 4, 1).isoformat())
    # Apr 1 → Apr 29 ≫ 5 trading days → silent
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is True


def test_never_fired_no_enabled_at_returns_false():
    card = _card(last_fired_at=None, enabled_at=None)
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is False


def test_unknown_cadence_returns_false():
    card = _card(cadence="bogus")
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is False


def test_non_string_last_fired_at_returns_false():
    # Future schema bug: int instead of ISO string. Should not crash, should not flag silent.
    card = _card(last_fired_at=12345)
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is False


def test_naive_now_utc_treated_as_utc():
    # Defensive: caller passes naive datetime — function should not crash.
    from datetime import datetime as _dt
    naive_now = _dt(2026, 4, 29, 18, 0)  # no tzinfo
    card = _card(cadence="daily", last_fired_at=_utc(2026, 4, 22).isoformat())
    # Apr 22 → Apr 29 = 5 trading days; daily threshold = 5 → silent
    assert _compute_should_be_silent(card, naive_now, MULTS) is True


import pytest

from tradelab.live import silence_checker
from tradelab.live.notify import Severity


@pytest.fixture(autouse=True)
def _reset_silent_set():
    silence_checker._silent_cards.clear()
    yield
    silence_checker._silent_cards.clear()


def _enabled_card(cid="foo-v1", cadence="daily", last_fired_iso=None, enabled_at_iso=None):
    return {
        "card_id": cid,
        "status": "enabled",
        "symbol": "AAPL",
        "cadence": cadence,
        "last_fired_at": last_fired_iso,
        "enabled_at": enabled_at_iso or _utc(2026, 4, 1).isoformat(),
    }


def test_tick_outside_rth_no_notify_no_state_change(monkeypatch):
    fired = []
    cards = {"a": _enabled_card("a", last_fired_iso=_utc(2020, 1, 1).isoformat())}
    # Saturday — not RTH
    silence_checker.tick(
        now_utc=_utc(2026, 4, 25, 14),
        cards=cards,
        multipliers=MULTS,
        notify_fn=lambda *a, **kw: fired.append(a),
    )
    assert fired == []
    assert silence_checker.silent_set() == set()


def test_tick_transition_into_silent_fires_warning_once():
    fired = []
    cards = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    # Wed Apr 29 14:00 ET ≈ 18:00 UTC — RTH, 5 trading days since Apr 22
    now = _utc(2026, 4, 29, 18)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS,
                        notify_fn=lambda sev, title, body: fired.append((sev, title, body)))
    assert silence_checker.is_silent("foo-v1") is True
    assert len(fired) == 1
    sev, title, body = fired[0]
    assert sev == Severity.WARNING
    assert title == "Card silent"
    assert "foo-v1" in body and "AAPL" in body and "daily" in body


def test_tick_silent_then_silent_no_repeat_notify():
    fired = []
    cards = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    now = _utc(2026, 4, 29, 18)
    notify_fn = lambda sev, title, body: fired.append((sev, title, body))
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    assert len(fired) == 1


def test_tick_card_fires_after_silence_clears_silently():
    fired = []
    cards_silent = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards_silent,
                        multipliers=MULTS, notify_fn=lambda *a: fired.append(a))
    assert silence_checker.is_silent("foo-v1") is True
    # Now card fires — last_fired_at moves forward
    cards_fresh = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 29, 17).isoformat())}
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards_fresh,
                        multipliers=MULTS, notify_fn=lambda *a: fired.append(a))
    assert silence_checker.is_silent("foo-v1") is False
    assert len(fired) == 1  # only the entry-into-silent, no exit notify


def test_tick_multiple_cards_independent_transitions():
    fired = []
    cards = {
        "a": _enabled_card("a", last_fired_iso=_utc(2026, 4, 22).isoformat()),
        "b": _enabled_card("b", last_fired_iso=_utc(2026, 4, 28).isoformat()),
        "c": _enabled_card("c", cadence="manual", last_fired_iso=_utc(2020, 1, 1).isoformat()),
    }
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards, multipliers=MULTS,
                        notify_fn=lambda sev, title, body: fired.append(body))
    assert silence_checker.is_silent("a") is True
    assert silence_checker.is_silent("b") is False
    assert silence_checker.is_silent("c") is False  # manual
    assert len(fired) == 1
    assert "a" in fired[0]


def test_silent_set_returns_copy_not_reference():
    silence_checker._silent_cards.add("a")
    s = silence_checker.silent_set()
    s.add("b")
    assert "b" not in silence_checker._silent_cards


# ---- T5: is_rth boundary tests ---------------------------------------------

def test_is_rth_weekday_noon_et_is_true():
    # Wed Apr 22 2026 12:00 ET = 16:00 UTC
    assert silence_checker.is_rth(_utc(2026, 4, 22, 16)) is True


def test_is_rth_weekday_pre_open_is_false():
    # Wed Apr 22 2026 09:00 ET = 13:00 UTC (before 9:30 open)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 13)) is False


def test_is_rth_weekday_post_close_is_false():
    # Wed Apr 22 2026 16:30 ET = 20:30 UTC (after 4pm close)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 20, 30)) is False


def test_is_rth_saturday_is_false():
    # Sat Apr 25 2026 noon ET — not a trading day
    assert silence_checker.is_rth(_utc(2026, 4, 25, 16)) is False


def test_is_rth_sunday_is_false():
    assert silence_checker.is_rth(_utc(2026, 4, 26, 16)) is False


def test_is_rth_holiday_is_false():
    # Good Friday Apr 3 2026 — NYSE closed even though it's Friday
    assert silence_checker.is_rth(_utc(2026, 4, 3, 16)) is False


def test_is_rth_at_market_open_boundary_is_true():
    # Exactly 9:30:00 ET = 13:30 UTC → True (open is inclusive)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 13, 30)) is True


def test_is_rth_at_market_close_boundary_is_false():
    # Exactly 16:00:00 ET = 20:00 UTC → False (close is exclusive)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 20, 0)) is False


import time


# ---- T6: thread lifecycle --------------------------------------------------

def test_start_creates_running_thread_then_stop_joins_cleanly():
    silence_checker.start()
    try:
        assert silence_checker._thread is not None
        assert silence_checker._thread.is_alive()
        assert silence_checker._thread.daemon is True
    finally:
        silence_checker.stop()
    assert silence_checker._thread is None


def test_start_is_idempotent():
    silence_checker.start()
    first = silence_checker._thread
    try:
        silence_checker.start()
        assert silence_checker._thread is first  # same thread, not replaced
    finally:
        silence_checker.stop()


def test_stop_when_not_running_is_safe():
    # No prior start; stop should not raise
    silence_checker.stop()
    assert silence_checker._thread is None
