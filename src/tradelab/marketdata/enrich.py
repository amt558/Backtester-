"""
Enrich raw OHLCV DataFrames with the indicators that strategies expect.

This is the bridge between ``marketdata.download_symbols`` (which returns
raw OHLCV: Date/Open/High/Low/Close/Volume) and strategies like
S2PocketPivot (which require pre-computed Pocket_Pivot/Trend_OK/RS_21d/
EMA10/ATR_pct/...).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def enrich_with_indicators(
    df: pd.DataFrame, spy_close: Optional[pd.Series] = None, symbol: Optional[str] = None
) -> pd.DataFrame:
    """
    Add the full indicator set to a raw OHLCV DataFrame.

    Args:
        df: DataFrame with columns Date, Open, High, Low, Close, Volume
        spy_close: SPY close Series indexed by date, for RS_21d computation.
                   If None (or symbol == 'SPY'), RS_21d is filled with 0.0.
        symbol: symbol name — used to short-circuit RS_21d when this IS SPY.

    Returns:
        DataFrame with original columns plus the S2/canary indicator set.
    """
    df = df.copy()

    df["RSI"] = _rsi(df["Close"], 14)
    df["ATR"] = _atr(df["High"], df["Low"], df["Close"], 14)
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


def enrich_universe(
    data: dict[str, pd.DataFrame], benchmark: str = "SPY"
) -> dict[str, pd.DataFrame]:
    """
    Enrich a whole universe. Processes benchmark first (so its Close series is
    available for RS computation on the other symbols).
    """
    out: dict[str, pd.DataFrame] = {}
    spy_close: Optional[pd.Series] = None

    if benchmark in data:
        bench_df = enrich_with_indicators(data[benchmark], spy_close=None, symbol=benchmark)
        out[benchmark] = bench_df
        spy_close = bench_df.set_index("Date")["Close"]

    for sym, df in data.items():
        if sym == benchmark:
            continue
        out[sym] = enrich_with_indicators(df, spy_close=spy_close, symbol=sym)

    return out
