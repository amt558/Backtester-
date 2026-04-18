"""
S2 Pocket Pivot strategy.

Port of the entry logic from C:/TradingScripts/s2_backtest.py entry_check().
Signals are per-bar flags; the engine handles position tracking and exits.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .base import Strategy


class S2PocketPivot(Strategy):
    """Pocket Pivot with trend alignment + RS filter + dynamic ATR trailing stop."""

    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        "atr_pct_max": 8.0,
        "rs_threshold": 0.0,
        "ema10_proximity": 0.97,
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 1.5,
        "trail_tighten_atr": 1.0,
        "hold_bars_max": 20,
    }

    tunable_params = {
        "atr_pct_max": (5.0, 12.0),
        "rs_threshold": (-2.0, 5.0),
        "ema10_proximity": (0.93, 1.0),
        "stop_atr_mult": (0.8, 2.5),
        "trail_tight_mult": (0.5, 1.5),
        "trail_wide_mult": (1.0, 2.5),
        "trail_tighten_atr": (0.5, 2.0),
    }

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Compute per-bar entry signals for each symbol.

        Adds three columns to each DataFrame:
          - buy_signal   (bool)   True on bars where all entry gates pass
          - entry_stop   (float)  Close - stop_atr_mult * ATR (initial stop)
          - entry_score  (float)  RS_21d + Vol_Ratio (for ranking when slots are tight)
        """
        p = self.params
        out: dict[str, pd.DataFrame] = {}

        for sym, df in data.items():
            df = df.copy()

            # Fresh Pocket Pivot: today True, previous bar False
            pp = df["Pocket_Pivot"].fillna(False).astype(bool)
            pp_prev = pp.shift(1).fillna(False).astype(bool)
            fresh_pp = pp & (~pp_prev)

            # Universal gates
            gate_atr = df["ATR_pct"] <= p["atr_pct_max"]
            gate_trend = df["Trend_OK"].fillna(False).astype(bool)
            gate_above50 = df["Above50"].fillna(False).astype(bool)
            gate_rs = df["RS_21d"].fillna(-np.inf) >= p["rs_threshold"]
            gate_proximity = df["Close"] > df["EMA10"] * p["ema10_proximity"]

            # Guard against rows with missing ATR (insufficient warmup)
            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)

            df["buy_signal"] = (
                fresh_pp
                & gate_atr
                & gate_trend
                & gate_above50
                & gate_rs
                & gate_proximity
                & atr_valid
            )

            df["entry_stop"] = df["Close"] - p["stop_atr_mult"] * df["ATR"]
            df["entry_score"] = df["RS_21d"].fillna(0.0) + df["Vol_Ratio"].fillna(0.0)

            out[sym] = df

        return out
