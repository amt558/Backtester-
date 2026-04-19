"""
Canary 3: LEAK-CANARY — deliberate forward look-ahead bias.

Signal at T peeks at Close[T+lookahead]. Entry-delay test must collapse this.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..strategies.base import Strategy
from ._indicators import atr, sma


class LeakCanary(Strategy):
    name = "leak_canary"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "lookahead_bars": 1.0,
        "up_threshold": 0.01,
        "stop_atr_mult": 2.0,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }
    tunable_params: dict = {}

    def generate_signals(self, data, spy_close=None):
        p = self.params
        lookahead = max(1, int(round(float(p["lookahead_bars"]))))
        threshold = float(p["up_threshold"])
        out = {}
        for sym, df in data.items():
            df = df.copy()
            df["ATR"] = atr(df)
            df["SMA50"] = sma(df["Close"], 50)

            future_close = df["Close"].shift(-lookahead)
            leak_signal = (future_close > df["Close"] * (1.0 + threshold)).fillna(False)

            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)
            df["buy_signal"] = leak_signal & atr_valid

            if lookahead > 0 and len(df) >= lookahead:
                tail_idx = df.index[-lookahead:]
                df.loc[tail_idx, "buy_signal"] = False

            df["entry_stop"] = df["Close"] - float(p["stop_atr_mult"]) * df["ATR"]
            df["entry_score"] = 1.0
            out[sym] = df
        return out
