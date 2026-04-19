"""
Leave-One-Symbol-Out (LOSO) cross-validation.

Drops each symbol (except the benchmark) from the universe in turn, re-runs
the baseline backtest, and reports per-fold metrics. High variance in OOS
PF across folds means the strategy's edge is concentrated in a few names.

Pragmatic reduction vs master plan: this version does NOT run a per-fold
Optuna study (plan calls that "critical"). Running Optuna per fold multiplies
compute by ~10x and is only meaningful when Optuna's best params are the
baseline — which requires feeding an OptunaResult through. Phase 1.1 can
upgrade this once the suite's integration-test pattern is proven.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..engines.backtest import run_backtest
from ..results import BacktestMetrics


class LOSOFold(BaseModel):
    held_out_symbol: str
    metrics: BacktestMetrics


class LOSOResult(BaseModel):
    """Per-fold LOSO results + aggregate dispersion."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    folds: list[LOSOFold]
    pf_mean: float
    pf_min: float
    pf_max: float
    pf_spread: float   # max - min


def run_loso(
    strategy,
    ticker_data,
    benchmark: str = "SPY",
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> LOSOResult:
    """
    For each non-benchmark symbol, drop it and re-run backtest.
    Returns per-fold metrics + aggregate PF dispersion.
    """
    symbols = [s for s in ticker_data.keys() if s != benchmark]

    folds: list[LOSOFold] = []
    for held_out in symbols:
        subset = {s: df for s, df in ticker_data.items() if s != held_out}
        if len(subset) < 2:
            continue   # need at least benchmark + 1 traded symbol
        bt = run_backtest(
            strategy, subset,
            start=start, end=end, spy_close=spy_close,
        )
        folds.append(LOSOFold(held_out_symbol=held_out, metrics=bt.metrics))

    if not folds:
        return LOSOResult(folds=[], pf_mean=0.0, pf_min=0.0, pf_max=0.0, pf_spread=0.0)

    pfs = [f.metrics.profit_factor for f in folds]
    pf_mean = sum(pfs) / len(pfs)
    pf_min = min(pfs)
    pf_max = max(pfs)
    return LOSOResult(
        folds=folds,
        pf_mean=pf_mean,
        pf_min=pf_min,
        pf_max=pf_max,
        pf_spread=pf_max - pf_min,
    )
