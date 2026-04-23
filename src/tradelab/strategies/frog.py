"""frog -- TODO one-line description.

Entry rules:
  - TODO: describe entry conditions

Stop: tradelab default (Close - stop_atr_mult * ATR)
Exit: tradelab default (trailing ATR + SMA50 break)
Score: RS_21d for slot ranking (override if you want different)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .simple import SimpleStrategy


class v2(SimpleStrategy):
    name = "frog"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        # --- strategy-specific params (add yours below) ---
        # 'atr_pct_max': 8.0,
        # 'rs_threshold': 0.0,

        # --- engine exit params (leave these unless you know why) ---
        'stop_atr_mult': 1.5,
        'trail_tight_mult': 1.0,
        'trail_wide_mult': 2.0,
        'trail_tighten_atr': 1.5,
    }

    tunable_params = {
        # param_name: (low, high)  --  for Optuna search space
        'stop_atr_mult': (1.0, 2.5),
    }

    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        """Return True to enter a long on this bar.

        Enriched columns available on `row`:
          Open, High, Low, Close, Volume, ATR, ATR_pct,
          SMA10/21/50/200, EMA10/21, Vol_MA20, Vol_Ratio,
          Trend_OK, Above50, Pocket_Pivot, RS_21d
        """
        if prev is None:
            return False
        # TODO: implement your entry logic. Return True on entry bars.
        return False

    def entry_score(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> float:
        """Higher score wins when slots are tight. Default: use RS_21d."""
        return float(row.get("RS_21d", 1.0) or 0.0)
