"""Trading-day calendar — NYSE 2026 holidays + Sat/Sun handling."""
from datetime import date, datetime, timezone

from tradelab.live.trading_calendar import count_trading_days_between, is_trading_day


def test_is_trading_day_weekday_in_2026():
    assert is_trading_day(date(2026, 4, 22)) is True   # Wednesday


def test_is_trading_day_saturday_returns_false():
    assert is_trading_day(date(2026, 4, 25)) is False


def test_is_trading_day_sunday_returns_false():
    assert is_trading_day(date(2026, 4, 26)) is False


def test_is_trading_day_new_year_2026_holiday():
    assert is_trading_day(date(2026, 1, 1)) is False


def test_is_trading_day_good_friday_2026():
    assert is_trading_day(date(2026, 4, 3)) is False   # Good Friday


def test_is_trading_day_independence_observed_2026():
    # Jul 4 2026 = Saturday → NYSE observes Friday Jul 3
    assert is_trading_day(date(2026, 7, 3)) is False


def _utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_count_trading_days_same_day_zero():
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 22, 23)) == 0


def test_count_trading_days_wed_to_thu_one():
    # Wed Apr 22 → Thu Apr 23 = 1 trading day elapsed
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 23)) == 1


def test_count_trading_days_fri_to_mon_skips_weekend():
    # Fri Apr 24 → Mon Apr 27 = 1 trading day (Mon)
    assert count_trading_days_between(_utc(2026, 4, 24), _utc(2026, 4, 27)) == 1


def test_count_trading_days_full_week_five():
    # Wed Apr 22 → Wed Apr 29 = Thu, Fri, Mon, Tue, Wed = 5
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 29)) == 5


def test_count_trading_days_skips_holiday():
    # Thu Apr 2 → Mon Apr 6: Apr 3 = Good Friday holiday → only Apr 6 counts = 1
    assert count_trading_days_between(_utc(2026, 4, 2), _utc(2026, 4, 6)) == 1


def test_count_trading_days_negative_returns_zero():
    # Defensive: end < start should not crash
    assert count_trading_days_between(_utc(2026, 4, 29), _utc(2026, 4, 22)) == 0
