"""The dial-gauge synthetic strategy — locked baseline for engine drift detection."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..strategies.base import Strategy


def build_dial_gauge_universe(start="2022-01-03", n_bars=500, symbol="DIAL"):
    t = np.arange(n_bars, dtype=float)
    close = 100.0 * (1.001 ** t) + 2.0 * np.sin(2.0 * np.pi * t / 5.0)
    dates = pd.date_range(start=start, periods=n_bars, freq="B")
    df = pd.DataFrame({
        "Date": dates, "Open": close,
        "High": close + 0.25, "Low": close - 0.25,
        "Close": close, "Volume": np.full(n_bars, 1_000_000, dtype=np.int64),
    })
    return {symbol: df}


class DialGauge(Strategy):
    name = "dial_gauge"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "stop_atr_mult": 2.0,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }
    tunable_params: dict = {}

    def generate_signals(self, data, spy_close=None):
        p = self.params
        out = {}
        for sym, df in data.items():
            df = df.copy()
            prev_close = df["Close"].shift(1)
            tr = pd.concat([
                df["High"] - df["Low"],
                (df["High"] - prev_close).abs(),
                (df["Low"]  - prev_close).abs(),
            ], axis=1).max(axis=1)
            df["ATR"] = tr.ewm(alpha=1.0/14, adjust=False).mean()
            df["SMA50"] = df["Close"].rolling(50).mean()
            up = df["Close"] > df["Close"].shift(1)
            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)
            df["buy_signal"] = up.fillna(False) & atr_valid
            df["entry_stop"] = df["Close"] - float(p["stop_atr_mult"]) * df["ATR"]
            df["entry_score"] = 1.0
            out[sym] = df
        return out
