"""
Validation suite — parallel, report-only layer beside the robustness verdict.

This package NEVER feeds compute_verdict() and is never a member of
VerdictResult / RobustnessSuiteResult. See suite.py for the rationale (the
verdict aggregation is asymmetric; adding signals would re-weight locked
baselines). Promotion of any test into the verdict is a separate, explicit,
versioned decision.

Tier 1 (ledger-only, sync): win_loss_streak, expectancy_stability, pf_by_month.
Tier 2 (equity/parquet, sync): drawdown_stress, volatility_bucketing.
Tier 3 (engine re-runs, opt-in): cost_sensitivity, random_entry_benchmark.
"""
from .deep import (
    cost_sensitivity,
    gate_contribution_isolation,
    random_entry_benchmark,
    run_validation_suite_deep,
)
from .suite import (
    SUITE_VERSION,
    ValidationReport,
    ValidationSignal,
    drawdown_stress,
    expectancy_stability,
    pf_by_month,
    run_validation_suite,
    volatility_bucketing,
    win_loss_streak,
)

__all__ = [
    "SUITE_VERSION",
    "ValidationReport",
    "ValidationSignal",
    "cost_sensitivity",
    "drawdown_stress",
    "expectancy_stability",
    "gate_contribution_isolation",
    "pf_by_month",
    "random_entry_benchmark",
    "run_validation_suite",
    "run_validation_suite_deep",
    "volatility_bucketing",
    "win_loss_streak",
]
