"""notify() — single-line JSONL append for cross-process event delivery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradelab.live import notify
from tradelab.live.notify import Severity


@pytest.fixture(autouse=True)
def _isolated_events_path(tmp_path, monkeypatch):
    p = tmp_path / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", p)
    yield p


def test_severity_enum_values():
    assert Severity.CRITICAL.value == "critical"
    assert Severity.WARNING.value == "warning"
    assert Severity.INFO.value == "info"


def test_notify_appends_one_jsonl_line(_isolated_events_path):
    notify.notify(Severity.CRITICAL, "Test title", "Test body")
    lines = _isolated_events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["severity"] == "critical"
    assert event["title"] == "Test title"
    assert event["body"] == "Test body"
    assert event["channels"] is None  # null = use routing matrix


def test_notify_with_explicit_channels(_isolated_events_path):
    notify.notify(Severity.INFO, "T", "B", channels={"browser"})
    event = json.loads(_isolated_events_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["channels"] == ["browser"]


def test_notify_ts_is_iso_utc(_isolated_events_path):
    notify.notify(Severity.WARNING, "T", "B")
    event = json.loads(_isolated_events_path.read_text(encoding="utf-8").splitlines()[0])
    parsed = datetime.fromisoformat(event["ts"])
    assert parsed.tzinfo is not None
    # Within 5s of now
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 5.0


def test_notify_appends_does_not_overwrite(_isolated_events_path):
    notify.notify(Severity.INFO, "first", "")
    notify.notify(Severity.INFO, "second", "")
    lines = _isolated_events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "first"
    assert json.loads(lines[1])["title"] == "second"


def test_notify_creates_parent_dir_if_missing(tmp_path, monkeypatch):
    deep = tmp_path / "does" / "not" / "exist" / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", deep)
    notify.notify(Severity.INFO, "x", "y")
    assert deep.exists()
