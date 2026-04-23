"""Post-backtest diagnostic helpers.

Computes secondary analytics that aren't needed by the backtest loop itself
but that downstream reporting/verdict logic consumes:

  * ``compute_regime_breakdown`` — classify each trade by benchmark regime
    (bull / chop / bear) at entry date; emit per-regime metrics. Used to
    surface regime dependence as a first-class verdict signal.

  * ``compute_monthly_pnl`` — aggregate trades by calendar month of EXIT
    date; emit per-month wins/losses/net_pnl. Used for post-mortem ("what
    months hurt?") diagnostics on the Trades tab.

Both return plain dict / list-of-dict structures so they serialize cleanly
into ``BacktestResult.regime_breakdown`` / ``BacktestResult.monthly_pnl``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd


_REGIME_KEYS = ("bull", "chop", "bear")


def classify_regime(spy_close: Optional[pd.Series]) -> Optional[pd.Series]:
    """Return a per-date regime Series ('bull'|'chop'|'bear') derived from SPY.

    Bull = Close > SMA200 AND SMA200 slope > 0 over the last 10 bars.
    Bear = Close < SMA200 AND SMA200 slope < 0 over the last 10 bars.
    Chop = anything else (including transitional / warmup).

    Returns None if the benchmark series is too short for a 200-SMA + slope.
    """
    if spy_close is None or len(spy_close) < 220:
        return None
    close = pd.Series(spy_close).copy()
    close.index = pd.to_datetime(close.index)
    sma200 = close.rolling(200).mean()
    slope = sma200 - sma200.shift(10)
    regime = pd.Series("chop", index=close.index, dtype=object)
    regime[(close > sma200) & (slope > 0)] = "bull"
    regime[(close < sma200) & (slope < 0)] = "bear"
    # NaNs during warmup stay as "chop" — classification is conservative there
    regime[sma200.isna() | slope.isna()] = "chop"
    return regime


def _empty_regime_row() -> dict:
    return {
        "n_trades": 0, "win_rate": 0.0, "pf": 0.0,
        "net_pnl": 0.0, "avg_ret_pct": 0.0,
    }


def compute_regime_breakdown(
    trades: list, spy_close: Optional[pd.Series]
) -> dict:
    """Classify each trade by regime at entry_date and aggregate metrics.

    Args:
        trades: list of Trade objects (must have entry_date str, pnl, pnl_pct)
        spy_close: benchmark close series with DateTimeIndex (or None)

    Returns:
        Empty dict if regime classification unavailable. Otherwise:
        {"bull": {...}, "chop": {...}, "bear": {...}}
    """
    regime_series = classify_regime(spy_close)
    if regime_series is None or not trades:
        return {}

    buckets: dict[str, list] = {k: [] for k in _REGIME_KEYS}
    for t in trades:
        try:
            ts = pd.Timestamp(t.entry_date)
        except Exception:
            continue
        # snap to last available regime at or before entry_date
        idx = regime_series.index
        mask = idx <= ts
        if not mask.any():
            continue
        last_dt = idx[mask][-1]
        r = regime_series.loc[last_dt]
        if r not in buckets:
            continue
        buckets[r].append(t)

    out: dict[str, dict] = {}
    for regime in _REGIME_KEYS:
        bkt = buckets[regime]
        if not bkt:
            out[regime] = _empty_regime_row()
            continue
        wins = [t for t in bkt if t.pnl > 0]
        losses = [t for t in bkt if t.pnl <= 0]
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses))
        if gl > 0:
            pf = gp / gl
        elif gp > 0:
            pf = 10.0
        else:
            pf = 0.0
        out[regime] = {
            "n_trades": len(bkt),
            "win_rate": round(len(wins) / max(len(bkt), 1) * 100, 2),
            "pf": round(min(pf, 10.0), 3),
            "net_pnl": round(float(sum(t.pnl for t in bkt)), 2),
            "avg_ret_pct": round(float(np.mean([t.pnl_pct for t in bkt])), 3),
        }
    return out


def regime_spread_ratio(regime_breakdown: dict, min_trades: int = 10) -> Optional[float]:
    """Return the worst-regime PF / best-regime PF ratio, or None if fewer
    than 2 regimes have ``min_trades`` trades each. Lower = more concentrated."""
    if not regime_breakdown:
        return None
    pfs = [
        r["pf"] for r in regime_breakdown.values()
        if r.get("n_trades", 0) >= min_trades and r.get("pf", 0) > 0
    ]
    if len(pfs) < 2:
        return None
    lo, hi = min(pfs), max(pfs)
    return (lo / hi) if hi > 0 else None


def worst_regime_pf(regime_breakdown: dict, min_trades: int = 5) -> Optional[float]:
    """Return the smallest PF among regimes with at least ``min_trades``.
    None if no regime qualifies."""
    if not regime_breakdown:
        return None
    pfs = [
        r["pf"] for r in regime_breakdown.values()
        if r.get("n_trades", 0) >= min_trades
    ]
    return min(pfs) if pfs else None


def compute_monthly_pnl(trades: list) -> list[dict]:
    """Group trades by exit-date month and aggregate.

    Returns a list sorted by month ascending: each entry is
    ``{month, n_trades, wins, losses, net_pnl, avg_ret_pct}``.
    """
    if not trades:
        return []
    by_month: dict[str, list] = defaultdict(list)
    for t in trades:
        try:
            key = pd.Timestamp(t.exit_date).strftime("%Y-%m")
        except Exception:
            continue
        by_month[key].append(t)

    rows: list[dict] = []
    for month in sorted(by_month.keys()):
        bkt = by_month[month]
        wins = [t for t in bkt if t.pnl > 0]
        losses = [t for t in bkt if t.pnl <= 0]
        rows.append({
            "month": month,
            "n_trades": len(bkt),
            "wins": len(wins),
            "losses": len(losses),
            "net_pnl": round(float(sum(t.pnl for t in bkt)), 2),
            "avg_ret_pct": round(float(np.mean([t.pnl_pct for t in bkt])), 3),
        })
    return rows
