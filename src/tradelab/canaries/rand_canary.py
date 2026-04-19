"""
Canary 1: RAND-CANARY — random entry, no edge.

tradelab must detect absence of edge. If this canary ever produces a
ROBUST verdict, the tool is broken.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..strategies.base import Strategy
from ._indicators import atr, sma, stable_seed


class RandCanary(Strategy):
    name = "rand_canary"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "entry_probability": 0.02,
        "seed": 42,
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
            df["ATR"] = atr(df)
            df["SMA50"] = sma(df["Close"], 50)
            rng = np.random.default_rng(stable_seed(int(p["seed"]), sym))
            raw = rng.random(len(df)) < float(p["entry_probability"])
            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)
            df["buy_signal"] = pd.Series(raw, index=df.index) & atr_valid
            df["entry_stop"] = df["Close"] - float(p["stop_atr_mult"]) * df["ATR"]
            df["entry_score"] = 1.0
            out[sym] = df
        return out
