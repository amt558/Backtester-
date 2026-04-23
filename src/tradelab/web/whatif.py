"""Single-symbol What-If backtest runner.

Loads a registered strategy, overrides params, runs one-symbol backtest
against the parquet cache, returns metrics + equity curve. Designed for
interactive slider debouncing on the Research tab modal.

Not for universe backtests — those go through `tradelab run` CLI.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from tradelab.engines.backtest import run_backtest
from tradelab.marketdata import cache
from tradelab.registry import instantiate_strategy, StrategyNotRegistered


class WhatIfError(Exception):
    pass


def _load_cached(symbols: list[str], timeframe: str) -> dict:
    """Read parquet cache for each symbol. Returns {symbol: df} (missing symbols omitted)."""
    data = {}
    for sym in symbols:
        df = cache.read(sym, timeframe)
        if df is not None and not df.empty:
            data[sym] = df
    return data


def run_whatif(
    strategy_name: str,
    symbol: str,
    params: dict,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """Run one-symbol backtest with param overrides.

    Args:
        strategy_name: registered strategy id
        symbol: single ticker, must be in parquet cache
        params: slider values; merged on top of strategy defaults
        start, end: optional date overrides; default to config window

    Returns:
        {metrics: {...}, equity_curve: [{date, equity}, ...]}

    Raises:
        WhatIfError on unknown strategy, missing data, or backtest failure.
    """
    try:
        strategy = instantiate_strategy(strategy_name, param_overrides=params)
    except StrategyNotRegistered as e:
        raise WhatIfError(f"strategy not registered: {e}") from e

    ticker_data = _load_cached([symbol], strategy.timeframe)
    if symbol not in ticker_data:
        raise WhatIfError(f"no data for {symbol} in parquet cache")

    spy_close = None
    if strategy.requires_benchmark:
        spy_data = _load_cached(["SPY"], strategy.timeframe)
        if "SPY" in spy_data:
            spy_close = spy_data["SPY"].set_index("Date")["Close"]

    try:
        result = run_backtest(
            strategy,
            ticker_data,
            start=start,
            end=end,
            spy_close=spy_close,
        )
    except Exception as e:
        raise WhatIfError(f"backtest failed: {e}") from e

    return {
        "metrics": _extract_metrics(result),
        "equity_curve": _extract_equity_curve(result),
        "params_used": dict(strategy.params),
    }


def _extract_metrics(result) -> dict:
    """Pull a stable subset of metrics from BacktestResult for the UI."""
    m = getattr(result, "metrics", None)
    if m is None:
        return {}
    # BacktestMetrics is a pydantic BaseModel — convert to dict.
    if hasattr(m, "model_dump"):
        m = m.model_dump()
    if not isinstance(m, dict):
        return {}
    return {
        "profit_factor": m.get("profit_factor"),
        "win_rate": m.get("win_rate"),
        "max_drawdown_pct": m.get("max_drawdown_pct"),
        "total_trades": m.get("total_trades"),
        "net_pnl": m.get("net_pnl"),
        "sharpe_ratio": m.get("sharpe_ratio"),
        "annual_return": m.get("annual_return"),
    }


def _extract_equity_curve(result) -> list[dict]:
    """Return equity curve as JSON-safe list of {date, equity} points."""
    curve = getattr(result, "equity_curve", None)
    if curve is None:
        return []
    if isinstance(curve, list) and curve and isinstance(curve[0], dict):
        return curve
    if isinstance(curve, pd.DataFrame):
        return [
            {"date": str(r["date"]), "equity": float(r["equity"])}
            for _, r in curve.iterrows()
        ]
    return []
