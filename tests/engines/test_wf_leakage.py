"""
Regression test for the walk-forward leakage fix.

Purpose
-------
`run_backtest` must close end-of-window positions using a bar WITHIN the
requested [start, end] window, never a bar after it. The original bug in
`s2_backtest.py` used `df.index[-1]` (the symbol's last full-dataset bar),
which on walk-forward sub-windows leaked forward price data into OOS
results. The fix in `src/tradelab/engines/backtest.py` (lines ~184-212)
uses `window_end_date = all_dates[-1]` and clamps the per-symbol close
date to `<= window_end_date`.

This test constructs synthetic data where:
  - the pre-boundary price regime is ~100
  - the post-boundary price regime is ~200
  - a position is forced open 3 bars before the boundary

If the fix is intact: end-of-window exit price is ~100 (small PnL).
If the fix is reverted: exit price is ~200 (massive inflated PnL).

Related docs
------------
  - TRADELAB_MASTER_PLAN.md, Part III, Task 0.0
  - reports/wf_fix_verification_2026-04-19.md

Usage
-----
    pytest tests/engines/test_wf_leakage.py -v

Exit code must be 0 for Pre-Phase-0 to be considered complete.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.backtest import run_backtest


# ---------------------------------------------------------------------------
# Mock strategy — duck-types the Strategy interface consumed by run_backtest.
# Deliberately does NOT inherit from tradelab.strategies.base.Strategy so the
# test has zero coupling to that module's evolution.
# ---------------------------------------------------------------------------

class _MockLeakageStrategy:
    """Minimal strategy exposing only what run_backtest touches."""

    name = "leakage_canary"
    tunable_params: dict = {}
    # Params chosen so the trail stop mathematics cannot fire on flat prices.
    params = {
        "trail_tighten_atr": 2.0,
        "trail_tight_mult": 1.0,
        "trail_wide_mult":  2.5,
    }

    def __init__(self, signaled_df_by_symbol: dict[str, pd.DataFrame]):
        self._signaled = signaled_df_by_symbol

    def generate_signals(self, ticker_data, spy_close=None):
        # run_backtest always calls with ticker_data; we ignore it and return
        # the pre-built signaled data fixtures.
        return self._signaled


# ---------------------------------------------------------------------------
# Synthetic data builder
# ---------------------------------------------------------------------------

def _build_cliff_data(symbol: str, entry_date: str, boundary: str) -> pd.DataFrame:
    """
    One symbol, business-day bars from 2023-01-01 through 2023-12-31.

    Price behavior:
      - before and on `boundary` : ~100 (with negligible drift for ATR > 0)
      - after `boundary`         : rises linearly toward ~200 by year end

    A buy_signal = True is placed on `entry_date`. Exit mechanisms (trail
    stop, SMA50 break) are disabled by construction:
      - ATR fixed at 1.0 and trail_wide_mult = 2.5 → stop is ~2.5 below price
      - Low is only 0.5 below Close → Low > stop, trail never fires
      - SMA50 is always 5 below Close → Close > SMA50, that exit never fires

    The position therefore survives to the end of the backtest window and
    MUST be closed by the end-of-window liquidation block.
    """
    dates = pd.date_range("2023-01-01", "2023-12-31", freq="B")
    n = len(dates)
    boundary_ts = pd.Timestamp(boundary)

    pre_mask = dates <= boundary_ts
    pre_count = int(pre_mask.sum())
    post_count = n - pre_count

    pre_prices = 100.0 + np.linspace(0.0, 0.4, pre_count)
    post_prices = np.linspace(120.0, 200.0, post_count)  # clear regime break
    prices = np.concatenate([pre_prices, post_prices])

    df = pd.DataFrame({
        "Date":        dates,
        "Open":        prices,
        "High":        prices + 0.5,
        "Low":         prices - 0.5,
        "Close":       prices,
        "ATR":         1.0,
        "SMA50":       prices - 5.0,
        "buy_signal":  False,
        "entry_stop":  50.0,
        "entry_score": 1.0,
    })
    df.loc[df["Date"] == pd.Timestamp(entry_date), "buy_signal"] = True
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def cliff_fixture():
    """Standard cliff-data fixture used by the core leakage test."""
    symbol = "TEST"
    entry_date = "2023-06-27"   # 3 business days before boundary
    boundary = "2023-06-30"     # window end
    data = _build_cliff_data(symbol, entry_date, boundary)
    strat = _MockLeakageStrategy({symbol: data})
    return {
        "symbol": symbol,
        "entry_date": entry_date,
        "boundary": boundary,
        "strategy": strat,
    }


def _run(strat, window_start, window_end):
    """Invoke run_backtest with all knobs passed explicitly (no config dep)."""
    return run_backtest(
        strat,
        ticker_data=None,       # MockStrategy ignores this
        start=window_start,
        end=window_end,
        capital=100_000,
        pos_pct=10.0,
        max_pos=5,
        commission=1.0,
    )


def test_end_of_window_exit_date_is_inside_window(cliff_fixture):
    """Exit date of the end-of-window trade must be <= window end."""
    result = _run(cliff_fixture["strategy"], "2023-01-01", cliff_fixture["boundary"])
    assert len(result.trades) == 1, (
        f"Expected exactly one end-of-window trade, got {len(result.trades)}. "
        "The mock strategy should produce one entry and no natural exit."
    )
    t = result.trades[0]
    assert pd.Timestamp(t.exit_date) <= pd.Timestamp(cliff_fixture["boundary"]), (
        f"LEAKAGE: exit_date {t.exit_date} is AFTER window end "
        f"{cliff_fixture['boundary']}. The end-of-window liquidation block in "
        "backtest.py is reading a forward bar. Inspect the block near line 184."
    )


def test_end_of_window_exit_reason_is_end_of_window(cliff_fixture):
    """Sanity: the trade closes via the end-of-window path, not a trail stop."""
    result = _run(cliff_fixture["strategy"], "2023-01-01", cliff_fixture["boundary"])
    assert result.trades[0].exit_reason == "End of Window"


def test_end_of_window_exit_price_reflects_pre_boundary_regime(cliff_fixture):
    """
    Exit price must reflect the pre-boundary price regime (~100), not the
    post-boundary regime (~200). A price > 105 is a smoking-gun indicator
    of forward leakage.
    """
    result = _run(cliff_fixture["strategy"], "2023-01-01", cliff_fixture["boundary"])
    t = result.trades[0]
    assert t.exit_price <= 105.0, (
        f"LEAKAGE: exit_price is {t.exit_price}, but the pre-boundary regime "
        "tops out near 100.5. The engine has closed the position using a "
        "post-boundary bar. Inspect backtest.py lines ~184-212."
    )


def test_end_of_window_pnl_is_not_inflated(cliff_fixture):
    """PnL% on a flat-regime position should be near zero, not ~100%."""
    result = _run(cliff_fixture["strategy"], "2023-01-01", cliff_fixture["boundary"])
    t = result.trades[0]
    assert abs(t.pnl_pct) < 5.0, (
        f"LEAKAGE: end-of-window PnL% is {t.pnl_pct}, which is far too large "
        "for a price regime that was ~flat throughout the window. This is the "
        "exact signature of the forward-leak bug described in ROADMAP Task 0.0."
    )


def test_extending_window_past_boundary_changes_pnl(cliff_fixture):
    """
    Positive control: the same entry, evaluated through 2023-12-31 (which
    includes the post-boundary regime), MUST produce substantially different
    PnL than the window-ending-at-boundary case. If these two runs produce
    similar PnL, either the test fixture is broken or the engine is ignoring
    the `end` parameter entirely.
    """
    result_short = _run(cliff_fixture["strategy"], "2023-01-01", cliff_fixture["boundary"])
    # Rebuild strategy object so no mutable state leaks between runs
    data = _build_cliff_data(cliff_fixture["symbol"], cliff_fixture["entry_date"],
                             cliff_fixture["boundary"])
    strat_long = _MockLeakageStrategy({cliff_fixture["symbol"]: data})
    result_long = _run(strat_long, "2023-01-01", "2023-12-31")

    short_pnl_pct = result_short.trades[0].pnl_pct
    # Long-window run may exit via trail stop in the rising regime — that's
    # fine, we only care that the outcome differs materially from the short
    # window's flat-regime exit.
    if result_long.trades:
        long_pnl_pct = result_long.trades[0].pnl_pct
    else:
        long_pnl_pct = 0.0
    assert abs(long_pnl_pct - short_pnl_pct) > 5.0, (
        f"Control failed: short-window PnL% ({short_pnl_pct}) and long-window "
        f"PnL% ({long_pnl_pct}) are too similar. Either the `end` parameter is "
        "being ignored or the synthetic fixture is not producing the intended "
        "price regime break."
    )
