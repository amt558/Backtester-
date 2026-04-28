"""Tests for /tradelab/cards* GET handlers."""
from __future__ import annotations

import json
import urllib.error
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


def test_get_card_archive_empty_directory_returns_empty_payload(tmp_path: Path, monkeypatch) -> None:
    """Archive dir exists but contains no files → 200 with empty payload (lenient).

    Documents the intentional soft behavior: partial archives serve what's there.
    A missing archive_dir returns 404; an empty archive_dir returns 200 with {}.
    """
    archive_root = tmp_path / "pine_archive"
    (archive_root / "foo-v1").mkdir(parents=True)
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: archive_root)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/archive"
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload == {}


def test_get_card_archive_malformed_verdict_returns_error_in_payload(tmp_path: Path, monkeypatch) -> None:
    """Malformed verdict.json is wrapped as {"verdict": {"error": "..."}} at HTTP 200.

    Soft-error design: pine_source still flows through, frontend can show what
    succeeded and what failed without losing the whole archive.
    """
    archive_root = tmp_path / "pine_archive"
    card_dir = archive_root / "foo-v1"
    card_dir.mkdir(parents=True)
    (card_dir / "strategy.pine").write_text("// pine source", encoding="utf-8")
    (card_dir / "verdict.json").write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: archive_root)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/archive"
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["pine_source"] == "// pine source"
    assert "error" in payload["verdict"]


def test_get_receiver_status_reports_up(tmp_path: Path, monkeypatch) -> None:
    """Receiver and ngrok both responding → both up=True."""
    def fake_probe(url: str, timeout: float):
        if "8878" in url:
            return {"status": "ok", "cards_loaded": 3}
        if "4040" in url:
            return {"tunnels": [
                {"public_url": "https://abcd-1234.ngrok-free.app",
                 "proto": "https"}
            ]}
        raise ValueError(f"unexpected url {url}")

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["receiver_up"] is True
    assert payload["ngrok_up"] is True
    assert payload["ngrok_url"] == "https://abcd-1234.ngrok-free.app"
    assert payload["cards_loaded"] == 3


def test_get_receiver_status_reports_down(monkeypatch) -> None:
    """Both probes fail → both up=False, no ngrok URL."""
    def fake_probe(url: str, timeout: float):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["receiver_up"] is False
    assert payload["ngrok_up"] is False
    assert payload["ngrok_url"] is None


def test_get_receiver_status_mixed_states(monkeypatch) -> None:
    """Receiver up, ngrok down → only receiver=True."""
    call_count = {"count": 0}
    def fake_probe(url: str, timeout: float):
        call_count["count"] += 1
        if "8878" in url:
            return {"status": "ok", "cards_loaded": 2}
        raise urllib.error.URLError("ngrok down")

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["receiver_up"] is True
    assert payload["ngrok_up"] is False
    assert payload["ngrok_url"] is None
    assert payload["cards_loaded"] == 2
    assert call_count["count"] == 2  # both probes ran independently


def test_get_receiver_status_ngrok_no_https_tunnel(monkeypatch) -> None:
    """ngrok responds but has no HTTPS tunnel yet (only HTTP)."""
    def fake_probe(url: str, timeout: float):
        if "8878" in url:
            return {"status": "ok", "cards_loaded": 0}
        return {"tunnels": [{"proto": "http", "public_url": "http://abcd-1234.ngrok-free.app"}]}

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["ngrok_up"] is False  # no HTTPS tunnel found
    assert payload["ngrok_url"] is None


# ─── PATCH /tradelab/cards/<id> ──────────────────────────────────────────────


def _seed_card(tmp_path: Path, monkeypatch, card_id: str, **fields) -> Path:
    """Test helper: write one-card cards.json + monkeypatch path."""
    cards_path = tmp_path / "cards.json"
    base = {
        "card_id": card_id, "secret": "x" * 32, "symbol": "AAPL",
        "status": "disabled", "quantity": 1,
    }
    base.update(fields)
    cards_path.write_text(json.dumps({card_id: base}), encoding="utf-8")
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")
    return cards_path


