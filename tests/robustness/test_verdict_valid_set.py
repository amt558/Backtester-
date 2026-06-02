"""Engine-side guards for the canonical verdict set (VALID_VERDICTS).

Pins the single-source-of-truth invariant added alongside `tradelab robustness`:
the producer (compute_verdict) and the validator (VerdictResult) draw from the
SAME set, so the CLI imports it instead of hardcoding the three labels.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from pydantic import ValidationError

from tradelab.robustness.verdict import (
    VALID_VERDICTS, VERDICT_ROBUST, VERDICT_INCONCLUSIVE, VERDICT_FRAGILE,
    VerdictResult, compute_verdict,
)


def test_valid_verdicts_is_exactly_the_three_labels():
    assert VALID_VERDICTS == frozenset({"ROBUST", "INCONCLUSIVE", "FRAGILE"})
    # the named constants ARE the members: producer-source == enforced set
    assert {VERDICT_ROBUST, VERDICT_INCONCLUSIVE, VERDICT_FRAGILE} == VALID_VERDICTS


def test_verdictresult_rejects_out_of_set_value():
    # BOGUS-raises: a corrupted/typo'd verdict cannot escape the engine.
    with pytest.raises(ValidationError):
        VerdictResult(verdict="BOGUS")


@pytest.mark.parametrize("good", ["ROBUST", "INCONCLUSIVE", "FRAGILE"])
def test_verdictresult_accepts_valid_values(good):
    assert VerdictResult(verdict=good).verdict == good


def test_every_verdict_literal_compute_verdict_can_emit_is_valid():
    """AST scan of compute_verdict's source: every STRING literal assigned to a
    name `verdict` must be in VALID_VERDICTS. Catches a future rogue
    ``verdict = "WOBBLY"`` even in an unreached branch. After the
    producer-from-constant refactor there are ZERO such literals (assignments
    go through the VERDICT_* names), so this also forbids reintroducing a raw
    literal. A rogue assigned via a Name constant is instead caught by the
    field_validator at construction (test above)."""
    tree = ast.parse(inspect.getsource(compute_verdict))
    emitted = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "verdict" for t in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    bad = emitted - VALID_VERDICTS
    assert not bad, f"compute_verdict can emit non-VALID_VERDICTS literals: {bad}"
