"""
Robustness suite orchestrator — run all tests, aggregate into a verdict,
return a single structured result ready for reporting and dashboarding.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..engines.dsr import deflated_sharpe_ratio
from ..results import BacktestResult, OptunaResult, WalkForwardResult
from .entry_delay import EntryDelayResult, run_entry_delay
from .loso import LOSOResult, run_loso
from .monte_carlo import MonteCarloResult, run_monte_carlo
from .noise_injection import NoiseInjectionResult, run_noise_injection
from .param_landscape import ParamLandscapeResult, run_param_landscape
from .verdict import VerdictResult, compute_verdict


class RobustnessSuiteResult(BaseModel):
    """Bundle of all robustness outputs + the aggregate verdict."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: str
    dsr_probability: Optional[float] = None
    monte_carlo: Optional[MonteCarloResult] = None
    param_landscape: Optional[ParamLandscapeResult] = None
    entry_delay: Optional[EntryDelayResult] = None
    loso: Optional[LOSOResult] = None
    noise_injection: Optional[NoiseInjectionResult] = None
    verdict: VerdictResult


def run_robustness_suite(
    strategy,
    ticker_data,
    backtest_result: BacktestResult,
    optuna_result: Optional[OptunaResult] = None,
    wf_result: Optional[WalkForwardResult] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    mc_n_simulations: int = 500,
    landscape_grid_size: int = 5,
    loso_n_trials_per_fold: Optional[int] = None,
    noise_n_seeds: int = 50,
    noise_sigma_bp: float = 5.0,
    show_progress: bool = False,
    skip: Optional[list[str]] = None,
) -> RobustnessSuiteResult:
    """
    Run all robustness tests and aggregate into a verdict.

    Args:
        skip: list of test names to skip — one or more of
              ['monte_carlo', 'param_landscape', 'entry_delay', 'loso', 'noise'].
              Useful when iterating on reporting without waiting for the
              full suite to finish each time.
    """
    skip = set(skip or [])

    mc = None
    if "monte_carlo" not in skip:
        mc = run_monte_carlo(
            backtest_result, n_simulations=mc_n_simulations,
            progress=show_progress,
        )

    landscape = None
    if "param_landscape" not in skip and strategy.tunable_params:
        landscape = run_param_landscape(
            strategy, ticker_data,
            optuna_result=optuna_result, spy_close=spy_close,
            start=start, end=end, grid_size=landscape_grid_size,
        )

    ed = None
    if "entry_delay" not in skip:
        ed = run_entry_delay(
            strategy, ticker_data,
            spy_close=spy_close, start=start, end=end,
        )

    lo = None
    if "loso" not in skip:
        lo = run_loso(
            strategy, ticker_data,
            spy_close=spy_close, start=start, end=end,
            n_trials_per_fold=loso_n_trials_per_fold,
        )

    ni = None
    if "noise" not in skip:
        ni = run_noise_injection(
            strategy, ticker_data, backtest_result.metrics,
            n_seeds=noise_n_seeds, noise_sigma_bp=noise_sigma_bp,
            spy_close=spy_close, start=start, end=end,
        )

    # DSR (computed from the baseline equity curve; not a re-evaluation)
    returns = backtest_result.daily_returns()
    dsr = None
    if returns is not None and len(returns) >= 10:
        n_trials = optuna_result.n_trials if optuna_result else 1
        import math
        p = deflated_sharpe_ratio(returns.values, n_trials=n_trials)
        dsr = None if math.isnan(p) else float(p)

    verdict = compute_verdict(
        backtest_result,
        dsr=dsr, mc=mc, landscape=landscape,
        entry_delay=ed, loso=lo, wf=wf_result, noise=ni,
    )

    return RobustnessSuiteResult(
        strategy=backtest_result.strategy,
        dsr_probability=dsr,
        monte_carlo=mc,
        param_landscape=landscape,
        entry_delay=ed,
        loso=lo,
        noise_injection=ni,
        verdict=verdict,
    )
