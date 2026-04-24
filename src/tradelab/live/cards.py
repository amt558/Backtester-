"""Card registry — JSON-backed, thread-safe for read.

One card = one immutable strategy version × one symbol. Live trade execution
is gated by card lookup + secret validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Optional


class CardRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()
        self._cards: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self.path.exists():
                self._cards = json.loads(self.path.read_text(encoding="utf-8-sig"))
            else:
                self._cards = {}

    def get(self, card_id: str) -> Optional[dict]:
        with self._lock:
            return self._cards.get(card_id)

    def all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._cards)

    def count(self) -> int:
        with self._lock:
            return len(self._cards)
