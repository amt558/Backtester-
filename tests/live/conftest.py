"""Shared fixtures for tests/live.

Two responsibilities:

1. **Autouse redirect of notify_events.jsonl paths** — any test that exercises
   a code path calling `notify.notify(...)` (directly or via the receiver
   webhook → guardrail-block → CRITICAL notify chain) would otherwise write
   test fixtures into the production `live/notify_events.jsonl`. Two
   module-level constants point at that file:
     - `tradelab.live.notify.NOTIFY_EVENTS_PATH` (producer-side)
     - `tradelab.live.daily_summary.NOTIFY_PATH` (digest audit-line)
   Both are captured at import time, so we monkeypatch both for every test.
   Tests that explicitly monkeypatch either constant inside their body
   stack correctly on top of the autouse redirect.

2. **Shared `patched_receiver` fixture** for receiver webhook-flow tests —
   formerly duplicated across `test_receiver_guardrails.py` and
   `test_receiver_alpaca_wrap.py`. Consolidates: cards.json + alerts.jsonl
   tmp paths, AlpacaState stub, _fetch_last_price stub, submit_market_order
   stub, notify capture (always on — harmless when unused), and TestClient
   with raise_server_exceptions=False (harmless for tests that only check
   status codes).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _redirect_notify_events_path(tmp_path, monkeypatch):
    target = tmp_path / "notify_events.jsonl"
    from tradelab.live import notify
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", target)
    try:
        from tradelab.live import daily_summary
        monkeypatch.setattr(daily_summary, "NOTIFY_PATH", target, raising=False)
    except ImportError:
        # daily_summary may not be importable in all test environments
        pass
    yield target


_DEFAULT_CARD = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AAPL",
    "status": "enabled", "quantity": 10,
    "cooldown_seconds": 30, "daily_limit": 5,
    "allow_collision": False, "allow_naked_short": False,
}


@pytest.fixture
def patched_receiver(tmp_path, monkeypatch):
    """Receiver fixture for webhook-flow tests. Returns a dict with:
      - cards_path / alerts_path: tmp file paths
      - fake_state: MagicMock AlpacaState (override side_effect to fail)
      - notify_calls: list of {severity, title, message} captured from notify
      - client: FastAPI TestClient(app, raise_server_exceptions=False)
    """
    from tradelab.live.cards import CardRegistry
    from tradelab.live import receiver as rec

    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": _DEFAULT_CARD}), encoding="utf-8")
    alerts_path = tmp_path / "alerts.jsonl"

    monkeypatch.setattr(rec, "ALERT_LOG", alerts_path)
    monkeypatch.setattr(rec, "cards", CardRegistry(cards_path))
    monkeypatch.setattr(rec, "_card_state", {})

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

    monkeypatch.setattr(rec, "_fetch_last_price", lambda symbol: 200.0)
    monkeypatch.setattr(
        rec, "submit_market_order",
        lambda symbol, action, qty, coid: {"id": "ORD-1", "status": "accepted"},
    )

    notify_calls: list[dict] = []

    def _capture_notify(severity, title, message, *args, **kwargs):
        notify_calls.append({"severity": severity, "title": title, "message": message})

    monkeypatch.setattr(rec._notify, "notify", _capture_notify)

    return {
        "cards_path": cards_path,
        "alerts_path": alerts_path,
        "fake_state": fake_state,
        "notify_calls": notify_calls,
        "client": TestClient(rec.app, raise_server_exceptions=False),
    }
