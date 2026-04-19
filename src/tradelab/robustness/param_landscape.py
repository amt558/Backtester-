"""
Parameter landscape test — 5x5 joint grid on the two most-important params.

Why this and not Optuna importance alone: Optuna tells you which params
*matter* for the fitness metric, but it doesn't tell you whether the best
point is a cliff or a plateau. A cliff (fitness collapses when you nudge the
best params by one grid step) is overfit; a plateau is robust.

Smoothness ratio: stdev of fitness across the grid divided by the best
fitness. High ratios (> 0.3) mean the landscape is rough; low ratios (< 0.1)
mean the landscape is smooth enough that the best point generalises.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..engines.backtest import run_backtest
from ..results import BacktestResult, OptunaResult


class ParamLandscapeResult(BaseModel):
    """Output of the parameter-landscape joint grid scan."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    top_params: list[str]            # names of the 2 params varied
    grid_values: list[list[float]]   # [param0_values, param1_values]
    fitness_grid: list[list[float]]  # fitness_grid[i][j] = fitness at (param0_values[i], param1_values[j])
    best_fitness: float
    mean_fitness: float
    std_fitness: float
    smoothness_ratio: float          # std / best, lower = smoother
    cliff_flag: bool                 # True if best neighbour drops > 50%


def _compute_fitness(bt: BacktestResult, min_trades: int = 5) -> float:
    """Same formula tradelab uses for Optuna: PF * sqrt(trades) * (1 - |DD|/100)."""
    import math
    m = bt.metrics
    if m.total_trades < min_trades:
        return 0.0
    dd_penalty = max(0.0, 1.0 - abs(m.max_drawdown_pct) / 100.0)
    return float(m.profit_factor * math.sqrt(m.total_trades) * dd_penalty)


def _neighbour_fitness_drop(fitness: np.ndarray, i: int, j: int) -> float:
    """Largest drop to any orthogonal neighbour, as a fraction of the centre."""
    centre = fitness[i, j]
    if centre <= 0:
        return 0.0
    neighbours = []
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ni, nj = i + di, j + dj
        if 0 <= ni < fitness.shape[0] and 0 <= nj < fitness.shape[1]:
            neighbours.append(fitness[ni, nj])
    if not neighbours:
        return 0.0
    worst = min(neighbours)
    return float((centre - worst) / centre)


def _pick_top_two_params(strategy, opt: Optional[OptunaResult]) -> list[str]:
    """Return names of the 2 most-important params. Fall back to first 2 tunables."""
    if opt and opt.param_importance:
        ranked = sorted(opt.param_importance.items(), key=lambda kv: kv[1], reverse=True)
        names = [n for n, _ in ranked[:2]]
        if len(names) == 2:
            return names
    tunables = list(strategy.tunable_params.keys())
    return tunables[:2]


def run_param_landscape(
    strategy,
    ticker_data,
    optuna_result: Optional[OptunaResult] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    grid_size: int = 5,
) -> ParamLandscapeResult:
    """
    Run an N x N backtest grid on the 2 most-important params.

    Args:
        strategy: instantiated Strategy (with its current params used as the grid centre)
        ticker_data: enriched OHLCV dict
        optuna_result: optional — if provided, the top-2 important params are picked
            from here; otherwise the first 2 entries in strategy.tunable_params are used
        grid_size: grid dimension; 5 → 25 backtests
    """
    top_params = _pick_top_two_params(strategy, optuna_result)
    if len(top_params) < 2:
        # Nothing tunable — return an empty result
        return ParamLandscapeResult(
            top_params=top_params,
            grid_values=[[], []],
            fitness_grid=[],
            best_fitness=0.0, mean_fitness=0.0, std_fitness=0.0,
            smoothness_ratio=0.0, cliff_flag=False,
        )

    # Grid values: take the strategy's tunable_params bounds (if present),
    # else a symmetric window around the current value
    axes: list[np.ndarray] = []
    for name in top_params:
        bounds = strategy.tunable_params.get(name)
        current = float(strategy.params.get(name, 1.0))
        if bounds:
            low, high = bounds
            axes.append(np.linspace(float(low), float(high), grid_size))
        else:
            span = max(abs(current) * 0.5, 0.5)
            axes.append(np.linspace(current - span, current + span, grid_size))

    fitness = np.zeros((grid_size, grid_size), dtype=float)
    # Re-run backtest at each grid cell with the 2 params overridden
    baseline_params = dict(strategy.params)
    for i, v0 in enumerate(axes[0]):
        for j, v1 in enumerate(axes[1]):
            strategy.params = {**baseline_params,
                               top_params[0]: float(v0),
                               top_params[1]: float(v1)}
            bt = run_backtest(strategy, ticker_data,
                              start=start, end=end, spy_close=spy_close)
            fitness[i, j] = _compute_fitness(bt)

    # Restore
    strategy.params = baseline_params

    best = float(fitness.max())
    mean = float(fitness.mean())
    std = float(fitness.std())
    smoothness = (std / best) if best > 0 else 0.0

    # Cliff flag: if best cell has any neighbour where fitness drops > 50%
    bi, bj = np.unravel_index(fitness.argmax(), fitness.shape)
    drop = _neighbour_fitness_drop(fitness, int(bi), int(bj))
    cliff = drop > 0.50

    return ParamLandscapeResult(
        top_params=top_params,
        grid_values=[axes[0].tolist(), axes[1].tolist()],
        fitness_grid=fitness.tolist(),
        best_fitness=best, mean_fitness=mean, std_fitness=std,
        smoothness_ratio=smoothness, cliff_flag=cliff,
    )
