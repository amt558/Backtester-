"""NotifyDispatcher — watchdog tail of notify_events.jsonl + channel fan-out."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tradelab.live import live_config, notify
from tradelab.live.notify import Severity
from tradelab.live.notify_dispatcher import NotifyDispatcher


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    events = tmp_path / "notify_events.jsonl"
    cfg_path = tmp_path / "live_config.json"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", events)
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", cfg_path)
    live_config.reload()
    # Default to all 5 channels enabled for routing tests
    live_config.update({"notifications": {"enabled_channels": ["browser", "audible", "windows_toast", "ntfy", "email"]}})
    yield events


def _start_dispatcher(events_path) -> NotifyDispatcher:
    d = NotifyDispatcher(events_path=events_path)
    d.start()
    # Allow watcher thread to register
    time.sleep(0.1)
    return d


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_dispatcher_calls_browser_channel_for_info_severity(_isolated_paths, monkeypatch):
    calls = []
    def fake_browser_send(severity, title, body, config):
        calls.append((severity, title, body))
        return True

    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", fake_browser_send)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "info-title", "info-body")
        assert _wait_for(lambda: len(calls) == 1)
        assert calls[0] == ("info", "info-title", "info-body")
    finally:
        d.stop()


def test_dispatcher_resolves_critical_to_all_default_channels(_isolated_paths, monkeypatch):
    fired = set()
    def make(name):
        def _send(s, t, b, c):
            fired.add(name)
            return True
        return _send

    from tradelab.live.notify_channels import CHANNELS
    for name in ("browser", "audible", "windows_toast", "ntfy", "email"):
        monkeypatch.setitem(CHANNELS, name, make(name))

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.CRITICAL, "boom", "everything")
        assert _wait_for(lambda: fired == {"browser", "audible", "windows_toast", "ntfy", "email"})
    finally:
        d.stop()


def test_dispatcher_isolates_channel_failure(_isolated_paths, monkeypatch):
    successes = []
    def good_send(s, t, b, c):
        successes.append("good")
        return True
    def bad_send(s, t, b, c):
        raise RuntimeError("transport down")

    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", bad_send)
    monkeypatch.setitem(CHANNELS, "audible", good_send)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.WARNING, "T", "B")  # WARNING routes to browser+audible+windows_toast
        assert _wait_for(lambda: "good" in successes)
    finally:
        d.stop()


def test_dispatcher_explicit_channels_override_routing(_isolated_paths, monkeypatch):
    calls = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "ntfy", lambda s, t, b, c: calls.append("ntfy") or True)
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: calls.append("browser") or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "T", "B", channels={"ntfy"})  # INFO normally → browser only
        assert _wait_for(lambda: calls == ["ntfy"])
    finally:
        d.stop()


def test_dispatcher_skips_disabled_channel(_isolated_paths, monkeypatch):
    live_config.update({"notifications": {"enabled_channels": ["browser"]}})  # only browser enabled
    fired = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "ntfy", lambda s, t, b, c: fired.append("ntfy") or True)
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: fired.append("browser") or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.CRITICAL, "T", "B")  # would route to all 5; only browser enabled
        assert _wait_for(lambda: fired == ["browser"], timeout=1.0)
        assert "ntfy" not in fired
    finally:
        d.stop()


def test_dispatcher_starts_at_eof_skips_existing_events(_isolated_paths, monkeypatch):
    # Pre-write an event that was "missed"
    notify.notify(Severity.CRITICAL, "old", "should be skipped")
    fired = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: fired.append((t, b)) or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "new", "should fire")
        assert _wait_for(lambda: ("new", "should fire") in fired)
        assert ("old", "should be skipped") not in fired
    finally:
        d.stop()
