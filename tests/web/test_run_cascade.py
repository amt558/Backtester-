"""Slice 1 of Task 15: pure helper that finds cards whose scoring_run_id
sits in a given set of run_ids. Used by the upcoming /tradelab/runs/preview-delete
endpoint to drive Tier 2 / Tier 4 escalation modals.

The helper is deliberately pure: caller passes an iterable of card dicts
(typically `CardRegistry.all_hydrated().values()`) and a set of candidate
run_ids. No I/O, no DB access.
"""

from tradelab.web.run_cascade import cards_powered_by_runs


def test_empty_run_ids_returns_empty_list():
    cards = [{"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"}]
    assert cards_powered_by_runs(set(), cards) == []


def test_no_matching_run_ids_returns_empty_list():
    cards = [{"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"}]
    assert cards_powered_by_runs({"r-does-not-exist"}, cards) == []


def test_single_card_match_returns_one_link():
    cards = [{"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"}]
    result = cards_powered_by_runs({"r1"}, cards)
    assert result == [
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"}
    ]


def test_multiple_matches_across_cards():
    cards = [
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"},
        {"card_id": "c2", "base_name": "y", "scoring_run_id": "r2", "status": "disabled"},
        {"card_id": "c3", "base_name": "x", "scoring_run_id": "r99", "status": "enabled"},
    ]
    result = cards_powered_by_runs({"r1", "r2"}, cards)
    assert len(result) == 2
    assert {r["card_id"] for r in result} == {"c1", "c2"}


def test_card_without_scoring_run_id_is_skipped():
    """Smoke / test cards lack scoring_run_id; they must NOT match any run."""
    cards = [
        {"card_id": "smoke", "base_name": "smoke-amzn", "status": "enabled"},  # no scoring_run_id
        {"card_id": "real", "base_name": "y", "scoring_run_id": "r1", "status": "enabled"},
    ]
    result = cards_powered_by_runs({"r1"}, cards)
    assert len(result) == 1
    assert result[0]["card_id"] == "real"


def test_empty_cards_iterable_returns_empty():
    """Defensive: no cards at all (fresh install) returns empty cascade."""
    assert cards_powered_by_runs({"r1"}, []) == []


def test_accepts_dict_values_view():
    """CardRegistry.all_hydrated() returns dict; caller passes .values()."""
    cards_dict = {
        "c1": {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled"},
    }
    result = cards_powered_by_runs({"r1"}, cards_dict.values())
    assert len(result) == 1


def test_disabled_card_still_returned_when_run_matches():
    """Disabled cards still depend on a run; FE may want to clean them up too."""
    cards = [{"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "disabled"}]
    result = cards_powered_by_runs({"r1"}, cards)
    assert len(result) == 1
    assert result[0]["status"] == "disabled"


def test_returned_dict_has_exactly_four_fields():
    """Pin the contract: card_id, base_name, scoring_run_id, status (no leak of other card fields)."""
    cards = [{
        "card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
        "secret": "DO_NOT_LEAK", "quantity": 100, "cadence": "daily",
    }]
    result = cards_powered_by_runs({"r1"}, cards)
    assert len(result) == 1
    assert set(result[0].keys()) == {"card_id", "base_name", "scoring_run_id", "status"}
    assert "secret" not in result[0]
