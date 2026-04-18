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