def test_patch_card_updates_status(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"status": "enabled"}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"error": None, "data": {"updated": "foo-v1"}}
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["status"] == "enabled"


def test_patch_card_404_when_missing(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/no-such-card",
        json.dumps({"status": "enabled"}).encode(),
    )
    assert status == 404
    assert json.loads(body)["error"] == "card not found"


def test_patch_card_rejects_unknown_field(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"secret": "new-secret", "status": "enabled"}).encode(),
    )
    assert status == 400
    assert "unknown field" in json.loads(body)["error"]


def test_patch_card_rejects_invalid_status(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"status": "garbage"}).encode(),
    )
    assert status == 400


def test_patch_card_rejects_negative_quantity(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"quantity": -1}).encode(),
    )
    assert status == 400


def test_patch_card_accepts_null_quantity(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1", quantity=5)
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"quantity": None}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["quantity"] is None


# ─── DELETE /tradelab/cards/<id> ─────────────────────────────────────────────


def test_delete_card_removes_with_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/foo-v1",
        json.dumps({"confirm": "DELETE"}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "foo-v1" not in on_disk


def test_delete_card_rejects_without_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/foo-v1",
        json.dumps({}).encode(),
    )
    assert status == 400
    assert "confirm" in json.loads(body)["error"]
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "foo-v1" in on_disk


def test_delete_card_404_when_missing(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/no-such-card",
        json.dumps({"confirm": "DELETE"}).encode(),
    )
    assert status == 404


# ─── POST /tradelab/cards/bulk-toggle ────────────────────────────────────────


def _seed_n_cards(tmp_path, monkeypatch, ids):
    cards_path = tmp_path / "cards.json"
    cards = {
        cid: {"card_id": cid, "secret": "x" * 32, "symbol": "AAPL",
              "status": "disabled", "quantity": 1}
        for cid in ids
    }
    cards_path.write_text(json.dumps(cards), encoding="utf-8")
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")
    return cards_path


def test_bulk_toggle_enables_all(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1", "b-v1", "c-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-toggle",
        json.dumps({"ids": ["a-v1", "b-v1", "c-v1"], "status": "enabled"}).encode(),
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload == {"updated": ["a-v1", "b-v1", "c-v1"], "failed": []}
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert all(on_disk[cid]["status"] == "enabled" for cid in ["a-v1", "b-v1", "c-v1"])


def test_bulk_toggle_reports_failed_ids(tmp_path: Path, monkeypatch):
    _seed_n_cards(tmp_path, monkeypatch, ["a-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-toggle",
        json.dumps({"ids": ["a-v1", "ghost-v1"], "status": "enabled"}).encode(),
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["updated"] == ["a-v1"]
    assert payload["failed"] == [{"id": "ghost-v1", "reason": "card not found"}]


def test_bulk_delete_removes_with_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1", "b-v1", "c-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-delete",
        json.dumps({"ids": ["a-v1", "b-v1"], "confirm": "DELETE"}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert set(on_disk.keys()) == {"c-v1"}


def test_bulk_delete_rejects_without_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-delete",
        json.dumps({"ids": ["a-v1"]}).encode(),
    )
    assert status == 400
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "a-v1" in on_disk


def test_tracking_error_endpoint_returns_insufficient_for_no_live(
    tmp_path: Path, monkeypatch
) -> None:
    """If a card has tv_trades but no live fills, status is 'insufficient'."""
    archive = tmp_path / "pine_archive" / "alpha-v1"
    archive.mkdir(parents=True)
    (archive / "tv_trades.csv").write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30:00,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    # load_live_returns_for_card already returns [] (stub) — no extra monkeypatch needed.

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/alpha-v1/tracking-error"
    )

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["status"] == "insufficient"
    assert payload["n_live_trades"] == 0
    assert payload["te"] is None
    assert payload["ks_p"] is None


def test_tracking_error_endpoint_404_when_no_csv(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing tv_trades.csv → 404."""
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/never-existed-v1/tracking-error"
    )

    assert status == 404
    assert json.loads(body)["error"] is not None
