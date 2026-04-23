"""Qullamaggie Episodic Pivot — port of the setup described in the DeepVue
backtest suite and Qullamaggie's published rules.

Entry (all must hold on bar T):
  - %Chg(T) >= pct_chg_min          (big up-day)
  - Close(T) > High(T-1)            (breaks prior day's high)
  - $Vol 20-day MA >= dollar_vol_min (liquidity)
  - ADR% 20-day >= adr_min          (enough daily range to work with)
  - Close > SMA50                   (trend gate, from enriched 'Above50')
  - Close >= high_52w_proximity * 52-week high (positional — near highs)

Stop: entry bar low minus a small buffer (via tradelab engine's
Close - stop_atr_mult * ATR; stop_atr_mult tunable).
Exit: tradelab engine default (ATR-trailing + Below-SMA50). The source's
10-EMA trail is approximated — matching exactly needs a custom exit hook.

Score: ADR% (stocks with more daily range get slot priority when full).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..indicators import adr_pct
from .simple import SimpleStrategy


class QullamaggieEP(SimpleStrategy):
    name = "qullamaggie_ep"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        "pct_chg_min": 7.5,               # % — DeepVue's baseline
        "dollar_vol_min": 30_000_000.0,   # $ — DeepVue's baseline ($30M/day)
        "adr_min": 4.0,                   # % — Qullamaggie's own ADR filter
        "high_52w_proximity": 0.70,       # fraction — within 30% of 52W high
        # Engine exit params
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        "pct_chg_min":        (5.0, 12.0),
        "dollar_vol_min":     (10_000_000.0, 100_000_000.0),
        "adr_min":            (2.0, 7.0),
        "high_52w_proximity": (0.55, 0.90),
        "stop_atr_mult":      (1.0, 2.5),
    }

    # ----- Pre-compute DeepVue-specific columns before per-bar iteration.
    def _add_qm_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["Pct_Chg"] = df["Close"].pct_change() * 100.0
        dollar_vol = df["Close"] * df["Volume"]
        df["DollarVol_MA20"] = dollar_vol.rolling(20).mean()
        # ADR via the shared indicator lib (takes capitalized OK via _lc)
        df["ADR_pct_20d"] = adr_pct(df, 20)
        df["High_52w"] = df["High"].rolling(252).max()
        return df

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        enriched = {sym: self._add_qm_columns(df) for sym, df in data.items()}
        return super().generate_signals(enriched, spy_close=spy_close)

    # ----- Per-bar entry check (SimpleStrategy protocol).
    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        if prev is None:
            return False

        # %Chg threshold (big up-day)
        pct = row.get("Pct_Chg")
        if pd.isna(pct) or pct < params["pct_chg_min"]:
            return False

        # Break of previous high
        prev_high = prev.get("High")
        if pd.isna(prev_high) or row["Close"] <= prev_high:
            return False

        # Liquidity via 20-day average dollar volume
        dv = row.get("DollarVol_MA20")
        if pd.isna(dv) or dv < params["dollar_vol_min"]:
            return False

        # Range gate
        adr = row.get("ADR_pct_20d")
        if pd.isna(adr) or adr < params["adr_min"]:
            return False

        # Trend gate (from enriched)
        if not bool(row.get("Above50", False)):
            return False

        # 52-week-high proximity
        hi52 = row.get("High_52w")
        if pd.isna(hi52) or row["Close"] < params["high_52w_proximity"] * hi52:
            return False

        return True

    def entry_score(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> float:
        adr = row.get("ADR_pct_20d", 0.0)
        if pd.isna(adr):
            return 0.0
        return float(adr)
