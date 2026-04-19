"""PIT inception-date validator tests."""
from __future__ import annotations

import pandas as pd
import pytest

from tradelab.marketdata import PITViolation, assert_pit_valid, check_pit


def _df(first_date: str, n: int = 20) -> pd.DataFrame:
    dates = pd.date_range(first_date, periods=n, freq="B")
    return pd.DataFrame({
        "Date": dates,
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000,
    })


def test_check_pit_empty_when_all_pre_inception():
    data = {"AAPL": _df("2020-01-06"), "MSFT": _df("2020-01-06")}
    assert check_pit(data, start="2020-01-15") == {}


def test_check_pit_flags_late_symbol():
    # AAPL starts before window; NEWSTOCK starts well after
    data = {"AAPL": _df("2020-01-06"), "NEWSTOCK": _df("2023-06-15")}
    violations = check_pit(data, start="2022-01-01")
    assert "NEWSTOCK" in violations
    assert "AAPL" not in violations


def test_check_pit_grace_absorbs_weekend():
    # Requested 2022-01-01 (Saturday); earliest bar 2022-01-03 (Monday) → OK
    data = {"AAPL": _df("2022-01-03")}
    assert check_pit(data, start="2022-01-01") == {}


def test_assert_pit_valid_raises_on_violation():
    data = {"NEWSTOCK": _df("2023-06-15")}
    with pytest.raises(PITViolation) as exc_info:
        assert_pit_valid(data, start="2022-01-01")
    msg = str(exc_info.value)
    assert "NEWSTOCK" in msg
    assert "2023-06-15" in msg


def test_assert_pit_valid_silent_when_clean():
    data = {"AAPL": _df("2021-12-20")}
    assert_pit_valid(data, start="2022-01-01")   # does not raise


def test_check_pit_ignores_empty_frames():
    data = {"AAPL": _df("2020-01-06"), "EMPTY": pd.DataFrame()}
    # Empty frame doesn't trigger violation (downloader already dropped it)
    assert check_pit(data, start="2020-01-15") == {}


def test_assert_pit_valid_names_all_offenders():
    data = {
        "OLD": _df("2020-01-06"),
        "NEWA": _df("2023-01-10"),
        "NEWB": _df("2024-05-01"),
    }
    with pytest.raises(PITViolation) as exc_info:
        assert_pit_valid(data, start="2022-01-01")
    msg = str(exc_info.value)
    assert "NEWA" in msg and "NEWB" in msg
    assert "OLD" not in msg
