"""Trading-day calendar — NYSE 2026 holidays + Sat/Sun handling."""
from datetime import date

from tradelab.live.trading_calendar import is_trading_day


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
