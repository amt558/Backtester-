"""Calibration utilities: §1 confound check, retrospective, hit-rate analysis.

Per the CALIBRATED v3 spec:
docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md
"""
from .retrospective import (
    run_retrospective_calibration,
    compute_per_strategy_outcomes,
    compute_per_signal_seed_hit_rates,
    load_predicted_verdict,
    RetrospectiveResult,
)
from .alpaca_trade_history import fetch_filled_orders, pair_buy_sell_into_trades
from .bot_log_attribution import parse_position_added_lines, attribute_trade

__all__ = [
    "run_retrospective_calibration", "compute_per_strategy_outcomes",
    "compute_per_signal_seed_hit_rates", "load_predicted_verdict",
    "RetrospectiveResult", "fetch_filled_orders", "pair_buy_sell_into_trades",
    "parse_position_added_lines", "attribute_trade",
]
