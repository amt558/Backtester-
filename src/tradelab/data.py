"""
DEPRECATED — CSV loader. DO NOT USE in new code.

The active tradelab workflow reads from the Twelve Data parquet cache via
``tradelab.marketdata.download_symbols``. This CSV-based module is kept only
for backwards compatibility with external helper scripts and tests. All
active CLI paths (run / backtest / optimize / compare / gate-check) have
been migrated off this module.

If you're writing new code, import from ``tradelab.marketdata`` instead.
Setting ``paths.data_dir`` in the yaml is optional and has no effect on
the active workflow.

Loads 1-min OHLCV CSVs from the configured data dir. Handles multiple CSV
formats, including mislabeled columns where Date_YMD contains ISO dates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import get_config


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _parse_format_a(df: pd.DataFrame) -> pd.DataFrame:
    """Handle Date_YMD + Time columns. Values may be numeric YYYYMMDD or ISO YYYY-MM-DD."""
    date_sample = str(df["Date_YMD"].dropna().iloc[0])

    if "-" in date_sample:
        # Column is mislabeled — actually ISO format like "2025-04-04"
        time_str = df["Time"].astype(str)
        df["datetime"] = pd.to_datetime(
            df["Date_YMD"].astype(str) + " " + time_str,
            format="mixed",
            errors="coerce",
        )
    else:
        # True YYYYMMDD + HHMMSS
        date_str = df["Date_YMD"].astype(str)
        time_str = df["Time"].astype(str).str.zfill(6)
        df["datetime"] = pd.to_datetime(
            date_str + time_str,
            format="%Y%m%d%H%M%S",
            errors="coerce",
        )

    df = df.dropna(subset=["datetime"]).set_index("datetime")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _load_raw_1min(path: Path) -> pd.DataFrame:
    """
    Format-aware 1-min CSV loader. Handles three formats:
      A: Ticker,Date_YMD,Time,...  (either YYYYMMDD+HHMMSS or ISO values)
      B: datetime,open,high,...    (Twelve Data native)
      C: Ticker,Date,Time,...      (ISO YYYY-MM-DD + HH:MM)
    """
    df = pd.read_csv(path, low_memory=False)
    cols_lower = {c.lower() for c in df.columns}

    if "date_ymd" in cols_lower and "time" in cols_lower:
        return _parse_format_a(df).sort_index()

    if "datetime" in cols_lower:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime")
        rename_map = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()

    if "date" in cols_lower and "time" in cols_lower:
        combined = df["Date"].astype(str) + " " + df["Time"].astype(str)
        df["datetime"] = pd.to_datetime(combined, format="mixed", errors="coerce")
        df = df.dropna(subset=["datetime"]).set_index("datetime")
        return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()

    raise ValueError(f"Unrecognized CSV format at {path.name}. Columns: {list(df.columns)}")


def load_daily_with_indicators(symbol: str, spy_close: Optional[pd.Series] = None) -> pd.DataFrame:
    """Load a symbol's 1-min CSV, resample to daily, compute all S2 indicators."""
    data_dir = get_config().data_path()
    path = data_dir / f"{symbol}_1min.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV for {symbol}: {path}")

    raw = _load_raw_1min(path)

    agg_rules = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    df = raw.resample("1D").agg(agg_rules).dropna()
    df = df.reset_index().rename(columns={"datetime": "Date"})

    df["RSI"] = calc_rsi(df["Close"], 14)
    df["ATR"] = calc_atr(df["High"], df["Low"], df["Close"], 14)
    df["ATR_pct"] = df["ATR"] / df["Close"] * 100

    df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["SMA10"] = df["Close"].rolling(10).mean()
    df["SMA21"] = df["Close"].rolling(21).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    df["Vol_MA20"] = df["Volume"].rolling(20).mean()
    df["Vol_Ratio"] = df["Volume"] / df["Vol_MA20"].replace(0, np.nan)
    df["Vol_OK"] = df["Volume"] > df["Vol_MA20"]

    df["Trend_OK"] = (df["SMA10"] > df["SMA21"]) & (df["SMA21"] > df["SMA50"])
    df["Above50"] = df["Close"] > df["SMA50"]
    df["Above200"] = df["Close"] > df["SMA200"]

    down_vol = df["Volume"].where(df["Close"] < df["Close"].shift(1), 0)
    df["Max_Down_Vol_10"] = down_vol.rolling(10).max()
    df["Pocket_Pivot"] = (
        (df["Close"] > df["Close"].shift(1))
        & (df["Volume"] > df["Max_Down_Vol_10"])
        & (df["Close"] > df["EMA21"])
    )

    if spy_close is not None and symbol != "SPY":
        spy_al = spy_close.reindex(df["Date"]).ffill()
        stock_ret = df.set_index("Date")["Close"].pct_change(21)
        spy_ret = spy_al.pct_change(21)
        df["RS_21d"] = (stock_ret.values - spy_ret.values) * 100
    else:
        df["RS_21d"] = 0.0

    return df


def load_universe(symbols: list[str], benchmark: Optional[str] = None) -> dict[str, pd.DataFrame]:
    """Load multiple symbols at once, with benchmark loaded first for RS computation."""
    ticker_data: dict[str, pd.DataFrame] = {}
    spy_close: Optional[pd.Series] = None

    if benchmark:
        bench_df = load_daily_with_indicators(benchmark, spy_close=None)
        ticker_data[benchmark] = bench_df
        spy_close = bench_df.set_index("Date")["Close"]

    for sym in symbols:
        if sym == benchmark:
            continue
        try:
            ticker_data[sym] = load_daily_with_indicators(sym, spy_close=spy_close)
        except Exception as e:
            print(f"  [warn] skipping {sym}: {type(e).__name__}: {e}")

    return ticker_data


def list_available_symbols() -> list[str]:
    """Scan the configured data_dir and return all symbols with _1min.csv files."""
    data_dir = get_config().data_path()
    return sorted(p.stem.replace("_1min", "") for p in data_dir.glob("*_1min.csv"))