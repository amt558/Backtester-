"""
Monte Carlo trade-order test — 3 resampling methods x 4 drawdown metrics.

The question: how unlucky was this specific ordering of winning and losing
trades? If the observed max drawdown is the 90th percentile of what you'd
expect from shuffling the trade sequence, the edge is path-dependent.

Methods:
  shuffle       — random permutation of trade P&L (preserves marginal dist)
  bootstrap     — sample with replacement (adds resampling noise)
  block_bootstrap — sample blocks of consecutive trades (preserves
                    local autocorrelation; block size = sqrt(n) heuristic)

Metrics (all computed on the cumulative-equity curve of each simulation):
  max_dd           — maximum peak-to-trough drawdown %
  max_loss_streak  — longest consecutive-losing-trades run
  time_underwater  — fraction of trades spent below previous equity peak
  ulcer_index      — sqrt(mean(drawdown_pct^2))
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..results import BacktestResult


class MCMetricDistribution(BaseModel):
    """One metric's distribution across N simulations for one resampling method."""
    metric: str
    method: str
    observed: float
    samples: list[float] = Field(default_factory=list)
    percentile_of_observed: float   # 0..100; where `observed` lands in the sim dist

    @property
    def mean(self) -> float:
        return float(np.mean(self.samples)) if self.samples else float("nan")

    @property
    def p5(self) -> float:
        return float(np.percentile(self.samples, 5)) if self.samples else float("nan")

    @property
    def p95(self) -> float:
        return float(np.percentile(self.samples, 95)) if self.samples else float("nan")


class MonteCarloResult(BaseModel):
    """Aggregate output for the full 3-methods x 4-metrics grid."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    n_simulations: int
    n_trades: int
    methods: list[str]
    metrics: list[str]
    distributions: list[MCMetricDistribution] = Field(default_factory=list)

    def get(self, method: str, metric: str) -> MCMetricDistribution:
        for d in self.distributions:
            if d.method == method and d.metric == metric:
                return d
        raise KeyError(f"No distribution for method={method} metric={metric}")


# --- helpers ---------------------------------------------------------------

def _cumulative_equity(pnls: np.ndarray, starting_equity: float = 100_000.0) -> np.ndarray:
    """Cumulative equity curve from a sequence of $-P&L per trade."""
    return starting_equity + np.cumsum(pnls)


def _max_drawdown_pct(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    drawdowns = (equity - peaks) / peaks * 100.0
    return float(drawdowns.min())


def _max_loss_streak(pnls: np.ndarray) -> int:
    if len(pnls) == 0:
        return 0
    losing = pnls <= 0
    best = 0
    cur = 0
    for x in losing:
        if x:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(best)


def _time_underwater(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    underwater = equity < peaks
    return float(underwater.sum() / len(equity))


def _ulcer_index(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    dd_pct = (equity - peaks) / peaks * 100.0
    return float(math.sqrt(np.mean(dd_pct ** 2)))


METRIC_FUNCS = {
    "max_dd":         lambda pnls, eq: _max_drawdown_pct(eq),
    "max_loss_streak": lambda pnls, eq: float(_max_loss_streak(pnls)),
    "time_underwater": lambda pnls, eq: _time_underwater(eq),
    "ulcer_index":     lambda pnls, eq: _ulcer_index(eq),
}


def _resample(pnls: np.ndarray, method: str, rng: np.random.Generator) -> np.ndarray:
    if method == "shuffle":
        idx = rng.permutation(len(pnls))
        return pnls[idx]
    if method == "bootstrap":
        idx = rng.integers(0, len(pnls), size=len(pnls))
        return pnls[idx]
    if method == "block_bootstrap":
        n = len(pnls)
        block = max(1, int(round(math.sqrt(n))))
        nblocks = n // block + 1
        starts = rng.integers(0, max(1, n - block + 1), size=nblocks)
        pieces = [pnls[s:s + block] for s in starts]
        out = np.concatenate(pieces)[:n]
        return out
    raise ValueError(f"Unknown resampling method: {method}")


# --- public API -----------------------------------------------------------

def run_monte_carlo(
    bt: BacktestResult,
    n_simulations: int = 500,
    methods: list[str] = None,
    metrics: list[str] = None,
    seed: int = 101,
    starting_equity: float = 100_000.0,
    progress: bool = False,
) -> MonteCarloResult:
    """
    Resample the trade P&L sequence N times per method and compute each
    drawdown metric's distribution under the resampling null. Return the
    observed value's percentile in each distribution.

    Args:
        bt: baseline BacktestResult — the trade sequence to perturb.
        n_simulations: number of resamples per method.
        methods: default ['shuffle','bootstrap','block_bootstrap'].
        metrics: default ['max_dd','max_loss_streak','time_underwater','ulcer_index'].
        seed: reproducibility seed for the RNG.
        starting_equity: starting cash for cumulative-equity curve.
    """
    if methods is None:
        methods = ["shuffle", "bootstrap", "block_bootstrap"]
    if metrics is None:
        metrics = list(METRIC_FUNCS.keys())

    pnls = np.array([t.pnl for t in bt.trades], dtype=float)
    n_trades = len(pnls)

    # Observed metrics (from actual trade sequence)
    obs_eq = _cumulative_equity(pnls, starting_equity)
    observed = {m: METRIC_FUNCS[m](pnls, obs_eq) for m in metrics}

    distributions: list[MCMetricDistribution] = []
    if n_trades < 2:
        # Degenerate — produce empty distributions so the report just shows dashes
        for method in methods:
            for metric in metrics:
                distributions.append(MCMetricDistribution(
                    metric=metric, method=method,
                    observed=observed.get(metric, 0.0),
                    samples=[], percentile_of_observed=float("nan"),
                ))
        return MonteCarloResult(
            n_simulations=0, n_trades=n_trades,
            methods=methods, metrics=metrics,
            distributions=distributions,
        )

    rng = np.random.default_rng(seed)

    # Optional Rich progress bar
    pbar_ctx = None
    if progress:
        try:
            from rich.progress import Progress
            pbar_ctx = Progress()
            pbar_ctx.start()
            task_ids = {m: pbar_ctx.add_task(f"MC {m}", total=n_simulations) for m in methods}
        except Exception:
            pbar_ctx = None

    for method in methods:
        sims: dict[str, list[float]] = {m: [] for m in metrics}
        for _ in range(n_simulations):
            resampled = _resample(pnls, method, rng)
            eq = _cumulative_equity(resampled, starting_equity)
            for m in metrics:
                sims[m].append(METRIC_FUNCS[m](resampled, eq))
            if pbar_ctx is not None:
                pbar_ctx.update(task_ids[method], advance=1)

        for metric in metrics:
            samples = sims[metric]
            obs = observed[metric]
            # Percentile: fraction of samples <= observed, x 100
            if samples:
                pct = 100.0 * float(np.mean([s <= obs for s in samples]))
            else:
                pct = float("nan")
            distributions.append(MCMetricDistribution(
                metric=metric, method=method,
                observed=float(obs),
                samples=samples,
                percentile_of_observed=pct,
            ))

    if pbar_ctx is not None:
        pbar_ctx.stop()

    return MonteCarloResult(
        n_simulations=n_simulations, n_trades=n_trades,
        methods=methods, metrics=metrics,
        distributions=distributions,
    )
