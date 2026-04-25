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


def test_set_status_updates_in_place(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A})
    reg.set_status("foo-v1", "enabled")
    assert reg.get("foo-v1")["status"] == "enabled"


def test_set_quantity_accepts_int_and_none(tmp_path: Path):
    reg = _seed(tmp_path, {"foo-v1": CARD_A})
    reg.set_quantity("foo-v1", 7)
    assert reg.get("foo-v1")["quantity"] == 7
    reg.set_quantity("foo-v1", None)
    assert reg.get("foo-v1")["quantity"] is None


# ─── Bulk operations: must persist exactly once per call ──────────────
#
# Per-id loops that call set_status/delete (each doing its own _persist)
# fail on Windows: the receiver's cards.json watcher holds a momentary
# read handle after each os.replace, and the next rapid os.replace can
# collide with WinError 5 "Access is denied". Bulk operations therefore
# must do all in-memory mutations first and write once at the end.

def _wrap_persist_counter(reg):
    """Replace reg._persist with a counter; return a [count] list."""
    count = [0]
    original = reg._persist
    def counting(state):
        count[0] += 1
        return original(state)
    reg._persist = counting
    return count


def test_bulk_update_status_applies_all_and_persists_once(tmp_path: Path):
    reg = _seed(tmp_path, {
        "a-v1": dict(CARD_A, card_id="a-v1"),
        "b-v1": dict(CARD_A, card_id="b-v1"),
        "c-v1": dict(CARD_A, card_id="c-v1"),
    })
    persist_count = _wrap_persist_counter(reg)

    updated, failed = reg.bulk_update_status(["a-v1", "b-v1", "c-v1"], "enabled")

    assert updated == ["a-v1", "b-v1", "c-v1"]
    assert failed == []
    assert persist_count[0] == 1
    on_disk = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8-sig"))
    assert all(on_disk[cid]["status"] == "enabled" for cid in ["a-v1", "b-v1", "c-v1"])


def test_bulk_update_status_reports_missing_in_failed(tmp_path: Path):
    reg = _seed(tmp_path, {"a-v1": dict(CARD_A, card_id="a-v1")})
    persist_count = _wrap_persist_counter(reg)

    updated, failed = reg.bulk_update_status(["a-v1", "ghost-v1"], "enabled")

    assert updated == ["a-v1"]
    assert failed == [{"id": "ghost-v1", "reason": "card not found"}]
    assert persist_count[0] == 1


def test_bulk_update_status_all_missing_does_not_persist(tmp_path: Path):
    reg = _seed(tmp_path, {"a-v1": dict(CARD_A, card_id="a-v1")})
    persist_count = _wrap_persist_counter(reg)

    updated, failed = reg.bulk_update_status(["x-v1", "y-v1"], "enabled")

    assert updated == []
    assert len(failed) == 2
    assert persist_count[0] == 0


def test_bulk_delete_removes_all_and_persists_once(tmp_path: Path):
    reg = _seed(tmp_path, {
        "a-v1": dict(CARD_A, card_id="a-v1"),
        "b-v1": dict(CARD_A, card_id="b-v1"),
        "c-v1": dict(CARD_A, card_id="c-v1"),
    })
    persist_count = _wrap_persist_counter(reg)

    deleted, failed = reg.bulk_delete(["a-v1", "b-v1"])

    assert deleted == ["a-v1", "b-v1"]
    assert failed == []
    assert persist_count[0] == 1
    on_disk = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8-sig"))
    assert set(on_disk.keys()) == {"c-v1"}


def test_bulk_delete_reports_missing_in_failed(tmp_path: Path):
    reg = _seed(tmp_path, {"a-v1": dict(CARD_A, card_id="a-v1")})
    persist_count = _wrap_persist_counter(reg)

    deleted, failed = reg.bulk_delete(["a-v1", "ghost-v1"])

    assert deleted == ["a-v1"]
    assert failed == [{"id": "ghost-v1", "reason": "card not found"}]
    assert persist_count[0] == 1


def test_bulk_delete_all_missing_does_not_persist(tmp_path: Path):
    reg = _seed(tmp_path, {"a-v1": dict(CARD_A, card_id="a-v1")})
    persist_count = _wrap_persist_counter(reg)

    deleted, failed = reg.bulk_delete(["x-v1", "y-v1"])

    assert deleted == []
    assert len(failed) == 2
    assert persist_count[0] == 0
