"""Receiver per-card runtime state: record_attempt / record_fire /
hydrate_card_state_from_alerts_log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradelab.live.guardrails import CardRuntimeState, get_rth_window_start
from tradelab.live import receiver as rec


def _alert(ts: str, card_id: str, status: str) -> dict:
    return {"ts": ts, "card_id": card_id, "status": status,
            "payload": {}, "details": {}}


def test_record_attempt_sets_last_attempted_at():
    states: dict[str, CardRuntimeState] = {}
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    rec.record_attempt(states, "foo-v1", now)
    assert states["foo-v1"].last_attempted_at == now


def test_record_attempt_updates_existing():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    earlier = now - timedelta(seconds=30)
    states = {"foo-v1": CardRuntimeState(last_attempted_at=earlier, fires_today=2)}
    rec.record_attempt(states, "foo-v1", now)
    assert states["foo-v1"].last_attempted_at == now
    # Other fields untouched
    assert states["foo-v1"].fires_today == 2


def test_record_fire_increments_count_in_same_window():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    window = get_rth_window_start(now)
    states = {"foo-v1": CardRuntimeState(fires_today=2, fire_window_start=window)}
    rec.record_fire(states, "foo-v1", now)
    assert states["foo-v1"].fires_today == 3
    assert states["foo-v1"].last_fired_at == now
    assert states["foo-v1"].fire_window_start == window


def test_record_fire_resets_count_in_new_window():
    yesterday_window = datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)
    today = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states = {"foo-v1": CardRuntimeState(fires_today=99, fire_window_start=yesterday_window)}
    rec.record_fire(states, "foo-v1", today)
    assert states["foo-v1"].fires_today == 1
    assert states["foo-v1"].fire_window_start == get_rth_window_start(today)


def test_record_fire_first_time_starts_window():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states: dict[str, CardRuntimeState] = {}
    rec.record_fire(states, "foo-v1", now)
    assert states["foo-v1"].fires_today == 1
    assert states["foo-v1"].fire_window_start == get_rth_window_start(now)
    assert states["foo-v1"].last_fired_at == now


def test_hydrate_from_alerts_log_rebuilds_state(tmp_path: Path):
    log = tmp_path / "alerts.jsonl"
    today_open = get_rth_window_start(datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc))
    yesterday = (today_open - timedelta(days=1)).isoformat()
    today_t1 = (today_open + timedelta(hours=1)).isoformat()
    today_t2 = (today_open + timedelta(hours=2)).isoformat()
    log.write_text(
        "\n".join([
            json.dumps(_alert(yesterday, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t1, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t2, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t2, "bar-v1", "guardrail_blocked")),
        ]),
        encoding="utf-8",
    )
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states = rec.hydrate_card_state_from_alerts_log(log, now)
    foo = states["foo-v1"]
    assert foo.fires_today == 2  # only today's order_submitted entries
    assert foo.last_fired_at.isoformat() == today_t2
    # bar-v1 had only a guardrail_blocked, not an order_submitted; it
    # should NOT have a last_fired_at — but record_attempt-style entries
    # are not the responsibility of hydration (we only restore fire stats)
    assert "bar-v1" not in states or states["bar-v1"].fires_today == 0


def test_hydrate_handles_missing_log_file(tmp_path: Path):
    states = rec.hydrate_card_state_from_alerts_log(
        tmp_path / "missing.jsonl", datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert states == {}


def test_hydrate_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "alerts.jsonl"
    today = (get_rth_window_start(datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc))
             + timedelta(hours=1)).isoformat()
    log.write_text(
        "\n".join([
            "not-json",
            json.dumps(_alert(today, "foo-v1", "order_submitted")),
            "{",
        ]),
        encoding="utf-8",
    )
    states = rec.hydrate_card_state_from_alerts_log(
        log, datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert states["foo-v1"].fires_today == 1
