# Direction A — Slice 1: Live Trading Tab Foundation (Read-Only + Hot-Reload) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only "Live Trading" tab in the dashboard that lists every card grouped by `base_name` with derived status (last fired, last status, 24h fire count), plus a watchdog-based hot-reload in the receiver so any change to `cards.json` is picked up automatically. No mutations yet — that's Slice 2. This validates the file-watcher architecture end-to-end before mutations build on top.

**Architecture:**
- Backend: receiver gains a `watchdog` Observer on `cards.json` that calls `CardRegistry.reload()` on file changes (debounced, mtime-checked). Dashboard launcher (`:8877`) gains 4 new GET endpoints under `/tradelab/cards*` and `/tradelab/receiver/status`. New `tradelab.web.cards_view` module derives last-fired/last-status/24h-count from `alerts.jsonl` and groups cards by `base_name`.
- Frontend: New "Live Trading" tab in `command_center.html` peer to existing tabs. Renders the grouped card list with a receiver-up status chip. Read-only: no toggles, no inline edits, no delete buttons (those land in Slice 2).
- Backward compat: `CardRegistry.all_hydrated()` fills missing v1 fields (`cadence`, `last_fired_at`, `last_attempted_at`, `daily_limit`, etc.) with defaults so existing cards work unchanged.

**Tech Stack:** Python 3.12, FastAPI (receiver), Python `http.server` + custom dispatch (dashboard launcher), pytest, pydantic, watchdog (new), vanilla JS (no framework) for the dashboard.

**Spec:** `docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md`

**Conventions to follow:**
- Tests live under `tradelab/tests/live/` (live module) and `tradelab/tests/web/` (web module)
- Test fixtures use `tmp_path` and `monkeypatch` to override path helpers (`handlers._cards_path`, etc.) — see `test_strategy_history.py` for reference
- Handler responses use the `{"error": null|str, "data": <payload>}` envelope via the existing `_ok()` and `_err()` helpers
- Commit messages follow the existing `feat(web): ...` / `fix: ...` style; include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` footer

---

## Task 1: Add `watchdog` dependency

**Files:**
- Modify: `tradelab/pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml dependencies block**

Open `C:/TradingScripts/tradelab/pyproject.toml` and add `"watchdog>=3.0.0",` to the `dependencies` array, right after the `"python-dateutil>=2.9.0",` line:

```toml
dependencies = [
    "optuna>=4.8.0",
    "optuna-dashboard>=0.18.0",
    "plotext>=5.2.8",
    "quantstats>=0.0.81",
    "typer>=0.12.0",
    "rich>=13.0.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0.0",
    "jinja2>=3.1.0",
    "pandas>=2.3.0",
    "numpy>=2.0.0",
    "plotly>=6.0.0",
    "python-dateutil>=2.9.0",
    "watchdog>=3.0.0",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `cd C:/TradingScripts/tradelab && pip install -e .`

Expected: `Successfully installed watchdog-X.Y.Z` (or "Requirement already satisfied" if a version is present).

- [ ] **Step 3: Verify import works**

Run: `python -c "from watchdog.observers import Observer; from watchdog.events import FileSystemEventHandler; print('ok')"`

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab
git add pyproject.toml
git commit -m "$(cat <<'EOF'
deps: add watchdog for cards.json hot-reload

Slice 1 of Direction A. Receiver will use watchdog.Observer to detect
cards.json changes and call CardRegistry.reload() automatically,
removing the manual receiver-restart step after every Accept.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `_hydrate_card` helper for backward compatibility

**Files:**
- Modify: `tradelab/src/tradelab/live/cards.py`
- Test: `tradelab/tests/live/test_cards_hydrate.py`

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/live/test_cards_hydrate.py`:

```python
"""Tests for _hydrate_card backward-compat helper."""
from __future__ import annotations

from tradelab.live.cards import _hydrate_card


MINIMAL_OLD_CARD = {
    "card_id": "foo-v1",
    "secret": "s" * 32,
    "symbol": "AMZN",
    "status": "disabled",
    "quantity": None,
}


def test_hydrate_fills_missing_v1_fields() -> None:
    out = _hydrate_card(MINIMAL_OLD_CARD)
    assert out["cadence"] == "daily"
    assert out["last_fired_at"] is None
    assert out["last_attempted_at"] is None
    assert out["enabled_at"] is None
    assert out["daily_limit"] == 5
    assert out["cooldown_seconds"] == 30
    assert out["allow_collision"] is False
    assert out["allow_naked_short"] is False


def test_hydrate_preserves_existing_v1_fields() -> None:
    rich_card = dict(MINIMAL_OLD_CARD,
                     cadence="intraday",
                     daily_limit=50,
                     allow_collision=True)
    out = _hydrate_card(rich_card)
    assert out["cadence"] == "intraday"
    assert out["daily_limit"] == 50
    assert out["allow_collision"] is True
    # Non-overridden defaults still applied
    assert out["cooldown_seconds"] == 30


def test_hydrate_preserves_legacy_v0_fields() -> None:
    out = _hydrate_card(MINIMAL_OLD_CARD)
    assert out["card_id"] == "foo-v1"
    assert out["secret"] == "s" * 32
    assert out["symbol"] == "AMZN"
    assert out["status"] == "disabled"
    assert out["quantity"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_cards_hydrate.py -v`

Expected: FAIL with `ImportError: cannot import name '_hydrate_card'`.

- [ ] **Step 3: Implement `_hydrate_card` in cards.py**

