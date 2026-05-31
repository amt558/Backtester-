"""
Validation suite — a PARALLEL, REPORT-ONLY layer beside the robustness verdict.

WHY THIS IS SEPARATE FROM verdict.py (do not collapse them):
    `compute_verdict()` aggregates signals asymmetrically — any single fragile
    signal caps the verdict at INCONCLUSIVE, and ROBUST requires
    `n_robust >= max(3, len(signals) // 2)`. Adding signals into that pool
    re-weights the verdict for *every* strategy and would silently flip locked
    baselines (Viprasol v8.2, CG-TFE v1.5). So this module:

      * NEVER imports or calls `compute_verdict`.
      * Produces a `ValidationReport` that is a SIBLING of `VerdictResult`,
        not a member of it or of `RobustnessSuiteResult`.
      * Emits the same record shape the dashboard already knows
        ({name, outcome, reason}) so the frontend can render it with the
        existing SIG_DEFS-style machinery — plus an optional `value` for
        programmatic use.

    Promoting any of these tests into the verdict aggregator is a separate,
    explicit, versioned decision for later — never automatic.

OUTCOME COLOURS ARE COSMETIC. The `outcome` field (robust/inconclusive/fragile)
exists only to colour a future research panel red/amber/green. It feeds nothing.
The thresholds below are deliberately simple and are flagged for review.

TIER 1 — ledger-only, synchronous, verdict-neutral:
    win_loss_streak, expectancy_stability (rolling 20-trade), pf_by_month.
TIER 2 — equity/parquet, synchronous, verdict-neutral:
    drawdown_stress (equity_curve calendar-window scan),
    volatility_bucketing (ATR% terciles from the Twelve Data → parquet cache;
    NEVER fetches — a cache miss is just inconclusive).

Tier-1 tests read only `BacktestResult.trades[]`; drawdown_stress reads
`equity_curve`; volatility_bucketing reads cached parquet OHLCV per ticker.
(Trade.entry_date is an ISO 'YYYY-MM-DD' string — date-only, no intraday time,
confirmed even for 1H strategies.)
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ..marketdata import cache
from ..marketdata.enrich import enrich_with_indicators
from ..results import BacktestResult, Trade

# ── Tunables (cosmetic colouring + JSON safety) ──────────────────────────────
SUITE_VERSION = "1"
ROLLING_WINDOW = 20          # Expectancy Stability window, in trades
PF_CAP = 99.0                # cap for "profitable month with zero losses"
                             # (keeps PF finite & JSON-serialisable; no inf/NaN)

# Expectancy-stability colour thresholds (fraction of positive rolling windows)
_EXP_FRAC_ROBUST = 0.80
_EXP_FRAC_FRAGILE = 0.50

# PF-by-month colour thresholds (fraction of profitable months, PF >= 1)
_PFM_FRAC_ROBUST = 0.70
_PFM_FRAC_FRAGILE = 0.50

# Drawdown-stress colour thresholds (worst short-window peak-to-trough, %)
_DD_WINDOWS_DAYS = (14, 21)  # 2-week and 3-week calendar windows
_DD_STRESS_ROBUST_PCT = 8.0
_DD_STRESS_FRAGILE_PCT = 20.0

# Volatility-bucketing settings
_VOL_N_BUCKETS = 3           # low / medium / high ATR% terciles
_VOL_MIN_TRADES = 15         # need enough bucketable trades to be meaningful


class ValidationSignal(BaseModel):
    """One report-only validation check.

    Shape mirrors robustness `VerdictSignal` ({name, outcome, reason}) so the
    dashboard renders it with the existing machinery. NOTE: the current
    frontend extracts the displayed number from `reason` via regex and ignores
    `value`; `value` is carried for forward-compat / programmatic access.
    """
    name: str
    outcome: str            # "robust" | "inconclusive" | "fragile" — COSMETIC
    reason: str
    value: Optional[float] = None
    detail: dict = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Parallel, report-only bundle. Sibling to VerdictResult — never a member
    of it, and never consulted by compute_verdict()."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: str
    suite_version: str = SUITE_VERSION
    signals: list[ValidationSignal] = Field(default_factory=list)
    generated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )


# ── helpers ──────────────────────────────────────────────────────────────────

def _chronological(trades: list[Trade]) -> list[Trade]:
    """Sort by (entry_date, exit_date). ISO date strings sort lexicographically,
    so plain string ordering is correct here."""
    return sorted(trades, key=lambda t: (t.entry_date, t.exit_date))


def _safe(x: float) -> Optional[float]:
    """Map inf/NaN to None so the serialized report stays valid JSON."""
    if x is None or math.isinf(x) or math.isnan(x):
        return None
    return float(x)


# ── Test 1: Win/Loss Streak ──────────────────────────────────────────────────

def win_loss_streak(bt: BacktestResult) -> ValidationSignal:
    """Longest consecutive win / loss runs over the chronological ledger.

    A trade is a win if pnl > 0, a loss if pnl < 0; an exact-zero (scratch)
    trade breaks both runs without extending either.

    Cosmetic outcome compares the observed longest LOSS run against the
    expected longest run under an i.i.d. Bernoulli model with the observed
    loss rate (Schilling's approximation, E ≈ ln(n·q) / ln(1/q)). A loss run
    far beyond chance hints at clustering/regime dependence -> fragile colour.
    """
    trades = _chronological(bt.trades)
    n = len(trades)
    if n == 0:
        return ValidationSignal(
            name="win_loss_streak", outcome="inconclusive",
            reason="No trades in ledger", value=None,
            detail={"max_win_streak": 0, "max_loss_streak": 0,
                    "current_streak": 0, "n_trades": 0},
        )

    max_win = max_loss = 0
    cur = 0  # signed running streak: +k wins / -k losses
    wins = losses = 0
    for t in trades:
        if t.pnl > 0:
            wins += 1
            cur = cur + 1 if cur > 0 else 1
            max_win = max(max_win, cur)
        elif t.pnl < 0:
            losses += 1
            cur = cur - 1 if cur < 0 else -1
            max_loss = max(max_loss, -cur)
        else:
            cur = 0  # scratch breaks both runs

    detail = {
        "max_win_streak": max_win,
        "max_loss_streak": max_loss,
        "current_streak": cur,
        "n_trades": n,
        "wins": wins,
        "losses": losses,
    }

    decisive = wins + losses
    q = losses / decisive if decisive else 0.0
    expected_max_loss: Optional[float] = None
    if decisive >= 2 and 0.0 < q < 1.0:
        expected_max_loss = math.log(decisive * q) / math.log(1.0 / q)
        expected_max_loss = max(1.0, expected_max_loss)
    detail["expected_max_loss_streak"] = _safe(expected_max_loss) if expected_max_loss else None

    if expected_max_loss is None:
        outcome = "inconclusive"
        reason = f"Max loss streak {max_loss} (insufficient mix to baseline)"
    elif max_loss >= 2.0 * expected_max_loss:
        outcome = "fragile"
        reason = (f"Max loss streak {max_loss} ≥ 2× expected "
                  f"({expected_max_loss:.1f}) — losses cluster beyond chance")
    elif max_loss <= expected_max_loss:
        outcome = "robust"
        reason = (f"Max loss streak {max_loss} ≤ expected "
                  f"({expected_max_loss:.1f}) — no worse than chance")
    else:
        outcome = "inconclusive"
        reason = (f"Max loss streak {max_loss} vs expected "
                  f"{expected_max_loss:.1f}")

    return ValidationSignal(
        name="win_loss_streak", outcome=outcome, reason=reason,
        value=float(max_loss), detail=detail,
    )


# ── Test 2: Expectancy Stability (rolling 20-trade) ──────────────────────────

def expectancy_stability(bt: BacktestResult,
                         window: int = ROLLING_WINDOW) -> ValidationSignal:
    """Rolling per-trade expectancy (mean pnl_pct) over a sliding `window`.

    `value` = fraction of rolling windows with positive expectancy. Stable &
    consistently-positive expectancy reads robust; mostly-negative or negative
    overall reads fragile. <window trades -> inconclusive (no full window).
    """
    trades = _chronological(bt.trades)
    n = len(trades)
    rets = [t.pnl_pct for t in trades]

    if n < window:
        return ValidationSignal(
            name="expectancy_stability", outcome="inconclusive",
            reason=f"Only {n} trades (< {window}-trade window)", value=None,
            detail={"window": window, "n_windows": 0, "n_trades": n},
        )

    rolling = [sum(rets[i:i + window]) / window for i in range(n - window + 1)]
    n_windows = len(rolling)
    n_pos = sum(1 for m in rolling if m > 0)
    frac_pos = n_pos / n_windows
    overall_exp = sum(rets) / n

    mean_roll = sum(rolling) / n_windows
    var_roll = sum((m - mean_roll) ** 2 for m in rolling) / n_windows
    std_roll = math.sqrt(var_roll)
    cv = (std_roll / abs(mean_roll)) if mean_roll != 0 else None

    detail = {
        "window": window,
        "n_windows": n_windows,
        "n_trades": n,
        "frac_positive_windows": round(frac_pos, 4),
        "overall_expectancy_pct": _safe(overall_exp),
        "min_window_expectancy_pct": _safe(min(rolling)),
        "max_window_expectancy_pct": _safe(max(rolling)),
        "rolling_cv": _safe(cv),
    }

    if frac_pos >= _EXP_FRAC_ROBUST and overall_exp > 0:
        outcome = "robust"
    elif frac_pos < _EXP_FRAC_FRAGILE or overall_exp <= 0:
        outcome = "fragile"
    else:
        outcome = "inconclusive"

    reason = (f"{n_pos}/{n_windows} rolling windows positive "
              f"({frac_pos*100:.0f}%), overall expectancy {overall_exp:+.2f}%")
    return ValidationSignal(
        name="expectancy_stability", outcome=outcome, reason=reason,
        value=round(frac_pos, 4), detail=detail,
    )


# ── Test 3: PF by Month ──────────────────────────────────────────────────────

def pf_by_month(bt: BacktestResult) -> ValidationSignal:
    """Profit factor per calendar month, grouped by entry month (entry_date[:7]).

    PF = Σ(positive pnl) / |Σ(negative pnl)|. Computed off trades[] because
    BacktestResult.monthly_pnl carries net_pnl/win-loss *counts* only — it lacks
    the gross win/loss needed for PF. A month with profits and zero losses has
    undefined PF; it is capped at PF_CAP and flagged `no_losses` so the report
    never serializes inf/NaN.

    `value` = fraction of profitable months (PF >= 1).
    """
    buckets: dict[str, list[float]] = {}
    for t in bt.trades:
        buckets.setdefault(t.entry_date[:7], []).append(t.pnl)

    if not buckets:
        return ValidationSignal(
            name="pf_by_month", outcome="inconclusive",
            reason="No trades in ledger", value=None,
            detail={"months": [], "n_months": 0},
        )

    months = []
    for month in sorted(buckets):
        pnls = buckets[month]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        no_losses = gl == 0.0
        if no_losses:
            pf = PF_CAP if gp > 0 else 0.0
        else:
            pf = min(gp / gl, PF_CAP)
        months.append({
            "month": month,
            "pf": round(pf, 4),
            "gross_profit": round(gp, 2),
            "gross_loss": round(gl, 2),
            "n_trades": len(pnls),
            "no_losses": no_losses,
        })

    n_months = len(months)
    n_profitable = sum(1 for m in months if m["pf"] >= 1.0)
    frac_profitable = n_profitable / n_months
    worst = min(m["pf"] for m in months)

    detail = {
        "months": months,
        "n_months": n_months,
        "n_profitable_months": n_profitable,
        "frac_profitable_months": round(frac_profitable, 4),
        "worst_month_pf": round(worst, 4),
    }

    if frac_profitable >= _PFM_FRAC_ROBUST:
        outcome = "robust"
    elif frac_profitable < _PFM_FRAC_FRAGILE:
        outcome = "fragile"
    else:
        outcome = "inconclusive"

    reason = (f"{n_profitable}/{n_months} months profitable "
              f"({frac_profitable*100:.0f}%), worst-month PF {worst:.2f}")
    return ValidationSignal(
        name="pf_by_month", outcome=outcome, reason=reason,
        value=round(frac_profitable, 4), detail=detail,
    )


# ── Test 4: Drawdown Stress (equity_curve scan) ──────────────────────────────

def _worst_window_drawdown(dates: list, equity: list[float], window_days: int):
    """Worst peak-to-trough drawdown where peak and trough fall within the same
    trailing `window_days` calendar window. O(n) via a monotonic deque of
    candidate peak indices (works on irregularly-spaced equity points).

    Returns (worst_dd_fraction <= 0, trough_date, peak_date)."""
    worst = 0.0
    trough_d = peak_d = None
    dq: deque[int] = deque()  # indices, equity non-increasing front→back
    for i in range(len(equity)):
        while dq and equity[dq[-1]] <= equity[i]:
            dq.pop()
        dq.append(i)
        while dates[i] - dates[dq[0]] > timedelta(days=window_days):
            dq.popleft()
        peak = equity[dq[0]]
        if peak > 0:
            dd = (equity[i] - peak) / peak
            if dd < worst:
                worst, trough_d, peak_d = dd, dates[i], dates[dq[0]]
    return worst, trough_d, peak_d


def drawdown_stress(bt: BacktestResult) -> ValidationSignal:
    """Worst peak-to-trough drawdown concentrated inside 2- and 3-week windows.

    Scans the equity curve by CALENDAR window (not bar count) so it behaves
    identically on daily mark-to-market curves and irregular per-trade curves.
    `value` = worst 3-week (21-day) drawdown magnitude in %.

    Cosmetic outcome flags a strategy that takes a violent short-horizon hit.
    """
    curve = sorted(bt.equity_curve, key=lambda p: p["date"])
    if len(curve) < 2:
        return ValidationSignal(
            name="drawdown_stress", outcome="inconclusive",
            reason=f"Equity curve has {len(curve)} point(s) — cannot scan",
            value=None, detail={"n_points": len(curve)},
        )

    dates = [datetime.fromisoformat(str(p["date"])[:10]).date() for p in curve]
    equity = [float(p["equity"]) for p in curve]

    detail: dict = {"n_points": len(curve)}
    worst_by_window: dict[int, float] = {}
    for w in _DD_WINDOWS_DAYS:
        dd, trough_d, peak_d = _worst_window_drawdown(dates, equity, w)
        pct = abs(dd) * 100.0
        worst_by_window[w] = pct
        detail[f"worst_{w}d_dd_pct"] = round(pct, 2)
        detail[f"worst_{w}d_trough"] = trough_d.isoformat() if trough_d else None
        detail[f"worst_{w}d_peak"] = peak_d.isoformat() if peak_d else None

    # overall (all-time) max drawdown for context
    peak = equity[0]
    overall = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            overall = min(overall, (e - peak) / peak)
    detail["overall_max_dd_pct"] = round(abs(overall) * 100.0, 2)

    worst_14 = worst_by_window[_DD_WINDOWS_DAYS[0]]
    value = worst_by_window[_DD_WINDOWS_DAYS[1]]  # 3-week magnitude

    if worst_14 >= _DD_STRESS_FRAGILE_PCT:
        outcome = "fragile"
    elif worst_14 <= _DD_STRESS_ROBUST_PCT:
        outcome = "robust"
    else:
        outcome = "inconclusive"

    reason = (f"Worst 2wk drawdown {worst_14:.1f}%, 3wk {value:.1f}% "
              f"(all-time max {detail['overall_max_dd_pct']:.1f}%)")
    return ValidationSignal(
        name="drawdown_stress", outcome=outcome, reason=reason,
        value=round(value, 2), detail=detail,
    )


# ── Test 5: Volatility Bucketing (strategy's OWN ATR% from parquet) ──────────

OHLCVLoader = Callable[[str, str], Optional[pd.DataFrame]]


def _default_loader(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Read OHLCV from the Twelve Data → parquet cache ONLY. Never fetches —
    the single-data-source rule means a cache miss is just a cache miss."""
    return cache.read(symbol, timeframe)


def _pf(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl == 0.0:
        return PF_CAP if gp > 0 else 0.0
    return min(gp / gl, PF_CAP)


def volatility_bucketing(
    bt: BacktestResult,
    ohlcv_loader: Optional[OHLCVLoader] = None,
    n_buckets: int = _VOL_N_BUCKETS,
) -> ValidationSignal:
    """Bucket trades by the strategy's OWN realized volatility (ATR%) at entry,
    then report PF / win-rate per volatility regime.

    ATR% is the same `ATR_pct` strategies see (marketdata.enrich), computed from
    the symbol's cached parquet OHLCV — NO external VIX, NO fetch. A trade is
    placed in a low/medium/high ATR% tercile based on the ATR% on its entry bar.
    `value` = fraction of buckets that are profitable (PF >= 1); a concentrated
    edge (profitable in only one regime) reads fragile.
    """
    loader = ohlcv_loader or _default_loader

    # ATR%-at-entry per trade, loading each ticker's parquet once.
    atr_by_symbol: dict[str, pd.Series] = {}
    missing: set[str] = set()
    rows: list[tuple[float, float, float]] = []  # (atr_pct, pnl, pnl_pct)
    for t in bt.trades:
        sym = t.ticker.upper()
        if sym in missing:
            continue
        if sym not in atr_by_symbol:
            df = loader(sym, bt.timeframe)
            if df is None or getattr(df, "empty", True) or "Close" not in df:
                missing.add(sym)
                continue
            enr = enrich_with_indicators(df)
            s = (enr.assign(Date=pd.to_datetime(enr["Date"]))
                    .set_index("Date")["ATR_pct"].sort_index())
            atr_by_symbol[sym] = s
        atr_series = atr_by_symbol[sym]
        atr = atr_series.asof(pd.Timestamp(str(t.entry_date)[:10]))
        if atr is None or pd.isna(atr):
            continue
        rows.append((float(atr), t.pnl, t.pnl_pct))

    detail: dict = {
        "n_trades": len(bt.trades),
        "n_bucketable": len(rows),
        "symbols_missing_cache": sorted(missing),
        "buckets": [],
    }

    if not rows:
        return ValidationSignal(
            name="volatility_bucketing", outcome="inconclusive",
            reason=("No cached OHLCV for any traded symbol "
                    f"({len(missing)} symbol(s) missing) — cannot bucket"),
            value=None, detail=detail,
        )
    if len(rows) < _VOL_MIN_TRADES:
        return ValidationSignal(
            name="volatility_bucketing", outcome="inconclusive",
            reason=f"Only {len(rows)} bucketable trades (< {_VOL_MIN_TRADES})",
            value=None, detail=detail,
        )

    atr_vals = pd.Series([r[0] for r in rows])
    try:
        labels = pd.qcut(atr_vals, q=n_buckets, labels=False, duplicates="drop")
    except (ValueError, IndexError):
        labels = None
    if labels is None or labels.nunique() < 2:
        return ValidationSignal(
            name="volatility_bucketing", outcome="inconclusive",
            reason="ATR% too degenerate to split into volatility buckets",
            value=None, detail=detail,
        )

    n_actual = int(labels.max()) + 1
    edges = atr_vals.quantile([i / n_actual for i in range(n_actual + 1)]).tolist()
    buckets = []
    for b in range(n_actual):
        idx = [i for i in range(len(rows)) if labels.iloc[i] == b]
        pnls = [rows[i][1] for i in idx]
        wins = sum(1 for p in pnls if p > 0)
        buckets.append({
            "bucket": ["low", "medium", "high"][b] if n_actual == 3 else f"q{b+1}",
            "atr_pct_lo": round(float(edges[b]), 3),
            "atr_pct_hi": round(float(edges[b + 1]), 3),
            "n_trades": len(idx),
            "win_rate": round(wins / len(idx), 4) if idx else 0.0,
            "pf": round(_pf(pnls), 4),
            "avg_ret_pct": round(sum(rows[i][2] for i in idx) / len(idx), 4) if idx else 0.0,
        })
    detail["buckets"] = buckets

    n_profitable = sum(1 for b in buckets if b["pf"] >= 1.0)
    frac_profitable = n_profitable / n_actual
    pfs = [b["pf"] for b in buckets]
    spread = (min(pfs) / max(pfs)) if max(pfs) > 0 else 0.0
    detail["frac_profitable_buckets"] = round(frac_profitable, 4)
    detail["pf_spread_lo_hi"] = round(spread, 4)

    if frac_profitable >= 0.999:
        outcome = "robust"
    elif frac_profitable < 0.5:
        outcome = "fragile"
    else:
        outcome = "inconclusive"

    reason = (f"{n_profitable}/{n_actual} vol buckets profitable "
              f"({frac_profitable*100:.0f}%), PF spread lo/hi {spread:.2f}")
    return ValidationSignal(
        name="volatility_bucketing", outcome=outcome, reason=reason,
        value=round(frac_profitable, 4), detail=detail,
    )


# ── Orchestrator ─────────────────────────────────────────────────────────────

_TESTS = (win_loss_streak, expectancy_stability, pf_by_month,
          drawdown_stress, volatility_bucketing)


def run_validation_suite(bt: BacktestResult) -> ValidationReport:
    """Run all tier-1 validation tests over a backtest's trade ledger.

    Pure, synchronous, ledger-only. Returns a ValidationReport sibling to the
    robustness verdict — it is never passed to compute_verdict()."""
    return ValidationReport(
        strategy=bt.strategy,
        signals=[test(bt) for test in _TESTS],
    )
