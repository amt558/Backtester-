"""End-to-end webhook → guardrail pipeline → alpaca submit / block."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tradelab.live.cards import CardRegistry
from tradelab.live.guardrails import CardRuntimeState
from tradelab.live import receiver as rec


CARD = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AAPL",
    "status": "enabled", "quantity": 10,
    "cooldown_seconds": 30, "daily_limit": 5,
    "allow_collision": False, "allow_naked_short": False,
}


@pytest.fixture
def patched_receiver(tmp_path, monkeypatch):
    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": CARD}), encoding="utf-8")
    alerts_path = tmp_path / "alerts.jsonl"

    monkeypatch.setattr(rec, "ALERT_LOG", alerts_path)
    monkeypatch.setattr(rec, "cards", CardRegistry(cards_path))
    monkeypatch.setattr(rec, "_card_state", {})

    # Stub AlpacaState so guardrails see a fully-stocked account
    class _Acct:
        buying_power = "1000000"
    class _Pos:
        symbol = "AAPL"
        qty = "100"
    fake_state = MagicMock()
    fake_state.positions.return_value = [_Pos()]
    fake_state.account.return_value = _Acct()
    fake_state.open_orders.return_value = []
    fake_state.invalidate = MagicMock()
    monkeypatch.setattr(rec, "_alpaca_state", fake_state, raising=False)

    # Stub last-price fetch
    monkeypatch.setattr(rec, "_fetch_last_price", lambda symbol: 200.0)

    # Stub Alpaca submit
    monkeypatch.setattr(
        rec, "submit_market_order",
        lambda symbol, action, qty, coid: {"id": "ORD-1", "status": "accepted"},
    )

    return {
        "cards_path": cards_path,
        "alerts_path": alerts_path,
        "fake_state": fake_state,
        "client": TestClient(rec.app),
    }


def _alert_payload(action="buy", **overrides):
    base = {
        "card_id": "foo-v1", "secret": "s" * 32,
        "symbol": "AAPL", "action": action, "contracts": 1,
    }
    base.update(overrides)
    return base


def test_webhook_passes_guardrails_and_submits(patched_receiver):
    resp = patched_receiver["client"].post("/webhook", json=_alert_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # last_fired_at written to cards.json
    on_disk = json.loads(patched_receiver["cards_path"].read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["last_fired_at"] is not None
    # alpaca_state invalidated after submit
    assert patched_receiver["fake_state"].invalidate.call_count >= 1
    # alert log written with order_submitted
    log = patched_receiver["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    statuses = [json.loads(l)["status"] for l in log]
    assert "order_submitted" in statuses


def test_webhook_blocked_by_cooldown_returns_403(patched_receiver):
    """Two webhooks within cooldown_seconds — second must be blocked."""
    p = patched_receiver
    # First webhook fires successfully
    r1 = p["client"].post("/webhook", json=_alert_payload())
    assert r1.status_code == 200
    # Second webhook immediately after — cooldown trips
    r2 = p["client"].post("/webhook", json=_alert_payload())
    assert r2.status_code == 403
    body = r2.json()
    assert "cooldown" in body["error"].lower()
    log = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "cooldown_active"


def test_webhook_blocked_logs_guardrail_blocked_with_reason_field(patched_receiver):
    p = patched_receiver
    # Pre-load state so daily_limit trips
    rec._card_state["foo-v1"] = CardRuntimeState(
        fires_today=999,
        fire_window_start=rec.get_rth_window_start(datetime.now(timezone.utc)),
    )
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 403
    log = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "daily_limit_exceeded"


def test_webhook_naked_short_blocked_when_no_position(patched_receiver):
    p = patched_receiver
    p["fake_state"].positions.return_value = []  # no inventory
    r = p["client"].post("/webhook", json=_alert_payload(action="sell"))
    assert r.status_code == 403
    body = r.json()
    assert "no_position_to_sell" in body["error"]


def test_webhook_records_fire_only_on_successful_submit(patched_receiver, monkeypatch):
    """If Alpaca submit fails, fires_today must NOT increment."""
    p = patched_receiver
    monkeypatch.setattr(
        rec, "submit_market_order",
        MagicMock(side_effect=RuntimeError("alpaca down")),
    )
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 500
    state = rec._card_state.get("foo-v1")
    assert state is None or state.fires_today == 0
    # last_attempted_at still set (we made an attempt)
    if state is not None:
        assert state.last_attempted_at is not None


def test_webhook_attempts_recorded_even_when_blocked(patched_receiver):
    """A blocked webhook must still update last_attempted_at — that's how
    a flood gets debounced even when every attempt is blocking."""
    p = patched_receiver
    # Prime state so the first webhook is blocked by cooldown
    primed = datetime.now(timezone.utc) - timedelta(seconds=1)
    rec._card_state["foo-v1"] = CardRuntimeState(last_attempted_at=primed)
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 403
    state = rec._card_state["foo-v1"]
    # last_attempted_at advanced from the primed value
    assert state.last_attempted_at is not None
    assert state.last_attempted_at > primed
