"""
CG-TFE v1.5 — Pine Script SCAFFOLD port.

Source: CG_TFE_v15_Scaffold.pine (Pine v6, 190 lines).

⚠ THIS IS A SCAFFOLD. Three of five modules are placeholders per the Pine
source's own disclaimer:
  Module 1  Session Filters         IMPLEMENTED (adapted to daily bars)
  Module 2  Gate 1 (LPR HA + DS)    PLACEHOLDER — always returns True
  Module 3  Gate 2 (HP OB + score)  PLACEHOLDER — always returns True
  Module 4  CCI/RSI Entry Signal    PLACEHOLDER — fires every hold_bars * 5
  Module 5  Time-Based Exit         approximated via engine ATR-trail

The Pine source was written for intraday timeframes (15m–1H per production
config). Tradelab runs daily bars. Adaptations:
  - `skipOpeningBars` dropped (no intraday sessions on daily bars)
  - `sessionWindow` dropped (same reason)
  - `skipFriday` preserved — still meaningful on daily bars
  - Entry cadence kept at "every N bars" but N scaled down since each bar
    is now a day (Pine had 50 intraday bars ≈ 1 session; on daily that'd
    be 50 days — so we use N = hold_bars * 5 ≈ 50 days default)

**Running this strategy through the robustness suite will show whatever
verdict the scaffold trades produce — which is NOT an evaluation of the
real CG-TFE edge (which doesn't exist yet in this file).**

To activate CG-TFE properly, replace the three placeholder methods below
(`_gate1_HA_Trend`, `_gate2_HP_OrderBlock`, `_cci_rsi_entry`) with the
real logic. Their signatures are documented inline.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .simple import SimpleStrategy


class CgTfeV15(SimpleStrategy):
    name = "cg_tfe_v15"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "skip_friday": 1.0,          # 1=True, 0=False
        "hold_bars": 10.0,           # Pine default
        "entry_cadence_bars": 50.0,  # Module 4 placeholder fires every N bars
        # Exit approximation via engine ATR-trail
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    tunable_params = {
        # Nothing meaningful to tune on a scaffold. These are included so the
        # optimizer has something to explore if someone hits --optimize.
        "entry_cadence_bars": (10.0, 100.0),
        "stop_atr_mult":      (0.8, 2.5),
        "trail_tight_mult":   (0.5, 1.5),
        "trail_wide_mult":    (1.0, 2.5),
        "trail_tighten_atr":  (0.5, 2.0),
    }

    # ---- Placeholder modules (replace with real logic) ----

    def _gate1_HA_Trend(self, row: pd.Series, prev: Optional[pd.Series]) -> bool:
        """Module 2: Heikin-Ashi trend direction + LPR slope + DS threshold.
        TODO: implement. Scaffold returns True."""
        return True

    def _gate2_HP_OrderBlock(self, row: pd.Series, prev: Optional[pd.Series]) -> bool:
        """Module 3: HP Order Block + momentum Z + volume score.
        TODO: implement. Scaffold returns True."""
        return True

    def _cci_rsi_entry(self, row: pd.Series, prev: Optional[pd.Series],
                        bar_index: int, cadence_bars: int) -> bool:
        """Module 4: CCI-crosses-zero + RSI-turn-from-oversold.
        TODO: implement. Scaffold fires every cadence_bars."""
        return cadence_bars > 0 and (bar_index % cadence_bars == 0)

    # ---- Per-bar entry decision ----

    def entry_signal(
        self,
        row: pd.Series,
        prev: Optional[pd.Series],
        params: dict,
        prev2: Optional[pd.Series] = None,
    ) -> bool:
        if prev is None:
            return False

        # Module 1: session filters (on daily: only Friday skip is meaningful)
        if bool(params.get("skip_friday", 1.0)):
            try:
                date = pd.Timestamp(row["Date"])
                if date.weekday() == 4:   # Friday = 4 in pandas; dayofweek.friday in Pine
                    return False
            except (KeyError, ValueError):
                pass

        # Bar index helper: the engine doesn't hand us a bar index directly,
        # but row.name is the positional integer index after reset_index().
        bi = int(row.name) if row.name is not None else 0

        if not self._gate1_HA_Trend(row, prev):
            return False
        if not self._gate2_HP_OrderBlock(row, prev):
            return False
        cadence = max(1, int(round(float(params.get("entry_cadence_bars", 50.0)))))
        if not self._cci_rsi_entry(row, prev, bi, cadence):
            return False
        return True
