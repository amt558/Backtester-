"""T13: receiver wraps Alpaca-state-touching guardrails with FAIL-CLOSED try/except.

If `evaluate_guardrails(...)` raises (because alpaca_state.positions() / .account() /
.open_orders() bubbled up an Alpaca API error or other unexpected exception), the
webhook handler must:
  - log alerts.jsonl line with status="guardrail_blocked", reason="alpaca_unreachable"
  - fire _notify.notify(Severity.CRITICAL, ...)
  - return JSONResponse status 503 with body containing "alpaca_unreachable"

The `patched_receiver` fixture lives in tests/live/conftest.py.
"""
from __future__ import annotations

import json

import pytest
from alpaca.common.exceptions import APIError

from tradelab.live import receiver as rec


def _alert_payload(action="buy", **overrides):
    base = {
        "card_id": "foo-v1", "secret": "s" * 32,
        "symbol": "AAPL", "action": action, "contracts": 1,
    }
    base.update(overrides)
    return base


def test_webhook_returns_503_when_alpaca_state_raises_apierror(patched_receiver):
    """APIError from alpaca_state.account() must produce 503 + fail-closed log/notify.

    For action="buy" the call order in evaluate_guardrails is cooldown → daily_limit →
    collision → naked_short (no-op for buy) → buying_power, where buying_power hits
    alpaca_state.account() first. So .account() is the right surface to fail.
    """
    p = patched_receiver
    p["fake_state"].account.side_effect = APIError("alpaca down")

    resp = p["client"].post("/webhook", json=_alert_payload())

    assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "alpaca_unreachable" in body["error"], f"body={body!r}"

    # alerts.jsonl tail must record the fail-closed block
    log_lines = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log_lines[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "alpaca_unreachable"

    # notify fired with CRITICAL severity AND with the APIError-specific title
    # ("Alpaca state fetch failed"). Anchoring on the title is what distinguishes
    # the APIError branch from the generic-Exception branch — without this the
    # test would still pass if a future maintainer accidentally swapped the
    # exception handler order and absorbed APIError into the generic branch.
    assert len(p["notify_calls"]) >= 1
    assert any(
        c["severity"] == rec.Severity.CRITICAL
        and c["title"] == "Alpaca state fetch failed"
        for c in p["notify_calls"]
    ), f"notify_calls={p['notify_calls']!r}"
    # And the response body for APIError specifically does NOT carry the
    # type-name prefix (the generic branch does); pin that asymmetry.
    assert body["error"] == "alpaca_unreachable: alpaca down", f"body={body!r}"


def test_webhook_returns_503_when_alpaca_state_raises_generic_exception(patched_receiver):
    """A non-APIError exception from alpaca_state must still fail-closed (broader catch)."""
    p = patched_receiver
    p["fake_state"].account.side_effect = RuntimeError("network blew up")

    resp = p["client"].post("/webhook", json=_alert_payload())

    assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "alpaca_unreachable" in body["error"], f"body={body!r}"
    assert "RuntimeError" in body["error"], f"body={body!r}"

    log_lines = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log_lines[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "alpaca_unreachable"

    assert len(p["notify_calls"]) >= 1
    assert any(c["severity"] == rec.Severity.CRITICAL for c in p["notify_calls"])


def test_webhook_happy_path_unaffected_by_wrap(patched_receiver):
    """The wrap must not regress the success path (fake_state methods do not raise)."""
    p = patched_receiver
    resp = p["client"].post("/webhook", json=_alert_payload())
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
