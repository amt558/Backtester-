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
- Walk-forward decay: wf_decay (half-vs-half OOS PF ratio)

Diagnostics surfaced (no aggregation impact):
- trade_efficiency: portfolio captured / ideal $ ratio (MFE-based)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..results import BacktestMetrics, BacktestResult, WalkForwardResult
from .diagnostics import compute_wf_decay, compute_trade_efficiency
from .entry_delay import EntryDelayResult
from .loso import LOSOResult
from .monte_carlo import MonteCarloResult
from .noise_injection import NoiseInjectionResult
from .param_landscape import ParamLandscapeResult


# Canonical verdict labels — the single source of truth for the three values
# compute_verdict can emit. The producer (compute_verdict) assigns from these
# names and VerdictResult validates against VALID_VERDICTS, so the set that is
# PRODUCED and the set that is ENFORCED cannot diverge. Importers (e.g. the
# `tradelab robustness` CLI) must import VALID_VERDICTS rather than duplicate
# the literals, or a hardcoded copy could call a legitimate new value
# "malformed" and fail the gate for a non-corruption reason.
VERDICT_ROBUST = "ROBUST"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_FRAGILE = "FRAGILE"
VALID_VERDICTS = frozenset({VERDICT_ROBUST, VERDICT_INCONCLUSIVE, VERDICT_FRAGILE})


# Hard disqualifier-floor tokens — non-overridable promotion blockers that sit
# FAR below the verdict engine's own FRAGILE thresholds. These are computed by
# hard_disqualifiers() ALONGSIDE compute_verdict (never inside it): the verdict
# aggregation is advisory and overridable; the floor is not. A tripped token
# means "cannot promote, full stop", independent of the categorical verdict.
DISQ_DSR_NEG = "DSR_NEGATIVE"
DISQ_NEG_EXPECT = "NEG_NET_EXPECTANCY"


class VerdictSignal(BaseModel):
    """One labelled check and its FRAGILE/ROBUST/INCONCLUSIVE outcome."""
    name: str
    outcome: str   # "robust" | "inconclusive" | "fragile"
    reason: str


class VerdictResult(BaseModel):
    """Aggregate verdict + the signals that drove it."""
    verdict: str   # ROBUST | INCONCLUSIVE | FRAGILE
    signals: list[VerdictSignal] = Field(default_factory=list)
    diagnostics: dict[str, Optional[float]] = Field(default_factory=dict)

    @field_validator("verdict")
    @classmethod
    def _verdict_in_valid_set(cls, v: str) -> str:
        # Hardens the core: a corrupted/typo'd verdict cannot escape the
        # engine. Rejects anything outside VALID_VERDICTS at construction.
        if v not in VALID_VERDICTS:
            raise ValueError(
                f"verdict must be one of {sorted(VALID_VERDICTS)}, got {v!r}"
            )
        return v

    @property
    def fragile_signals(self) -> list[VerdictSignal]:
        return [s for s in self.signals if s.outcome == "fragile"]

    @property
    def robust_signals(self) -> list[VerdictSignal]:
        return [s for s in self.signals if s.outcome == "robust"]