Edit `tradelab/src/tradelab/live/cards.py` and add this function below the existing imports (around line 17, before `class CardExistsError`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_cards_hydrate.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/cards.py tests/live/test_cards_hydrate.py
git commit -m "$(cat <<'EOF'
feat(live): _hydrate_card fills v1 fields with defaults

Lets pre-Direction-A cards (without cadence/daily_limit/etc.) be read
by the new Live Trading tab without a one-shot migration. Existing v0
fields are preserved; missing v1 fields get sensible defaults.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `CardRegistry.all_hydrated()` method

**Files:**
- Modify: `tradelab/src/tradelab/live/cards.py`
- Test: `tradelab/tests/live/test_cards_hydrate.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/live/test_cards_hydrate.py`:

```python
import json
from pathlib import Path
from tradelab.live.cards import CardRegistry


def test_all_hydrated_returns_hydrated_cards(tmp_path: Path) -> None:
    path = tmp_path / "cards.json"
    raw = {
        "old-v1": {"card_id": "old-v1", "secret": "x" * 32,
                   "symbol": "AAPL", "status": "disabled", "quantity": None},
        "new-v2": {"card_id": "new-v2", "secret": "y" * 32,
                   "symbol": "MSFT", "status": "enabled", "quantity": 10,
                   "cadence": "weekly", "daily_limit": 1},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    reg = CardRegistry(path)

    hydrated = reg.all_hydrated()

    assert hydrated["old-v1"]["cadence"] == "daily"
    assert hydrated["old-v1"]["daily_limit"] == 5
    assert hydrated["new-v2"]["cadence"] == "weekly"
    assert hydrated["new-v2"]["daily_limit"] == 1
    # Original .all() must remain unhydrated for backward compat
    assert "cadence" not in reg.all()["old-v1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_cards_hydrate.py::test_all_hydrated_returns_hydrated_cards -v`

Expected: FAIL with `AttributeError: 'CardRegistry' object has no attribute 'all_hydrated'`.

- [ ] **Step 3: Add the method to CardRegistry**

Edit `tradelab/src/tradelab/live/cards.py`. Add this method to `CardRegistry` (insert after the `all()` method, around line 44):

```python
    def all_hydrated(self) -> dict[str, dict]:
        """Return all cards with v1 defaults filled in.

        Use this from new (Direction A) callers. Existing callers using
        all() continue to see raw on-disk data.
        """
        with self._lock:
            return {cid: _hydrate_card(card) for cid, card in self._cards.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_cards_hydrate.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/cards.py tests/live/test_cards_hydrate.py
git commit -m "$(cat <<'EOF'
feat(live): CardRegistry.all_hydrated() returns v1-defaulted cards

New callers (cards_view, Live Trading tab handlers) use all_hydrated()
so they see consistent v1 fields. Existing .all() unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Create `cards_view.derive_last_status` (read alerts.jsonl tail)

**Files:**
- Create: `tradelab/src/tradelab/web/cards_view.py`
- Test: `tradelab/tests/web/test_cards_view.py`

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/web/test_cards_view.py`:

```python
"""Tests for tradelab.web.cards_view derived-fields helpers."""
from __future__ import annotations

import json
from pathlib import Path

from tradelab.web import cards_view


def _write_alerts(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def test_derive_last_status_returns_most_recent_for_card(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": "2026-04-25T09:30:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "bar-v1",
         "status": "order_failed"},
        {"ts": "2026-04-25T10:30:00+00:00", "card_id": "foo-v1",
         "status": "order_failed"},
    ])

    out = cards_view.derive_last_status(["foo-v1", "bar-v1", "baz-v1"], log)

    assert out["foo-v1"] == "order_failed"
    assert out["bar-v1"] == "order_failed"
    assert out["baz-v1"] is None  # no entries → None


def test_derive_last_status_handles_missing_log(tmp_path: Path) -> None:
    log = tmp_path / "does_not_exist.jsonl"
    out = cards_view.derive_last_status(["foo-v1"], log)
    assert out == {"foo-v1": None}


def test_derive_last_status_skips_malformed_lines(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    log.write_text(
        '{"ts": "2026-04-25T09:30:00+00:00", "card_id": "foo-v1", "status": "order_submitted"}\n'
        'NOT JSON\n'
        '{"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1", "status": "order_failed"}\n',
        encoding="utf-8",
    )
    out = cards_view.derive_last_status(["foo-v1"], log)
    assert out["foo-v1"] == "order_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tradelab.web.cards_view'`.

- [ ] **Step 3: Create cards_view.py with derive_last_status**

Create `tradelab/src/tradelab/web/cards_view.py`:

```python
"""Derive Live-Trading-tab view fields from cards.json + alerts.jsonl.

Pure functions — no I/O beyond reading files. Caller passes paths in
so tests can use tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional


def _iter_alerts(log_path: Path) -> Iterable[dict]:
    """Yield each parseable JSON object from alerts.jsonl. Malformed lines
    are silently skipped — alerts.jsonl is append-only and partial writes
    on crash are possible."""
    if not log_path.exists():
        return
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def derive_last_status(card_ids: Iterable[str], log_path: Path) -> dict[str, Optional[str]]:
    """For each card_id, return the most recent alert's status, or None
    if no alert has ever been logged for that card.

    "Most recent" = last occurrence in the file (we trust append-order).
    """
    wanted = set(card_ids)
    last: dict[str, Optional[str]] = {cid: None for cid in wanted}
    for entry in _iter_alerts(log_path):
        cid = entry.get("card_id")
        if cid in wanted:
            last[cid] = entry.get("status")
    return last
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/cards_view.py tests/web/test_cards_view.py
git commit -m "$(cat <<'EOF'
feat(web): cards_view.derive_last_status from alerts.jsonl

First building block for Live Trading tab derived fields. Reads each
card_id's most recent alerts.jsonl entry and returns its status.
Malformed lines silently skipped — alerts.jsonl is append-only and
partial writes on crash are real.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add `cards_view.derive_fire_counts` (24h fires per card)

**Files:**
- Modify: `tradelab/src/tradelab/web/cards_view.py`
- Test: `tradelab/tests/web/test_cards_view.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/web/test_cards_view.py`:

```python
from datetime import datetime, timedelta, timezone


def test_derive_fire_counts_filters_to_24h_window(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    now = datetime.now(timezone.utc)
    _write_alerts(log, [
        {"ts": (now - timedelta(hours=30)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},  # too old
        {"ts": (now - timedelta(hours=10)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=2)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "card_id": "bar-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=5)).isoformat(),
         "card_id": "foo-v1", "status": "order_failed"},  # not order_submitted, ignored
    ])

    counts = cards_view.derive_fire_counts(
        ["foo-v1", "bar-v1", "baz-v1"], log, hours=24
    )

    assert counts["foo-v1"] == 2  # only the two within 24h that submitted
    assert counts["bar-v1"] == 1
    assert counts["baz-v1"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py::test_derive_fire_counts_filters_to_24h_window -v`

Expected: FAIL with `AttributeError: module 'tradelab.web.cards_view' has no attribute 'derive_fire_counts'`.

- [ ] **Step 3: Implement derive_fire_counts**

Append to `tradelab/src/tradelab/web/cards_view.py`:

```python
def derive_fire_counts(
    card_ids: Iterable[str],
    log_path: Path,
    hours: int = 24,
) -> dict[str, int]:
    """Count `order_submitted` alerts per card_id in the last `hours` hours.

    Other statuses (order_failed, guardrail_blocked, etc.) are NOT counted —
    a "fire" means an order actually went to Alpaca.
    """
    wanted = set(card_ids)
    counts: dict[str, int] = {cid: 0 for cid in wanted}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for entry in _iter_alerts(log_path):
        cid = entry.get("card_id")
        if cid not in wanted:
            continue
        if entry.get("status") != "order_submitted":
            continue
        ts_str = entry.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts >= cutoff:
            counts[cid] += 1
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/cards_view.py tests/web/test_cards_view.py
git commit -m "$(cat <<'EOF'
feat(web): cards_view.derive_fire_counts (24h order_submitted count)

Only counts statuses == "order_submitted" — order_failed and
guardrail_blocked don't count as fires for the 24h badge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Add `cards_view.group_by_base_name`

**Files:**
- Modify: `tradelab/src/tradelab/web/cards_view.py`
- Test: `tradelab/tests/web/test_cards_view.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/web/test_cards_view.py`:

```python
def test_group_by_base_name_extracts_and_groups() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "disabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
        "viprasol-amzn-v3": {"card_id": "viprasol-amzn-v3", "status": "enabled"},
        "scalper-spy-v1": {"card_id": "scalper-spy-v1", "status": "enabled"},
        "manual-card": {"card_id": "manual-card", "status": "disabled"},  # no -vN
    }
    groups = cards_view.group_by_base_name(cards)

    by_name = {g["base_name"]: g for g in groups}

    assert "viprasol-amzn" in by_name
    assert "scalper-spy" in by_name
    assert "manual-card" in by_name  # cards without -vN form their own group

    vip = by_name["viprasol-amzn"]
    assert vip["enabled_count"] == 2
    assert vip["total_count"] == 3
    # Within group: enabled first (sorted by version desc), then disabled
    assert [c["card_id"] for c in vip["cards"]] == [
        "viprasol-amzn-v3", "viprasol-amzn-v2", "viprasol-amzn-v1"
    ]


def test_group_by_base_name_flags_multi_enabled_collision() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "enabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
    }
    groups = cards_view.group_by_base_name(cards)
    assert groups[0]["multi_enabled_warning"] is True


def test_group_by_base_name_no_warning_when_one_enabled() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "disabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
    }
    groups = cards_view.group_by_base_name(cards)
    assert groups[0]["multi_enabled_warning"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py::test_group_by_base_name_extracts_and_groups -v`

Expected: FAIL with `AttributeError: module 'tradelab.web.cards_view' has no attribute 'group_by_base_name'`.

- [ ] **Step 3: Implement group_by_base_name**

Append to `tradelab/src/tradelab/web/cards_view.py`:

```python
import re

_VERSION_PATTERN = re.compile(r"^(?P<base>.+)-v(?P<n>\d+)$")


def _parse_card_id(card_id: str) -> tuple[str, Optional[int]]:
    """Split card_id into (base_name, version). version is None if no -vN suffix."""
    m = _VERSION_PATTERN.match(card_id)
    if not m:
        return card_id, None
    return m.group("base"), int(m.group("n"))


def group_by_base_name(cards: dict[str, dict]) -> list[dict]:
    """Group cards by their base_name (the part before -vN).

    Returns groups sorted by base_name asc. Within each group, cards are
    sorted enabled-first then version-desc, with disabled appended after.

    Each group dict shape:
        {
          "base_name": str,
          "enabled_count": int,
          "total_count": int,
          "multi_enabled_warning": bool,
          "cards": [hydrated card dicts in display order],
        }
    """
    by_base: dict[str, list[tuple[Optional[int], dict]]] = {}
    for cid, card in cards.items():
        base, version = _parse_card_id(cid)
        by_base.setdefault(base, []).append((version, card))

    groups = []
    for base_name in sorted(by_base.keys()):
        entries = by_base[base_name]
        enabled = [(v, c) for v, c in entries if c.get("status") == "enabled"]
        disabled = [(v, c) for v, c in entries if c.get("status") != "enabled"]
        # Sort each by version desc; cards without version go last
        def _sortkey(t):
            v, _ = t
            return (-v if v is not None else 1, 0)
        enabled.sort(key=_sortkey)
        disabled.sort(key=_sortkey)
        ordered = [c for _, c in enabled] + [c for _, c in disabled]
        groups.append({
            "base_name": base_name,
            "enabled_count": len(enabled),
            "total_count": len(entries),
            "multi_enabled_warning": len(enabled) > 1,
            "cards": ordered,
        })
    return groups
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/cards_view.py tests/web/test_cards_view.py
git commit -m "$(cat <<'EOF'
feat(web): cards_view.group_by_base_name with collision warning

Cards group by the part before -vN. Within group: enabled first sorted
by version desc, disabled after. multi_enabled_warning flag fires when
2+ versions are simultaneously enabled (UI surfaces this as a yellow
group-header warning per spec §5.4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add `cards_view.list_cards_view` aggregator

**Files:**
- Modify: `tradelab/src/tradelab/web/cards_view.py`
- Test: `tradelab/tests/web/test_cards_view.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/web/test_cards_view.py`:

```python
def test_list_cards_view_combines_grouping_and_derivations(tmp_path: Path) -> None:
    cards = {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32, "symbol": "AAPL",
                   "status": "enabled", "quantity": 10, "cadence": "daily"},
        "foo-v2": {"card_id": "foo-v2", "secret": "y" * 32, "symbol": "AAPL",
                   "status": "disabled", "quantity": None},  # missing v1 fields
    }
    log = tmp_path / "alerts.jsonl"
    now = datetime.now(timezone.utc)
    _write_alerts(log, [
        {"ts": (now - timedelta(hours=2)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
    ])

    view = cards_view.list_cards_view(cards, log)

    assert "groups" in view
    assert "total_cards" in view
    assert "total_enabled" in view
    assert view["total_cards"] == 2
    assert view["total_enabled"] == 1

    foo_group = view["groups"][0]
    assert foo_group["base_name"] == "foo"
    foo_v1 = foo_group["cards"][0]  # enabled first
    assert foo_v1["card_id"] == "foo-v1"
    assert foo_v1["last_status"] == "order_submitted"
    assert foo_v1["fires_24h"] == 2
    # foo-v2 was missing v1 fields — hydration should NOT happen here
    # (caller is expected to pass already-hydrated cards). But the derived
    # fields should still attach.
    foo_v2 = foo_group["cards"][1]
    assert foo_v2["last_status"] is None
    assert foo_v2["fires_24h"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py::test_list_cards_view_combines_grouping_and_derivations -v`

Expected: FAIL with `AttributeError: module 'tradelab.web.cards_view' has no attribute 'list_cards_view'`.

- [ ] **Step 3: Implement list_cards_view**

Append to `tradelab/src/tradelab/web/cards_view.py`:

```python
def list_cards_view(cards: dict[str, dict], alerts_log: Path) -> dict:
    """Top-level aggregator for GET /tradelab/cards.

    Caller is responsible for passing hydrated cards (typically via
    CardRegistry.all_hydrated()). This function only handles derivations
    and grouping — it does NOT mutate cards or read cards.json itself.
    """
    card_ids = list(cards.keys())
    last_status = derive_last_status(card_ids, alerts_log)
    fires_24h = derive_fire_counts(card_ids, alerts_log, hours=24)

    enriched: dict[str, dict] = {}
    for cid, card in cards.items():
        enriched[cid] = {
            **card,
            "last_status": last_status.get(cid),
            "fires_24h": fires_24h.get(cid, 0),
        }

    groups = group_by_base_name(enriched)
    total_enabled = sum(g["enabled_count"] for g in groups)
    return {
        "groups": groups,
        "total_cards": len(cards),
        "total_enabled": total_enabled,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/cards_view.py tests/web/test_cards_view.py
git commit -m "$(cat <<'EOF'
feat(web): cards_view.list_cards_view aggregator

Top-level entrypoint for GET /tradelab/cards. Combines grouping +
derived last_status + 24h fire count into one payload shape the
frontend can render directly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire GET /tradelab/cards endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py`
- Test: `tradelab/tests/web/test_cards_handlers.py`

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/web/test_cards_handlers.py`:

```python
"""Tests for /tradelab/cards* GET handlers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import handlers


def _seed(tmp_path: Path, cards: dict, alerts: list[dict]) -> tuple[Path, Path]:
    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps(cards), encoding="utf-8")
    alerts_path = tmp_path / "alerts.jsonl"
    alerts_path.write_text(
        "\n".join(json.dumps(a) for a in alerts) + ("\n" if alerts else ""),
        encoding="utf-8",
    )
    return cards_path, alerts_path


def test_get_cards_returns_grouped_view(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32,
                   "symbol": "AAPL", "status": "enabled", "quantity": 5},
    }, [])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, status = handlers.handle_get_with_status("/tradelab/cards")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["total_cards"] == 1
    assert payload["total_enabled"] == 1
    assert payload["groups"][0]["base_name"] == "foo"


def test_get_cards_handles_missing_cards_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "no_cards.json")
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")

    body, status = handlers.handle_get_with_status("/tradelab/cards")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload == {"groups": [], "total_cards": 0, "total_enabled": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py -v`

Expected: FAIL with `AttributeError: module 'tradelab.web.handlers' has no attribute '_alerts_log_path'`.

- [ ] **Step 3: Add `_alerts_log_path` helper and the route**

Edit `tradelab/src/tradelab/web/handlers.py`. After the existing `_cards_path()` helper (around line 124), add:

```python
def _alerts_log_path() -> Path:
    return Path("live") / "alerts.jsonl"
```

Then update the imports at the top of the file to include `cards_view`:

```python
from tradelab.web import audit_reader, cards_view, freshness, new_strategy, ranges, whatif
```

(Only `cards_view` is new — preserve the rest of the existing import line as-is.)

In `handle_get_with_status`, before the final `return _err("not found"), 404`, add:

```python
    if path == "/tradelab/cards":
        cards_path = _cards_path()
        if not cards_path.exists():
            return _ok({"groups": [], "total_cards": 0, "total_enabled": 0}), 200
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        view = cards_view.list_cards_view(
            reg.all_hydrated(),
            _alerts_log_path(),
        )
        return _ok(view), 200
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run full pytest to verify no regressions**

Run: `cd C:/TradingScripts/tradelab && pytest -x`

Expected: All tests pass (count should be ≥ 413 + 8 new = 421).

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET /tradelab/cards returns grouped Live Trading view

First read endpoint for the new tab. Returns groups (by base_name) +
totals + per-card last_status + 24h fire count. Empty payload when
cards.json doesn't exist yet (fresh install).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Wire GET /tradelab/cards/<id>/alerts endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py`
- Modify: `tradelab/src/tradelab/web/cards_view.py`
- Test: `tradelab/tests/web/test_cards_handlers.py` (extend)
- Test: `tradelab/tests/web/test_cards_view.py` (extend)

- [ ] **Step 1: Write the failing test for the helper**

Append to `tradelab/tests/web/test_cards_view.py`:

```python
def test_tail_alerts_for_card_returns_most_recent_first(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": "2026-04-25T09:00:00+00:00", "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": "2026-04-25T09:30:00+00:00", "card_id": "bar-v1", "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1", "status": "order_failed"},
    ])

    out = cards_view.tail_alerts_for_card("foo-v1", log, limit=10)

    assert len(out) == 2
    assert out[0]["ts"] == "2026-04-25T10:00:00+00:00"  # most recent first
    assert out[1]["ts"] == "2026-04-25T09:00:00+00:00"


def test_tail_alerts_for_card_respects_limit(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": f"2026-04-25T09:0{i}:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"}
        for i in range(8)
    ])
    out = cards_view.tail_alerts_for_card("foo-v1", log, limit=3)
    assert len(out) == 3
    # Most recent 3 (indices 7, 6, 5)
    assert out[0]["ts"] == "2026-04-25T09:07:00+00:00"
    assert out[2]["ts"] == "2026-04-25T09:05:00+00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py::test_tail_alerts_for_card_returns_most_recent_first -v`

Expected: FAIL with `AttributeError: module 'tradelab.web.cards_view' has no attribute 'tail_alerts_for_card'`.

- [ ] **Step 3: Implement tail_alerts_for_card**

Append to `tradelab/src/tradelab/web/cards_view.py`:

```python
def tail_alerts_for_card(
    card_id: str,
    log_path: Path,
    limit: int = 50,
) -> list[dict]:
    """Return up to `limit` most-recent alerts for a card_id, newest first."""
    matches = [e for e in _iter_alerts(log_path) if e.get("card_id") == card_id]
    return list(reversed(matches[-limit:]))
```

- [ ] **Step 4: Verify the helper test passes**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_view.py -v`

Expected: 10 passed.

- [ ] **Step 5: Write the failing handler test**

Append to `tradelab/tests/web/test_cards_handlers.py`:

```python
def test_get_card_alerts_returns_tail(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32,
                   "symbol": "AAPL", "status": "enabled", "quantity": 5},
    }, [
        {"ts": "2026-04-25T09:00:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1",
         "status": "order_failed"},
    ])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/alerts?limit=50"
    )

    assert status == 200
    payload = json.loads(body)["data"]
    assert len(payload["alerts"]) == 2
    assert payload["alerts"][0]["status"] == "order_failed"  # newest first


def test_get_card_alerts_limit_param(tmp_path: Path, monkeypatch) -> None:
    cards_path, alerts_path = _seed(tmp_path, {}, [
        {"ts": f"2026-04-25T09:0{i}:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"}
        for i in range(5)
    ])
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)

    body, _ = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/alerts?limit=2"
    )
    payload = json.loads(body)["data"]
    assert len(payload["alerts"]) == 2
```

- [ ] **Step 6: Run handler test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py::test_get_card_alerts_returns_tail -v`

Expected: FAIL with 404 because the route doesn't exist yet.

- [ ] **Step 7: Wire the route**

In `tradelab/src/tradelab/web/handlers.py`, in `handle_get_with_status`, immediately after the `/tradelab/cards` route added in Task 8, add:

```python
    m = re.match(r"^/tradelab/cards/([^/]+)/alerts$", path)
    if m:
        try:
            limit = int(q.get("limit", "50"))
        except (TypeError, ValueError):
            limit = 50
        alerts = cards_view.tail_alerts_for_card(
            m.group(1), _alerts_log_path(), limit=limit
        )
        return _ok({"alerts": alerts}), 200
```

- [ ] **Step 8: Run handler tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py -v`

Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/cards_view.py src/tradelab/web/handlers.py tests/web/test_cards_view.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET /tradelab/cards/<id>/alerts tail endpoint

Frontend Live Trading slide-pane reads this for the Recent Alerts tab.
Newest-first ordering, configurable limit (default 50).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Wire GET /tradelab/cards/<id>/archive endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py`
- Test: `tradelab/tests/web/test_cards_handlers.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/web/test_cards_handlers.py`:

```python
def test_get_card_archive_returns_pine_and_verdict(tmp_path: Path, monkeypatch) -> None:
    archive_root = tmp_path / "pine_archive"
    card_dir = archive_root / "foo-v1"
    card_dir.mkdir(parents=True)
    (card_dir / "strategy.pine").write_text("// pine source", encoding="utf-8")
    (card_dir / "verdict.json").write_text(
        json.dumps({"verdict": "ROBUST", "dsr": 0.75}),
        encoding="utf-8",
    )
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: archive_root)

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/foo-v1/archive"
    )

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["pine_source"] == "// pine source"
    assert payload["verdict"]["verdict"] == "ROBUST"


def test_get_card_archive_404_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/never-existed-v1/archive"
    )
    assert status == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py::test_get_card_archive_returns_pine_and_verdict -v`

Expected: FAIL — route returns 404 from the catch-all because it's not implemented.

- [ ] **Step 3: Wire the route**

In `tradelab/src/tradelab/web/handlers.py`, in `handle_get_with_status`, immediately after the `/tradelab/cards/<id>/alerts` route added in Task 9, add:

```python
    m = re.match(r"^/tradelab/cards/([^/]+)/archive$", path)
    if m:
        card_id = m.group(1)
        archive_dir = _pine_archive_root() / card_id
        if not archive_dir.exists():
            return _err("archive not found"), 404
        pine_path = archive_dir / "strategy.pine"
        verdict_path = archive_dir / "verdict.json"
        out: dict = {}
        if pine_path.exists():
            out["pine_source"] = pine_path.read_text(encoding="utf-8")
        if verdict_path.exists():
            try:
                out["verdict"] = json.loads(
                    verdict_path.read_text(encoding="utf-8-sig")
                )
            except json.JSONDecodeError as e:
                out["verdict"] = {"error": f"verdict.json parse failed: {e}"}
        return _ok(out), 200
```

- [ ] **Step 4: Run handler tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py -v`

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET /tradelab/cards/<id>/archive serves frozen Pine + verdict

Frontend slide-pane Pine Archive tab reads this. 404 when no archive
folder exists for the card_id (would happen if archive was rmtree'd or
card was hand-rolled without going through Score/Accept).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Wire GET /tradelab/receiver/status endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py`
- Test: `tradelab/tests/web/test_cards_handlers.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/web/test_cards_handlers.py`:

```python
import urllib.error


def test_get_receiver_status_reports_up(tmp_path: Path, monkeypatch) -> None:
    """Receiver and ngrok both responding → both up=True."""
    def fake_probe(url: str, timeout: float):
        if "8878" in url:
            return {"status": "ok", "cards_loaded": 3}
        if "4040" in url:
            return {"tunnels": [
                {"public_url": "https://abcd-1234.ngrok-free.app",
                 "proto": "https"}
            ]}
        raise ValueError(f"unexpected url {url}")

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["receiver_up"] is True
    assert payload["ngrok_up"] is True
    assert payload["ngrok_url"] == "https://abcd-1234.ngrok-free.app"
    assert payload["cards_loaded"] == 3


def test_get_receiver_status_reports_down(monkeypatch) -> None:
    """Both probes fail → both up=False, no ngrok URL."""
    def fake_probe(url: str, timeout: float):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(handlers, "_probe_json", fake_probe)
    body, status = handlers.handle_get_with_status("/tradelab/receiver/status")

    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["receiver_up"] is False
    assert payload["ngrok_up"] is False
    assert payload["ngrok_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py::test_get_receiver_status_reports_up -v`

Expected: FAIL — `_probe_json` doesn't exist yet.

- [ ] **Step 3: Implement the probe helper and the route**

In `tradelab/src/tradelab/web/handlers.py`, near the other private helpers (after `_alerts_log_path`), add:

```python
def _probe_json(url: str, timeout: float = 1.5) -> dict:
    """Tiny GET-and-parse-JSON helper used by /receiver/status. Returns
    parsed JSON dict on success; raises on any error so the caller can
    use a single try/except to mark the probe as down."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

In `handle_get_with_status`, immediately after the `/tradelab/cards/<id>/archive` route, add:

```python
    if path == "/tradelab/receiver/status":
        receiver_up = False
        cards_loaded = None
        try:
            health = _probe_json("http://127.0.0.1:8878/health", timeout=1.5)
            receiver_up = health.get("status") == "ok"
            cards_loaded = health.get("cards_loaded")
        except Exception:
            pass

        ngrok_up = False
        ngrok_url = None
        try:
            tunnels = _probe_json("http://127.0.0.1:4040/api/tunnels", timeout=1.5)
            for t in tunnels.get("tunnels", []):
                if t.get("proto") == "https":
                    ngrok_url = t.get("public_url")
                    ngrok_up = bool(ngrok_url)
                    break
        except Exception:
            pass

        return _ok({
            "receiver_up": receiver_up,
            "ngrok_up": ngrok_up,
            "ngrok_url": ngrok_url,
            "cards_loaded": cards_loaded,
        }), 200
```

- [ ] **Step 4: Run handler tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/web/test_cards_handlers.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET /tradelab/receiver/status probes receiver + ngrok

Drives the receiver-status chip at the top of the Live Trading tab.
Both probes have a 1.5s timeout so the dashboard never blocks on a
dead receiver/ngrok. Either probe failing reports up=False; both
failing returns the empty-state shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Implement file-watcher in receiver

**Files:**
- Modify: `tradelab/src/tradelab/live/receiver.py`
- Test: `tradelab/tests/live/test_receiver_watcher.py`

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/live/test_receiver_watcher.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_receiver_watcher.py -v`

Expected: FAIL with `ImportError: cannot import name '_start_cards_watcher'`.

- [ ] **Step 3: Add `_start_cards_watcher` to receiver.py**

Edit `tradelab/src/tradelab/live/receiver.py`. Add these imports near the top (after existing imports):

```python
from threading import Lock
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
```

Then add this function above the `cards = CardRegistry(CARDS_PATH)` line (around line 38):

```python
class _CardsReloadHandler(FileSystemEventHandler):
    """Watchdog handler that calls registry.reload() on cards.json change.

    Debounces with a 100ms cooldown — atomic os.replace() can fire two
    events on Windows, and we only need one reload per write.
    """
    def __init__(self, registry: CardRegistry, watched_path: Path):
        self._registry = registry
        self._watched_name = watched_path.name
        self._watched_path = watched_path.resolve()
        self._lock = Lock()
        self._last_reload_at = 0.0
        self._last_mtime: float = 0.0

    def _maybe_reload(self) -> None:
        # Debounce + mtime gate
        with self._lock:
            now = time.time()
            if now - self._last_reload_at < 0.1:
                return
            try:
                mtime = self._watched_path.stat().st_mtime
            except FileNotFoundError:
                # File was deleted; nothing to reload
                return
            if mtime <= self._last_mtime:
                return
            self._last_mtime = mtime
            self._last_reload_at = now
        try:
            self._registry.reload()
            logger.info("cards.json reloaded; cards_loaded=%d",
                        self._registry.count())
        except Exception as e:
            logger.error("cards.json reload failed: %s", e)

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == self._watched_name:
            self._maybe_reload()

    def on_created(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == self._watched_name:
            self._maybe_reload()


def _start_cards_watcher(registry: CardRegistry, *, polling: bool = False):
    """Start a watchdog observer on the parent dir of registry.path.

    Returns the started observer; caller is responsible for stopping it.
    polling=True forces watchdog.PollingObserver (deterministic for tests
    on Windows where the native ReadDirectoryChangesW can be flaky in
    short-lived processes).
    """
    import time as _time  # ensure local binding; module-level time imported above

    handler = _CardsReloadHandler(registry, registry.path)
    observer_cls = PollingObserver if polling else Observer
    observer = observer_cls()
    # Watch the parent directory; filter by filename in the handler
    watch_dir = str(registry.path.parent.resolve())
    Path(watch_dir).mkdir(parents=True, exist_ok=True)
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    return observer
```

Add `import time` to the top-level imports if it's not already there (it should be — receiver.py already uses datetime extensively but check that `import time` is present; if not, add it).

- [ ] **Step 4: Wire the watcher into FastAPI startup**

Still in `tradelab/src/tradelab/live/receiver.py`, after the `app = FastAPI(...)` line, add:

```python
@app.on_event("startup")
def _on_startup() -> None:
    global _cards_observer
    _cards_observer = _start_cards_watcher(cards, polling=False)
    logger.info("cards.json watcher started on %s", cards.path)


@app.on_event("shutdown")
def _on_shutdown() -> None:
    global _cards_observer
    if _cards_observer is not None:
        _cards_observer.stop()
        _cards_observer.join(timeout=3.0)
        _cards_observer = None


_cards_observer = None
```

- [ ] **Step 5: Run watcher tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/live/test_receiver_watcher.py -v`

Expected: 2 passed. (Allow up to 6 seconds total for both tests due to the 3-second polling waits.)

- [ ] **Step 6: Run full pytest to confirm no regressions**

Run: `cd C:/TradingScripts/tradelab && pytest -x`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/receiver.py tests/live/test_receiver_watcher.py
git commit -m "$(cat <<'EOF'
feat(live): receiver hot-reloads cards.json via watchdog

100ms debounce + mtime gate prevents the duplicate event Windows
sometimes fires for atomic os.replace(). FastAPI startup hook
schedules the observer; shutdown hook stops + joins it. Tests use
PollingObserver for deterministic behavior across OS file-event
backends.

After this commit, every Score → Accept is immediately visible to
the receiver — no more manual restart between approval and live.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Add Live Trading tab — HTML skeleton + tab button

**Files:**
- Modify: `C:/TradingScripts/command_center.html`

This is parent-repo work (not in the tradelab repo). All commands run from `C:/TradingScripts`.

- [ ] **Step 1: Locate the existing tab navigation in command_center.html**

Use the Grep tool (or equivalent) with pattern `tab-btn|data-tab=` against `C:/TradingScripts/command_center.html`, output mode `content` with `-n` line numbers, head limit ~20.

Note the line numbers where the tab buttons are defined and where their tab content sections live. You'll be inserting in those same regions.

- [ ] **Step 2: Add the Live Trading tab button**

Find the existing tab-button group (search for `data-tab="research"` to anchor; the buttons live in a `<div class="tabs">` or similar container near the top of the body). Add a new button immediately after the Research tab button:

```html
<button class="tab-btn" data-tab="live-trading">Live Trading</button>
```

(Match the exact class and attribute spelling used by the other buttons in that group; if the button class is `tab-button` instead of `tab-btn`, use that. Keep your addition consistent with the surrounding pattern.)

- [ ] **Step 3: Add the tab content container**

Find the existing tab-content sections (search for `id="tab-research"` or `data-tab-content="research"` — match whichever marker is used). After the closing tag of the Research tab content, insert:

```html
<section id="tab-live-trading" class="tab-content" hidden>
  <div class="lt-status-strip">
    <span id="lt-receiver-chip" class="lt-chip lt-chip--unknown">Receiver: …</span>
    <span id="lt-ngrok-chip" class="lt-chip lt-chip--unknown">ngrok: …</span>
    <span id="lt-totals" class="lt-totals">— cards enabled / —</span>
  </div>
  <div id="lt-cards-list" class="lt-cards-list">
    <p class="lt-loading">Loading cards…</p>
  </div>
</section>
```

(Again — match `class` / `id` / `hidden` conventions from the surrounding tab-content sections. If the codebase uses `style="display:none"` instead of the `hidden` attribute, use that instead.)

- [ ] **Step 4: Verify HTML still parses**

Run:
```bash
python -c "from html.parser import HTMLParser; HTMLParser().feed(open('C:/TradingScripts/command_center.html', encoding='utf-8').read()); print('parsed ok')"
```

Expected: `parsed ok`.

- [ ] **Step 5: Open the dashboard and visually verify**

Open the dashboard in a browser (start the launcher with `cd C:/TradingScripts && research_dashboard.bat` if it isn't already running) and click the new "Live Trading" tab button. Expected: tab switches; you see the three chips in the status strip and the "Loading cards…" placeholder. Cards list won't populate yet (JS comes in Task 15).

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): Live Trading tab skeleton

Scaffolding only — tab button, status strip with three chips
(receiver / ngrok / totals), and an empty cards-list container.
JS wiring lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Add Live Trading tab — CSS for chips, list, group headers, row layout

**Files:**
- Modify: `C:/TradingScripts/command_center.html`

- [ ] **Step 1: Add the Live Trading CSS block**

Find the closing `</style>` tag in the existing top-of-file `<style>` block of `command_center.html`. Insert these rules immediately before `</style>`:

```css
/* Live Trading tab */
.lt-status-strip {
  display: flex; gap: 16px; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid #2a3140;
  background: #161b22;
}
.lt-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 12px;
  font-size: 0.85em; font-weight: 600;
  border: 1px solid #2a3140; background: #1c2330;
}
.lt-chip--up      { color: #3dd68c; border-color: #2a5040; background: #162a23; }
.lt-chip--down    { color: #ff6b6b; border-color: #602828; background: #2a1818; }
.lt-chip--unknown { color: #9aa5b1; }
.lt-totals { margin-left: auto; color: #9aa5b1; font-size: 0.9em; }

.lt-cards-list { padding: 12px 16px; }
.lt-loading    { color: #9aa5b1; font-style: italic; }

.lt-group {
  margin-bottom: 18px; border: 1px solid #2a3140;
  border-radius: 8px; background: #161b22;
}
.lt-group-header {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border-bottom: 1px solid #2a3140;
}
.lt-group-name { font-weight: 700; color: #e6edf3; }
.lt-group-counts { color: #9aa5b1; font-size: 0.85em; }
.lt-group-warning {
  margin-left: auto; padding: 2px 8px; border-radius: 10px;
  background: #3a3520; color: #ffe9a0; border: 1px solid #5a4a1c;
  font-size: 0.78em;
}

.lt-row {
  display: grid;
  grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px;
  gap: 10px; align-items: center;
  padding: 8px 14px;
  border-top: 1px solid #1c2330;
  font-size: 0.9em;
}
.lt-row:hover { background: #1c2330; }
.lt-row--enabled  { /* default */ }
.lt-row--disabled { opacity: 0.65; }

.lt-pill {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 0.78em; font-weight: 600;
}
.lt-pill--enabled  { color: #3dd68c; background: #162a23; border: 1px solid #2a5040; }
.lt-pill--disabled { color: #9aa5b1; background: #1c2330; border: 1px solid #2a3140; }
.lt-pill--silent   { color: #ffe9a0; background: #3a3520; border: 1px solid #5a4a1c; }

.lt-laststatus--order_submitted   { color: #3dd68c; }
.lt-laststatus--order_failed      { color: #ff6b6b; }
.lt-laststatus--guardrail_blocked { color: #ff9f43; }
.lt-laststatus--none              { color: #6b7684; }

.lt-disclosure {
  padding: 6px 14px; color: #9aa5b1; font-size: 0.85em;
  cursor: pointer; user-select: none; border-top: 1px solid #1c2330;
}
.lt-disclosure:hover { color: #e6edf3; }
```

- [ ] **Step 2: Verify the parse still passes**

Run:
```bash
python -c "from html.parser import HTMLParser; HTMLParser().feed(open('C:/TradingScripts/command_center.html', encoding='utf-8').read()); print('parsed ok')"
```

Expected: `parsed ok`.

- [ ] **Step 3: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
ui(command-center): Live Trading tab styles (chips, rows, groups)

Status chips (up/down/unknown), grouped card containers, row grid
layout (9 columns matching the v1 spec), pill / last-status color
classes. No JS yet — next commit fetches and renders.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Add Live Trading tab — JS to fetch /tradelab/cards and render

**Files:**
- Modify: `C:/TradingScripts/command_center.html`

- [ ] **Step 1: Locate the JS module / script block**

The dashboard has a single large `<script>` block near the bottom. Use the Grep tool with pattern `function fetchRuns` or `function renderRuns` against `command_center.html` to find it.

- [ ] **Step 2: Add the Live Trading JS module**

Inside the existing top-level `<script>` block, just before the script's closing `</script>` tag, add:

```javascript
/* === Live Trading tab === */
const LT = (() => {
  const $list = () => document.getElementById('lt-cards-list');
  const $totals = () => document.getElementById('lt-totals');
  const $receiverChip = () => document.getElementById('lt-receiver-chip');
  const $ngrokChip = () => document.getElementById('lt-ngrok-chip');

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmtRelative(iso) {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '—';
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    return `${Math.floor(sec / 86400)}d ago`;
  }

  function renderRow(card) {
    const statusCls = card.status === 'enabled' ? 'enabled' : 'disabled';
    const lastStatusKey = card.last_status || 'none';
    return `
      <div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}">
        <span></span>
        <span>${escHtml(card.card_id)}</span>
        <span class="lt-pill lt-pill--${statusCls}">${escHtml(card.status)}</span>
        <span>${escHtml(card.symbol)}</span>
        <span>${card.quantity == null ? '—' : escHtml(card.quantity)}</span>
        <span>${escHtml(card.cadence || 'daily')}</span>
        <span>${fmtRelative(card.last_fired_at)}</span>
        <span class="lt-laststatus--${escHtml(lastStatusKey)}">
          ${card.last_status ? escHtml(card.last_status) : '—'}
        </span>
        <span>${card.fires_24h ?? 0}</span>
      </div>
    `;
  }

  function renderGroup(group) {
    const enabled = group.cards.filter(c => c.status === 'enabled');
    const disabled = group.cards.filter(c => c.status !== 'enabled');
    const warning = group.multi_enabled_warning
      ? `<span class="lt-group-warning">⚠ ${group.enabled_count} versions enabled — collision risk</span>`
      : '';
    const enabledHtml = enabled.map(renderRow).join('');
    const disabledHtml = disabled.map(renderRow).join('');
    const disclosureId = `lt-disclosure-${escHtml(group.base_name)}`;
    const disabledBlock = disabled.length > 0 ? `
      <div class="lt-disclosure" data-target="${disclosureId}">
        ▸ Show ${disabled.length} disabled version${disabled.length === 1 ? '' : 's'}
      </div>
      <div id="${disclosureId}" hidden>${disabledHtml}</div>
    ` : '';
    return `
      <div class="lt-group">
        <div class="lt-group-header">
          <span class="lt-group-name">${escHtml(group.base_name)}</span>
          <span class="lt-group-counts">${group.enabled_count} / ${group.total_count} versions</span>
          ${warning}
        </div>
        ${enabledHtml}
        ${disabledBlock}
      </div>
    `;
  }

  function bindDisclosureToggles() {
    document.querySelectorAll('.lt-disclosure').forEach(el => {
      el.addEventListener('click', () => {
        const target = document.getElementById(el.dataset.target);
        if (!target) return;
        const open = target.hasAttribute('hidden');
        if (open) {
          target.removeAttribute('hidden');
          el.textContent = el.textContent.replace('▸', '▾');
        } else {
          target.setAttribute('hidden', '');
          el.textContent = el.textContent.replace('▾', '▸');
        }
      });
    });
  }

  async function fetchAndRender() {
    try {
      const resp = await fetch('/tradelab/cards');
      const json = await resp.json();
      const view = json.data || { groups: [], total_cards: 0, total_enabled: 0 };
      $totals().textContent = `${view.total_enabled} cards enabled / ${view.total_cards}`;
      if (view.groups.length === 0) {
        $list().innerHTML = `<p class="lt-loading">No cards yet — Score → Accept a strategy to create one.</p>`;
        return;
      }
      $list().innerHTML = view.groups.map(renderGroup).join('');
      bindDisclosureToggles();
    } catch (err) {
      $list().innerHTML = `<p class="lt-loading">Failed to load: ${escHtml(err.message)}</p>`;
    }
  }

  async function refreshStatusChips() {
    try {
      const resp = await fetch('/tradelab/receiver/status');
      const json = await resp.json();
      const s = json.data || {};
      const recCls = s.receiver_up ? 'lt-chip--up' : 'lt-chip--down';
      const recText = s.receiver_up ? `Receiver: up (${s.cards_loaded ?? '?'} cards)` : 'Receiver: DOWN';
      $receiverChip().className = `lt-chip ${recCls}`;
      $receiverChip().textContent = recText;
      const ngCls = s.ngrok_up ? 'lt-chip--up' : 'lt-chip--down';
      const ngText = s.ngrok_up ? `ngrok: up` : 'ngrok: down';
      $ngrokChip().className = `lt-chip ${ngCls}`;
      $ngrokChip().textContent = ngText;
    } catch {
      $receiverChip().className = 'lt-chip lt-chip--unknown';
      $receiverChip().textContent = 'Receiver: ?';
      $ngrokChip().className = 'lt-chip lt-chip--unknown';
      $ngrokChip().textContent = 'ngrok: ?';
    }
  }

  function activate() {
    fetchAndRender();
    refreshStatusChips();
  }

  return { activate, fetchAndRender, refreshStatusChips };
})();

/* Hook into the existing tab-switch handler. The dashboard already
   wires tab-btn click to show/hide tab-content; we just need to
   trigger LT.activate() when the live-trading tab becomes active. */
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.tab-btn[data-tab="live-trading"]');
  if (btn) LT.activate();
});

/* If the URL hash already targets live-trading on page load, activate. */
if (location.hash.includes('tab=live-trading')) {
  document.addEventListener('DOMContentLoaded', () => LT.activate());
}
```

- [ ] **Step 2.5: Adapt the tab-activation hook to match existing wiring**

The dashboard's existing tab system is the source of truth for switching tabs. Run `grep -n "tab-btn\|switchTab\|activeTab\|tab-content" "C:/TradingScripts/command_center.html" | head -30` to find how the existing tabs handle activation. If the existing code uses a function like `switchTab(name)` or fires a custom event, replace the bare `addEventListener('click', ...)` shim above with a call into that mechanism. Common patterns:

- If there's a `switchTab(name)` function: append `if (name === 'live-trading') LT.activate();` inside it.
- If tab buttons toggle a class without a function: keep the click handler shown above.
- If tab content uses `data-tab-content` instead of `id="tab-X"`: rename the section's `id` in Task 13 to match (or change the JS selectors here).

The principle: do NOT break the existing tab system; integrate with whatever it already does.

- [ ] **Step 3: Verify the script still parses**

Run a JS syntax check on the inline script. Save the file's `<script>` block to a temp file and use `node --check`:

```bash
python -c "
import re
html = open('C:/TradingScripts/command_center.html', encoding='utf-8').read()
# Extract every <script> block and concatenate (matches the existing repo convention)
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, flags=re.S)
open('C:/TradingScripts/.tmp_check.js', 'w', encoding='utf-8').write('\n'.join(scripts))
print('extracted', len(scripts), 'script blocks')
"
node --check "C:/TradingScripts/.tmp_check.js" && rm "C:/TradingScripts/.tmp_check.js"
```

Expected: no output from `node --check` (no syntax errors). The file gets cleaned up.

- [ ] **Step 4: Manual smoke test**

Make sure the dashboard launcher is running (`cd C:/TradingScripts && python launch_dashboard.py` if needed). Open `http://localhost:8877/` in a browser, click the **Live Trading** tab, and verify:

- The three chips at the top reflect actual receiver/ngrok state (red if either is down, green if both up).
- If `tradelab/live/cards.json` has cards, you see them grouped by `base_name`. Try this with a real cards file from a previous Score → Accept.
- If cards.json is empty or missing, the empty-state placeholder shows.
- Click a "Show N disabled versions" disclosure — it expands and the arrow flips.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): Live Trading tab JS — fetch + group + render

Wires /tradelab/cards into the new tab. Status chips reflect real
receiver and ngrok state. Disabled-versions disclosure folds away
the noise so 30+ rows from delete-and-recreate iteration stay
manageable. Read-only — mutations land in Slice 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Auto-refresh status chips on a timer + smoke test the full slice

**Files:**
- Modify: `C:/TradingScripts/command_center.html`

- [ ] **Step 1: Add a periodic chip refresh while the Live Trading tab is visible**

Inside the IIFE returned by `LT` (just before `return { activate, fetchAndRender, refreshStatusChips };`), add:

```javascript
  let _statusTimer = null;
  function startStatusPolling() {
    if (_statusTimer) return;
    _statusTimer = setInterval(refreshStatusChips, 10_000);
  }
  function stopStatusPolling() {
    if (_statusTimer) { clearInterval(_statusTimer); _statusTimer = null; }
  }
```

Then change the returned object to expose them:

```javascript
  return { activate, fetchAndRender, refreshStatusChips, startStatusPolling, stopStatusPolling };
```

And update `activate()` to start polling:

```javascript
  function activate() {
    fetchAndRender();
    refreshStatusChips();
    startStatusPolling();
  }
```

Add a deactivation hook listening for clicks on OTHER tab buttons:

```javascript
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.tab-btn');
  if (btn && btn.dataset.tab && btn.dataset.tab !== 'live-trading') {
    LT.stopStatusPolling();
  }
});
```

- [ ] **Step 2: Re-run the JS parse check**

```bash
python -c "
import re
html = open('C:/TradingScripts/command_center.html', encoding='utf-8').read()
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, flags=re.S)
open('C:/TradingScripts/.tmp_check.js', 'w', encoding='utf-8').write('\n'.join(scripts))
"
node --check "C:/TradingScripts/.tmp_check.js" && rm "C:/TradingScripts/.tmp_check.js"
```

Expected: no syntax errors.

- [ ] **Step 3: Full-slice manual smoke test**

With the dashboard running and the receiver also running:

1. Open `http://localhost:8877/` and switch to **Live Trading**.
2. Watch the status chips for ~12 seconds — confirm they refresh (look for re-render flicker or use DevTools Network tab to confirm `/tradelab/receiver/status` is hit every ~10s).
3. Switch to **Research** tab — confirm DevTools Network stops seeing `/tradelab/receiver/status` requests.
4. Stop the receiver (`Stop-Process -Id (Get-NetTCPConnection -LocalPort 8878 -State Listen).OwningProcess -Force` in PowerShell). Within 10 seconds, the Receiver chip should flip from `up (N cards)` → `DOWN`.
5. Restart the receiver and confirm the chip returns to up within the next refresh.
6. End-to-end hot-reload validation: with the receiver running, open `tradelab/live/cards.json` in an editor, add a fake card (status: disabled), save. Open `http://127.0.0.1:8878/health` directly in another tab and confirm `cards_loaded` increments WITHOUT restarting the receiver. (This is the architecturally critical test that closes Slice 1.)

- [ ] **Step 4: Run the full pytest suite one more time**

Run: `cd C:/TradingScripts/tradelab && pytest -x`

Expected: 413 baseline + ~20 new tests, all passing.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): Live Trading status chips auto-refresh every 10s

Polling starts when the tab is activated, stops when another tab is
clicked. Catches receiver/ngrok crashes within 10s while user is
watching the tab.

Closes Slice 1 of Direction A: read-only Live Trading tab + receiver
hot-reload via watchdog file observer. Mutations (toggle, edit
quantity, delete, bulk, panic, guardrails, notifications, settings)
ship in Slice 2+.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Smoke-test summary doc + handoff for Slice 2

**Files:**
- Create: `C:/TradingScripts/2026-04-25-DIRECTION-A-SLICE-1-COMPLETE.md`

- [ ] **Step 1: Write the handoff document**

Create `C:/TradingScripts/2026-04-25-DIRECTION-A-SLICE-1-COMPLETE.md`:

```markdown
# Direction A Slice 1 — Complete & Handoff

**Date:** 2026-04-25
**Spec:** `tradelab/docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md`
**Plan:** `tradelab/docs/superpowers/plans/2026-04-25-direction-a-slice-1-live-tab-foundation.md`

## What shipped

- Read-only Live Trading tab in `command_center.html` with grouped card rows
- 4 new GET endpoints under `/tradelab/cards*` and `/tradelab/receiver/status`
- `tradelab.web.cards_view` aggregator + 4 helpers
- `CardRegistry.all_hydrated()` + `_hydrate_card` for v0/v1 backward compat
- Receiver hot-reloads `cards.json` via watchdog Observer (100ms debounce + mtime gate)
- ~20 new pytest tests; all green; baseline preserved

## Verified manually

(Check off after smoke test pass)
- [ ] Status chips show real receiver + ngrok state and refresh every 10s while tab active
- [ ] Cards list groups by base_name; disabled versions collapse
- [ ] Empty state shows when cards.json missing or has no entries
- [ ] Multi-enabled-version warning renders when 2+ -vN of same base are enabled
- [ ] Hot-reload: editing cards.json without restarting receiver bumps `/health.cards_loaded`

## Known limitations (intentional — Slice 2+)

- No toggle / edit quantity / delete buttons — Slice 2
- No bulk actions — Slice 2
- No per-card overrides UI — Slice 3 (alongside guardrails)
- No settings panel — Slice 4
- No silence detection / cadence picker — Slice 5
- No panic panel — Slice 6
- No daily email summary or notification system — Slice 4

## Handoff for Slice 2

Slice 2 = mutations (PATCH/DELETE on cards). Specifically:

- `PATCH /tradelab/cards/<id>` for status / quantity / cadence / overrides
- `DELETE /tradelab/cards/<id>` with `{confirm: "DELETE"}`
- `POST /tradelab/cards/bulk-toggle` and `bulk-delete`
- New `CardRegistry` methods: `update`, `delete`, `set_status`, `set_quantity`
- Drop the Session 3a `status='disabled'` guardrail in `cards.py:71-75` (PATCH endpoint is the toggle)
- FE: inline-edit quantity (click to edit), toggle button per row, trash button per row, checkbox column for bulk

Architecture from Slice 1 holds: dashboard writes `cards.json`; receiver picks up via watcher.
```

- [ ] **Step 2: Commit (parent repo)**

```bash
cd C:/TradingScripts
git add 2026-04-25-DIRECTION-A-SLICE-1-COMPLETE.md
git commit -m "$(cat <<'EOF'
docs: Direction A Slice 1 complete + handoff for Slice 2

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Final verification — full pytest one last time**

Run: `cd C:/TradingScripts/tradelab && pytest`

Expected: full suite green, count = original baseline (413) + ~20 new tests from Slice 1.

---

## Self-review checklist (run before handing off to subagent)

The following spec sections were addressed in this plan:

- §4.1 (file watcher) → Task 12
- §4.3 partial (cards.py changes for `_hydrate_card`, `all_hydrated`) → Tasks 2, 3
- §5 (Live Trading tab UI — status strip, grouping, row layout) → Tasks 13, 14, 15, 16
- §6 partial — read endpoints only:
  - GET `/tradelab/cards` → Task 8
  - GET `/tradelab/cards/<id>/alerts` → Task 9
  - GET `/tradelab/cards/<id>/archive` → Task 10
  - GET `/tradelab/receiver/status` → Task 11
- §11.1 (backward compat hydration) → Task 2
- §12.1 (unit-test coverage for cards/cards_view/handlers) → Tasks 2-12

Deferred to later slices (per spec §13 sequencing):
- All mutation endpoints (PATCH, DELETE, bulk, panic) — Slice 2 + 6
- Guardrails module — Slice 3
- Notification module + settings panel — Slice 4
- Silence detection — Slice 5
- §11.2 (drop Session 3a safety guardrail in cards.py:71-75) — Slice 2 (when PATCH ships)

End of plan.
