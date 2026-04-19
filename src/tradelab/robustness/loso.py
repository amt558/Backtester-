"""
Leave-One-Symbol-Out (LOSO) cross-validation.

Drops each symbol (except the benchmark) from the universe in turn, re-runs
backtest (optionally with a fresh Optuna study per fold), and reports
per-fold metrics. High variance in OOS PF across folds means the strategy's
edge is concentrated in a few names.

Two modes:
- Fast (default, n_trials_per_fold=None): re-use the passed-in strategy's
  current params. Every fold uses the same (baseline) parameter set.
- Per-fold Optuna (n_trials_per_fold=N): run a fresh Optuna study on each
  fold's subset to find per-fold best params, then evaluate. Per master
  plan anti-drift rule: each fold owns its study; never share across folds.

The per-fold-Optuna version multiplies compute by roughly N_folds × n_trials.
It's the more rigorous test but expensive; leave it for serious promotion
decisions.
"""
from __future__ import annotations

import copy
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..engines.backtest import run_backtest
from ..results import BacktestMetrics


class LOSOFold(BaseModel):
    held_out_symbol: str
    metrics: BacktestMetrics
    best_params: dict = Field(default_factory=dict)   # populated only if Optuna ran per-fold


class LOSOResult(BaseModel):
    """Per-fold LOSO results + aggregate dispersion."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    folds: list[LOSOFold]
    pf_mean: float
    pf_min: float
    pf_max: float
    pf_spread: float   # max - min
    n_trials_per_fold: int = 0   # 0 = baseline params; positive = Optuna per fold


def run_loso(
    strategy,
    ticker_data,
    benchmark: str = "SPY",
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    n_trials_per_fold: Optional[int] = None,
    seed_base: int = 42,
) -> LOSOResult:
    """
    For each non-benchmark symbol, drop it and re-run backtest.

    Args:
        strategy: baseline strategy (its params are the reference point)
        ticker_data: enriched universe dict
        benchmark: symbol never dropped (needed for RS)
        n_trials_per_fold: if positive, run a fresh Optuna study per fold
            with that many trials. None/0 reuses baseline params.
        seed_base: base seed; each fold uses seed_base + fold_index so
            studies are deterministic and distinct.

    Returns:
        LOSOResult with per-fold metrics + aggregate PF dispersion.
    """
    symbols = [s for s in ticker_data.keys() if s != benchmark]

    # Lazy import — run_optimization imports optuna which is heavy
    run_optimization = None
    if n_trials_per_fold and n_trials_per_fold > 0:
        from ..engines.optimizer import run_optimization as _ro
        run_optimization = _ro

    folds: list[LOSOFold] = []
    baseline_params = dict(strategy.params)

    for fold_idx, held_out in enumerate(symbols):
        subset = {s: df for s, df in ticker_data.items() if s != held_out}
        if len(subset) < 2:
            continue   # need at least benchmark + 1 traded symbol

        if run_optimization is not None:
            # Fresh Optuna study on this fold's subset
            strat_copy = copy.copy(strategy)
            strat_copy.params = dict(baseline_params)
            opt = run_optimization(
                strat_copy, subset,
                n_trials=n_trials_per_fold,
                seed=seed_base + fold_idx,
                spy_close=spy_close,
                start=start, end=end,
                verbose=False,
                rerun_best=True,
            )
            if opt.best_backtest is not None:
                folds.append(LOSOFold(
                    held_out_symbol=held_out,
                    metrics=opt.best_backtest.metrics,
                    best_params=dict(opt.best_trial.params) if opt.best_trial else {},
                ))
                continue
            # Optuna found nothing usable; fall through to baseline backtest
        bt = run_backtest(
            strategy, subset,
            start=start, end=end, spy_close=spy_close,
        )
        folds.append(LOSOFold(
            held_out_symbol=held_out, metrics=bt.metrics, best_params={},
        ))

    if not folds:
        return LOSOResult(
            folds=[], pf_mean=0.0, pf_min=0.0, pf_max=0.0, pf_spread=0.0,
            n_trials_per_fold=int(n_trials_per_fold or 0),
        )

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
        n_trials_per_fold=int(n_trials_per_fold or 0),
    )
