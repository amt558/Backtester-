"""Indicator primitives — shared library for strategies.

Exposes DeepVue-replicated indicators (originally from deepvue_mcp/indicators.py)
as the canonical implementations inside tradelab. Strategies and pre-filters
import from here; the MCP server can mirror or re-import.
"""
from .deepvue import (
    atr,
    atr_pct,
    adr_pct,
    sigma_spike,
    relative_measured_volatility,
    relative_strength,
    up_down_ratio,
    weinstein_stage,
    price_vs_ema,
    sma_alignment,
    dcr,
    wcr,
    relative_volume,
    volume_dry_up,
    pocket_pivot,
    open_equals_low,
    open_equals_high,
    buyable_gap_up,
    vcp_score,
    rs_new_high_before_price,
    minervini_trend_template,
    compute_all_indicators,
)

__all__ = [
    "atr", "atr_pct", "adr_pct", "sigma_spike",
    "relative_measured_volatility", "relative_strength", "up_down_ratio",
    "weinstein_stage", "price_vs_ema", "sma_alignment", "dcr", "wcr",
    "relative_volume", "volume_dry_up", "pocket_pivot",
    "open_equals_low", "open_equals_high", "buyable_gap_up",
    "vcp_score", "rs_new_high_before_price", "minervini_trend_template",
    "compute_all_indicators",
]
