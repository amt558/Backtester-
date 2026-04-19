"""Cache unit tests — filesystem only, no network."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tradelab.marketdata import cache


@pytest.fixture(autouse=True)
def _chdir_tmp(tmp_path, monkeypatch):
    """Each test gets its own cache directory by chdir-ing into a tmp_path."""
    monkeypatch.chdir(tmp_path)
    yield


def _sample_df(last_date="2024-01-10"):
    dates = pd.date_range("2024-01-01", last_date, freq="B")
    n = len(dates)
    return pd.DataFrame({
        "Date": dates,
        "Open": [100.0] * n,
        "High": [101.0] * n,
        "Low": [99.0] * n,
        "Close": [100.5] * n,
        "Volume": [1000] * n,
    })


def test_cache_write_and_read():
    df = _sample_df()
    cache.write("AAPL", df, source="test")
    back = cache.read("AAPL")
    assert back is not None
    assert len(back) == len(df)
    assert list(back.columns) == list(df.columns)


def test_cache_manifest_updates():
    cache.write("AAPL", _sample_df(), source="test")
    status = cache.cache_status("AAPL")
    assert status["AAPL"] is not None
    assert status["AAPL"]["source"] == "test"
    assert status["AAPL"]["rows"] > 0


def test_cache_missing_returns_none():
    assert cache.read("NONEXISTENT") is None


def test_cache_stale_when_missing():
    assert cache.is_stale("NEVERSEEN") is True


def test_cache_not_stale_when_fresh():
    # Build a df whose last bar is today — cannot be stale
    today = pd.Timestamp.now().normalize()
    df = pd.DataFrame({
        "Date": [today],
        "Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1000],
    })
    cache.write("AAPL", df, source="test")
    # Staleness check: last bar must be >= previous business day
    # For a df with today's date it will be >= any reasonable last-close
    assert cache.is_stale("AAPL") is False


def test_clear_cache_symbol():
    cache.write("AAPL", _sample_df(), source="test")
    cache.write("MSFT", _sample_df(), source="test")
    removed = cache.clear_cache("AAPL")
    assert removed == 1
    assert cache.read("AAPL") is None
    assert cache.read("MSFT") is not None


def test_clear_cache_all():
    cache.write("AAPL", _sample_df(), source="test")
    cache.write("MSFT", _sample_df(), source="test")
    removed = cache.clear_cache()
    assert removed >= 2
    assert cache.read("AAPL") is None
    assert cache.read("MSFT") is None
