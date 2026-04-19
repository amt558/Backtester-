"""
Cost-sensitivity sweep.

Re-runs a strategy at multiple commission levels to measure how much edge
is eaten by transaction costs. A strategy whose PF collapses from 1.6 to
0.9 between 1x and 2x commission is fragile to slippage/execution costs,
even if its baseline metrics look robust.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ..config import get_config
from ..results import BacktestMetrics
from .backtest import run_backtest


class CostSweepPoint(BaseModel):
    """One (commission_multiplier, metrics) observation from the sweep."""
    multiplier: float
    commission_per_trade: float
    metrics: BacktestMetrics


class CostSweepResult(BaseModel):
    """Aggregate output from running the strategy at several commission levels."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: str
    baseline_commission: float
    multipliers: list[float]
    points: list[CostSweepPoint]

    def to_table(self) -> pd.DataFrame:
        """Return a wide DataFrame suitable for reporting / plotting."""
        rows = []
        for p in self.points:
            m = p.metrics
            rows.append({
                "multiplier": p.multiplier,
                "commission_per_trade": p.commission_per_trade,
                "total_trades": m.total_trades,
                "profit_factor": m.profit_factor,
                "sharpe_ratio": m.sharpe_ratio,
                "pct_return": m.pct_return,
                "max_drawdown_pct": m.max_drawdown_pct,
                "final_equity": m.final_equity,
            })
        return pd.DataFrame(rows)


def run_cost_sweep(
    strategy,
    ticker_data,
    multipliers: Optional[list[float]] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> CostSweepResult:
    """
    Run the backtest once per commission multiplier, return a structured result.

    Args:
        strategy: instantiated Strategy
        ticker_data: enriched OHLCV dict
        multipliers: list of multipliers applied to the config's
            `defaults.commission_per_trade`. Default [0.0, 0.5, 1.0, 2.0, 4.0].
        spy_close: SPY close Series for RS-based strategies
        start, end: override config window

    Returns:
        CostSweepResult with one CostSweepPoint per multiplier.
    """
    cfg = get_config()
    base_commission = float(cfg.defaults.commission_per_trade)
    if multipliers is None:
        multipliers = [0.0, 0.5, 1.0, 2.0, 4.0]

    points: list[CostSweepPoint] = []
    for mult in multipliers:
        commission = base_commission * float(mult)
        bt = run_backtest(
            strategy, ticker_data,
            start=start, end=end,
            commission=commission,
            spy_close=spy_close,
        )
        points.append(CostSweepPoint(
            multiplier=float(mult),
            commission_per_trade=commission,
            metrics=bt.metrics,
        ))

    return CostSweepResult(
        strategy=strategy.name,
        baseline_commission=base_commission,
        multipliers=list(multipliers),
        points=points,
    )


def format_cost_sweep_markdown(result: CostSweepResult) -> str:
    """Render a cost-sweep result as a markdown section."""
    lines = [
        "## 8. Cost sensitivity sweep",
        "",
        f"Strategy re-evaluated across {len(result.points)} commission multipliers "
        f"of the baseline ${result.baseline_commission:.2f}/trade.",
        "",
        "| x | $/trade | Trades | PF | Sharpe | Return% | MaxDD% |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in result.points:
        m = p.metrics
        lines.append(
            f"| {p.multiplier:g}x | ${p.commission_per_trade:.2f} | {m.total_trades} "
            f"| {m.profit_factor} | {m.sharpe_ratio} | {m.pct_return}% | {m.max_drawdown_pct}% |"
        )
    lines.append("")
    return "\n".join(lines)
