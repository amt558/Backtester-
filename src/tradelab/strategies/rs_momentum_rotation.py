"""
Cross-sectional relative-strength momentum rotation — long-only, gate-tuned.

WHY THIS IS THE BEST-FIT ARCHETYPE (handbook §6.5)
--------------------------------------------------
The robustness gate rewards an edge that is DISTRIBUTED (across symbols and
time), DURABLE, and SIMPLE. Cross-sectional momentum is built for exactly that:

  - Edge spread across the universe by construction      -> LOSO robust
  - Cross-sectional momentum is a deep, durable anomaly   -> WFE / wf_decay / hold-out
  - Many names rotating -> high trade count               -> DSR sample size, >=4 WF windows
  - One coarse selection parameter (top fraction)         -> param_landscape smoothness, noise
  - Ranks on RS_21d, decisions on the bar close           -> entry_delay tolerant

LONG-ONLY REGIME PROTECTION (the engine cannot short)
-----------------------------------------------------
Two filters keep `regime_spread` from going fragile in down markets, by simply
NOT trading them (the long-only substitute for shorting):
  - per-name trend gate: Trend_OK AND Above200
  - market gate: benchmark (SPY) above its own 200-bar mean (toggle: market_filter)
In a broad bear tape the strategy goes to cash, so the adverse-regime bucket
stays small/healthy rather than contributing a losing PF.

HOW SELECTION MAPS ONTO THE ENGINE
----------------------------------
generate_signals receives the WHOLE universe (the `data` dict), so we can rank
symbols against each other per date — true cross-sectional selection. We flag
the top `top_frac` of names by RS_21d each bar; `entry_score = RS_21d` then lets
the engine's slot logic (max_concurrent_positions) keep the strongest when more
names qualify than there are slots. Exits use the engine's ATR trailing stop.

NOTE: clearing the gate proves not-overfit, not profitability. Human-owned,
reviewable template — confirm the floor (net_pnl > 0, dsr >= 0) before trusting
a card, and sweep `top_frac` to confirm a smoothness plateau.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .base import Strategy

_BENCHMARK = "SPY"


class RsMomentumRotation(Strategy):
    """Long the strongest `top_frac` of the universe by 21-bar relative strength,
    gated by per-name trend and an optional market-regime filter."""

    name = "rs_momentum_rotation"
    timeframe = "1D"
    requires_benchmark = True  # needs RS_21d and spy_close for the market gate

    default_params = {
        # --- selection (the one coarse edge parameter) ---
        "top_frac": 0.40,        # buy the top 40% of the universe by RS each bar
        "rs_min": 0.0,           # floor: don't buy names with non-positive RS
        "market_filter": 1.0,    # 1.0 = require SPY above its 200-bar mean; 0.0 = off
        # --- engine exit knobs (required by the trailing-stop logic) ---
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        "top_frac": (0.25, 0.60),
        "rs_min": (-2.0, 5.0),
        "stop_atr_mult": (1.0, 2.5),
    }

    ablatable_gates = {
        # Neutralise the RS floor and the market gate for the validation
        # suite's Gate Contribution Isolation test (report-only).
        "rs_floor":      {"rs_min": -1e9},
        "market_filter": {"market_filter": 0.0},
    }

    @staticmethod
    def _date_index(df: pd.DataFrame) -> pd.Index:
        """Return a date-aligned index for a symbol frame, whether the date is a
        'Date' column or already the frame's index."""
        if "Date" in df.columns:
            return pd.Index(df["Date"])
        return df.index

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        p = self.params
        top_frac = float(p.get("top_frac", 0.40))
        rs_min = float(p.get("rs_min", 0.0))
        stop_mult = float(p.get("stop_atr_mult", 1.5))
        use_mkt = float(p.get("market_filter", 1.0)) >= 0.5

        # --- Market-regime gate from the benchmark (long-only bear protection) ---
        mkt_ok: Optional[pd.Series] = None
        if use_mkt and spy_close is not None and len(spy_close) > 0:
            spy_sma = spy_close.rolling(200, min_periods=50).mean()
            mkt_ok = (spy_close > spy_sma)

        # --- Build the cross-sectional RS matrix (dates x candidate symbols) ---
        rs_frames: dict[str, pd.Series] = {}
        for sym, df in data.items():
            if sym == _BENCHMARK or "RS_21d" not in df.columns:
                continue
            d = df.set_index("Date") if "Date" in df.columns else df
            rs_frames[sym] = d["RS_21d"]

        if rs_frames:
            rs_mat = pd.DataFrame(rs_frames)
            # Row-wise percentile rank: 1.0 = strongest name that date. NaNs
            # (warmup bars with no RS) are skipped and never selected.
            rank_pct = rs_mat.rank(axis=1, pct=True)
            in_top = rank_pct >= (1.0 - top_frac)
        else:
            in_top = pd.DataFrame()

        out: dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            df = df.copy()
            n = len(df)
            atr = df["ATR"].values if "ATR" in df.columns else np.full(n, np.nan)
            atr_valid = ~np.isnan(atr) & (atr > 0)

            # Benchmark is never a tradable candidate.
            if sym == _BENCHMARK or sym not in getattr(in_top, "columns", []):
                df["buy_signal"] = False
                df["entry_stop"] = df["Close"].values - stop_mult * np.where(atr_valid, atr, 0.0)
                df["entry_score"] = 0.0
                out[sym] = df
                continue

            d_index = self._date_index(df)

            top_sel = in_top[sym].reindex(d_index).fillna(False).to_numpy(dtype=bool)
            rs = df["RS_21d"].fillna(-np.inf).values if "RS_21d" in df.columns else np.full(n, -np.inf)
            trend = df["Trend_OK"].fillna(False).astype(bool).values if "Trend_OK" in df.columns else np.zeros(n, bool)
            above200 = df["Above200"].fillna(False).astype(bool).values if "Above200" in df.columns else np.zeros(n, bool)

            if mkt_ok is not None:
                mkt = mkt_ok.reindex(d_index).fillna(False).to_numpy(dtype=bool)
            else:
                mkt = np.ones(n, dtype=bool)

            df["buy_signal"] = (
                top_sel
                & (rs >= rs_min)
                & trend
                & above200
                & atr_valid
                & mkt
            )
            df["entry_stop"] = df["Close"].values - stop_mult * np.where(atr_valid, atr, 0.0)
            df["entry_score"] = df["RS_21d"].fillna(0.0).values

            out[sym] = df

        return out
