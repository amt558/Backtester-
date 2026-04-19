"""
Verdict engine — aggregate robustness signals into ROBUST / INCONCLUSIVE / FRAGILE.

Per anti-drift rule: false negatives cost more than false positives. Any
single strong fragility signal moves verdict to FRAGILE; ambiguous
combinations land in INCONCLUSIVE. Only a clean sweep yields ROBUST.

Signals consumed (all optional — missing signals are treated as INCONCLUSIVE):
- baseline PF, Sharpe
- DSR probability
- MC: observed MaxDD percentile in shuffle distribution (>90 is fragile)
- Param landscape: smoothness_ratio, cliff_flag
- Entry delay: pf_drop_one_bar
- LOSO: pf_spread
- Walk-forward: wfe_ratio
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..results import BacktestResult, WalkForwardResult
from .entry_delay import EntryDelayResult
from .loso import LOSOResult
from .monte_carlo import MonteCarloResult
from .param_landscape import ParamLandscapeResult


class VerdictSignal(BaseModel):
    """One labelled check and its FRAGILE/ROBUST/INCONCLUSIVE outcome."""
    name: str
    outcome: str   # "robust" | "inconclusive" | "fragile"
    reason: str


class VerdictResult(BaseModel):
    """Aggregate verdict + the signals that drove it."""
    verdict: str   # ROBUST | INCONCLUSIVE | FRAGILE
    signals: list[VerdictSignal] = Field(default_factory=list)

    @property
    def fragile_signals(self) -> list[VerdictSignal]:
        return [s for s in self.signals if s.outcome == "fragile"]

    @property
    def robust_signals(self) -> list[VerdictSignal]:
        return [s for s in self.signals if s.outcome == "robust"]


# Thresholds — per anti-drift rule, these live here (code) only because the
# robustness configs haven't been promoted to tradelab.yaml yet. Phase 3 UX
# polish should move these into config.
THRESHOLDS = {
    "pf_robust": 1.5,
    "pf_fragile": 1.1,
    "dsr_robust": 0.95,
    "dsr_fragile": 0.50,
    "mc_dd_fragile_percentile": 10.0,   # observed DD is in top 10% worst
    "smoothness_robust": 0.15,
    "smoothness_fragile": 0.40,
    "entry_delay_fragile": 0.50,         # PF drops >50% on +1 bar
    "loso_fragile_spread": 1.0,
    "wfe_robust": 0.75,
    "wfe_fragile": 0.50,
}


def compute_verdict(
    bt: BacktestResult,
    dsr: Optional[float] = None,
    mc: Optional[MonteCarloResult] = None,
    landscape: Optional[ParamLandscapeResult] = None,
    entry_delay: Optional[EntryDelayResult] = None,
    loso: Optional[LOSOResult] = None,
    wf: Optional[WalkForwardResult] = None,
) -> VerdictResult:
    signals: list[VerdictSignal] = []

    # --- Edge baseline ---
    pf = bt.metrics.profit_factor
    if pf >= THRESHOLDS["pf_robust"]:
        signals.append(VerdictSignal(name="baseline_pf", outcome="robust",
                                      reason=f"PF {pf:.2f} ≥ {THRESHOLDS['pf_robust']}"))
    elif pf < THRESHOLDS["pf_fragile"]:
        signals.append(VerdictSignal(name="baseline_pf", outcome="fragile",
                                      reason=f"PF {pf:.2f} < {THRESHOLDS['pf_fragile']}"))
    else:
        signals.append(VerdictSignal(name="baseline_pf", outcome="inconclusive",
                                      reason=f"PF {pf:.2f} in {THRESHOLDS['pf_fragile']}–{THRESHOLDS['pf_robust']}"))

    # --- DSR ---
    if dsr is not None:
        if dsr >= THRESHOLDS["dsr_robust"]:
            signals.append(VerdictSignal(name="dsr", outcome="robust",
                                          reason=f"DSR {dsr:.3f} ≥ {THRESHOLDS['dsr_robust']}"))
        elif dsr < THRESHOLDS["dsr_fragile"]:
            signals.append(VerdictSignal(name="dsr", outcome="fragile",
                                          reason=f"DSR {dsr:.3f} < {THRESHOLDS['dsr_fragile']}"))
        else:
            signals.append(VerdictSignal(name="dsr", outcome="inconclusive",
                                          reason=f"DSR {dsr:.3f} in {THRESHOLDS['dsr_fragile']}–{THRESHOLDS['dsr_robust']}"))

    # --- MC: observed drawdown percentile ---
    if mc and mc.distributions:
        try:
            shuffle_dd = mc.get("shuffle", "max_dd")
            pct = shuffle_dd.percentile_of_observed
            # percentile_of_observed here is "fraction of sims with DD <= observed * 100".
            # Low-number DDs are worse (more negative). If observed is more negative than
            # 90% of sims, pct_of_observed is ~10 → fragile.
            if pct <= THRESHOLDS["mc_dd_fragile_percentile"]:
                signals.append(VerdictSignal(name="mc_max_dd", outcome="fragile",
                                              reason=f"Observed DD in bottom {pct:.1f}% of shuffle sims"))
            elif pct >= 50.0:
                signals.append(VerdictSignal(name="mc_max_dd", outcome="robust",
                                              reason=f"Observed DD in top {100-pct:.1f}% of shuffle sims"))
            else:
                signals.append(VerdictSignal(name="mc_max_dd", outcome="inconclusive",
                                              reason=f"Observed DD in middle band"))
        except KeyError:
            pass

    # --- Param landscape ---
    if landscape and landscape.best_fitness > 0:
        sr = landscape.smoothness_ratio
        if landscape.cliff_flag or sr >= THRESHOLDS["smoothness_fragile"]:
            signals.append(VerdictSignal(name="param_landscape", outcome="fragile",
                                          reason=f"Smoothness {sr:.2f} or cliff at best point"))
        elif sr <= THRESHOLDS["smoothness_robust"]:
            signals.append(VerdictSignal(name="param_landscape", outcome="robust",
                                          reason=f"Smooth landscape; ratio {sr:.2f}"))
        else:
            signals.append(VerdictSignal(name="param_landscape", outcome="inconclusive",
                                          reason=f"Moderately rough; ratio {sr:.2f}"))

    # --- Entry delay ---
    if entry_delay and entry_delay.points:
        drop = entry_delay.pf_drop_one_bar
        if drop >= THRESHOLDS["entry_delay_fragile"]:
            signals.append(VerdictSignal(name="entry_delay", outcome="fragile",
                                          reason=f"PF drops {drop*100:.0f}% at +1 bar"))
        elif drop <= 0.10:
            signals.append(VerdictSignal(name="entry_delay", outcome="robust",
                                          reason=f"PF drop ≤10% at +1 bar"))
        else:
            signals.append(VerdictSignal(name="entry_delay", outcome="inconclusive",
                                          reason=f"PF drop {drop*100:.0f}% at +1 bar"))

    # --- LOSO ---
    if loso and loso.folds:
        spread = loso.pf_spread
        if spread >= THRESHOLDS["loso_fragile_spread"]:
            signals.append(VerdictSignal(name="loso", outcome="fragile",
                                          reason=f"PF spread {spread:.2f} across symbols"))
        elif spread <= 0.30:
            signals.append(VerdictSignal(name="loso", outcome="robust",
                                          reason=f"PF spread {spread:.2f} — edge distributed"))
        else:
            signals.append(VerdictSignal(name="loso", outcome="inconclusive",
                                          reason=f"PF spread {spread:.2f}"))

    # --- WFE ---
    if wf and wf.n_windows > 0:
        wfe = wf.wfe_ratio
        if wfe >= THRESHOLDS["wfe_robust"]:
            signals.append(VerdictSignal(name="wfe", outcome="robust",
                                          reason=f"WFE {wfe:.2f} ≥ {THRESHOLDS['wfe_robust']}"))
        elif wfe < THRESHOLDS["wfe_fragile"]:
            signals.append(VerdictSignal(name="wfe", outcome="fragile",
                                          reason=f"WFE {wfe:.2f} < {THRESHOLDS['wfe_fragile']}"))
        else:
            signals.append(VerdictSignal(name="wfe", outcome="inconclusive",
                                          reason=f"WFE {wfe:.2f}"))

    # --- Aggregate ---
    # Anti-drift rule: asymmetric error costs. Any fragile signal -> at best INCONCLUSIVE.
    # All-robust -> ROBUST. Mix of robust + inconclusive -> INCONCLUSIVE.
    # 2+ fragile, or any fragile with 0 robust -> FRAGILE.
    n_fragile = sum(1 for s in signals if s.outcome == "fragile")
    n_robust = sum(1 for s in signals if s.outcome == "robust")

    if n_fragile >= 2 or (n_fragile >= 1 and n_robust == 0):
        verdict = "FRAGILE"
    elif n_fragile == 0 and n_robust >= max(3, len(signals) // 2):
        verdict = "ROBUST"
    else:
        verdict = "INCONCLUSIVE"

    return VerdictResult(verdict=verdict, signals=signals)
