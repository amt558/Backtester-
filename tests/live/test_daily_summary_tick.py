"""Tests for daily_summary.tick() gating + idempotency + retry policy."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tradelab.live import daily_summary


@pytest.fixture
def tick_env(tmp_path, monkeypatch):
    """Setup: empty state file, send succeeds by default, config enabled, today is trading."""
    state_path = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_path)

    # Stub config: enabled, send_time 16:00
    monkeypatch.setattr(daily_summary, "_config_enabled", lambda: True)
    monkeypatch.setattr(daily_summary, "_config_send_time", lambda: "16:00")
    monkeypatch.setattr(daily_summary, "_config_recipient", lambda: "test@example.com")

    # Stub trading day check
    monkeypatch.setattr(daily_summary, "_is_trading_day", lambda d: True)

    # Stub render to a known value
    monkeypatch.setattr(daily_summary, "render",
                        lambda now: ("test subject", "<html>test</html>"))

    # Stub email send
    send_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_send_email", send_mock)

    # Stub audit appender
    audit_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_append_audit_line", audit_mock)

    return {"state_path": state_path, "send": send_mock, "audit": audit_mock}


def test_tick_skips_when_not_trading_day(tick_env, monkeypatch):
    monkeypatch.setattr(daily_summary, "_is_trading_day", lambda d: False)
    daily_summary.tick(datetime(2026, 4, 25, 16, 0, 0))  # Sat
    tick_env["send"].assert_not_called()


def test_tick_skips_when_before_send_time(tick_env):
    daily_summary.tick(datetime(2026, 4, 27, 15, 59, 0))  # 1 min before 16:00
    tick_env["send"].assert_not_called()


def test_tick_skips_when_disabled(tick_env, monkeypatch):
    monkeypatch.setattr(daily_summary, "_config_enabled", lambda: False)
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_not_called()


def test_tick_fires_when_all_gates_pass(tick_env):
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_called_once()
    args = tick_env["send"].call_args
    assert args[0][0] == "test subject"
    assert "<html>test</html>" in args[0][1]
    # State file written with today's date
    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["last_sent_date"] == "2026-04-27"
    assert state["last_sent_failed"] is False
    # Audit line appended
    tick_env["audit"].assert_called_once()


def test_tick_idempotent_same_day(tick_env):
    """Two ticks within the same day after success → only one send."""
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    daily_summary.tick(datetime(2026, 4, 27, 16, 5, 0))
    tick_env["send"].assert_called_once()


def test_tick_resets_attempts_today_on_new_day(tick_env):
    """If state has yesterday's date with attempts_today=3, today's tick ignores attempts."""
    import json as _json
    tick_env["state_path"].write_text(_json.dumps({
        "last_sent_date": "2026-04-26",
        "last_sent_failed": True,
        "attempts_today": 3,
    }), encoding="utf-8")

    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_called_once()
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["last_sent_date"] == "2026-04-27"
    assert state["attempts_today"] == 0
