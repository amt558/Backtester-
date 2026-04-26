"""Receiver-side notify() integration: guardrail_blocked + order_failed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradelab.live import notify, live_config
from tradelab.live.receiver import app


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    notify_events = tmp_path / "notify_events.jsonl"
    cfg_path = tmp_path / "live_config.json"
    cards_path = tmp_path / "cards.json"
    alerts_path = tmp_path / "alerts.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", notify_events)
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", cfg_path)
    live_config.reload()

    from tradelab.live import receiver
    from tradelab.live.cards import CardRegistry
    cards_path.write_text(json.dumps({
        "test-aapl": {"card_id": "test-aapl", "status": "enabled", "symbol": "AAPL", "quantity": 1, "secret": "s", "cadence": "intraday", "daily_limit": 1, "cooldown_seconds": 5}
    }), encoding="utf-8")
    monkeypatch.setattr(receiver, "cards", CardRegistry(cards_path))
    monkeypatch.setattr(receiver, "ALERT_LOG", alerts_path)
    yield notify_events


_WEBHOOK_PAYLOAD = {
    "card_id": "test-aapl",
    "secret": "s",
    "action": "buy",
    "symbol": "AAPL",
    "contracts": 1,
}


def test_guardrail_blocked_writes_notify_event(_isolated, monkeypatch):
    """Webhook blocked by daily_limit=1 (already fired today) should write a notify event."""
    from tradelab.live import receiver
    # Pre-load runtime state so daily_limit blocks
    from datetime import datetime, timezone
    receiver._card_state["test-aapl"] = receiver.CardRuntimeState(fires_today=1, fire_window_start=datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0))

    client = TestClient(app)
    resp = client.post("/webhook", json=_WEBHOOK_PAYLOAD)
    assert resp.status_code == 403
    lines = _isolated.read_text(encoding="utf-8").splitlines()
    notify_events = [json.loads(line) for line in lines]
    assert len(notify_events) == 1
    assert notify_events[0]["severity"] == "critical"
    assert "Guardrail blocked" in notify_events[0]["title"]
    assert "test-aapl" in notify_events[0]["body"]
    assert "daily_limit_exceeded" in notify_events[0]["body"]


def test_order_failed_writes_notify_event(_isolated, monkeypatch):
    """Alpaca submit raising should write a CRITICAL notify event."""
    from tradelab.live import receiver
    from unittest.mock import patch
    # Skip guardrails so we reach the submit path
    monkeypatch.setattr(receiver, "evaluate_guardrails", lambda *a, **k: None)
    # Monkeypatch _fetch_last_price so buying-power check has a price
    monkeypatch.setattr(receiver, "_fetch_last_price", lambda symbol: 100.0)

    with patch("tradelab.live.receiver.submit_market_order",
               side_effect=RuntimeError("alpaca went down")):
        client = TestClient(app)
        resp = client.post("/webhook", json=_WEBHOOK_PAYLOAD)
    assert resp.status_code == 502
    lines = _isolated.read_text(encoding="utf-8").splitlines()
    notify_events = [json.loads(line) for line in lines]
    assert any(ev["severity"] == "critical" and "order failed" in ev["title"].lower() for ev in notify_events)


def test_buying_power_check_reads_max_exposure_from_live_config(_isolated):
    """check_buying_power should consult live_config, not a hardcoded constant."""
    live_config.update({"guardrails": {"max_exposure_pct": 0.5}})
    from tradelab.live.guardrails import check_buying_power

    class _Account:
        def __init__(self, buying_power):
            self.buying_power = buying_power

    class _AlpacaStub:
        def account(self):
            return _Account("10000")
        def open_orders(self):
            return []

    card = {"card_id": "x", "symbol": "AAPL", "quantity": 100}
    # Order notional = 100 * 100 = 10000; max_exposure_pct=0.5 → cap=5000 → blocked
    reason = check_buying_power(card, alpaca_state=_AlpacaStub(), qty=100, last_price=100.0)
    assert reason is not None
    assert reason.code == "insufficient_buying_power"

    live_config.update({"guardrails": {"max_exposure_pct": 1.0}})
    reason = check_buying_power(card, alpaca_state=_AlpacaStub(), qty=100, last_price=100.0)
    assert reason is None  # cap=10000, fits exactly
