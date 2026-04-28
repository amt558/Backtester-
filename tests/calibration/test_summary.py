"""Test calibration summary aggregations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
from tradelab.calibration.summary import (
    CalibrationSummaryResult,
    summarize_calibration,
    is_te_tripped_within_30d,
)


def test_empty_cards_yields_zero_counts():
    result = summarize_calibration(cards=[], te_loader=lambda card_id: {"status": "insufficient", "n_live_trades": 0})
    assert result.n_accepted == 0
    assert result.n_te_tripped_30d == 0
    assert result.median_pf_gap is None


def test_n_accepted_counts_only_accepted_cards():
    # Use a recent date so it falls within the 90d window
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    cards = [
        {"card_id": "a", "accepted_bool": True, "created_at": recent},
        {"card_id": "b", "accepted_bool": False, "created_at": recent},
    ]
    result = summarize_calibration(cards=cards, te_loader=lambda c: {"status": "insufficient", "n_live_trades": 0})
    assert result.n_accepted == 1


def test_te_tripped_logic():
    # If a card's TE went below 0.60 in any of first-30-days, it's tripped.
    assert is_te_tripped_within_30d({"decay_series": [0.9, 0.8, 0.5, 0.6, 0.7], "status": "ok"})
    assert not is_te_tripped_within_30d({"decay_series": [0.9, 0.85, 0.8, 0.78, 0.82], "status": "ok"})
    assert not is_te_tripped_within_30d({"status": "insufficient", "decay_series": None})


def test_aged_out_cards_excluded():
    """Cards accepted >90d ago shouldn't count."""
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    cards = [
        {"card_id": "old", "accepted_bool": True, "created_at": old},
        {"card_id": "recent", "accepted_bool": True, "created_at": recent},
    ]
    result = summarize_calibration(cards=cards, te_loader=lambda c: {"status": "insufficient"})
    assert result.n_accepted == 1  # only recent


def test_pf_gap_aggregation():
    """When TE data shows actual te values, median_pf_gap is computed."""
    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    cards = [
        {"card_id": "a", "accepted_bool": True, "created_at": recent},
        {"card_id": "b", "accepted_bool": True, "created_at": recent},
        {"card_id": "c", "accepted_bool": True, "created_at": recent},
    ]
    te_values = {"a": 0.9, "b": 0.7, "c": 0.5}
    def loader(card_id):
        return {"status": "ok", "te": te_values[card_id], "decay_series": [te_values[card_id]]}
    result = summarize_calibration(cards=cards, te_loader=loader, window_days=90)
    assert result.n_accepted == 3
    # PF gaps: 1-0.9=0.1, 1-0.7=0.3, 1-0.5=0.5 → median 0.3
    assert result.median_pf_gap == pytest.approx(0.3, abs=0.001)
