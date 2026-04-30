"""
Pure functions for the Research v3 expanded-tile QuantStats sub-grid.

Inputs: a pandas Series of daily percentage returns (the same object
quantstats.reports.html consumes; produced by BacktestResult.daily_returns()).

No I/O. No file reads. No HTTP. Just numpy/pandas math.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANNUAL_TRADING_DAYS = 252


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    excess = returns - rf / ANNUAL_TRADING_DAYS
    return float(np.sqrt(ANNUAL_TRADING_DAYS) * excess.mean() / excess.std(ddof=0))


def sortino(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ANNUAL_TRADING_DAYS
    downside = excess[excess < 0]
    if downside.empty or downside.std(ddof=0) == 0:
        return 0.0
    return float(np.sqrt(ANNUAL_TRADING_DAYS) * excess.mean() / downside.std(ddof=0))


def cagr(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    total = (1.0 + returns).prod()
    years = len(returns) / ANNUAL_TRADING_DAYS
    if years <= 0 or total <= 0:
        return 0.0
    return float(total ** (1.0 / years) - 1.0)


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def monthly_returns_matrix(returns: pd.Series) -> pd.DataFrame:
    """
    Return a year × 12 matrix of monthly compounded returns.
    Rows = years (oldest first); columns = month numbers 1..12.
    Cells with no data become NaN.
    """
    if returns.empty:
        return pd.DataFrame()
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    df = monthly.to_frame("ret").assign(
        year=lambda x: x.index.year, month=lambda x: x.index.month
    )
    return df.pivot(index="year", columns="month", values="ret")


def rolling_sharpe(returns: pd.Series, window: int = 30) -> pd.Series:
    if returns.empty:
        return returns.copy()
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std(ddof=0)
    return np.sqrt(ANNUAL_TRADING_DAYS) * mean / std


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Per-bar peak-to-trough drawdown as a fraction (e.g. -0.12 = -12%).

    Aligned to the input index. Always 0 (peak) or negative (below peak).
    Used by the Research v3 expanded-tile drawdown SVG chart.
    """
    if returns.empty:
        return returns.copy()
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    return (equity - peak) / peak
