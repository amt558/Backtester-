"""
Robustness suite — what Optuna cannot verify.

Five tests that together answer "is the edge real, or did we just get lucky?"
Optuna finds the best parameter set; robustness verifies that best is real.

- monte_carlo: perturb the trade sequence 3 different ways; see how far
  observed drawdown / loss streak / time underwater / ulcer index lie
  in their simulated null distributions
- param_landscape: 5x5 grid on the two most-important parameters; flag
  strategies whose edge vanishes when you nudge params
- entry_delay: re-run with signals shifted 0/+1/+2 bars; strategies that
  need exact timing are leak-prone
- loso: drop each symbol in turn; flag strategies whose edge depends on
  a single name

verdict: rule-based aggregator into ROBUST / INCONCLUSIVE / FRAGILE.
"""
from .entry_delay import EntryDelayResult, run_entry_delay
from .loso import LOSOResult, run_loso
from .monte_carlo import MonteCarloResult, run_monte_carlo
from .noise_injection import NoiseInjectionResult, run_noise_injection
from .param_landscape import ParamLandscapeResult, run_param_landscape
from .suite import RobustnessSuiteResult, run_robustness_suite
from .verdict import compute_verdict, VerdictResult

__all__ = [
    "EntryDelayResult", "run_entry_delay",
    "LOSOResult", "run_loso",
    "MonteCarloResult", "run_monte_carlo",
    "NoiseInjectionResult", "run_noise_injection",
    "ParamLandscapeResult", "run_param_landscape",
    "RobustnessSuiteResult", "run_robustness_suite",
    "VerdictResult", "compute_verdict",
]
