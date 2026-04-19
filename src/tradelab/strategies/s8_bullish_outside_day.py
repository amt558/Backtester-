"""
S8 Bullish Outside Day — port of /c/TradingScripts/FINAL STRATEGYIE/s8_bullish_outside_day.py

Bullish engulfing candle in uptrend with volume confirmation.

Entry on bar T iff:
  - Universal gates: ATR_pct ≤ atr_pct_max, Trend_OK, Above50, RS_21d ≥ rs_threshold
  - Bullish outside day: High[T] > High[T-1] AND Low[T] < Low[T-1] AND Close[T] > Open[T]
    (today's range engulfs yesterday's, AND today closed up)
  - Volume confirmation: Vol_Ratio > vol_ratio_min
  - Strong close: Close > SMA10
Stop: Low[T] - 0.5 * ATR   (approximated via engine's stop_atr_mult)
Score: RS_21d + Vol_Ratio

Note vs source: source's exit used Close < SMA21 for 2 bars ("EMA Break");
this port uses engine-default Close < SMA50. Same caveat as S4/S7.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .simple import SimpleStrategy


class S8BullishOutsideDay(SimpleStrategy):
    name = "s8_bullish_outside_day"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        "atr_pct_max": 8.0,
        "rs_threshold": 2.0,
        "vol_ratio_min": 1.5,
        # Engine exit knobs (match source's 1.0/1.5 ATR trail)
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 1.5,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        "atr_pct_max":         (5.0, 12.0),
        "rs_threshold":        (-2.0, 6.0),
        "vol_ratio_min":       (1.0, 3.0),
        "stop_atr_mult":       (0.8, 2.5),
        "trail_tight_mult":    (0.5, 1.5),
        "trail_wide_mult":     (1.0, 2.5),
        "trail_tighten_atr":   (0.5, 2.0),
    }

    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        if prev is None:
            return False

        # Universal gates
        if row.get("ATR_pct", 999) > params["atr_pct_max"]:
            return False
        if not bool(row.get("Trend_OK", False)):
            return False
        if not bool(row.get("Above50", False)):
            return False
        rs = row.get("RS_21d")
        if pd.isna(rs) or rs < params["rs_threshold"]:
            return False

        # Bullish outside day: today engulfs yesterday + closed up
        if row["High"] <= prev["High"]:
            return False
        if row["Low"] >= prev["Low"]:
            return False
        if row["Close"] <= row["Open"]:
            return False

        # Volume confirmation
        vr = row.get("Vol_Ratio")
        if pd.isna(vr) or vr <= params["vol_ratio_min"]:
            return False

        # Strong close above SMA10
        sma10 = row.get("SMA10")
        if pd.isna(sma10) or row["Close"] <= sma10:
            return False

        return True

    def entry_score(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> float:
        rs = row.get("RS_21d", 0.0)
        vr = row.get("Vol_Ratio", 0.0)
        rs_v = 0.0 if pd.isna(rs) else float(rs)
        vr_v = 0.0 if pd.isna(vr) else float(vr)
        return rs_v + vr_v
