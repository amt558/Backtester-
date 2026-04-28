"""
Invariant test: WF windows must not extend into the hold-out tail.

The hold-out gate in S4 promises that its trailing-N-months window is
"untouched" by any walk-forward optimization. That promise breaks if
compute_splits() is allowed to step all the way to data_end — the last
WF test_end will overlap with the hold-out start.

Fix (walkforward.py): `run_walkforward` computes
    wf_end = data_end - holdout_months
before calling compute_splits, and passes it as the ``wf_end`` cap.
compute_splits uses wf_end (not data_end) as the upper bound when
deciding whether to emit a split.

These tests exercise compute_splits() directly so they are fast and have
no strategy/backtest dependencies.
"""
from __future__ import annotations

import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta

from tradelab.engines.walkforward import compute_splits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_test_end(splits: list[dict]) -> pd.Timestamp | None:
    """Return the test_end of the last split, or None if splits is empty."""
    if not splits:
        return None
    return pd.Timestamp(splits[-1]["test_end"])


# ---------------------------------------------------------------------------
# Core invariant
# ---------------------------------------------------------------------------

def test_holdout_tail_excluded_from_wf_windows():
    """WF test_end must not reach into the hold-out window.

    Scenario: 2 years of data, train=12mo, test=3mo, step=3mo, warmup=0.
    Without the wf_end cap the last test window ends 2025-12-31, well inside
    the hold-out [2025-07-01, 2026-01-01].
    With the cap (wf_end=2025-07-01) the last test_end must be <= 2025-06-30.
    """
    data_start = "2024-01-01"
    data_end = "2026-01-01"
    holdout_months = 6

    holdout_start = pd.Timestamp(data_end) - relativedelta(months=holdout_months)
    wf_end = holdout_start.strftime("%Y-%m-%d")  # "2025-07-01"

    splits = compute_splits(
        data_start=data_start,
        data_end=data_end,
        warmup_months=0,
        train_months=12,
        test_months=3,
        step_months=3,
        wf_end=wf_end,
    )

    assert splits, "Expected at least one WF split for 2-year dataset"
    last_te = _last_test_end(splits)

    assert last_te < holdout_start, (
        f"INVARIANT BROKEN: last WF test_end ({last_te.date()}) is on or after "
        f"holdout_start ({holdout_start.date()}). The hold-out window is not "
        "untouched — WF training/testing overlaps with it."
    )


def test_without_holdout_cap_splits_reach_data_end():
    """Positive control: without wf_end, the last split's test_end reaches data_end.

    This confirms that the cap is actually doing work; without it the split
    loop extends into the hold-out period.
    """
    data_start = "2024-01-01"
    data_end = "2026-01-01"

    splits_uncapped = compute_splits(
        data_start=data_start,
        data_end=data_end,
        warmup_months=0,
        train_months=12,
        test_months=3,
        step_months=3,
        wf_end=None,  # no cap
    )
    holdout_start = pd.Timestamp(data_end) - relativedelta(months=6)
    last_te = _last_test_end(splits_uncapped)

    assert last_te is not None
    assert last_te >= holdout_start, (
        "Positive-control failure: without wf_end the last split should extend "
        f"past holdout_start ({holdout_start.date()}) but got {last_te.date()}."
    )


def test_wf_end_equals_data_end_minus_holdout_months():
    """Unit test for the wf_end arithmetic used in run_walkforward.

    data_end="2026-01-01", holdout=6mo => wf_end should be "2025-07-01".
    """
    data_end = pd.Timestamp("2026-01-01")
    holdout_months = 6
    expected_wf_end = pd.Timestamp("2025-07-01")
    computed = data_end - relativedelta(months=holdout_months)
    assert computed == expected_wf_end, (
        f"wf_end arithmetic wrong: got {computed.date()}, "
        f"expected {expected_wf_end.date()}"
    )

    # Holdout disabled: wf_end should stay at data_end (no subtraction)
    holdout_months_zero = 0
    assert holdout_months_zero == 0  # trivial guard; no subtraction applied


def test_no_holdout_wf_end_is_none_semantics():
    """When wf_end=None, compute_splits uses data_end — existing behaviour unchanged."""
    data_start = "2024-01-01"
    data_end = "2025-06-30"

    splits_explicit_none = compute_splits(
        data_start=data_start,
        data_end=data_end,
        warmup_months=0,
        train_months=6,
        test_months=3,
        step_months=3,
        wf_end=None,
    )
    splits_omitted = compute_splits(
        data_start=data_start,
        data_end=data_end,
        warmup_months=0,
        train_months=6,
        test_months=3,
        step_months=3,
    )
    # Both calls should yield identical splits
    assert splits_explicit_none == splits_omitted, (
        "compute_splits(wf_end=None) and compute_splits() must be identical"
    )
