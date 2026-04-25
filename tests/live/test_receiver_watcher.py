"""Tests for the cards.json file-watcher in the receiver.

Uses watchdog's PollingObserver (rather than the OS-native one) for test
determinism on Windows.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from tradelab.live.cards import CardRegistry
from tradelab.live.receiver import _start_cards_watcher


CARD_A = {"card_id": "foo-v1", "secret": "x" * 32, "symbol": "AAPL",
          "status": "disabled", "quantity": None}
CARD_B = {"card_id": "bar-v1", "secret": "y" * 32, "symbol": "MSFT",
          "status": "disabled", "quantity": None}


def _wait_until(predicate, timeout=3.0, interval=0.05):
    """Poll predicate until True or timeout. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_watcher_triggers_reload_on_external_write(tmp_path: Path) -> None:
    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": CARD_A}), encoding="utf-8")
    reg = CardRegistry(cards_path)
    assert reg.count() == 1

    observer = _start_cards_watcher(reg, polling=True)
    try:
        # External write that adds bar-v1
        new_state = {"foo-v1": CARD_A, "bar-v1": CARD_B}
        cards_path.write_text(json.dumps(new_state), encoding="utf-8")

        assert _wait_until(lambda: reg.count() == 2, timeout=3.0)
        assert reg.get("bar-v1") == CARD_B
    finally:
        observer.stop()
        observer.join(timeout=2.0)


def test_handler_burst_writes_each_get_reloaded(tmp_path: Path) -> None:
    """Burst writes must each be reflected — no time-based debounce.

    Regression: a 100ms time-debounce silently swallowed any burst
    writes that landed within the window, leaving the receiver's
    in-memory registry stale relative to disk. Reproduced live by
    seeding 8 cards back-to-back: receiver showed 4 while disk had 11.
    """
    from watchdog.events import FileMovedEvent
    from tradelab.live.receiver import _CardsReloadHandler

    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": CARD_A}), encoding="utf-8")
    reg = CardRegistry(cards_path)
    handler = _CardsReloadHandler(reg, cards_path)

    state = {"foo-v1": CARD_A}
    for i in range(5):
        cid = f"burst-{i}-v1"
        state[cid] = {**CARD_B, "card_id": cid}
        cards_path.write_text(json.dumps(state), encoding="utf-8")
        # Force-bump mtime in case OS coalesces same-second writes
        atime = cards_path.stat().st_atime
        import os as _os
        _os.utime(cards_path, (atime, atime + (i + 1) * 0.01))
        handler.on_moved(FileMovedEvent(
            src_path=str(cards_path.with_suffix(".json.tmp")),
            dest_path=str(cards_path),
        ))

    # All 5 burst writes must be reflected in the in-memory registry
    assert reg.count() == 6
    for i in range(5):
        assert reg.get(f"burst-{i}-v1") is not None


def test_handler_on_moved_triggers_reload(tmp_path: Path) -> None:
    """Atomic os.replace fires on_moved on Windows native Observer.

    Before fix: on_moved was unhandled, so PATCH/DELETE mutations through
    the dashboard (which persist via CardRegistry._persist → os.replace)
    silently failed to refresh the receiver's in-memory registry. A user
    could disable a card via UI but the receiver kept firing trades.

    The polling-based test above passes because PollingObserver checks
    mtime regardless of event type; production uses native Observer
    where on_moved is the actual signal for atomic replace.
    """
    from watchdog.events import FileMovedEvent
    from tradelab.live.receiver import _CardsReloadHandler

    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": CARD_A}), encoding="utf-8")
    reg = CardRegistry(cards_path)
    assert reg.count() == 1

    cards_path.write_text(
        json.dumps({"foo-v1": CARD_A, "bar-v1": CARD_B}), encoding="utf-8"
    )

    handler = _CardsReloadHandler(reg, cards_path)
    event = FileMovedEvent(
        src_path=str(cards_path.with_suffix(".json.tmp")),
        dest_path=str(cards_path),
    )
    handler.on_moved(event)

    assert reg.count() == 2
    assert reg.get("bar-v1") == CARD_B


def test_watcher_handles_missing_initial_file(tmp_path: Path) -> None:
    cards_path = tmp_path / "cards.json"
    # File doesn't exist yet
    reg = CardRegistry(cards_path)
    assert reg.count() == 0

    observer = _start_cards_watcher(reg, polling=True)
    try:
        cards_path.write_text(json.dumps({"foo-v1": CARD_A}), encoding="utf-8")
        assert _wait_until(lambda: reg.count() == 1, timeout=3.0)
    finally:
        observer.stop()
        observer.join(timeout=2.0)
