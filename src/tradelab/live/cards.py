"""Card registry — JSON-backed, thread-safe for read.

One card = one immutable strategy version × one symbol. Live trade execution
is gated by card lookup + secret validation.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Optional


_V1_DEFAULTS: dict = {
    "cadence": "daily",
    "last_fired_at": None,
    "last_attempted_at": None,
    "enabled_at": None,
    "daily_limit": 5,
    "cooldown_seconds": 30,
    "allow_collision": False,
    "allow_naked_short": False,
}


def _hydrate_card(card: dict) -> dict:
    """Fill missing v1 fields with defaults; preserve all existing keys.

    Lets v0 cards (pre Direction A) coexist with v1 logic without a
    one-shot data migration. Existing key wins via dict-merge order.
    """
    return {**_V1_DEFAULTS, **card}


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

    def all_hydrated(self) -> dict[str, dict]:
        """Return all cards with v1 defaults filled in.

        Use this from new (Direction A) callers. Existing callers using
        all() continue to see raw on-disk data.
        """
        with self._lock:
            return {cid: _hydrate_card(card) for cid, card in self._cards.items()}

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
        """Append a new card. Raises CardExistsError on duplicate."""
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
