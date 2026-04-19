"""
Canary strategies — deliberately-broken strategies used to verify that
tradelab's robustness machinery correctly flags fragility.

These are NOT tradable strategies. Never register them in the production
strategy registry. Run monthly via `scripts/run_canaries.py` as a health
check on the tool itself.

If any canary produces a "ROBUST" verdict, tradelab is broken and all
recent strategy verdicts are suspect until root-caused.

See TRADELAB_MASTER_PLAN.md, Pre-Phase-0 Task 0.0.5 for design rationale.
"""
from .rand_canary import RandCanary
from .overfit_canary import OverfitCanary
from .leak_canary import LeakCanary
from .survivor_canary import SurvivorCanary

__all__ = ["RandCanary", "OverfitCanary", "LeakCanary", "SurvivorCanary"]
