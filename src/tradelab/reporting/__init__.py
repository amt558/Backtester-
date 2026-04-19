"""Reporting — QuantStats-based HTML tearsheet + executive markdown report."""

from .tearsheet import render_backtest_tearsheet
from .executive import generate_executive_report

__all__ = ["render_backtest_tearsheet", "generate_executive_report"]
