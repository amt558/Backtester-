"""Orchestrator: CSV-derived trades → verdict + report folder + audit row.

The single entry point that callers (CLI, dashboard backend) use:

    parsed = parse_tv_trades_csv(csv_text, symbol="AMZN")
    out = score_trades(parsed, strategy_name="viprasol-amzn-v1", symbol="AMZN")
    folder = write_report_folder(out, base_name="viprasol-amzn-v1",
                                 pine_source=None, csv_text=csv_text)

Degraded relative to `tradelab run`:
  - no Optuna / WF / param landscape / entry delay / noise / LOSO
  - DSR uses n_trials=1
  - dashboard.html still renders, but several tabs will be empty
  - regime breakdown empty (no SPY data)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .engines._diagnostics import compute_monthly_pnl, metrics_from_trades
from .engines.dsr import classify_dsr, deflated_sharpe_ratio
from .io.tv_csv import ParsedTradesCSV
from .results import BacktestResult
from .robustness.monte_carlo import MonteCarloResult, run_monte_carlo
from .robustness.verdict import VerdictResult, compute_verdict


@dataclass
class CSVScoringOutput:
    backtest_result: BacktestResult
    dsr_probability: Optional[float]
    monte_carlo: Optional[MonteCarloResult]
    verdict: VerdictResult


def build_backtest_result_from_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
) -> BacktestResult:
    metrics = metrics_from_trades(parsed.trades, starting_equity=starting_equity)

    # Equity curve, one point per trade exit (good enough for QuantStats /
    # DSR resampling — shorter than a daily-bar curve but sufficient).
    equity = starting_equity
    curve: list[dict] = []
    for t in parsed.trades:
        equity += t.pnl
        curve.append({"date": t.exit_date, "equity": round(equity, 2)})

    # Annualize using calendar days in the window.
    try:
        d0 = datetime.strptime(parsed.start_date, "%Y-%m-%d")
        d1 = datetime.strptime(parsed.end_date, "%Y-%m-%d")
        days = max((d1 - d0).days, 1)
        if metrics.final_equity > 0 and starting_equity > 0:
            growth = metrics.final_equity / starting_equity
            ann = (growth ** (365.0 / days) - 1.0) * 100.0
            metrics = metrics.model_copy(update={"annual_return": round(ann, 3)})
    except (ValueError, OverflowError):
        pass

    monthly = compute_monthly_pnl(parsed.trades)

    return BacktestResult(
        strategy=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        params={},
        metrics=metrics,
        trades=list(parsed.trades),
        equity_curve=curve,
        regime_breakdown={},
        monthly_pnl=monthly,
    )


def score_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
    mc_simulations: int = 500,
) -> CSVScoringOutput:
    bt = build_backtest_result_from_trades(
        parsed, strategy_name=strategy_name, symbol=symbol,
        timeframe=timeframe, starting_equity=starting_equity,
    )

    # DSR on the trade-exit equity curve. Returns NaN for very short series.
    dsr_p: Optional[float] = None
    returns = bt.daily_returns()
    if returns is not None and len(returns) >= 2:
        p = deflated_sharpe_ratio(returns.values, n_trials=1)
        if not math.isnan(p):
            dsr_p = float(p)

    # MC: shuffles trade pnls; needs trades but no bar data.
    mc = None
    if bt.trades:
        try:
            mc = run_monte_carlo(bt, n_simulations=mc_simulations,
                                 starting_equity=starting_equity)
        except Exception:
            mc = None

    verdict = compute_verdict(bt, dsr=dsr_p, mc=mc)

    return CSVScoringOutput(
        backtest_result=bt,
        dsr_probability=dsr_p,
        monte_carlo=mc,
        verdict=verdict,
    )
