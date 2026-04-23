"""Interactive HTML dashboard — single file, Plotly-powered, 3 tabs."""
from .builder import build_dashboard
from .compare import build_compare_report
from .index import build_index
from .overview import build_overview

__all__ = ["build_dashboard", "build_compare_report", "build_index",
            "build_overview"]
