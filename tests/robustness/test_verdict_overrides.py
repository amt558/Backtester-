"""Task F: compute_verdict gains an opt-in, advisory `overrides` knob.

Overrides layer on top of the resolved thresholds for a single what-if
call. Default None must be byte-for-byte today's behaviour (the frozen
test_verdict.py is the regression for that). Overrides must NEVER mutate
the module-level THRESHOLDS, the yaml, or any persisted verdict.
"""
from __future__ import annotations

from tradelab.results import BacktestMetrics, BacktestResult
from tradelab.robustness import verdict as verdict_mod
from tradelab.robustness.verdict import compute_verdict


def _bt(pf: float = 1.4) -> BacktestResult:
    return BacktestResult(
        strategy="adv",
        start_date="2024-01-01",
        end_date="2024-06-01",
        metrics=BacktestMetrics(total_trades=30, profit_factor=pf),
    )


def _signal(vr, name):
    return next((s for s in vr.signals if s.name == name), None)


def test_overrides_flip_baseline_signal_without_mutating_thresholds():
    before = dict(verdict_mod.THRESHOLDS)
    bt = _bt(1.4)

    lenient = compute_verdict(bt, overrides={"pf_robust": 0.001, "pf_fragile": 0.0005})
    strict = compute_verdict(bt, overrides={"pf_robust": 9999.0, "pf_fragile": 9998.0})

    assert _signal(lenient, "baseline_pf").outcome == "robust"
    assert _signal(strict, "baseline_pf").outcome == "fragile"

    # Guardrail: the module-level THRESHOLDS dict is never mutated.
    assert dict(verdict_mod.THRESHOLDS) == before


def test_default_no_overrides_unchanged():
    bt = _bt(1.4)
    a = compute_verdict(bt)
    b = compute_verdict(bt, overrides=None)
    assert a.verdict == b.verdict
    assert [s.outcome for s in a.signals] == [s.outcome for s in b.signals]
