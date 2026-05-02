"""Tests for POST /tradelab/runs/preview-delete (Slice 2 of Task 15).

The endpoint takes {"run_ids": [...]} and returns {"cascade": [...]} listing
every live card whose scoring_run_id is in the request — so the FE can
escalate to a card-aware confirm modal (Tier 2 / Tier 4) before sending
the destructive DELETE / bulk-delete.

Read-only — no mutation.
"""
from __future__ import annotations

import json
from pathlib import Path

from tradelab.web import handlers


def _write_cards(cards_path: Path, *card_dicts) -> None:
    """Write a cards.json file matching the on-disk schema CardRegistry uses
    (a flat dict keyed by card_id), since handlers.py reads it through that
    path."""
    by_id = {c["card_id"]: c for c in card_dicts}
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text(json.dumps(by_id))


def test_preview_delete_empty_request_returns_empty_cascade(
    tmp_path: Path, monkeypatch,
) -> None:
    cards_path = tmp_path / "cards.json"
    _write_cards(
        cards_path,
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
         "symbol": "AMZN", "quantity": 1, "secret": "s"},
    )
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({"run_ids": []}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"cascade": []}


def test_preview_delete_no_matching_cards_returns_empty_cascade(
    tmp_path: Path, monkeypatch,
) -> None:
    cards_path = tmp_path / "cards.json"
    _write_cards(
        cards_path,
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
         "symbol": "AMZN", "quantity": 1, "secret": "s"},
    )
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({"run_ids": ["r-other"]}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"cascade": []}


def test_preview_delete_single_card_match(tmp_path: Path, monkeypatch) -> None:
    cards_path = tmp_path / "cards.json"
    _write_cards(
        cards_path,
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
         "symbol": "AMZN", "quantity": 1, "secret": "s"},
        {"card_id": "c2", "base_name": "y", "scoring_run_id": "r99", "status": "enabled",
         "symbol": "META", "quantity": 5, "secret": "s2"},
    )
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({"run_ids": ["r1"]}).encode(),
    )
    assert status == 200
    cascade = json.loads(body)["cascade"]
    assert len(cascade) == 1
    assert cascade[0] == {
        "card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
    }


def test_preview_delete_omits_card_secret_and_other_fields(
    tmp_path: Path, monkeypatch,
) -> None:
    """Pin the contract: cascade entries carry only the 4 link fields, never
    the full card record (which would leak `secret`)."""
    cards_path = tmp_path / "cards.json"
    _write_cards(
        cards_path,
        {"card_id": "c1", "base_name": "x", "scoring_run_id": "r1", "status": "enabled",
         "symbol": "AMZN", "quantity": 1, "secret": "DO_NOT_LEAK", "cadence": "daily"},
    )
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({"run_ids": ["r1"]}).encode(),
    )
    assert status == 200
    cascade = json.loads(body)["cascade"]
    assert set(cascade[0].keys()) == {"card_id", "base_name", "scoring_run_id", "status"}
    assert "DO_NOT_LEAK" not in body


def test_preview_delete_missing_run_ids_field_returns_400(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({}).encode(),
    )
    assert status == 400
    assert "run_ids" in json.loads(body)["error"]


def test_preview_delete_invalid_json_returns_400(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        b"not-json",
    )
    assert status == 400


def test_preview_delete_missing_cards_file_returns_empty_cascade(
    tmp_path: Path, monkeypatch,
) -> None:
    """If cards.json doesn't exist (fresh install), no cards depend on
    anything — cascade is empty, NOT a 5xx."""
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "no_cards.json")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/preview-delete",
        json.dumps({"run_ids": ["r1"]}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"cascade": []}
