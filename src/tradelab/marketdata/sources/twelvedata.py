"""
Twelve Data source — primary OHLCV provider.

Requires TWELVEDATA_API_KEY env var. If unset, caller falls back to yfinance.
Respects 144 req/min rate limit with a simple time-based throttle.
Handles HTTP 429 with exponential backoff.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import pandas as pd
import requests


BASE_URL = "https://api.twelvedata.com/time_series"
_LAST_REQUEST_TIME: float = 0.0
_MIN_INTERVAL = 60.0 / 144.0   # 144 req/min → ~0.42s between requests


def is_available() -> bool:
    return bool(os.environ.get("TWELVEDATA_API_KEY"))


def _throttle() -> None:
    global _LAST_REQUEST_TIME
    elapsed = time.time() - _LAST_REQUEST_TIME
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_REQUEST_TIME = time.time()


def _timeframe_to_interval(timeframe: str) -> str:
    mapping = {
        "1D": "1day",
        "1H": "1h",
        "30min": "30min",
        "15min": "15min",
        "5min": "5min",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def download(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1D",
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """
    Download one symbol from Twelve Data. Returns a DataFrame or None on failure.
    Normalizes columns to Date/Open/High/Low/Close/Volume.
    """
    api_key = os.environ.get("TWELVEDATA_API_KEY")
    if not api_key:
        return None

    params = {
        "symbol": symbol,
        "interval": _timeframe_to_interval(timeframe),
        "start_date": start,
        "end_date": end,
        "apikey": api_key,
        "format": "JSON",
        "outputsize": 5000,
    }

    for attempt in range(max_retries):
        _throttle()
        try:
            r = requests.get(BASE_URL, params=params, timeout=20)
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            return None

        payload = r.json()
        if payload.get("status") == "error":
            return None

        values = payload.get("values")
        if not values:
            return None

        df = pd.DataFrame(values)
        df = df.rename(columns={
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        })
        df["Date"] = pd.to_datetime(df["Date"])
        for col in ("Open", "High", "Low", "Close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64")
        df = df.sort_values("Date").reset_index(drop=True)
        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    return None
