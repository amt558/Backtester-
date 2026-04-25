"""CardRegistry.update / .delete / .set_status / .set_quantity (Slice 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.live.cards import CardRegistry


def _seed(tmp_path: Path, cards: dict) -> CardRegistry:
    path = tmp_path / "cards.json"
    path.write_text(json.dumps(cards), encoding="utf-8")
    return CardRegistry(path)


CARD_A = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AMZN",
    "status": "disabled", "quantity": 1,
}


def test_update_merges_fields_and_persists(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A})
    reg.update("foo-v1", {"status": "enabled", "quantity": 5})
    on_disk = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["status"] == "enabled"
    assert on_disk["foo-v1"]["quantity"] == 5
    # Untouched fields preserved
    assert on_disk["foo-v1"]["symbol"] == "AMZN"
    assert on_disk["foo-v1"]["secret"] == "s" * 32


def test_update_unknown_card_raises_keyerror(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A})
    with pytest.raises(KeyError, match="missing-id"):
        reg.update("missing-id", {"status": "enabled"})


def test_delete_removes_and_persists(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A, "bar-v1": dict(CARD_A, card_id="bar-v1")})
    reg.delete("foo-v1")
    assert reg.get("foo-v1") is None
    assert reg.get("bar-v1") is not None
    on_disk = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8-sig"))
    assert "foo-v1" not in on_disk
    assert "bar-v1" in on_disk


def test_delete_unknown_card_raises_keyerror(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A})
    with pytest.raises(KeyError, match="missing-id"):
        reg.delete("missing-id")
