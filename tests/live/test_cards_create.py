"""CardRegistry.create / next_version_for / CardExistsError."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.live.cards import CardExistsError, CardRegistry


DISABLED_CARD = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AMZN",
    "status": "disabled", "quantity": None,
}


def test_create_appends_and_persists(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)

    # In-memory
    assert reg.get("foo-v1") == DISABLED_CARD

    # Persisted to disk
    on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
    assert on_disk == {"foo-v1": DISABLED_CARD}


def test_create_duplicate_raises(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)
    with pytest.raises(CardExistsError):
        reg.create("foo-v1", DISABLED_CARD)


def test_create_rejects_enabled_status(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    enabled = dict(DISABLED_CARD, status="enabled")
    with pytest.raises(ValueError, match="disabled"):
        reg.create("foo-v1", enabled)


def test_next_version_for_empty_registry(tmp_path: Path):
    reg = CardRegistry(tmp_path / "cards.json")
    assert reg.next_version_for("viprasol-amzn") == 1


def test_next_version_for_with_existing_versions(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("viprasol-amzn-v1", dict(DISABLED_CARD, card_id="viprasol-amzn-v1"))
    reg.create("viprasol-amzn-v2", dict(DISABLED_CARD, card_id="viprasol-amzn-v2"))
    reg.create("other-v1", dict(DISABLED_CARD, card_id="other-v1"))
    assert reg.next_version_for("viprasol-amzn") == 3
    assert reg.next_version_for("other") == 2
    assert reg.next_version_for("unseen") == 1


def test_next_version_for_ignores_suffix_collisions(tmp_path: Path):
    """viprasol-amz-v1 must not be counted under base_name 'viprasol'."""
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("viprasol-v1", dict(DISABLED_CARD, card_id="viprasol-v1"))
    reg.create("viprasol-amz-v1", dict(DISABLED_CARD, card_id="viprasol-amz-v1"))
    assert reg.next_version_for("viprasol") == 2
    assert reg.next_version_for("viprasol-amz") == 2


def test_create_atomic_write_on_replace_failure(tmp_path: Path, monkeypatch):
    """If os.replace fails mid-write, the existing cards.json must be untouched."""
    import os as os_mod
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)
    first_contents = path.read_text(encoding="utf-8-sig")

    def failing_replace(*args, **kwargs):
        raise OSError("simulated filesystem error")
    monkeypatch.setattr(os_mod, "replace", failing_replace)

    with pytest.raises(OSError):
        reg.create("bar-v1", dict(DISABLED_CARD, card_id="bar-v1"))

    # cards.json unchanged on disk
    assert path.read_text(encoding="utf-8-sig") == first_contents
    # .tmp file may or may not exist; don't assert on it either way
