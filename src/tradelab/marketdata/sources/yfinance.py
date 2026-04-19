"""
yfinance source — fallback OHLCV provider.

No API key needed. Rate-limited by Yahoo's side; we just try and log failures.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def is_available() -> bool:
    try:
        import yfinance as _  # noqa: F401
        return True
    except ImportError:
        return False


def _timeframe_to_interval(timeframe: str) -> str:
    mapping = {
        "1D": "1d",
        "1H": "60m",
        "30min": "30m",
        "15min": "15m",
        "5min": "5m",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def download(symbol: str, start: str, end: str, timeframe: str = "1D") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=_timeframe_to_interval(timeframe),
                            auto_adjust=False, actions=False)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df = df.reset_index()
    df = df.rename(columns={"Datetime": "Date"})
    # For 1D bars, yfinance returns a "Date" column already
    if "Date" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "Date"})

    needed = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(set(df.columns)):
        return None

    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    df["Volume"] = df["Volume"].fillna(0).astype("int64")
    df = df.sort_values("Date").reset_index(drop=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]
