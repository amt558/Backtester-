"""Reporting — QuantStats-based HTML tearsheet + executive markdown report + robustness tearsheet."""

from .tearsheet import render_backtest_tearsheet, compute_quantstats_metrics
from .executive import generate_executive_report
from .robustness_tearsheet import render_robustness_tearsheet

__all__ = [
    "render_backtest_tearsheet", "compute_quantstats_metrics",
    "generate_executive_report",
    "render_robustness_tearsheet",
]
