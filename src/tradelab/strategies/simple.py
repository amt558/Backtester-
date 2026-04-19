"""
SimpleStrategy — minimum-ceremony base class for new strategy authors.

Mirrors the per-bar entry_fn / exit_fn pattern used by the original
/c/TradingScripts/FINAL STRATEGYIE/ strategies and the conceptual shape of
TradingView's strategy.entry() / strategy.exit() blocks.

Subclass and only implement two functions:

    class MyStrategy(SimpleStrategy):
        name = "my_strategy"
        default_params = {"rsi_threshold": 30, "atr_mult": 2.0,
                          "stop_atr_mult": 1.5, "trail_tight_mult": 1.0,
                          "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5}
        tunable_params = {"rsi_threshold": (20, 70), "atr_mult": (1.0, 3.0)}

        def entry_signal(self, row, prev, params):
            # Return True if this bar is an entry; False otherwise.
            # `row` is the current bar (pandas Series with all enriched columns);
            # `prev` is the previous bar (or None if first bar).
            return prev is not None and row["RSI"] < params["rsi_threshold"] \
                   and row["Close"] > prev["Close"]

        def entry_score(self, row, prev, params):
            # Return a number for ranking when slot count is tight.
            # Higher = better. Default is 1.0.
            return row.get("RS_21d", 1.0)

The base class produces the buy_signal / entry_stop / entry_score columns
the backtest engine consumes. Exits are still handled by the engine's
trailing-stop logic (uses stop_atr_mult / trail_*_mult / trail_tighten_atr
from your default_params). Override exit_signal() to add custom exits.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from .base import Strategy


class SimpleStrategy(Strategy):
    """
    Minimum-ceremony Strategy. Subclasses define entry_signal() (and
    optionally entry_score and exit_signal). Indicator columns expected
    on `row` are whatever your strategy reads — make sure your universe
    is enriched (cli_run does this automatically).

    Required default_params keys (the engine's exit logic uses these):
      stop_atr_mult, trail_tight_mult, trail_wide_mult, trail_tighten_atr
    """

    timeframe: str = "1D"
    requires_benchmark: bool = True

    # Subclasses MUST set these
    default_params: dict[str, Any] = {
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }
    tunable_params: dict[str, tuple[float, float]] = {}

    # ---------- Subclass override hooks ----------

    def entry_signal(self, row: pd.Series, prev: Optional[pd.Series],
                      params: dict, prev2: Optional[pd.Series] = None) -> bool:
        """
        Override: return True iff this bar is an entry.

        `row` has all enriched columns (Open/High/Low/Close/Volume +
        ATR, ATR_pct, RSI, EMA10, SMA10/21/50/200, Vol_MA20, Vol_Ratio,
        Trend_OK, Above50, Pocket_Pivot, RS_21d, ...).
        `prev` is the previous bar (None on the first bar).
        `prev2` is the bar before prev (None on the first two bars) — useful
        for inside-day / pattern checks needing 2-bar lookback.
        """
        raise NotImplementedError("Subclass must implement entry_signal")

    def entry_score(self, row: pd.Series, prev: Optional[pd.Series],
                     params: dict, prev2: Optional[pd.Series] = None) -> float:
        """Optional override: ranking score when slots are tight. Default 1.0."""
        return 1.0

    # ---------- Engine contract — usually no need to override ----------

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Walk each symbol's bars and call entry_signal/entry_score per bar.
        Produces buy_signal / entry_stop / entry_score columns.
        """
        p = self.params
        stop_mult = float(p.get("stop_atr_mult", 1.5))
        out: dict[str, pd.DataFrame] = {}

        for sym, df in data.items():
            df = df.copy()
            n = len(df)
            buy = np.zeros(n, dtype=bool)
            score = np.full(n, 1.0, dtype=float)

            atr_arr = df["ATR"].values if "ATR" in df.columns else np.full(n, np.nan)
            close_arr = df["Close"].values
            atr_valid = ~np.isnan(atr_arr) & (atr_arr > 0)

            # Per-bar evaluation with 2-bar lookback context.
            prev: Optional[pd.Series] = None
            prev2: Optional[pd.Series] = None
            for i in range(n):
                if not atr_valid[i]:
                    prev2 = prev
                    prev = df.iloc[i]
                    continue
                row = df.iloc[i]
                try:
                    if self.entry_signal(row, prev, p, prev2):
                        buy[i] = True
                        score[i] = float(self.entry_score(row, prev, p, prev2))
                except Exception:
                    # A subclass bug should never crash the whole backtest;
                    # treat as no-signal and continue.
                    pass
                prev2 = prev
                prev = row

            df["buy_signal"] = buy
            df["entry_stop"] = close_arr - stop_mult * np.where(atr_valid, atr_arr, 0.0)
            df["entry_score"] = score
            out[sym] = df
        return out
