"""Tests for tradelab.live.panic — Slice 6 panic logic.

Tests are organized by section:
  - Dataclass shape (Task 3)
  - L1 effect (Task 4)
  - L2 effect (Task 5)
  - L3 effect (Task 6)
  - Audit log + notify (interleaved with above)
  - Top-level execute_panic dispatch (Task 5/6)
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Section: dataclass shape ───────────────────────────────────────────

def test_cancel_action_fields():
    from tradelab.live.panic import CancelAction
    a = CancelAction(ok=True, error=None, order_id="alp-1",
                     client_order_id="card_a-123", card_id="card_a")
    assert a.ok is True
    assert a.error is None
    assert a.order_id == "alp-1"
    assert a.client_order_id == "card_a-123"
    assert a.card_id == "card_a"


def test_flatten_action_fields():
    from tradelab.live.panic import FlattenAction
    a = FlattenAction(ok=True, error=None, symbol="AAPL", qty="10",
                      side="sell", order_id="alp-2")
    assert a.symbol == "AAPL"
    assert a.qty == "10"
    assert a.side == "sell"
    assert a.order_id == "alp-2"


def test_panic_result_fields():
    from tradelab.live.panic import PanicResult
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=[],
        orders_cancelled=[],
        positions_flattened=[],
    )
    assert r.level == "L1"
    assert r.cards_disabled == []


# ─── Section: helper — _truncate_for_notification ───────────────────────

def test_truncate_under_10():
    from tradelab.live.panic import _truncate_for_notification
    ids = ["a", "b", "c"]
    assert _truncate_for_notification(ids) == "a, b, c"


def test_truncate_exactly_10():
    from tradelab.live.panic import _truncate_for_notification
    ids = [f"x{i}" for i in range(10)]
    out = _truncate_for_notification(ids)
    assert "+1 more" not in out
    assert "+0 more" not in out


def test_truncate_at_11():
    from tradelab.live.panic import _truncate_for_notification
    ids = [f"x{i}" for i in range(11)]
    out = _truncate_for_notification(ids)
    assert out.endswith("… +1 more")


def test_truncate_empty():
    from tradelab.live.panic import _truncate_for_notification
    assert _truncate_for_notification([]) == "(none)"


# ─── Section: helper — _build_notification_body ─────────────────────────

def test_build_body_l1_only_cards():
    from tradelab.live.panic import _build_notification_body, PanicResult
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=["card_a", "card_b"],
        orders_cancelled=[],
        positions_flattened=[],
    )
    body = _build_notification_body(r)
    assert "L1 panic" in body
    assert "Cards disabled (2)" in body
    assert "card_a, card_b" in body
    assert "Orders cancelled (0)" in body
    assert "Positions flattened: (none)" in body


def test_build_body_l3_with_failures():
    from tradelab.live.panic import (_build_notification_body, PanicResult,
                                      CancelAction, FlattenAction)
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L3",
        before_state_snapshot=[],
        cards_disabled=["card_a"],
        orders_cancelled=[CancelAction(ok=True, error=None, order_id="o1",
                                       client_order_id="c1", card_id="card_a"),
                          CancelAction(ok=False, error="APIError: 429",
                                       order_id="o2", client_order_id="c2",
                                       card_id="card_a")],
        positions_flattened=[FlattenAction(ok=True, error=None, symbol="AAPL",
                                           qty="10", side="sell", order_id="o3")],
    )
    body = _build_notification_body(r)
    assert "Errors: 1" in body  # one failed cancel


# ─── Section: execute_panic L1 ──────────────────────────────────────────

@pytest.fixture
def tmp_panic_log(monkeypatch, tmp_path):
    """Redirect panic_events.jsonl to a tmp file."""
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    return p


@pytest.fixture
def mock_card_registry(monkeypatch):
    """Mock the CardRegistry that panic.py loads to snapshot/disable cards."""
    from tradelab.live import panic

    cards_state = {
        "card_a": {"card_id": "card_a", "base_name": "S2_AAPL_LONG",
                   "status": "enabled", "qty": 100, "last_fired_at": "2026-04-26T13:00:00-04:00"},
        "card_b": {"card_id": "card_b", "base_name": "S4_MSFT_SHORT",
                   "status": "enabled", "qty": 50, "last_fired_at": None},
        "card_c": {"card_id": "card_c", "base_name": "S7_NVDA_LONG",
                   "status": "disabled", "qty": 200, "last_fired_at": None},
    }
    disabled_calls = []

    class FakeRegistry:
        def all_hydrated(self):
            return dict(cards_state)
        def set_status(self, card_id, status):
            cards_state[card_id]["status"] = status
            disabled_calls.append((card_id, status))

    fake = FakeRegistry()
    monkeypatch.setattr(panic, "_load_registry", lambda: fake)
    fake._calls = disabled_calls
    return fake


@pytest.fixture
def mock_notify(monkeypatch):
    from tradelab.live import panic
    calls = []

    def fake_notify(severity, title, body, **kwargs):
        calls.append({"severity": severity, "title": title, "body": body})

    monkeypatch.setattr(panic, "_notify_fn", fake_notify)
    return calls


def test_l1_disables_all_enabled_cards(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    result = execute_panic("L1")

    assert result.level == "L1"
    assert set(result.cards_disabled) == {"card_a", "card_b"}
    # card_c was already disabled — should NOT appear in cards_disabled
    assert "card_c" not in result.cards_disabled
    # set_status was called only for the enabled ones
    disabled_ids = {cid for cid, status in mock_card_registry._calls if status == "disabled"}
    assert disabled_ids == {"card_a", "card_b"}


def test_l1_no_alpaca_calls(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    with patch("tradelab.live.alpaca_client.list_open_orders") as lo, \
         patch("tradelab.live.alpaca_client.cancel_order_by_id") as co, \
         patch("tradelab.live.alpaca_client.list_positions") as lp, \
         patch("tradelab.live.alpaca_client.submit_market_order") as sm:
        execute_panic("L1")
        lo.assert_not_called()
        co.assert_not_called()
        lp.assert_not_called()
        sm.assert_not_called()


def test_l1_audit_log_appended(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    execute_panic("L1")

    lines = tmp_panic_log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == "L1"
    assert "ts" in entry
    assert set(entry["cards_disabled"]) == {"card_a", "card_b"}
    assert entry["orders_cancelled"] == []
    assert entry["positions_flattened"] == []


def test_l1_audit_log_snapshot_shape(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    execute_panic("L1")

    entry = json.loads(tmp_panic_log.read_text(encoding="utf-8").strip())
    snap = entry["before_state_snapshot"]
    assert len(snap) == 3  # all 3 cards (enabled + disabled)
    fields = set(snap[0].keys())
    assert {"card_id", "base_name", "status", "qty", "last_fired_at"}.issubset(fields)


def test_l1_notify_called_with_critical(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    from tradelab.live.notify import Severity

    execute_panic("L1")

    assert len(mock_notify) == 1
    assert mock_notify[0]["severity"] == Severity.CRITICAL
    assert "L1 panic" in mock_notify[0]["title"]
    assert "2 cards disabled" in mock_notify[0]["title"]


def test_l1_invalid_level_raises(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    with pytest.raises(ValueError):
        execute_panic("L4")


# ─── Section: execute_panic L2 ──────────────────────────────────────────

@pytest.fixture
def mock_alpaca_orders(monkeypatch):
    """Patch alpaca_client.list_open_orders + cancel_order_by_id with mocks."""
    from tradelab.live import alpaca_client
    list_calls = []
    cancel_calls = []

    def fake_list():
        return list_calls[0] if list_calls else []

    def fake_cancel(order_id):
        cancel_calls.append(order_id)

    monkeypatch.setattr(alpaca_client, "list_open_orders", fake_list)
    monkeypatch.setattr(alpaca_client, "cancel_order_by_id", fake_cancel)
    return list_calls, cancel_calls


def test_l2_cancels_only_tradelab_orders_by_default(
    tmp_panic_log, mock_card_registry, mock_notify, mock_alpaca_orders
):
    from tradelab.live.panic import execute_panic
    list_calls, cancel_calls = mock_alpaca_orders
    list_calls.append([
        {"id": "alp-1", "client_order_id": "card_a-1714142887000",
         "symbol": "AAPL", "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "manual-order-xyz",
         "symbol": "TSLA", "qty": "5", "side": "buy", "status": "new"},
    ])

    result = execute_panic("L2")

    assert cancel_calls == ["alp-1"]  # only tradelab order
    assert len(result.orders_cancelled) == 1
    assert result.orders_cancelled[0].ok is True
    assert result.orders_cancelled[0].order_id == "alp-1"


def test_l2_cancels_all_orders_when_flag_on(
    tmp_panic_log, mock_card_registry, mock_notify, mock_alpaca_orders
):
    from tradelab.live.panic import execute_panic
    list_calls, cancel_calls = mock_alpaca_orders
    list_calls.append([
        {"id": "alp-1", "client_order_id": "card_a-1714142887000",
         "symbol": "AAPL", "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "manual-order-xyz",
         "symbol": "TSLA", "qty": "5", "side": "buy", "status": "new"},
    ])

    result = execute_panic("L2", also_cancel_nontradelab=True)

    assert sorted(cancel_calls) == ["alp-1", "alp-2"]
    assert len(result.orders_cancelled) == 2
    # The manual one should record card_id=None
    by_oid = {a.order_id: a for a in result.orders_cancelled}
    assert by_oid["alp-2"].card_id is None
    assert by_oid["alp-1"].card_id == "card_a"


def test_l2_partial_failure_continues(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    monkeypatch.setattr(alpaca_client, "list_open_orders", lambda: [
        {"id": "alp-1", "client_order_id": "card_a-1", "symbol": "AAPL",
         "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "card_a-2", "symbol": "AAPL",
         "qty": "10", "side": "buy", "status": "new"},
    ])

    def fake_cancel(oid):
        if oid == "alp-2":
            raise Exception("simulated APIError")
    monkeypatch.setattr(alpaca_client, "cancel_order_by_id", fake_cancel)

    result = execute_panic("L2")

    assert len(result.orders_cancelled) == 2
    by_oid = {a.order_id: a for a in result.orders_cancelled}
    assert by_oid["alp-1"].ok is True
    assert by_oid["alp-2"].ok is False
    assert "simulated APIError" in (by_oid["alp-2"].error or "")
    # And the panic itself completed (audit + notify fired)
    assert tmp_panic_log.exists()
    assert len(mock_notify) == 1


def test_l2_list_orders_failure_recorded_as_synthetic_action(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    def fake_list():
        raise Exception("network down")
    monkeypatch.setattr(alpaca_client, "list_open_orders", fake_list)

    result = execute_panic("L2")

    assert len(result.orders_cancelled) == 1
    assert result.orders_cancelled[0].ok is False
    assert "network down" in (result.orders_cancelled[0].error or "")
    # L1 step still succeeded
    assert set(result.cards_disabled) == {"card_a", "card_b"}
