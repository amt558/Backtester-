"""
Point-In-Time (PIT) inception-date assertions.

Guards against the most common look-ahead failure in multi-symbol backtests:
requesting a start date that predates a symbol's actual inception. yfinance
and Twelve Data silently return empty or truncated data in this case, which
means the backtest either uses a smaller universe than requested (tilts
metrics) or the first bars of the PIT-violating symbol are synthetic
misrepresentations of a period in which the symbol did not yet trade.

tradelab's rule: if a symbol's earliest available bar is strictly AFTER the
requested start date, the backtest is invalid until either (a) the start
date is moved forward or (b) the symbol is removed from the universe.
"""
from __future__ import annotations

import pandas as pd


class PITViolation(Exception):
    """Raised when a symbol's data begins after the requested window start."""


def check_pit(
    data: dict[str, pd.DataFrame],
    start: str,
    grace_days: int = 5,
) -> dict[str, pd.Timestamp]:
    """
    Return a dict of {symbol: earliest_bar_date} for every symbol whose first
    bar is later than `start + grace_days`. An empty dict means all symbols
    had data available at or near the requested start.

    `grace_days` absorbs weekend/holiday misalignments (requesting 2022-01-01
    is fine if the first bar is 2022-01-03, a Monday).
    """
    start_ts = pd.Timestamp(start).normalize()
    threshold = start_ts + pd.Timedelta(days=grace_days)
    violations: dict[str, pd.Timestamp] = {}

    for symbol, df in data.items():
        if df is None or df.empty or "Date" not in df.columns:
            continue
        earliest = pd.Timestamp(df["Date"].min()).normalize()
        if earliest > threshold:
            violations[symbol] = earliest

    return violations


def assert_pit_valid(
    data: dict[str, pd.DataFrame],
    start: str,
    grace_days: int = 5,
) -> None:
    """
    Raise PITViolation if any symbol's data starts after the requested window.
    The exception message names the offending symbol(s) and their actual
    inception dates so the user can fix the universe or window immediately.
    """
    violations = check_pit(data, start, grace_days=grace_days)
    if not violations:
        return

    lines = [
        f"PIT violation: {len(violations)} symbol(s) have data starting after {start}:",
    ]
    for sym, earliest in sorted(violations.items()):
        lines.append(f"  - {sym}: first bar {earliest.date()}")
    lines.append(
        "Either move --start forward past the latest inception, or drop "
        "these symbols from the universe. Running with missing early data "
        "silently tilts metrics."
    )
    raise PITViolation("\n".join(lines))
