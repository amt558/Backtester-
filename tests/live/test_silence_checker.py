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