# Code-level fallback defaults — used only when the config subsystem is
# unavailable (e.g. during unit tests that import verdict without a yaml).
# The authoritative source is tradelab.yaml under `robustness.thresholds`
# (see config.RobustnessThresholds).
_FALLBACK_THRESHOLDS = {
    "pf_robust": 1.5,
    "pf_fragile": 1.1,
    "dsr_robust": 0.95,
    "dsr_fragile": 0.50,
    "mc_dd_fragile_percentile": 10.0,
    "smoothness_robust": 0.15,
    "smoothness_fragile": 0.40,
    "entry_delay_fragile": 0.50,
    "loso_fragile_spread": 1.0,
    "wfe_robust": 0.75,
    "wfe_fragile": 0.50,
    "noise_pf_drop_p5_fragile": 0.40,
    "noise_pf_drop_p5_robust": 0.10,
    # Regime dependence: worst-regime PF / best-regime PF below this ratio
    # flags fragile (strategy's edge is regime-conditional).
    "regime_spread_fragile": 0.40,
    "regime_spread_robust": 0.70,
    # Hard-fragile override: extreme regime concentration forces FRAGILE
    # regardless of other signals. Closes the loophole where a bull-only
    # strategy could score ROBUST under normal aggregation.
    "regime_spread_hard_fragile": 0.20,
    # Minimum trades per regime bucket to count toward spread computation.
    # Proportional to total trades, with an absolute floor for degenerate
    # cases. A regime must contribute >= max(abs_floor, total * pct/100)
    # trades to count as valid evidence.
    "regime_min_trades_pct": 10.0,
    "regime_min_trades_abs": 5,
    # S4: hold-out OOS gate. Run a backtest on a trailing untouched window
    # (default 6 months, configured under robustness.hold_out_window_months).
    # PF >= robust threshold = robust signal; PF < fragile threshold = fragile.
    "hold_out_robust_pf": 1.50,
    "hold_out_fragile_pf": 1.00,
    # wf_decay: half-vs-half ratio of aggregate OOS PF across walk-forward
    # windows. Late-half / early-half. Below fragile = decaying; above robust
    # = stable. Requires >= 4 valid windows for the signal to emit.
    "wf_decay_robust": 0.90,
    "wf_decay_fragile": 0.70,
}


def _resolve_thresholds() -> dict:
    """Read thresholds from active config if available, else fall back to code defaults."""
    try:
        from ..config import get_config
        cfg = get_config()
        return cfg.robustness.thresholds.model_dump()
    except Exception:
        return dict(_FALLBACK_THRESHOLDS)


# Backwards-compat module-level name; tests may inspect it.
THRESHOLDS = _FALLBACK_THRESHOLDS


def hard_disqualifiers(bt: BacktestMetrics, dsr: Optional[float]) -> list[str]:
    """Non-overridable promotion blockers, evaluated independently of the
    categorical verdict.

    Returns the tripped DISQ_* tokens (empty list = nothing fatal = eligible
    for advisory review). Pure: no side effects, no model mutation, and a
    deterministic token order (expectancy before DSR).

    Floor semantics — both blockers sit far below the verdict's own FRAGILE
    thresholds, so a clean verdict can never paper over them:
      - NEG_NET_EXPECTANCY: the post-cost bottom line is non-positive. Uses
        net_pnl, which the backtest engine accumulates from per-trade pnl
        already net of commission (entry+exit); profit_factor is a gross ratio
        and is deliberately NOT used here.
      - DSR_NEGATIVE: deflated Sharpe is strictly negative. None means missing
        data (not disqualified) and exactly 0.0 does not trip.
    """
    blockers: list[str] = []
    if bt.net_pnl <= 0:
        blockers.append(DISQ_NEG_EXPECT)
    if dsr is not None and dsr < 0.0:
        blockers.append(DISQ_DSR_NEG)
    return blockers


