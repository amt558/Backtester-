"""
Validation suite — TIER 3 (engine re-runs; expensive, opt-in).

Unlike tiers 1-2 (which read a saved `BacktestResult`), these tests RE-RUN the
backtest engine, so they need the live `(strategy, ticker_data, baseline_bt)`
context that exists inside a `tradelab run`. They are meant to run there (the
job manager already tracks `tradelab run` subprocesses) behind an opt-in flag —
NOT eagerly in every `--full`, because each is many full-portfolio backtests.

Same hard rules as the rest of the suite: REPORT-ONLY. These return
`ValidationSignal`s (sibling shape to verdict signals); they NEVER call
`compute_verdict` and never move a verdict. Cosmetic outcome thresholds only
colour a future panel.

Built (per the agreed recommendation):
  * cost_sensitivity      — formalizes the existing --full commission sweep into
                            a structured signal (commission AND slippage are the
                            same single cost lever the engine exposes).
  * random_entry_benchmark — real exits + RANDOM entries, N seeded sims; is the
                            edge in the entry signal, or just the exit/risk mgmt?

Parked (architectural gaps, see handoff): standalone Slippage panel (engine has
no fill-price lever, only commission) and Gate Contribution Isolation (the
Strategy interface exposes no per-gate toggle; ablation would mean editing
baseline strategy code). Time-of-Day stays blocked (date-only timestamps).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from ..canaries._indicators import stable_seed
from ..engines.backtest import run_backtest
from ..engines.cost_sweep import CostSweepResult, run_cost_sweep
from ..results import BacktestResult
from ..strategies.base import Strategy
from .suite import PF_CAP, ValidationSignal, _safe

# ── Tunables (cosmetic colouring) ────────────────────────────────────────────
# Cost sensitivity: PF at this commission multiple is the stress point.
_COST_STRESS_MULT = 2.0
_COST_ROBUST_PF = 1.30      # edge clearly survives doubled costs
_COST_FRAGILE_PF = 1.00     # edge dies (PF < 1) under doubled costs

# Random-entry benchmark
_RAND_N_SIMS = 200          # full backtests; configurable (1000 is heavy)
_RAND_SEED = 42
_RAND_ROBUST_PCT = 90.0     # real PF beats >= this % of random-entry sims
_RAND_FRAGILE_PCT = 50.0    # real entries no better than a coin flip


def _clean_pf(pf: Optional[float]) -> Optional[float]:
    """JSON-safe, capped profit factor (gross_loss==0 can yield inf)."""
    s = _safe(pf)
    return None if s is None else round(min(s, PF_CAP), 4)


# ── Test 6: Cost Sensitivity (commission + slippage = one cost lever) ────────

def cost_sensitivity(
    strategy,
    ticker_data,
    *,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    cost_sweep_result: Optional[CostSweepResult] = None,
) -> ValidationSignal:
    """How much edge survives higher transaction costs.

    Reuses the existing `run_cost_sweep` (re-runs the engine across commission
    multipliers). Pass the `--full` run's CostSweepResult to avoid recomputing.
    `value` = PF at the 2× cost stress point. The engine has a single cost
    lever, so this is the commission AND slippage sensitivity panel.
    """
    res = cost_sweep_result or run_cost_sweep(
        strategy, ticker_data, spy_close=spy_close, start=start, end=end,
    )
    by_mult = {round(float(p.multiplier), 4): p for p in res.points}
    if not by_mult:
        return ValidationSignal(
            name="cost_sensitivity", outcome="inconclusive",
            reason="Cost sweep produced no points", value=None, detail={},
        )

    base_mult = 1.0 if 1.0 in by_mult else min(by_mult)
    stress_mult = _COST_STRESS_MULT if _COST_STRESS_MULT in by_mult else max(by_mult)
    base_pf = _clean_pf(by_mult[base_mult].metrics.profit_factor)
    stress_pf = _clean_pf(by_mult[stress_mult].metrics.profit_factor)

    table = [{
        "multiplier": round(float(m), 4),
        "commission_per_trade": round(float(p.commission_per_trade), 4),
        "pf": _clean_pf(p.metrics.profit_factor),
        "pct_return": _safe(p.metrics.pct_return),
        "max_drawdown_pct": _safe(p.metrics.max_drawdown_pct),
        "total_trades": int(p.metrics.total_trades),
    } for m, p in sorted(by_mult.items())]

    drop = None
    if base_pf and base_pf > 0 and stress_pf is not None:
        drop = (base_pf - stress_pf) / base_pf

    detail = {
        "base_multiplier": base_mult,
        "stress_multiplier": stress_mult,
        "base_pf": base_pf,
        "stress_pf": stress_pf,
        "pf_drop_frac": _safe(drop),
        "points": table,
    }

    if stress_pf is None:
        outcome, reason = "inconclusive", f"PF undefined at {stress_mult:g}× cost"
    elif stress_pf >= _COST_ROBUST_PF:
        outcome = "robust"
        reason = f"PF {stress_pf:.2f} at {stress_mult:g}× cost (edge survives doubled costs)"
    elif stress_pf < _COST_FRAGILE_PF:
        outcome = "fragile"
        reason = f"PF {stress_pf:.2f} < 1.0 at {stress_mult:g}× cost (edge eaten by costs)"
    else:
        outcome = "inconclusive"
        reason = f"PF {stress_pf:.2f} at {stress_mult:g}× cost (marginal)"

    return ValidationSignal(
        name="cost_sensitivity", outcome=outcome, reason=reason,
        value=stress_pf, detail=detail,
    )


# ── Test 7: Random Entry Benchmark (real exits + random entries) ─────────────

class _RandomEntryWrapper(Strategy):
    """Wraps a real strategy: keeps its exit machinery (params + `entry_stop`/
    `ATR` columns) but replaces `buy_signal` with seeded-random entries at the
    real per-symbol entry rate. Isolates how much edge lives in entry TIMING."""

    def __init__(self, base_strategy: Strategy, entry_rate_by_sym: dict[str, float], seed: int):
        super().__init__(name=f"{base_strategy.name}__rand", params=dict(base_strategy.params))
        self._base = base_strategy
        self._rates = entry_rate_by_sym
        self._seed = seed
        self.timeframe = base_strategy.timeframe
        self.requires_benchmark = base_strategy.requires_benchmark

    def generate_signals(self, data, spy_close=None):
        signaled = self._base.generate_signals(data, spy_close=spy_close)
        out: dict[str, pd.DataFrame] = {}
        for sym, df in signaled.items():
            df = df.copy()
            n = len(df)
            rng = np.random.default_rng(stable_seed(self._seed, sym))
            atr = df.get("ATR")
            if atr is not None:
                atr_valid = atr.notna() & (atr > 0)
            else:
                atr_valid = pd.Series(True, index=df.index)
            raw = rng.random(n) < float(self._rates.get(sym, 0.0))
            df["buy_signal"] = (pd.Series(raw, index=df.index) & atr_valid).fillna(False)
            out[sym] = df
        return out


def _entry_rates(base_strategy: Strategy, data, spy_close) -> dict[str, float]:
    """Real entry rate per symbol = real buy_signals / ATR-valid bars."""
    signaled = base_strategy.generate_signals(data, spy_close=spy_close)
    rates: dict[str, float] = {}
    for sym, df in signaled.items():
        buys = df.get("buy_signal")
        if buys is None:
            rates[sym] = 0.0
            continue
        buys = buys.fillna(False)
        atr = df.get("ATR")
        if atr is not None:
            valid = atr.notna() & (atr > 0)
            denom = int(valid.sum())
            num = int((buys & valid).sum())
        else:
            denom = len(df)
            num = int(buys.sum())
        rates[sym] = (num / denom) if denom > 0 else 0.0
    return rates


def random_entry_benchmark(
    strategy,
    ticker_data,
    baseline_bt: BacktestResult,
    *,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    n_sims: int = _RAND_N_SIMS,
    seed: int = _RAND_SEED,
) -> ValidationSignal:
    """Benchmark the real strategy's PF against N random-entry sims that keep the
    real exit logic. `value` = percentile of the real PF in the random
    distribution. A low percentile means the entry signal adds little — the
    edge is in the exit/risk management, not the entry.
    """
    real_pf = _clean_pf(baseline_bt.metrics.profit_factor)
    rates = _entry_rates(strategy, ticker_data, spy_close)
    avg_rate = float(np.mean([r for r in rates.values()])) if rates else 0.0

    detail: dict = {"real_pf": real_pf, "n_sims_requested": n_sims,
                    "avg_entry_rate": round(avg_rate, 5)}

    if real_pf is None or not any(r > 0 for r in rates.values()):
        return ValidationSignal(
            name="random_entry_benchmark", outcome="inconclusive",
            reason="No entries (or undefined PF) to benchmark", value=None,
            detail=detail,
        )

    sim_pfs: list[float] = []
    for k in range(n_sims):
        wrapper = _RandomEntryWrapper(strategy, rates, seed=seed + k)
        bt = run_backtest(wrapper, ticker_data, start=start, end=end, spy_close=spy_close)
        if bt.metrics.total_trades > 0:
            pf = bt.metrics.profit_factor
            if not (pf is None or math.isnan(pf) or math.isinf(pf)):
                sim_pfs.append(min(float(pf), PF_CAP))

    detail["n_sims_productive"] = len(sim_pfs)
    if len(sim_pfs) < max(10, n_sims // 5):
        return ValidationSignal(
            name="random_entry_benchmark", outcome="inconclusive",
            reason=(f"Only {len(sim_pfs)}/{n_sims} random-entry sims produced "
                    f"trades — too few to benchmark"),
            value=None, detail=detail,
        )

    arr = np.array(sim_pfs, dtype=float)
    pct = float((arr <= real_pf).mean() * 100.0)
    detail.update({
        "random_pf_mean": round(float(arr.mean()), 4),
        "random_pf_std": round(float(arr.std()), 4),
        "random_pf_p50": round(float(np.percentile(arr, 50)), 4),
        "random_pf_p95": round(float(np.percentile(arr, 95)), 4),
        "real_pf_percentile": round(pct, 1),
    })

    if pct >= _RAND_ROBUST_PCT:
        outcome = "robust"
    elif pct <= _RAND_FRAGILE_PCT:
        outcome = "fragile"
    else:
        outcome = "inconclusive"

    reason = (f"Real PF {real_pf:.2f} beats {pct:.0f}% of {len(sim_pfs)} "
              f"random-entry sims (median random PF {detail['random_pf_p50']:.2f})")
    return ValidationSignal(
        name="random_entry_benchmark", outcome=outcome, reason=reason,
        value=round(pct, 1), detail=detail,
    )


# ── Test 8: Gate Contribution Isolation (ablate one gate per re-run) ─────────

_GATE_IMPROVE_FRAC = 0.20   # removing a gate that improves PF by >=20% = over-gated


def gate_contribution_isolation(
    strategy,
    ticker_data,
    baseline_bt: BacktestResult,
    *,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> ValidationSignal:
    """Re-run the backtest with each declared gate neutralised, one at a time, to
    measure that gate's contribution.

    Reads the strategy's opt-in `ablatable_gates` map (param overrides that make
    a gate always-true). For each gate: PF_ablated − PF_baseline.
      delta < 0  → gate is load-bearing (removing it hurts).
      delta ≈ 0  → gate barely matters.
      delta > 0  → gate is HURTING returns (over-gated / overfit).
    `value` = the largest PF improvement from dropping a single gate.

    Inconclusive when the strategy declares no ablatable gates (the default for
    every strategy, including the locked baselines, until an owner opts in).
    """
    gates = dict(getattr(strategy, "ablatable_gates", {}) or {})
    base_pf = _clean_pf(baseline_bt.metrics.profit_factor)
    detail: dict = {"base_pf": base_pf, "gates": []}

    if not gates:
        return ValidationSignal(
            name="gate_contribution_isolation", outcome="inconclusive",
            reason="Strategy declares no ablatable_gates — gate isolation unavailable",
            value=None, detail=detail,
        )
    if base_pf is None:
        return ValidationSignal(
            name="gate_contribution_isolation", outcome="inconclusive",
            reason="Baseline PF undefined — cannot compare ablations", value=None,
            detail=detail,
        )

    rows = []
    for gate_name, override in gates.items():
        ablated = type(strategy)(name=strategy.name,
                                 params={**strategy.params, **override})
        bt = run_backtest(ablated, ticker_data, start=start, end=end, spy_close=spy_close)
        ablated_pf = _clean_pf(bt.metrics.profit_factor)
        delta = (ablated_pf - base_pf) if ablated_pf is not None else None
        rows.append({
            "gate": gate_name,
            "ablated_pf": ablated_pf,
            "delta_pf": _safe(delta),
            "ablated_trades": int(bt.metrics.total_trades),
        })
    detail["gates"] = rows

    deltas = [r["delta_pf"] for r in rows if r["delta_pf"] is not None]
    if not deltas:
        return ValidationSignal(
            name="gate_contribution_isolation", outcome="inconclusive",
            reason="No gate produced a comparable PF", value=None, detail=detail,
        )

    max_improve = max(deltas)             # most positive = most "harmful" gate
    worst_gate = max(rows, key=lambda r: (r["delta_pf"] if r["delta_pf"] is not None else -1e9))

    if max_improve >= _GATE_IMPROVE_FRAC * base_pf:
        outcome = "fragile"
        reason = (f"Dropping '{worst_gate['gate']}' raises PF {base_pf:.2f}→"
                  f"{worst_gate['ablated_pf']:.2f} (+{max_improve:.2f}) — over-gated")
    elif max_improve <= 0.05 * base_pf:
        outcome = "robust"
        reason = (f"All {len(rows)} gates load-bearing "
                  f"(best ablation Δ {max_improve:+.2f} PF)")
    else:
        outcome = "inconclusive"
        reason = (f"Mixed: best ablation '{worst_gate['gate']}' Δ {max_improve:+.2f} PF "
                  f"from base {base_pf:.2f}")

    return ValidationSignal(
        name="gate_contribution_isolation", outcome=outcome, reason=reason,
        value=round(max_improve, 4), detail=detail,
    )


# ── Deep orchestrator ────────────────────────────────────────────────────────

def run_validation_suite_deep(
    strategy,
    ticker_data,
    baseline_bt: BacktestResult,
    *,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    n_sims: int = _RAND_N_SIMS,
    seed: int = _RAND_SEED,
    cost_sweep_result: Optional[CostSweepResult] = None,
) -> list[ValidationSignal]:
    """Run the tier-3 (engine re-run) validation tests. Report-only; the caller
    merges these into the same validation.json as the tier 1-2 signals."""
    return [
        cost_sensitivity(
            strategy, ticker_data, spy_close=spy_close, start=start, end=end,
            cost_sweep_result=cost_sweep_result,
        ),
        gate_contribution_isolation(
            strategy, ticker_data, baseline_bt, spy_close=spy_close,
            start=start, end=end,
        ),
        random_entry_benchmark(
            strategy, ticker_data, baseline_bt, spy_close=spy_close,
            start=start, end=end, n_sims=n_sims, seed=seed,
        ),
    ]
