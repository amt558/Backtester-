"""
Canary 4: SURVIVOR-CANARY — survivorship bias via curated universe.

LOSO must flag the per-symbol PF spread on the curated 5-symbol universe.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..strategies.base import Strategy
from ._indicators import atr, ema, sma


CURATED_UNIVERSE: list[str] = ["NVDA", "MSFT", "AVGO", "AMD", "LLY"]


class SurvivorCanary(Strategy):
    name = "survivor_canary"
    timeframe = "1D"
    requires_benchmark = False

    CURATED_UNIVERSE = CURATED_UNIVERSE

    default_params = {
        "fast_n": 50.0,
        "slow_n": 200.0,
        "stop_atr_mult": 2.0,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 3.0,
        "trail_tighten_atr": 2.0,
    }
    tunable_params: dict = {}

    def generate_signals(self, data, spy_close=None):
        p = self.params
        fast_n = max(2, int(round(float(p["fast_n"]))))
        slow_n = max(fast_n + 1, int(round(float(p["slow_n"]))))
        out = {}
        for sym, df in data.items():
            df = df.copy()
            df["ATR"] = atr(df)
            df["SMA50"] = sma(df["Close"], 50)
            df["EMA_fast"] = ema(df["Close"], fast_n)
            df["EMA_slow"] = ema(df["Close"], slow_n)
            above = df["EMA_fast"] > df["EMA_slow"]
            above_prev = above.shift(1).fillna(False)
            cross_up = above & (~above_prev)
            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)
            df["buy_signal"] = cross_up & atr_valid
            df["entry_stop"] = df["Close"] - float(p["stop_atr_mult"]) * df["ATR"]
            df["entry_score"] = 1.0
            out[sym] = df
        return out