def compute_verdict(
    bt: BacktestResult,
    dsr: Optional[float] = None,
    mc: Optional[MonteCarloResult] = None,
    landscape: Optional[ParamLandscapeResult] = None,
    entry_delay: Optional[EntryDelayResult] = None,
    loso: Optional[LOSOResult] = None,
    wf: Optional[WalkForwardResult] = None,
    noise: Optional[NoiseInjectionResult] = None,
    overrides: Optional[dict] = None,
) -> VerdictResult:
    # Read thresholds from config on each call so yaml edits take effect
    # without a process restart.
    THRESHOLDS = _resolve_thresholds()
    # ADVISORY, opt-in: layer caller-supplied overrides on top of the resolved
    # thresholds for THIS call only. A fresh dict — never mutates the resolved
    # config, the module-level THRESHOLDS, or the yaml. Default None = today's
    # behaviour, byte-for-byte (the frozen test_verdict.py is the regression).
    if overrides:
        THRESHOLDS = {**THRESHOLDS, **overrides}
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

    # --- Noise injection ---
    if noise and noise.points:
        drop = noise.pf_drop_p5_from_baseline
        if drop >= THRESHOLDS["noise_pf_drop_p5_fragile"]:
            signals.append(VerdictSignal(name="noise_injection", outcome="fragile",
                                          reason=f"PF drops {drop*100:.0f}% at p5 noisy run"))
        elif drop <= THRESHOLDS["noise_pf_drop_p5_robust"]:
            signals.append(VerdictSignal(name="noise_injection", outcome="robust",
                                          reason=f"PF drop ≤{THRESHOLDS['noise_pf_drop_p5_robust']*100:.0f}% at p5 noisy run"))
        else:
            signals.append(VerdictSignal(name="noise_injection", outcome="inconclusive",
                                          reason=f"PF drop {drop*100:.0f}% at p5 noisy run"))

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

    # --- wf_decay: rolling OOS PF, half-vs-half ratio ---
    # Catches temporal decay that aggregate WFE collapses into one ratio.
    # Outer guard on n_windows is a coarse pre-filter; compute_wf_decay
    # filters to valid (non-None test_metrics) windows internally and
    # returns None if fewer than 4 valid remain.
    if wf and wf.n_windows >= 4:
        decay = compute_wf_decay(wf)
        if decay is not None:
            if decay >= THRESHOLDS["wf_decay_robust"]:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="robust",
                    reason=f"Late-half OOS PF is {decay:.0%} of early-half (stable)",
                ))
            elif decay < THRESHOLDS["wf_decay_fragile"]:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="fragile",
                    reason=f"Late-half OOS PF only {decay:.0%} of early-half (decaying)",
                ))
            else:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="inconclusive",
                    reason=f"Late-half OOS PF {decay:.0%} of early-half",
                ))

    # --- S4: Hold-out OOS gate (Generalization, Critical) ---
    # PF on a trailing window the walk-forward training never touched.
    # Robust threshold passes the gate; fragile threshold flags it; in
    # between is inconclusive. No signal is emitted when wf.holdout_result
    # is None (gate disabled or dataset too short for a meaningful window).
    if wf is not None and getattr(wf, "holdout_result", None) is not None:
        ho_pf = wf.holdout_result.profit_factor
        ho_months = wf.holdout_window_months or 0
        if ho_pf is None or ho_pf <= 0:
            outcome = "inconclusive"
            reason = (
                f"hold-out PF undefined or zero on {ho_months}mo window "
                f"(no closed losses or no trades)"
            )
        elif ho_pf >= THRESHOLDS["hold_out_robust_pf"]:
            outcome = "robust"
            reason = (
                f"hold-out PF {ho_pf:.2f} ≥ {THRESHOLDS['hold_out_robust_pf']:.2f} "
                f"on {ho_months}mo untouched window"
            )
        elif ho_pf < THRESHOLDS["hold_out_fragile_pf"]:
            outcome = "fragile"
            reason = (
                f"hold-out PF {ho_pf:.2f} < {THRESHOLDS['hold_out_fragile_pf']:.2f} "
                f"on {ho_months}mo untouched window"
            )
        else:
            outcome = "inconclusive"
            reason = (
                f"hold-out PF {ho_pf:.2f} between "
                f"{THRESHOLDS['hold_out_fragile_pf']:.2f}–"
                f"{THRESHOLDS['hold_out_robust_pf']:.2f} "
                f"on {ho_months}mo window"
            )
        signals.append(VerdictSignal(name="hold_out_oos", outcome=outcome, reason=reason))

    # --- Regime spread (worst-regime PF / best-regime PF) ---
    # Three-tier: hard-fragile override / soft-fragile contribution /
    # robust, with a proportional sample-size guard so we never flag based
    # on noisy tiny-sample regimes.
    rb = getattr(bt, "regime_breakdown", None) or {}
    if rb:
        total_trades = sum(int(r.get("n_trades", 0)) for r in rb.values())
        pct = float(THRESHOLDS.get("regime_min_trades_pct", 10.0))
        abs_floor = int(THRESHOLDS.get("regime_min_trades_abs", 5))
        min_trades = max(abs_floor, int(round(total_trades * pct / 100.0)))

        valid = [(name, r) for name, r in rb.items()
                 if r.get("n_trades", 0) >= min_trades and r.get("pf", 0) > 0]
        pfs = [r["pf"] for _, r in valid]

        # Dominant regime — always reported in reasons for transparency
        dominant = ""
        if total_trades > 0:
            top_name, top_row = max(
                rb.items(), key=lambda kv: kv[1].get("n_trades", 0),
            )
            share_pct = (top_row.get("n_trades", 0) / total_trades) * 100
            dominant = f" | {top_name}={share_pct:.0f}% of trades"

        if len(valid) < 2:
            # Can't compute a meaningful spread - treat as inconclusive
            signals.append(VerdictSignal(
                name="regime_spread", outcome="inconclusive",
                reason=(f"Insufficient data: only {len(valid)} regime(s) "
                        f"with >= {min_trades} trades ({pct:.0f}% of "
                        f"{total_trades} total, floor {abs_floor}){dominant}"),
            ))
        else:
            lo, hi = min(pfs), max(pfs)
            ratio = lo / hi if hi > 0 else 0.0
            soft_t = THRESHOLDS["regime_spread_fragile"]
            hard_t = THRESHOLDS.get("regime_spread_hard_fragile", 0.0)
            robust_t = THRESHOLDS["regime_spread_robust"]

            if ratio < soft_t:
                # Soft-fragile signal always fires when below soft threshold
                signals.append(VerdictSignal(
                    name="regime_spread", outcome="fragile",
                    reason=(f"Worst-regime PF {lo:.2f} is {ratio*100:.0f}% of "
                            f"best-regime PF {hi:.2f} "
                            f"(< {int(soft_t*100)}%){dominant}"),
                ))
                # Hard-fragile signal fires ADDITIONALLY at stricter threshold.
                # Aggregation below will force FRAGILE if this signal is present.
                if hard_t > 0 and ratio < hard_t:
                    signals.append(VerdictSignal(
                        name="regime_spread_hard", outcome="fragile",
                        reason=(f"HARD OVERRIDE: Worst-regime PF {lo:.2f} is "
                                f"only {ratio*100:.0f}% of best-regime PF {hi:.2f} "
                                f"(< {int(hard_t*100)}%). Strategy's edge is "
                                f"regime-specific; structural fragility{dominant}"),
                    ))
            elif ratio >= robust_t:
                signals.append(VerdictSignal(
                    name="regime_spread", outcome="robust",
                    reason=(f"Regime PFs consistent ({lo:.2f}/{hi:.2f}, "
                            f"ratio {ratio:.2f}){dominant}"),
                ))
            else:
                signals.append(VerdictSignal(
                    name="regime_spread", outcome="inconclusive",
                    reason=(f"Regime PF ratio {ratio:.2f} "
                            f"(lo {lo:.2f} / hi {hi:.2f}){dominant}"),
                ))

    # --- Aggregate ---
    # Anti-drift rule: asymmetric error costs. Any fragile signal -> at best INCONCLUSIVE.
    # All-robust -> ROBUST. Mix of robust + inconclusive -> INCONCLUSIVE.
    # 2+ fragile, or any fragile with 0 robust -> FRAGILE.
    n_fragile = sum(1 for s in signals if s.outcome == "fragile")
    n_robust = sum(1 for s in signals if s.outcome == "robust")

    if n_fragile >= 2 or (n_fragile >= 1 and n_robust == 0):
        verdict = VERDICT_FRAGILE
    elif n_fragile == 0 and n_robust >= max(3, len(signals) // 2):
        verdict = VERDICT_ROBUST
    else:
        verdict = VERDICT_INCONCLUSIVE

    # Hard-gate override: extreme regime concentration forces FRAGILE
    # regardless of the normal aggregation. This exists because a
    # bull-only strategy with otherwise-clean signals shouldn't be
    # allowed to score ROBUST — the edge isn't an edge, it's a regime bet.
    if any(s.name == "regime_spread_hard" and s.outcome == "fragile" for s in signals):
        verdict = VERDICT_FRAGILE

    # --- Diagnostics (no aggregation impact, surface for dashboards) ---
    diagnostics: dict[str, Optional[float]] = {
        "trade_efficiency": compute_trade_efficiency(bt),
    }

    return VerdictResult(verdict=verdict, signals=signals, diagnostics=diagnostics)
