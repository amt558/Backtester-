"""Handlers for GET/PATCH /tradelab/live/config."""
from __future__ import annotations

import json

import pytest

from tradelab.live import live_config
from tradelab.web import handlers


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    p = tmp_path / "live_config.json"
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", p)
    live_config.reload()
    yield p


def test_get_live_config_masks_smtp_password():
    live_config.update({"notifications": {"smtp": {"password": "supersecret"}}})
    body, status = handlers.handle_live_config_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"]["notifications"]["smtp"]["password"] == "******"


def test_get_live_config_returns_defaults_on_first_call():
    body, status = handlers.handle_live_config_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["data"]["notifications"]["enabled_channels"] == ["browser"]


def test_patch_live_config_persists_partial_payload():
    body, status = handlers.handle_live_config_patch({
        "notifications": {"ntfy": {"topic": "tradelab-amit-7g3k2x"}}
    })
    assert status == 200
    cfg = live_config.get()
    assert cfg["notifications"]["ntfy"]["topic"] == "tradelab-amit-7g3k2x"
    assert cfg["notifications"]["ntfy"]["server"] == "https://ntfy.sh"  # untouched


def test_patch_live_config_ignores_masked_password():
    live_config.update({"notifications": {"smtp": {"password": "real-pw"}}})
    body, status = handlers.handle_live_config_patch({
        "notifications": {"smtp": {"password": "******", "host": "smtp.foo.com"}}
    })
    assert status == 200
    cfg = live_config.get()
    assert cfg["notifications"]["smtp"]["password"] == "real-pw"  # preserved
    assert cfg["notifications"]["smtp"]["host"] == "smtp.foo.com"  # updated


def test_patch_live_config_rejects_unknown_top_level_key():
    body, status = handlers.handle_live_config_patch({"experimental_thing": True})
    assert status == 400
    assert "unknown" in json.loads(body)["error"].lower()


def test_patch_live_config_rejects_non_dict_payload():
    body, status = handlers.handle_live_config_patch("not a dict")
    assert status == 400


def test_patch_live_config_validates_max_exposure_pct_range():
    body, status = handlers.handle_live_config_patch({"guardrails": {"max_exposure_pct": 1.5}})
    assert status == 400
    assert "max_exposure_pct" in json.loads(body)["error"]


def test_patch_live_config_validates_severity_routing_keys():
    body, status = handlers.handle_live_config_patch({"notifications": {"severity_routing": {"unknown_severity": ["browser"]}}})
    assert status == 400


def test_test_notification_endpoint_writes_to_notify_events(tmp_path, monkeypatch):
    from tradelab.live import notify
    events_path = tmp_path / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", events_path)
    body, status = handlers.handle_test_notification({"channel": "browser", "severity": "info"})
    assert status == 200
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["channels"] == ["browser"]
    assert event["severity"] == "info"


def test_test_notification_rejects_unknown_channel():
    body, status = handlers.handle_test_notification({"channel": "carrier_pigeon", "severity": "critical"})
    assert status == 400
