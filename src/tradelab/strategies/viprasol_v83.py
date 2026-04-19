"""
Viprasol v8.3 — Pine Script port.

Source: C:/Users/AAASH/OneDrive/Desktop/New folder (4)/Viprasol_v83_Screened.pine
(which itself is a Pine v6 port of an AFL strategy).

Core mechanics:
  Composite score (0..10): 10 boolean conditions across trend, volume,
    momentum, volatility, and relative strength. Enter when score ≥ minScore.
  Exit: TP% / MaxLoss% / %Trail (armed after peak% ≥ activate) / time limit.

Tradelab-side porting decisions (documented honestly):
  1. Per-symbol Optuna params (22 symbols) are NOT applied — tradelab's engine
     doesn't do per-symbol lookups. This port uses the v8.2 baseline fallback
     (rsLookback=35, atrThreshold=0.5, holdLimit=3, tpTarget=3.5,
     trailStop=2.0, trailActivate=1.0, maxLoss=8.0, minScore=5) and lets
     Optuna re-tune on tradelab's universe. Per-symbol tuning is a future
     feature (Phase 5+).
  2. Pine's TP%/MaxLoss%/%Trail/Time exit model maps imperfectly onto
     tradelab's ATR-trail engine. Exit is approximated via:
        stop_atr_mult — initial hard stop (equivalent to maxLossPerc-ish)
        trail_tight/wide_mult — the trail half after activation
     The time-based (holdLimit bars) exit has no direct engine support;
     approximated by the trail tightening. Result: entry decisions are
     faithful to Pine; exit behaviour is materially different.
  3. Pine's VWAP on daily bars is ill-defined (session-resetting). This
     port uses typical price HLC3 as the VWAP proxy in the score. On 1D
     bars this is approximately correct; on intraday it would diverge.
  4. MACD(12,26,9) and EMA9/EMA50 are computed inline (not in enrich).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .base import Strategy


class ViprasolV83(Strategy):
    name = "viprasol_v83"
    timeframe = "1D"
    requires_benchmark = True

    default_params = {
        # Entry/score params (v8.2 baseline from Pine fallback)
        "rs_lookback": 35,
        "atr_threshold": 0.5,
        "min_score": 5.0,
        "require_pos_rs": 1.0,    # 1=True, 0=False
        # Exit approximations (ATR-trail engine)
        "stop_atr_mult": 1.5,     # initial hard stop; rough proxy for maxLossPerc
        "trail_tight_mult": 1.0,  # tight trail after peak
        "trail_wide_mult": 2.0,   # wide trail before peak
        "trail_tighten_atr": 1.0, # peak gain (in ATR) that arms the tight trail
    }

    tunable_params = {
        "rs_lookback":   (15.0, 70.0),
        "atr_threshold": (0.1, 2.0),
        "min_score":     (3.0, 9.0),
        "stop_atr_mult": (0.8, 2.5),
        "trail_tight_mult":  (0.5, 1.5),
        "trail_wide_mult":   (1.0, 2.5),
        "trail_tighten_atr": (0.5, 2.0),
    }

    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        p = self.params
        rs_lookback = max(1, int(round(float(p["rs_lookback"]))))
        atr_threshold = float(p["atr_threshold"])
        min_score = float(p["min_score"])
        require_pos_rs = bool(p.get("require_pos_rs", 1.0))

        out: dict[str, pd.DataFrame] = {}

        # Align SPY once for vectorised RS computation
        spy_ser: Optional[pd.Series] = None
        if spy_close is not None:
            spy_ser = spy_close.copy()
            spy_ser.index = pd.to_datetime(spy_ser.index)

        for sym, df in data.items():
            df = df.copy()
            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            opn = df["Open"]
            volume = df["Volume"]

            # --- indicators Pine uses (add what enrich doesn't already have) ---
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema21 = df.get("EMA21", close.ewm(span=21, adjust=False).mean())
            ema50 = close.ewm(span=50, adjust=False).mean()

            # Daily "VWAP" proxy: typical price (HLC3). Pine uses session-resetting
            # ta.vwap; on daily bars that degenerates and HLC3 is close-enough.
            vwap = (high + low + close) / 3.0

            vol20 = df.get("Vol_MA20", volume.rolling(20).mean())
            rsi = df.get("RSI", self._rsi(close, 14))

            # MACD (12, 26, 9)
            macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            macd_sig = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = macd_line - macd_sig

            atr = df.get("ATR", self._atr(high, low, close, 14))
            atr_pct = (atr / close * 100.0).where(close > 0, 0.0)

            # RS over rs_lookback bars vs SPY
            if spy_ser is not None and sym != "SPY":
                dates = pd.to_datetime(df["Date"])
                spy_al = spy_ser.reindex(dates).ffill().values
                spy_ref = np.roll(spy_al, rs_lookback)
                close_ref = close.shift(rs_lookback).values
                s_perf = np.where(
                    (close_ref > 0) & np.isfinite(close_ref),
                    (close.values - close_ref) / close_ref * 100.0, 0.0,
                )
                b_perf = np.where(
                    (spy_ref > 0) & np.isfinite(spy_ref),
                    (spy_al - spy_ref) / spy_ref * 100.0, 0.0,
                )
                rs_val = s_perf - b_perf
                # Early bars (lookback not populated yet) → 0
                rs_val[:rs_lookback] = 0.0
            else:
                rs_val = np.zeros(len(df))

            # --- composite score (0..10) matching Pine exactly ---
            sc = np.zeros(len(df), dtype=int)
            sc += (close > vwap).fillna(False).astype(int).values
            sc += (ema9 > ema21).fillna(False).astype(int).values
            sc += (close > ema50).fillna(False).astype(int).values
            sc += (ema21 > ema50).fillna(False).astype(int).values
            sc += (volume > vol20 * 1.5).fillna(False).astype(int).values   # v8.3 tightening
            sc += (close > opn).fillna(False).astype(int).values
            sc += ((rsi > 45) & (rsi < 85)).fillna(False).astype(int).values
            sc += (macd_hist > 0).fillna(False).astype(int).values
            sc += (atr_pct >= atr_threshold).fillna(False).astype(int).values
            # RS gate: +1 if RS > 0, else +0 (Pine uses 1 if no benchmark, same idea)
            sc += (rs_val > 0).astype(int)

            # --- entry gate ---
            atr_valid = atr.notna() & (atr > 0)
            atr_ok = (atr_pct >= atr_threshold).fillna(False)
            rs_ok = pd.Series(rs_val > 0, index=df.index) if require_pos_rs else pd.Series(True, index=df.index)
            sc_ok = pd.Series(sc >= min_score, index=df.index)

            buy = sc_ok & atr_ok & rs_ok & atr_valid

            df["buy_signal"] = buy.fillna(False).astype(bool)
            df["entry_stop"] = close - float(p["stop_atr_mult"]) * atr
            # Higher score + stronger RS → better entry score (for slot ranking)
            df["entry_score"] = sc.astype(float) + np.clip(rs_val, -100.0, 100.0) / 10.0

            # Make the extra indicators available (harmless, useful for debugging)
            df["VIP_score"] = sc
            df["VIP_rs"] = rs_val
            df["VIP_macd_hist"] = macd_hist
            df["EMA9"] = ema9
            df["EMA50"] = ema50
            df["VWAP"] = vwap

            out[sym] = df

        return out

    # -- local fallback indicators (used only if enrich didn't already attach) --

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        up = delta.clip(lower=0.0)
        down = (-delta).clip(lower=0.0)
        avg_up = up.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_down = down.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_up / avg_down.replace(0.0, np.nan)
        return 100.0 - 100.0 / (1.0 + rs)

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, adjust=False).mean()
