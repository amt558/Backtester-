"""Card registry — JSON-backed, thread-safe for read.

One card = one immutable strategy version × one symbol. Live trade execution
is gated by card lookup + secret validation.

Session 3a adds mutation surface: create (append-only, disabled-by-default)
+ next_version_for (for -v{n} auto-versioning). No update/delete in 3a.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Optional


class CardExistsError(Exception):
    """Raised by CardRegistry.create when card_id is already present."""


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

    def next_version_for(self, base_name: str) -> int:
        """Return n such that {base_name}-v{n} is the next unused id.

        Matches strictly: base_name followed by '-v' followed by digits to end.
        base_name='viprasol' does NOT collide with 'viprasol-amz-v1'.
        """
        pattern = re.compile(rf"^{re.escape(base_name)}-v(\d+)$")
        with self._lock:
            versions = []
            for cid in self._cards:
                m = pattern.match(cid)
                if m:
                    versions.append(int(m.group(1)))
            return (max(versions) + 1) if versions else 1

    def create(self, card_id: str, data: dict) -> None:
        """Append a new card. Raises CardExistsError on duplicate.

        Safety guardrail for Session 3a: every created card must have
        status='disabled'. Lifecycle (enable/disable/delete) is Session 3b
        — remove this assertion when the toggle endpoint ships.
        """
        if data.get("status") != "disabled":
            raise ValueError(
                f"Session 3a safety: new cards must have status='disabled', "
                f"got {data.get('status')!r}"
            )
        with self._lock:
            if card_id in self._cards:
                raise CardExistsError(card_id)
            new_cards = dict(self._cards)
            new_cards[card_id] = data
            self._persist(new_cards)
            self._cards = new_cards

    def _persist(self, cards: dict[str, dict]) -> None:
        """Atomic write: JSON -> .tmp -> os.replace(cards.json)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(cards, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
