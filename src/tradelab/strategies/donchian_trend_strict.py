"""
Donchian trend-breakout — long-only, STRICT regime gate (Trend_OK AND Above200).

One concrete strategy per file (house convention + the Import-modal names a
strategy after its file stem). The strict gate keeps the strategy flat in bear
regimes (the long-only substitute for shorting), so the adverse-regime bucket
stays healthy or falls below the min-trades floor — protecting `regime_spread`.
Score against donchian_trend_loose to see the filter move the verdict.

DESIGN CHOICE -> GATE SIGNAL  (handbook §2 / §10)
  prior-bar Donchian high (shift 1)  -> entry_delay / no-lookahead / noise
  single coarse breakout length      -> param_landscape smoothness, WFE
  strict gate (Trend_OK & Above200)  -> regime_spread (long-only lever)
  ATR initial + engine trailing stop -> MC max-drawdown percentile
  RS + volume entry_score            -> trade quality when slots are tight
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .base import Strategy


class DonchianTrendStrict(Strategy):
    """Long-only Donchian breakout with a strict regime gate (Trend_OK & Above200)."""

    name = "donchian_trend_strict"
    timeframe = "1D"
    requires_benchmark = True  # uses RS_21d for entry_score ranking

    default_params = {
        "breakout_len": 55,
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }
    tunable_params = {
        "breakout_len": (40, 80),
        "stop_atr_mult": (1.0, 2.5),
    }
    ablatable_gates: dict[str, dict] = {}

    def _trend_filter(self, df: pd.DataFrame) -> pd.Series:
        trend = df["Trend_OK"].fillna(False).astype(bool)
        above200 = df["Above200"].fillna(False).astype(bool)
        return trend & above200

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        p = self.params
        n_break = int(p.get("breakout_len", 55))
        stop_mult = float(p.get("stop_atr_mult", 1.5))
        out: dict[str, pd.DataFrame] = {}

        for sym, df in data.items():
            df = df.copy()

            # Prior-bar Donchian high (exclude current bar -> entry_delay safe).
            prior_high = df["High"].rolling(n_break, min_periods=n_break).max().shift(1)
            breakout = df["Close"] > prior_high
            trend_ok = self._trend_filter(df).fillna(False).astype(bool)

            atr_valid = df["ATR"].notna() & (df["ATR"] > 0)
            break_valid = prior_high.notna()

            df["buy_signal"] = (
                breakout.fillna(False).astype(bool)
                & trend_ok
                & atr_valid
                & break_valid
            )
            df["entry_stop"] = df["Close"] - stop_mult * df["ATR"]
            df["entry_score"] = (
                df.get("RS_21d", pd.Series(0.0, index=df.index)).fillna(0.0)
                + df.get("Vol_Ratio", pd.Series(0.0, index=df.index)).fillna(0.0)
            )
            out[sym] = df

        return out
