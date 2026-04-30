"""LiveConfig — runtime config for notification channels + guardrail thresholds."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.live import live_config


@pytest.fixture(autouse=True)
def _isolated_config_path(tmp_path, monkeypatch):
    p = tmp_path / "live_config.json"
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", p)
    live_config.reload()
    yield p


def test_load_writes_defaults_if_missing(_isolated_config_path):
    cfg = live_config.get()
    assert cfg["schema_version"] == 1
    assert cfg["notifications"]["enabled_channels"] == ["browser"]
    assert cfg["guardrails"]["max_exposure_pct"] == 0.90
    assert _isolated_config_path.exists()
    on_disk = json.loads(_isolated_config_path.read_text(encoding="utf-8"))
    assert on_disk == cfg


def test_save_roundtrip(_isolated_config_path):
    cfg = live_config.get()
    cfg["notifications"]["enabled_channels"] = ["browser", "audible"]
    live_config.save(cfg)
    live_config.reload()
    assert live_config.get()["notifications"]["enabled_channels"] == ["browser", "audible"]


def test_save_is_atomic(_isolated_config_path, tmp_path):
    cfg = live_config.get()
    cfg["notifications"]["smtp"]["host"] = "smtp.example.com"
    live_config.save(cfg)
    # No leftover .tmp file after save
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_mask_passwords_replaces_nonempty_smtp_password(_isolated_config_path):
    cfg = live_config.get()
    cfg["notifications"]["smtp"]["password"] = "supersecret"
    masked = live_config.mask_passwords(cfg)
    assert masked["notifications"]["smtp"]["password"] == "******"
    # Non-mutating: original cfg untouched
    assert cfg["notifications"]["smtp"]["password"] == "supersecret"


def test_mask_passwords_leaves_empty_password_empty(_isolated_config_path):
    cfg = live_config.get()
    masked = live_config.mask_passwords(cfg)
    assert masked["notifications"]["smtp"]["password"] == ""


def test_load_merges_new_default_keys_into_existing_file(_isolated_config_path):
    # Simulate an old file missing a key that defaults adds
    _isolated_config_path.write_text(json.dumps({"schema_version": 1, "guardrails": {"max_exposure_pct": 0.5}}), encoding="utf-8")
    live_config.reload()
    cfg = live_config.get()
    # Existing key preserved
    assert cfg["guardrails"]["max_exposure_pct"] == 0.5
    # Missing default added
    assert cfg["notifications"]["enabled_channels"] == ["browser"]


def test_load_preserves_unknown_keys(_isolated_config_path):
    _isolated_config_path.write_text(json.dumps({"schema_version": 1, "experimental": {"foo": "bar"}}), encoding="utf-8")
    live_config.reload()
    assert live_config.get()["experimental"] == {"foo": "bar"}


def test_update_in_place_then_save(_isolated_config_path):
    live_config.update({"notifications": {"ntfy": {"topic": "tradelab-test"}}})
    cfg = live_config.get()
    assert cfg["notifications"]["ntfy"]["topic"] == "tradelab-test"
    # Other ntfy fields not blown away
    assert cfg["notifications"]["ntfy"]["server"] == "https://ntfy.sh"


# ─── B19: dotted-path get() ──────────────────────────────────────────


def test_get_dotted_path_returns_leaf_value(_isolated_config_path):
    """Defaults set email_digest.send_time = '16:00'."""
    assert live_config.get("email_digest.send_time") == "16:00"
    assert live_config.get("email_digest.enabled") is False
    assert live_config.get("guardrails.max_exposure_pct") == 0.90


def test_get_dotted_path_returns_default_when_missing(_isolated_config_path):
    assert live_config.get("does_not_exist.nope", "fallback") == "fallback"
    assert live_config.get("email_digest.brand_new_field", 42) == 42
    # Empty default works (None, 0, "", [], etc.)
    assert live_config.get("missing", None) is None
    assert live_config.get("missing", 0) == 0
    assert live_config.get("missing", "") == ""


def test_get_dotted_path_raises_when_missing_no_default(_isolated_config_path):
    with pytest.raises(KeyError, match="path not found"):
        live_config.get("does_not_exist.nope")


def test_get_dotted_path_walks_through_nested_dicts(_isolated_config_path):
    """Multi-segment paths must descend correctly."""
    live_config.update({"notifications": {"smtp": {"host": "smtp.example.com"}}})
    assert live_config.get("notifications.smtp.host") == "smtp.example.com"
    assert live_config.get("notifications.smtp.port") == 587  # default preserved


def test_get_dotted_path_does_not_traverse_non_dict_leaves(_isolated_config_path):
    """If a segment hits a non-dict value mid-path, treat as missing (not a crash)."""
    # max_exposure_pct is a float; trying to descend into it should hit default
    assert live_config.get("guardrails.max_exposure_pct.subkey", "missing") == "missing"


def test_get_no_args_still_returns_full_dict(_isolated_config_path):
    """Backwards compat: no-arg get() unchanged."""
    cfg = live_config.get()
    assert isinstance(cfg, dict)
    assert "schema_version" in cfg
    # Same identity as cache (existing contract preserved)
    assert live_config.get() is cfg
