"""Tests for POST /tradelab/live/panic and GET /tradelab/live/panic/last-event."""
import json
from unittest.mock import MagicMock, patch

import pytest

from tradelab.web import handlers


# ─── POST /tradelab/live/panic ─────────────────────────────────────────

def _post(path, payload):
    return handlers.handle_post_with_status(path, json.dumps(payload).encode())


def test_post_panic_l1_happy(monkeypatch, tmp_path):
    """L1 with correct confirm word returns 200 with PanicResult envelope."""
    from tradelab.live import panic

    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")

    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=["card_a"],
        orders_cancelled=[],
        positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        body, status = _post("/tradelab/live/panic",
                             {"level": "L1", "confirm": "DISABLE"})

    assert status == 200
    env = json.loads(body)
    assert env["ok"] is True
    assert env["data"]["level"] == "L1"
    assert env["data"]["cards_disabled"] == ["card_a"]
    ep.assert_called_once_with("L1", also_cancel_nontradelab=False)


def test_post_panic_wrong_confirm_word_400():
    body, status = _post("/tradelab/live/panic",
                         {"level": "L1", "confirm": "PANIC"})
    assert status == 400
    env = json.loads(body)
    assert env["ok"] is False
    assert "confirm" in env["error"].lower()


def test_post_panic_invalid_level_400():
    body, status = _post("/tradelab/live/panic",
                         {"level": "L4", "confirm": "DISABLE"})
    assert status == 400


def test_post_panic_l1_ignores_also_cancel_flag(monkeypatch, tmp_path):
    """L1 with also_cancel_nontradelab=True must not pass it to execute_panic
    (or, if passed, execute_panic ignores it for L1; either is acceptable —
    we test the safer behavior of not passing it for L1)."""
    from tradelab.live import panic
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")
    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00", level="L1", before_state_snapshot=[],
        cards_disabled=[], orders_cancelled=[], positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        _post("/tradelab/live/panic",
              {"level": "L1", "confirm": "DISABLE", "also_cancel_nontradelab": True})
    # For L1 the flag is meaningless; assert it was passed as False (defense)
    ep.assert_called_once_with("L1", also_cancel_nontradelab=False)


def test_post_panic_l2_passes_flag(monkeypatch, tmp_path):
    from tradelab.live import panic
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")
    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00", level="L2", before_state_snapshot=[],
        cards_disabled=[], orders_cancelled=[], positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        _post("/tradelab/live/panic",
              {"level": "L2", "confirm": "PANIC", "also_cancel_nontradelab": True})
    ep.assert_called_once_with("L2", also_cancel_nontradelab=True)


def test_post_panic_missing_level_400():
    body, status = _post("/tradelab/live/panic", {"confirm": "DISABLE"})
    assert status == 400


def test_post_panic_missing_confirm_400():
    body, status = _post("/tradelab/live/panic", {"level": "L1"})
    assert status == 400


# ─── GET /tradelab/live/panic/last-event ───────────────────────────────

def _get(path):
    return handlers.handle_get_with_status(path)


def test_get_last_event_returns_null_when_file_missing(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"] is None


def test_get_last_event_returns_null_when_file_empty(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"] is None


def test_get_last_event_returns_most_recent(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    e1 = {"ts": "2026-04-26T14:32:07-04:00", "level": "L1",
          "cards_disabled": ["card_a"], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    e2 = {"ts": "2026-04-26T15:01:42-04:00", "level": "L2",
          "cards_disabled": ["card_b"], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    p.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)

    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"]["ts"] == "2026-04-26T15:01:42-04:00"
    assert env["data"]["level"] == "L2"


def test_get_last_event_handles_corrupt_trailing_line(monkeypatch, tmp_path):
    """If the last line is malformed JSON, return the most recent valid line."""
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    e1 = {"ts": "2026-04-26T14:32:07-04:00", "level": "L1",
          "cards_disabled": [], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    p.write_text(json.dumps(e1) + "\nthis-is-not-json\n", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)

    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"]["ts"] == "2026-04-26T14:32:07-04:00"
