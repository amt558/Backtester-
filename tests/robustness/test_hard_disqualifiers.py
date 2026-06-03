"""Hard disqualifier-floor tests.

The floor is two non-overridable promotion blockers that sit FAR below the
verdict engine's own FRAGILE thresholds: a negative net bottom line after
costs, and a negative deflated Sharpe. hard_disqualifiers is a pure function
ALONGSIDE compute_verdict (not inside it, not a method) — it never mutates a
model and is deterministic.
"""
from __future__ import annotations

from tradelab.results import BacktestMetrics
from tradelab.robustness.verdict import (
    hard_disqualifiers,
    DISQ_DSR_NEG,
    DISQ_NEG_EXPECT,
)


def _metrics(net_pnl: float, pf: float = 1.0) -> BacktestMetrics:
    """Minimal metrics carrying just the fields the floor reads."""
    return BacktestMetrics(
        total_trades=100, wins=60, losses=40, win_rate=60.0,
        profit_factor=pf, net_pnl=net_pnl,
    )


def test_neg_net_expectancy_trips_alone():
    # v83-like: negative net bottom line, PF below 1, but DSR not negative.
    m = _metrics(net_pnl=-1234.0, pf=0.76)
    assert hard_disqualifiers(m, dsr=0.42) == [DISQ_NEG_EXPECT]


def test_dsr_negative_trips_alone():
    m = _metrics(net_pnl=5000.0, pf=1.4)
    assert hard_disqualifiers(m, dsr=-0.1) == [DISQ_DSR_NEG]


def test_both_blockers_trip_together():
    m = _metrics(net_pnl=-500.0, pf=0.8)
    result = hard_disqualifiers(m, dsr=-0.1)
    assert set(result) == {DISQ_NEG_EXPECT, DISQ_DSR_NEG}
    assert len(result) == 2


def test_fragile_but_not_blocked_returns_empty():
    # Positive net, positive DSR — may still be FRAGILE per the verdict
    # engine, but nothing here is fatal. Floor stays out of the way.
    m = _metrics(net_pnl=2500.0, pf=1.05)
    assert hard_disqualifiers(m, dsr=0.42) == []


def test_dsr_none_does_not_trip():
    # None = missing data, NOT disqualified.
    m = _metrics(net_pnl=2500.0, pf=1.3)
    assert hard_disqualifiers(m, dsr=None) == []


def test_dsr_zero_boundary_does_not_trip():
    # Strict < 0: exactly 0.0 must NOT trip.
    m = _metrics(net_pnl=2500.0, pf=1.3)
    assert hard_disqualifiers(m, dsr=0.0) == []


def test_every_returnable_string_is_a_known_constant():
    allowed = {DISQ_DSR_NEG, DISQ_NEG_EXPECT}
    scenarios = [
        (_metrics(net_pnl=-1.0, pf=0.7), 0.42),
        (_metrics(net_pnl=10.0, pf=1.2), -0.1),
        (_metrics(net_pnl=-1.0, pf=0.7), -0.1),
        (_metrics(net_pnl=10.0, pf=1.2), 0.42),
        (_metrics(net_pnl=10.0, pf=1.2), None),
        (_metrics(net_pnl=10.0, pf=1.2), 0.0),
        (_metrics(net_pnl=0.0, pf=1.0), 0.0),
    ]
    for m, dsr in scenarios:
        for token in hard_disqualifiers(m, dsr=dsr):
            assert token in allowed
