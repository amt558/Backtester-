"""
S7 RDZ Momentum — port of /c/TradingScripts/FINAL STRATEGYIE/s7_rdz_momentum.py

Mean-reversion entry: trigger when RSI z-score (RDZ) crosses below -1.2
(deeply oversold relative to its own 20-bar history) on a stock that is
otherwise trending.

Custom indicators not in tradelab.marketdata.enrich (computed inline below):
  RDZ    = (RSI - rolling_mean(RSI, 20)) / rolling_std(RSI, 20)
            — RSI z-score; negative = oversold vs. own history
  Sigma  = (Close - Close[-1]) / rolling_std(Close - Close[-1], 100)
            — daily change z-score, used as a volatility-spike filter

Entry on bar T iff:
  - Universal gates: ATR_pct ≤ atr_pct_max, Trend_OK, Above50, RS_21d ≥ rs_threshold
  - Volatility-spike filter: |Sigma[T]| < sigma_max
  - RDZ cross-down: RDZ[T-1] ≥ rdz_entry AND RDZ[T] < rdz_entry
  - Volume confirmation: Vol_OK (today's volume > 20-day avg)
Stop: Close - stop_atr_mult * ATR
Score: |RDZ| + RS_21d / 10  (deeper-oversold + higher-RS preferred)

Note vs source: the source's exit had a Below-SMA21 break test; this port
uses the engine's default Below-SMA50 trail for now (same caveat as S4 —
SimpleStrategy doesn't yet expose a custom exit hook).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .simple import SimpleStrategy


class S7RdzMomentum(SimpleStrategy):
    name = "s7_rdz_momentum"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        "atr_pct_max": 10.0,
        "rs_threshold": 3.0,
        "rdz_entry": -1.2,
        "sigma_max": 3.0,
        # Engine exit knobs (port of source's tighter trail values)
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 0.8,
        "trail_wide_mult": 1.5,
        "trail_tighten_atr": 0.8,
    }

    tunable_params = {
        "atr_pct_max":   (5.0, 15.0),
        "rs_threshold":  (0.0, 6.0),
        "rdz_entry":     (-2.5, -0.5),
        "sigma_max":     (2.0, 5.0),
        "stop_atr_mult": (0.8, 2.5),
        "trail_tight_mult":  (0.4, 1.5),
        "trail_wide_mult":   (1.0, 2.5),
        "trail_tighten_atr": (0.3, 2.0),
    }

    # ---- override to add RDZ + Sigma before per-bar loop ----

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        augmented: dict[str, pd.DataFrame] = {}
        for sym, df in data.items():
            df = df.copy()
            if "RSI" in df.columns:
                df["RSI_mean"] = df["RSI"].rolling(20).mean()
                df["RSI_std"] = df["RSI"].rolling(20).std()
                df["RDZ"] = (df["RSI"] - df["RSI_mean"]) / df["RSI_std"].replace(0, np.nan)
            else:
                df["RDZ"] = np.nan
            chg = df["Close"] - df["Close"].shift(1)
            chg_std = chg.rolling(100).std()
            df["Sigma"] = chg / chg_std.replace(0, np.nan)
            augmented[sym] = df
        return super().generate_signals(augmented, spy_close)

    # ---- per-bar entry decision ----

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

        # Volatility-spike filter
        sigma = row.get("Sigma")
        if pd.isna(sigma) or abs(sigma) >= params["sigma_max"]:
            return False

        # RDZ cross-down
        rdz = row.get("RDZ")
        rdz_prev = prev.get("RDZ")
        if pd.isna(rdz) or pd.isna(rdz_prev):
            return False
        if not (rdz_prev >= params["rdz_entry"] and rdz < params["rdz_entry"]):
            return False

        # Volume confirmation
        if not bool(row.get("Vol_OK", False)):
            return False

        return True

    def entry_score(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> float:
        rdz = row.get("RDZ", 0.0)
        rs = row.get("RS_21d", 0.0)
        rdz_v = 0.0 if pd.isna(rdz) else abs(float(rdz))
        rs_v = 0.0 if pd.isna(rs) else float(rs)
        return rdz_v + rs_v / 10.0
