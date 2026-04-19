"""
S4 Inside Day Breakout — port of /c/TradingScripts/FINAL STRATEGYIE/s4_inside_day_breakout.py

Logic (verbatim from the source):
  Entry on bar T iff:
    - bar T-1 was an inside day (High[T-1] < High[T-2] AND Low[T-1] > Low[T-2])
    - Close[T] > High[T-1]                          (breakout above prev high)
    - Vol_Ratio[T] > 1.2                             (volume confirmation)
    - Universal gates: ATR_pct ≤ 8, Trend_OK, Above50, RS_21d ≥ 0
  Stop: prev_low - 0.5 * ATR  (tighter than tradelab default; communicated to engine via stop_atr_mult)
  Score (for slot ranking): RS_21d + Vol_Ratio
  Exit: tradelab engine default (ATR-trailing stop + Below SMA50).

Note vs source: the source's exit had a Below-SMA21 break test instead of
the engine's Below-SMA50. Behavior will be close but not identical until
SimpleStrategy exposes a custom exit hook (Phase 2 polish item).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .simple import SimpleStrategy


class S4InsideDayBreakout(SimpleStrategy):
    name = "s4_inside_day_breakout"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        "atr_pct_max": 8.0,
        "rs_threshold": 0.0,
        "vol_ratio_min": 1.2,
        # Engine-required exit params (the source used 0.5*ATR; we approximate
        # via stop_atr_mult since SimpleStrategy uses Close - mult * ATR
        # rather than prev.Low - 0.5 * ATR. Stops are slightly different but
        # behavior is comparable.)
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        "atr_pct_max":   (5.0, 12.0),
        "rs_threshold":  (-2.0, 5.0),
        "vol_ratio_min": (1.0, 2.5),
        "stop_atr_mult": (0.8, 2.5),
    }

    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        if prev is None or prev2 is None:
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

        # Inside-day check on the PREVIOUS bar (vs. the bar before that)
        prev_inside_day = (prev["High"] < prev2["High"]) and (prev["Low"] > prev2["Low"])
        if not prev_inside_day:
            return False

        # Breakout above prev high
        if row["Close"] <= prev["High"]:
            return False

        # Volume confirmation
        vr = row.get("Vol_Ratio")
        if pd.isna(vr) or vr <= params["vol_ratio_min"]:
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
        return float((rs if not pd.isna(rs) else 0.0) + (vr if not pd.isna(vr) else 0.0))
