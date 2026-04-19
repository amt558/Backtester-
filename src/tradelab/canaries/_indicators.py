"""
Indicator helpers shared across canary strategies.

Simple and dependency-free. Canaries are self-contained: input is raw
OHLCV, output is a DataFrame with the columns the backtest engine requires.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_down = down.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_up / avg_down.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def stable_seed(seed: int, token: str) -> int:
    digest = hashlib.sha256(f"{seed}:{token}".encode("utf-8")).hexdigest()
    return int(digest, 16) % (2**32)
