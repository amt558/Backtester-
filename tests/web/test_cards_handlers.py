"""Tests for /tradelab/cards* GET handlers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import handlers


def _seed(tmp_path: Path, cards: dict, alerts: list[dict]) -> tuple[Path, Path]:
    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps(cards), encoding="utf-8")
    alerts_path = tmp_path / "alerts.jsonl"
    alerts_path.write_text(
        "\n".join(json.dumps(a) for a in alerts) + ("\n" if alerts else ""),
        encoding="utf-8",
    )
    return cards_path, alerts_path


def test_get_cards_returns_grouped_view(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32,
                   "symbol": "AAPL", "status": "enabled", "quantity": 5},
    }, [])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, status = handlers.handle_get_with_status("/tradelab/cards")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["total_cards"] == 1
    assert payload["total_enabled"] == 1
    assert payload["groups"][0]["base_name"] == "foo"


def test_get_cards_handles_missing_cards_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "no_cards.json")
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")

    body, status = handlers.handle_get_with_status("/tradelab/cards")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload == {"groups": [], "total_cards": 0, "total_enabled": 0}


def test_get_card_alerts_returns_tail(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32,
                   "symbol": "AAPL", "status": "enabled", "quantity": 5},
    }, [
        {"ts": "2026-04-25T09:00:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1",
         "status": "order_failed"},
    ])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/alerts?limit=50"
    )

    assert status == 200
    payload = json.loads(body)["data"]
    assert len(payload["alerts"]) == 2
    assert payload["alerts"][0]["status"] == "order_failed"  # newest first


def test_get_card_alerts_limit_param(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {}, [
        {"ts": f"2026-04-25T09:0{i}:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"}
        for i in range(5)
    ])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, _ = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/alerts?limit=2"
    )
    payload = json.loads(body)["data"]
    assert len(payload["alerts"]) == 2


def test_get_card_archive_returns_pine_and_verdict(tmp_path: Path, monkeypatch) -> None:
    archive_root = tmp_path / "pine_archive"
    card_dir = archive_root / "foo-v1"
    card_dir.mkdir(parents=True)
    (card_dir / "strategy.pine").write_text("// pine source", encoding="utf-8")
    (card_dir / "verdict.json").write_text(
        json.dumps({"verdict": "ROBUST", "dsr": 0.75}),
        encoding="utf-8",
    )
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: archive_root)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/archive"
    )

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["pine_source"] == "// pine source"
    assert payload["verdict"]["verdict"] == "ROBUST"


def test_get_card_archive_404_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/never-existed-v1/archive"
    )
    assert status == 404
