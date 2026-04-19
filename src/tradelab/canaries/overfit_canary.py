"""
Canary 2: OVERFIT-CANARY — 6-parameter pathological strategy.

DSR + WF must catch the IS/OOS decay after Optuna runs many trials on this.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..strategies.base import Strategy
from ._indicators import atr, ema, rsi, sma


class OverfitCanary(Strategy):
    name = "overfit_canary"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "rsi_threshold": 50.0,
        "vol_mult": 1.0,
        "vol_ma_n": 20.0,
        "ema_n": 20.0,
        "atr_low": 0.5,
        "atr_high": 5.0,
        "stop_atr_mult": 2.0,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        "rsi_threshold": (20.0, 80.0),
        "vol_mult":      (0.5, 3.0),
        "vol_ma_n":      (5.0, 50.0),
        "ema_n":         (5.0, 50.0),
        "atr_low":       (0.1, 2.0),
        "atr_high":      (2.0, 10.0),
    }

    def generate_signals(self, data, spy_close=None):
        p = self.params
        vol_ma_n = max(2, int(round(float(p["vol_ma_n"]))))
        ema_n = max(2, int(round(float(p["ema_n"]))))
        out = {}
        for sym, df in data.items():
            df = df.copy()
            df["ATR"] = atr(df)
            df["ATR_pct"] = (df["ATR"] / df["Close"]) * 100.0
            df["SMA50"] = sma(df["Close"], 50)
            df["RSI"] = rsi(df["Close"])
            df["Vol_MA"] = sma(df["Volume"], vol_ma_n)
            df["EMA_filter"] = ema(df["Close"], ema_n)

            g_rsi = df["RSI"] < float(p["rsi_threshold"])
            g_vol = df["Volume"] > float(p["vol_mult"]) * df["Vol_MA"]
            g_ema = df["Close"] > df["EMA_filter"]
            g_atr = (df["ATR_pct"] >= float(p["atr_low"])) & (df["ATR_pct"] <= float(p["atr_high"]))
            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)

            df["buy_signal"] = (
                g_rsi.fillna(False) & g_vol.fillna(False) &
                g_ema.fillna(False) & g_atr.fillna(False) & atr_valid
            )
            df["entry_stop"] = df["Close"] - float(p["stop_atr_mult"]) * df["ATR"]
            df["entry_score"] = df["RSI"].fillna(50.0)
            out[sym] = df
        return out
