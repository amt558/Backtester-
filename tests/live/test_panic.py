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
