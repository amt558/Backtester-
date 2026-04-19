"""
QuantStats-based HTML tearsheet generation.

Takes any BacktestResult and produces a self-contained HTML file with
equity curve, drawdowns, monthly returns, Sharpe/Sortino, benchmark
comparison, and Monte Carlo risk analysis.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import get_config
from ..results import BacktestResult


def render_backtest_tearsheet(
    result: BacktestResult,
    output_path: Optional[Path] = None,
    benchmark_returns: Optional[pd.Series] = None,
    title: Optional[str] = None,
) -> Path:
    """
    Generate a QuantStats HTML tearsheet from a BacktestResult.

    Args:
        result: BacktestResult with equity_curve populated.
        output_path: Where to save the HTML. If None, auto-named under
                     reports_dir from config.
        benchmark_returns: Daily return series for benchmark (e.g. SPY).
                           If None, QuantStats runs without comparison.
        title: Report title. If None, uses strategy name + run date.

    Returns:
        Path to the generated HTML file.
    """
    # Import lazily so a missing quantstats only fails at report time, not
    # at module import time (useful during Session 1 when we just want the
    # CLI skeleton to load).
    try:
        import matplotlib
        matplotlib.use("Agg")
        import quantstats as qs
    except ImportError as e:
        raise ImportError(
            "quantstats not installed. Run: pip install quantstats"
        ) from e

    returns = result.daily_returns()
    if returns is None or len(returns) == 0:
        raise ValueError(
            f"Backtest '{result.strategy}' has no equity curve data; "
            "cannot generate tearsheet."
        )

    # Resolve output path
    if output_path is None:
        reports_dir = get_config().reports_path()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{result.strategy}_{stamp}.html"
        output_path = reports_dir / fname
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if title is None:
        title = f"{result.strategy} — tearsheet ({result.start_date} → {result.end_date})"

    # QuantStats is noisy about deprecation warnings from its seaborn deps.
    # Silence them during report generation.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        qs.reports.html(
            returns,
            benchmark=benchmark_returns,
            output=str(output_path),
            title=title,
            download_filename=output_path.name,
        )

    return output_path


def compute_quantstats_metrics(result: BacktestResult,
                                 benchmark_returns: Optional[pd.Series] = None) -> dict[str, float]:
    """
    Pull a comprehensive metric panel from QuantStats. Returns a flat dict
    of {metric_name: value} ready for tabular rendering. Returns {} if
    quantstats can't be imported or the equity curve is too short.
    """
    try:
        import quantstats as qs
    except ImportError:
        return {}

    returns = result.daily_returns()
    if returns is None or len(returns) < 30:
        return {}

    out: dict[str, float] = {}
    # Each tuple: (display_name, callable_on_returns)
    # We swallow per-metric errors so one bad metric doesn't kill the panel.
    metric_calls: list[tuple[str, callable]] = [
        ("CAGR",                lambda r: qs.stats.cagr(r) * 100),
        ("Sharpe",              lambda r: qs.stats.sharpe(r)),
        ("Sortino",             lambda r: qs.stats.sortino(r)),
        ("Smart Sharpe",        lambda r: qs.stats.smart_sharpe(r)),
        ("Smart Sortino",       lambda r: qs.stats.smart_sortino(r)),
        ("Calmar",              lambda r: qs.stats.calmar(r)),
        ("Omega",               lambda r: qs.stats.omega(r)),
        ("Profit factor",       lambda r: qs.stats.profit_factor(r)),
        ("Profit ratio",        lambda r: qs.stats.profit_ratio(r)),
        ("Common-sense ratio",  lambda r: qs.stats.common_sense_ratio(r)),
        ("CPC index",           lambda r: qs.stats.cpc_index(r)),
        ("Tail ratio",          lambda r: qs.stats.tail_ratio(r)),
        ("Payoff ratio",        lambda r: qs.stats.payoff_ratio(r)),
        ("Win rate %",          lambda r: qs.stats.win_rate(r) * 100),
        ("Win/loss ratio",      lambda r: qs.stats.win_loss_ratio(r)),
        ("Volatility (ann) %",  lambda r: qs.stats.volatility(r) * 100),
        ("VaR 95 % (daily)",    lambda r: qs.stats.value_at_risk(r) * 100),
        ("Expected shortfall %", lambda r: qs.stats.conditional_value_at_risk(r) * 100),
        ("Max drawdown %",      lambda r: qs.stats.max_drawdown(r) * 100),
        ("Avg drawdown %",      lambda r: qs.stats.to_drawdown_series(r).mean() * 100),
        ("Recovery factor",     lambda r: qs.stats.recovery_factor(r)),
        ("Risk of ruin %",      lambda r: qs.stats.risk_of_ruin(r) * 100),
        ("Ulcer index",         lambda r: qs.stats.ulcer_index(r)),
        ("Ulcer perf index",    lambda r: qs.stats.ulcer_performance_index(r)),
        ("Skew",                lambda r: qs.stats.skew(r)),
        ("Kurtosis",            lambda r: qs.stats.kurtosis(r)),
        ("Kelly criterion",     lambda r: qs.stats.kelly_criterion(r)),
        ("Best day %",          lambda r: qs.stats.best(r) * 100),
        ("Worst day %",         lambda r: qs.stats.worst(r) * 100),
        ("Avg return %",        lambda r: qs.stats.avg_return(r) * 100),
        ("Avg win %",           lambda r: qs.stats.avg_win(r) * 100),
        ("Avg loss %",          lambda r: qs.stats.avg_loss(r) * 100),
        ("Consecutive wins",    lambda r: qs.stats.consecutive_wins(r)),
        ("Consecutive losses",  lambda r: qs.stats.consecutive_losses(r)),
        ("Exposure %",          lambda r: qs.stats.exposure(r) * 100),
    ]
    for name, fn in metric_calls:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                v = fn(returns)
            if v is None:
                continue
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if vf == vf and abs(vf) < 1e15:    # NaN guard + sanity bound
                out[name] = vf
        except Exception:
            continue

    # Benchmark-relative metrics (only if benchmark provided)
    if benchmark_returns is not None and len(benchmark_returns) > 30:
        rel_calls: list[tuple[str, callable]] = [
            ("Alpha (vs bench)", lambda r, b: qs.stats.greeks(r, b).get("alpha", float("nan"))),
            ("Beta (vs bench)",  lambda r, b: qs.stats.greeks(r, b).get("beta", float("nan"))),
            ("Information ratio", lambda r, b: qs.stats.information_ratio(r, b)),
            ("R^2 vs bench",     lambda r, b: qs.stats.r_squared(r, b)),
        ]
        for name, fn in rel_calls:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    v = fn(returns, benchmark_returns)
                if v is None:
                    continue
                try:
                    vf = float(v)
                except (TypeError, ValueError):
                    continue
                if vf == vf and abs(vf) < 1e15:
                    out[name] = vf
            except Exception:
                continue

    return out


def smoke_test_tearsheet(output_path: Optional[Path] = None) -> Path:
    """
    Generate a tearsheet from synthetic random-walk returns.
    Used by `tradelab config --test-reports` to verify the reporting pipeline
    works without any real strategy code.
    """
    import numpy as np

    np.random.seed(42)
    # 500 days of daily returns with slight positive drift
    returns = pd.Series(
        np.random.normal(0.0008, 0.015, 500),
        index=pd.date_range("2024-01-01", periods=500, freq="B"),
        name="smoke_test",
    )

    # Build a minimal BacktestResult
    equity = 100_000.0 * (1 + returns).cumprod()
    equity_curve = [
        {"date": d.strftime("%Y-%m-%d"), "equity": float(v)}
        for d, v in equity.items()
    ]

    result = BacktestResult(
        strategy="smoke_test",
        start_date=str(returns.index[0].date()),
        end_date=str(returns.index[-1].date()),
        equity_curve=equity_curve,
    )

    if output_path is None:
        reports_dir = get_config().reports_path()
        output_path = reports_dir / "smoke_test_tearsheet.html"

    return render_backtest_tearsheet(result, output_path=output_path,
                                      title="Smoke-test tearsheet")
