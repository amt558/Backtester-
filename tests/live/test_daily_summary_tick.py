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

    # Stub audit appenders (success + capped paths)
    audit_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_append_audit_line", audit_mock)
    capped_audit_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_append_capped_audit_line", capped_audit_mock)

    return {
        "state_path": state_path,
        "send": send_mock,
        "audit": audit_mock,
        "capped_audit": capped_audit_mock,
    }


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


# ─── Slice 7a T7: explicit retry-cap coverage (spec §3.5) ────────────


def test_tick_increments_attempts_on_send_failure(tick_env):
    """First failed send → attempts_today=1, last_sent_failed=True, last_sent_date NOT set
    (so the next tick will retry)."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 1
    assert state["last_sent_failed"] is True
    # last_sent_date NOT set — gate at next tick must let retry through
    assert state.get("last_sent_date") in (None,)
    # Audit line is for SUCCESS only — must not fire on failure
    tick_env["audit"].assert_not_called()


def test_tick_retries_after_failure(tick_env):
    """Second tick after a failure → another send attempt, attempts_today=2."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    daily_summary.tick(datetime(2026, 4, 27, 16, 1, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 2
    assert tick_env["send"].call_count == 2


def test_tick_retry_cap_at_5_attempts(tick_env):
    """5th failed attempt → state.last_sent_date set to today; 6th tick is skipped."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    for i in range(5):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 5
    assert state["last_sent_date"] == "2026-04-27"
    assert state["last_sent_failed"] is True

    # 6th tick should skip (idempotency gate matches)
    daily_summary.tick(datetime(2026, 4, 27, 16, 5, 0))
    assert tick_env["send"].call_count == 5  # no new attempt


def test_tick_capped_failure_fires_warning_with_no_further_retries_suffix(tick_env, monkeypatch):
    """Per spec §3.5 step 6: when cap is hit, the WARNING notify body must contain
    ' — no further retries today' so operator can grep for cap events.
    (B21 hint: this is currently the ONLY operator-visible signal the digest gave up;
    if B21 is later resolved, add an assertion for the daily_digest_capped jsonl line too.)"""
    notify_mock = MagicMock()
    # Patch where notify is imported INSIDE the failure branch (lazy import)
    monkeypatch.setattr("tradelab.live.notify.notify", notify_mock)
    tick_env["send"].side_effect = RuntimeError("smtp down")

    for i in range(5):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))

    # 5 notify calls total, one per failed attempt
    assert notify_mock.call_count == 5
    # The 5th (capped) call body must contain the suffix
    final_call_body = notify_mock.call_args_list[-1][0][2]
    assert " — no further retries today" in final_call_body
    # The 1st-4th must NOT contain it
    for call in notify_mock.call_args_list[:-1]:
        assert " — no further retries today" not in call[0][2]


def test_tick_post_cap_idempotency_holds_across_many_ticks(tick_env):
    """Once capped, all subsequent ticks (not just one) must remain no-ops.
    Defensive against a regression where the idempotency gate gets a side-effect
    that flips state (e.g. clearing last_sent_failed)."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    for i in range(5):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))
    assert tick_env["send"].call_count == 5

    # 100 more ticks across the rest of the day — none should re-fire send
    for minute in range(5, 105):
        daily_summary.tick(datetime(2026, 4, 27, 16, minute % 60, 0))
    assert tick_env["send"].call_count == 5
    tick_env["audit"].assert_not_called()


def test_tick_capped_failure_appends_daily_digest_capped_audit_line(tick_env):
    """B21: on cap (5th failure), a structured CRITICAL audit line must be
    appended to notify_events.jsonl exactly once. Operator visibility into
    the give-up event without scanning per-attempt WARNINGs."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    for i in range(4):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))
    # 4 failures so far — not yet capped
    tick_env["capped_audit"].assert_not_called()

    # 5th failure → cap
    daily_summary.tick(datetime(2026, 4, 27, 16, 4, 0))
    tick_env["capped_audit"].assert_called_once()
    args = tick_env["capped_audit"].call_args[0]
    assert args[0] == "2026-04-27"  # today_str
    assert args[1] == 5  # attempts
    assert "RuntimeError: smtp down" in args[2]  # last_error

    # 6th tick: idempotency gate hits, no new capped audit line
    daily_summary.tick(datetime(2026, 4, 27, 16, 5, 0))
    assert tick_env["capped_audit"].call_count == 1


def test_tick_non_capped_failure_does_not_append_capped_audit_line(tick_env):
    """1-4 failures must NOT write a capped audit line — only WARNING notifies."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    for i in range(4):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))
    tick_env["capped_audit"].assert_not_called()


def test_tick_new_day_after_capped_yesterday_resets_and_retries(tick_env):
    """Capped yesterday → fresh attempt today (attempts_today reset to 0)."""
    import json as _json
    # Pre-seed state as if yesterday was capped
    tick_env["state_path"].write_text(_json.dumps({
        "last_sent_date": "2026-04-26",
        "last_sent_failed": True,
        "attempts_today": 5,
    }), encoding="utf-8")

    # Today's tick — send succeeds this time
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_called_once()
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["last_sent_date"] == "2026-04-27"
    assert state["last_sent_failed"] is False
    assert state["attempts_today"] == 0
    tick_env["audit"].assert_called_once()
