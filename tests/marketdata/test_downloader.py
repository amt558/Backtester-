"""Downloader unit tests — all network calls mocked, no real API hits."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from tradelab.marketdata import download_symbols


@pytest.fixture(autouse=True)
def _chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def _mock_ohlcv(n=50):
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Date": dates,
        "Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
        "Close": [100.5] * n, "Volume": [1000] * n,
    })


def test_downloader_uses_twelvedata_when_key_present(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")
    with patch("tradelab.marketdata.downloader.td.download", return_value=_mock_ohlcv()) as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download") as yf_mock:
        out = download_symbols(["AAPL"], start="2024-01-01", end="2024-03-01")
    assert "AAPL" in out
    assert td_mock.called
    assert not yf_mock.called


def test_downloader_raises_without_key_by_default(monkeypatch):
    from tradelab.marketdata import MissingTwelveDataKey
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    # .env loader may have set it from a project-level .env; clear again AFTER
    # any module-level load by forcing reload
    from tradelab import env as env_mod
    env_mod._LOADED = True   # prevent auto-load
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    with pytest.raises(MissingTwelveDataKey):
        download_symbols(["AAPL"], start="2024-01-01", end="2024-03-01")


def test_downloader_falls_back_to_yfinance_when_explicitly_allowed(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    from tradelab import env as env_mod
    env_mod._LOADED = True
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    with patch("tradelab.marketdata.downloader.td.download") as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download", return_value=_mock_ohlcv()) as yf_mock:
        out = download_symbols(
            ["AAPL"], start="2024-01-01", end="2024-03-01",
            allow_yfinance_fallback=True,
        )
    assert "AAPL" in out
    assert not td_mock.called
    assert yf_mock.called


def test_downloader_falls_back_when_twelvedata_fails_and_fallback_allowed(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")
    with patch("tradelab.marketdata.downloader.td.download", return_value=None) as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download", return_value=_mock_ohlcv()) as yf_mock:
        out = download_symbols(
            ["AAPL"], start="2024-01-01", end="2024-03-01",
            allow_yfinance_fallback=True,
        )
    assert "AAPL" in out
    assert td_mock.called
    assert yf_mock.called


def test_downloader_does_not_fall_back_when_fallback_forbidden(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")
    with patch("tradelab.marketdata.downloader.td.download", return_value=None) as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download", return_value=_mock_ohlcv()) as yf_mock:
        out = download_symbols(
            ["AAPL"], start="2024-01-01", end="2024-03-01",
            allow_yfinance_fallback=False,
        )
    # Symbol not retrieved — TD failed, yf not allowed
    assert "AAPL" not in out
    assert td_mock.called
    assert not yf_mock.called


def test_downloader_skips_cached_symbols(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")
    # Put today's bar in cache so staleness check passes
    from tradelab.marketdata import cache
    today = pd.Timestamp.now().normalize()
    fresh = pd.DataFrame({
        "Date": [today], "Open": [100.0], "High": [101.0],
        "Low": [99.0], "Close": [100.5], "Volume": [1000],
    })
    cache.write("AAPL", fresh, source="test")

    with patch("tradelab.marketdata.downloader.td.download") as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download") as yf_mock:
        out = download_symbols(["AAPL"], start="2020-01-01", end=today.strftime("%Y-%m-%d"))
    assert "AAPL" in out
    # Neither download source called — cache hit
    assert not td_mock.called
    assert not yf_mock.called


def test_downloader_force_bypasses_cache(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")
    from tradelab.marketdata import cache
    today = pd.Timestamp.now().normalize()
    fresh = pd.DataFrame({
        "Date": [today], "Open": [100.0], "High": [101.0],
        "Low": [99.0], "Close": [100.5], "Volume": [1000],
    })
    cache.write("AAPL", fresh, source="test")

    with patch("tradelab.marketdata.downloader.td.download", return_value=_mock_ohlcv()) as td_mock, \
         patch("tradelab.marketdata.downloader.yf_src.download") as yf_mock:
        download_symbols(["AAPL"], start="2024-01-01", end="2024-03-01", force=True)
    assert td_mock.called


def test_downloader_continues_on_per_symbol_failure(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_key")

    def td_side_effect(sym, *args, **kwargs):
        return _mock_ohlcv() if sym == "AAPL" else None

    with patch("tradelab.marketdata.downloader.td.download", side_effect=td_side_effect), \
         patch("tradelab.marketdata.downloader.yf_src.download", return_value=None):
        out = download_symbols(["AAPL", "BADSYM"], start="2024-01-01", end="2024-03-01")
    assert "AAPL" in out
    assert "BADSYM" not in out
