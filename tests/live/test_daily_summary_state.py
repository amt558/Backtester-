"""Tests for daily_summary state file (digest_state.json)."""
import json
from pathlib import Path

import pytest

from tradelab.live import daily_summary


def test_read_state_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_summary, "STATE_PATH", tmp_path / "digest_state.json")
    state = daily_summary._read_state()
    assert state == {}


def test_read_state_corrupt_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    p.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    assert daily_summary._read_state() == {}


def test_write_state_atomic(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    daily_summary._write_state({"last_sent_date": "2026-04-27", "attempts_today": 0})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["last_sent_date"] == "2026-04-27"
    assert data["attempts_today"] == 0


def test_write_state_then_read_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    payload = {
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T20:00:14+00:00",
        "attempts_today": 0,
    }
    daily_summary._write_state(payload)
    assert daily_summary._read_state() == payload


# ─── Slice 7a T8: daemon thread lifecycle (mirrors silence_checker) ──


@pytest.fixture
def _neutralized_tick(monkeypatch):
    """Lifecycle tests exercise threading mechanics, not tick() logic.
    Stub tick to a no-op so the daemon thread doesn't do real I/O or
    raise during these tests."""
    monkeypatch.setattr(daily_summary, "tick", lambda now: None)
    # Ensure we always start from a clean slate (a prior test may have left
    # _thread non-None if it crashed).
    daily_summary.stop()
    yield
    daily_summary.stop()


def test_start_creates_daemon_thread(_neutralized_tick):
    daily_summary.start()
    assert daily_summary._thread is not None
    assert daily_summary._thread.is_alive()
    assert daily_summary._thread.daemon is True
    assert daily_summary._thread.name == "daily_summary"


def test_start_is_idempotent(_neutralized_tick):
    daily_summary.start()
    t1 = daily_summary._thread
    daily_summary.start()  # second call must not spawn another thread
    t2 = daily_summary._thread
    assert t1 is t2  # same Thread object
    assert t1.is_alive()


def test_stop_joins_thread(_neutralized_tick):
    daily_summary.start()
    assert daily_summary._thread is not None
    daily_summary.stop()
    assert daily_summary._thread is None


def test_stop_when_not_running_is_safe(_neutralized_tick):
    """Calling stop on an already-stopped checker (or before start) is a no-op."""
    daily_summary.stop()  # never started — must not raise
    daily_summary.stop()  # double-stop — must not raise
    assert daily_summary._thread is None


def test_start_after_stop_creates_fresh_thread(_neutralized_tick):
    """Start → stop → start must create a brand-new thread (the stop event
    must be cleared so the new loop body actually runs)."""
    daily_summary.start()
    t1 = daily_summary._thread
    daily_summary.stop()
    daily_summary.start()
    t2 = daily_summary._thread
    assert t2 is not None
    assert t2 is not t1  # new Thread instance
    assert t2.is_alive()
