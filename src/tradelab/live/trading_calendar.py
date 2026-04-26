"""Trading-day calendar — NYSE 2026 holidays hardcoded.

For Slice 5 silence detection (intraday/daily cadence). Weekly uses calendar
days, doesn't touch this module. Spec §8.2 says "use pandas_market_calendars
if already a tradelab dep, else hardcode US holidays" — pmc is not a dep.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

NYSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day observed (Jul 4 2026 = Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
})


def is_trading_day(d: date) -> bool:
    """True for Mon-Fri excluding NYSE holidays."""
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return d not in NYSE_HOLIDAYS_2026
