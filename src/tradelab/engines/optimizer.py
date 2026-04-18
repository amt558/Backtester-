"""
Optuna optimizer engine.

Port of C:/TradingScripts/s2_optuna.py. Strategy-agnostic — uses each
strategy's `tunable_params` dict to define the search space, so this works
for S2 today and any future strategy that declares its ranges.

Returns OptunaResult (Pydantic) rather than a raw study object.
"""
from __future__ import annotations

import copy
from typing import Optional

import numpy as np
import optuna

from ..config import get_config
from ..results import OptunaResult, OptunaTrial, BacktestResult
from .backtest import run_backtest


def _fitness(metrics) -> float:
    """
    Fitness = PF * sqrt(trades) * (1 - |DD|/100)
    Zero if trades < min_trades threshold or PF invalid.
    Caps PF at 10 to prevent outlier domination.
    """
    cfg = get_config()
    min_trades = cfg.optuna.min_trades_threshold

    n_trades = metrics.total_trades
    if n_trades < min_trades:
        return 0.0

    pf = metrics.profit_factor
    if pf <= 0 or not np.isfinite(pf):
        return 0.0
    pf = min(pf, 10.0)

    max_dd = abs(metrics.max_drawdown_pct)
    dd_penalty = max(0.0, 1 - min(max_dd, 99.0) / 100)

    return float(pf * np.sqrt(n_trades) * dd_penalty)


def _suggest_params(trial: optuna.Trial, tunable: dict[str, tuple[float, float]]) -> dict:
    """Draw one parameter set from a trial using the strategy's declared ranges."""
    return {
        name: trial.suggest_float(name, lo, hi)
        for name, (lo, hi) in tunable.items()
    }


def _objective(trial, base_strategy, ticker_data, spy_close, start, end):
    """One Optuna trial: backtest with suggested params, return fitness."""
    # Clone the strategy so the base object's params aren't mutated across trials
    strat = copy.copy(base_strategy)
    strat.params = {**base_strategy.params, **_suggest_params(trial, base_strategy.tunable_params)}

    try:
        result = run_backtest(
            strat, ticker_data, start=start, end=end, spy_close=spy_close,
        )
    except Exception as e:
        trial.set_user_attr("error", str(e)[:100])
        return 0.0

    # Stash metrics on the trial for downstream reporting
    m = result.metrics
    trial.set_user_attr("pf", m.profit_factor)
    trial.set_user_attr("trades", m.total_trades)
    trial.set_user_attr("wins", m.wins)
    trial.set_user_attr("losses", m.losses)
    trial.set_user_attr("win_rate", m.win_rate)
    trial.set_user_attr("max_dd", m.max_drawdown_pct)
    trial.set_user_attr("annual_return", m.annual_return)
    trial.set_user_attr("pct_return", m.pct_return)
    trial.set_user_attr("sharpe", m.sharpe_ratio)
    trial.set_user_attr("avg_win_pct", m.avg_win_pct)
    trial.set_user_attr("avg_loss_pct", m.avg_loss_pct)
    trial.set_user_attr("avg_bars_held", m.avg_bars_held)

    return _fitness(m)


def run_optimization(
    strategy,
    ticker_data,
    n_trials: Optional[int] = None,
    seed: Optional[int] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    verbose: bool = True,
    rerun_best: bool = True,
) -> OptunaResult:
    """
    Run Optuna study over strategy.tunable_params.

    Args:
        strategy: instantiated Strategy
        ticker_data: loaded universe
        n_trials: override optuna.n_trials_default from config
        seed: override optuna.seed from config
        spy_close: benchmark close series
        start, end: backtest window
        verbose: show Optuna progress bar
        rerun_best: if True, re-runs a full BacktestResult with best params
                    and attaches it to OptunaResult.best_backtest

    Returns:
        OptunaResult with best trial, all trials, param importance, and
        optionally the full backtest of the best parameter set.
    """
    cfg = get_config()
    n_trials = n_trials or cfg.optuna.n_trials_default
    seed = seed if seed is not None else cfg.optuna.seed

    if not strategy.tunable_params:
        raise ValueError(
            f"Strategy {strategy.name!r} declares no tunable_params — nothing to optimize."
        )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        study_name=strategy.name,
    )

    study.optimize(
        lambda trial: _objective(trial, strategy, ticker_data, spy_close, start, end),
        n_trials=n_trials,
        show_progress_bar=verbose,
    )

    # Convert all trials to Pydantic
    all_trials = []
    for t in study.trials:
        if t.value is None:
            continue
        all_trials.append(OptunaTrial(
            number=t.number,
            fitness=float(t.value),
            params=dict(t.params),
            metrics=dict(t.user_attrs),
        ))

    # Best trial
    best_t = study.best_trial
    best_trial = OptunaTrial(
        number=best_t.number,
        fitness=float(best_t.value) if best_t.value is not None else 0.0,
        params=dict(best_t.params),
        metrics=dict(best_t.user_attrs),
    )

    # Param importances (may fail if all trials produced identical fitness)
    importance: dict[str, float] = {}
    try:
        raw = optuna.importance.get_param_importances(study)
        importance = {k: float(v) for k, v in raw.items()}
    except Exception:
        pass

    # Optionally re-run with best params to get a full BacktestResult
    best_backtest: Optional[BacktestResult] = None
    if rerun_best and best_t.value and best_t.value > 0:
        best_strat = copy.copy(strategy)
        best_strat.params = {**strategy.params, **best_trial.params}
        best_backtest = run_backtest(
            best_strat, ticker_data, start=start, end=end, spy_close=spy_close,
        )

    return OptunaResult(
        strategy=strategy.name,
        n_trials=n_trials,
        best_trial=best_trial,
        all_trials=all_trials,
        param_importance=importance,
        best_backtest=best_backtest,
    )