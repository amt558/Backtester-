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
