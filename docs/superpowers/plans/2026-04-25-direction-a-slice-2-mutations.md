# Direction A — Slice 2 (Card Mutations) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PATCH/DELETE/bulk endpoints and Live Trading FE controls so card lifecycle (toggle, edit quantity, delete) requires zero `cards.json` editing.

**Architecture:** Backend mutations call new `CardRegistry` methods that write through the existing atomic `_persist()` (`os.replace`). Atomic replace fires the Slice 1 watchdog → receiver hot-reloads automatically. FE is vanilla JS extending the existing `LT` IIFE in `command_center.html`; each control optimistically updates then refetches `/tradelab/cards`.

**Tech Stack:** Python stdlib (`json`, `RLock`, `os.replace`), watchdog (already wired Slice 1), vanilla JS (no framework).

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `tradelab/src/tradelab/live/cards.py` | Drop Session 3a guardrail in `create()`; add `update`, `delete`, `set_status`, `set_quantity` |
| Modify | `tradelab/src/tradelab/web/cards_view.py` | Switch enrichment to `copy.deepcopy` (line 156-165) |
| Modify | `tradelab/src/tradelab/web/handlers.py` | Add `handle_patch_with_status`; add 4 cards mutation routes; allowed-field validation |
| Modify | `tradelab/launch_dashboard.py` (parent repo) | Add `do_PATCH` dispatcher mirroring `do_DELETE` |
| Modify | `tradelab/tests/live/test_cards_create.py` | Delete obsolete `test_create_rejects_enabled_status` |
| Create | `tradelab/tests/live/test_cards_mutations.py` | 6+ tests for `update`/`delete`/`set_status`/`set_quantity` |
| Modify | `tradelab/tests/web/test_cards_handlers.py` | Add 8+ PATCH/DELETE/bulk handler tests |
| Modify | `command_center.html` (parent repo) | Checkbox column, toggle button, inline-edit qty, trash button, delete modal, bulk action strip |

Baseline: 449 tests passing at end of Slice 1. Target end-of-Slice-2: ~462+.

---

## Conventions (load-bearing — Slice 1 validated these)

- **TDD strict:** failing test → verify it fails for the right reason → minimal impl → green → commit.
- **Test layout:** `from __future__ import annotations` at top; pytest `tmp_path` fixture; `monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)` for path overrides; `monkeypatch.setattr(handlers, "_alerts_log_path", lambda: alerts_path)` when alerts matter.
- **Response envelope:** `_ok(data)` returns `{"error": null, "data": <data>}`; `_err(msg, data=None)` returns `{"error": msg, "data": <data>}`. Both already in `handlers.py:724-729`.
- **Commits:** Direct to `master` in tradelab repo (no branches). Conventional `feat(layer): one-line summary`. Footer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Atomic write:** All persistence goes through `CardRegistry._persist()` which already does `tmp.write_text → os.replace(tmp, path)`. This is what fires the Windows watcher reliably.
- **HTML selectors (verified against current `command_center.html`):** Live Trading tab content is `<div id="live-trading" class="tab-content">` (NOT `id="tab-live-trading"`). Row grid is `.lt-row { grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px; }` — the leading `24px` is currently an empty `<span></span>` and is the slot for the Slice 2 checkbox.
- **DO NOT** introduce a separate FastAPI app, framework, or rebuild the LT module. Extend the existing `LT = (() => { ... })()` IIFE at `command_center.html:4255`.

---

## Allowed PATCH fields (single source of truth)

The PATCH endpoint accepts ONLY these fields. Anything else returns `400` with `{"error": "unknown field: X"}`.

| Field | Type | Validation |
|---|---|---|
| `status` | str | Must be `"enabled"` or `"disabled"` |
| `quantity` | int \| null | If int, must be `>= 1`. `null` allowed (=use card default) |
| `cadence` | str | Must be in `{"intraday", "daily", "weekly", "manual"}` |
| `daily_limit` | int | Must be `>= 0` |
| `cooldown_seconds` | int | Must be `>= 0` |
| `allow_collision` | bool | — |
| `allow_naked_short` | bool | — |

Validation lives in the **handler** (system boundary). `CardRegistry.update` is internal — it trusts callers to pass already-validated fields.

---

## Task 1: Drop Session 3a guardrail (carry-over)

**Files:**
- Modify: `tradelab/src/tradelab/live/cards.py:94-112` (remove `status='disabled'` check)
- Modify: `tradelab/tests/live/test_cards_create.py:39-44` (delete obsolete test)

- [ ] **Step 1: Delete the obsolete test first** (TDD reverse: removing rejection is the spec change)

In `tradelab/tests/live/test_cards_create.py`, delete the entire `test_create_rejects_enabled_status` function (lines 39-44):

```python
def test_create_rejects_enabled_status(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    enabled = dict(DISABLED_CARD, status="enabled")
    with pytest.raises(ValueError, match="disabled"):
        reg.create("foo-v1", enabled)
```

- [ ] **Step 2: Run the test file to confirm only that test was removed**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_create.py -v
```

Expected: 3 tests pass (was 4), no failures, no collection errors.

- [ ] **Step 3: Drop the assertion in `cards.py`**

Replace `cards.py:94-112` (`create` method) with:

```python
    def create(self, card_id: str, data: dict) -> None:
        """Append a new card. Raises CardExistsError on duplicate."""
        with self._lock:
            if card_id in self._cards:
                raise CardExistsError(card_id)
            new_cards = dict(self._cards)
            new_cards[card_id] = data
            self._persist(new_cards)
            self._cards = new_cards
```

Also drop the now-misleading docstring sentence in the module docstring (`cards.py:6-7`):

```python
"""Card registry — JSON-backed, thread-safe for read.

One card = one immutable strategy version × one symbol. Live trade execution
is gated by card lookup + secret validation.
"""
```

- [ ] **Step 4: Run the full live tests**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/ -v
```

Expected: all green, count went down by 1.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add -p src/tradelab/live/cards.py tests/live/test_cards_create.py
git commit -m "$(cat <<'EOF'
refactor(live): drop Session 3a status='disabled' create guardrail

Slice 2 introduces the PATCH /tradelab/cards/<id> toggle which replaces
the create-time rejection. Cards are still created disabled by default
(Score → Accept never sets status='enabled'), but the registry no longer
enforces it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Switch `list_cards_view` to `copy.deepcopy` (carry-over)

**Files:**
- Modify: `tradelab/src/tradelab/web/cards_view.py:156-165`

The current shallow copy via `{**card, ...}` was safe for read-only Slice 1. Slice 2 mutations make aliasing the registry's in-memory cache a real bug.

- [ ] **Step 1: Write a regression test that proves aliasing risk**

Add to `tradelab/tests/web/test_cards_view.py` (file already exists):

```python
def test_list_cards_view_does_not_alias_registry_cache(tmp_path):
    """Mutating the view payload must NOT mutate the source cards dict."""
    from tradelab.web.cards_view import list_cards_view
    cards = {
        "foo-v1": {
            "card_id": "foo-v1", "symbol": "AAPL", "quantity": 5,
            "status": "enabled", "secret": "x" * 32,
            "nested": {"daily_limit": 5, "extra": [1, 2, 3]},
        }
    }
    alerts_log = tmp_path / "no_alerts.jsonl"

    view = list_cards_view(cards, alerts_log)

    # Mutate the enriched copy (both top-level and nested)
    enriched = view["groups"][0]["cards"][0]
    enriched["quantity"] = 999
    enriched["nested"]["daily_limit"] = 999

    # Source dict must be unchanged
    assert cards["foo-v1"]["quantity"] == 5
    assert cards["foo-v1"]["nested"]["daily_limit"] == 5
```

- [ ] **Step 2: Run it — expect failure on the nested assertion**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_view.py::test_list_cards_view_does_not_alias_registry_cache -v
```

Expected: FAIL on `assert cards["foo-v1"]["nested"]["daily_limit"] == 5` (gets 999 because of shallow copy on the nested dict).

- [ ] **Step 3: Switch to deepcopy**

In `cards_view.py`, add the import at the top:

```python
import copy
```

Replace the body of the `for cid, card in cards.items():` loop (lines 157-165) with:

```python
    enriched: dict[str, dict] = {}
    for cid, card in cards.items():
        copied = copy.deepcopy(card)
        copied["last_status"] = last_status.get(cid)
        copied["fires_24h"] = fires_24h.get(cid, 0)
        enriched[cid] = copied
```

Note: the NOTE comment block (lines 158-160) is removed entirely — its predicted concern is now resolved.

- [ ] **Step 4: Re-run**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_view.py -v
```

Expected: all green, including the new aliasing test.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add -p src/tradelab/web/cards_view.py tests/web/test_cards_view.py
git commit -m "$(cat <<'EOF'
fix(web): list_cards_view uses deepcopy to prevent registry aliasing

Slice 1 used a shallow {**card} spread which was safe while the view
was read-only. Slice 2's mutation endpoints make nested-dict aliasing
a real risk: a FE mutation on the response could silently mutate
CardRegistry's in-memory cache.

Adds a regression test that catches the aliasing via a nested dict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `CardRegistry.update` and `CardRegistry.delete`

**Files:**
- Create: `tradelab/tests/live/test_cards_mutations.py`
- Modify: `tradelab/src/tradelab/live/cards.py` (append two methods after `create`)

- [ ] **Step 1: Create the test file with failing `update` tests**

```python
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
```

- [ ] **Step 2: Run — expect failure**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py -v
```

Expected: collection succeeds, both tests fail with `AttributeError: 'CardRegistry' object has no attribute 'update'`.

- [ ] **Step 3: Implement `update`**

In `cards.py`, append after the `create` method (before `_persist`):

```python
    def update(self, card_id: str, fields: dict) -> None:
        """Merge `fields` into existing card. Raises KeyError if missing.

        Caller is responsible for validating field names and values
        (handler does this — registry trusts internal code).
        """
        with self._lock:
            if card_id not in self._cards:
                raise KeyError(card_id)
            new_cards = dict(self._cards)
            new_cards[card_id] = {**new_cards[card_id], **fields}
            self._persist(new_cards)
            self._cards = new_cards
```

- [ ] **Step 4: Run update tests — expect green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py::test_update_merges_fields_and_persists tests/live/test_cards_mutations.py::test_update_unknown_card_raises_keyerror -v
```

Expected: 2 passed.

- [ ] **Step 5: Add `delete` tests**

Append to `tests/live/test_cards_mutations.py`:

```python
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
```

- [ ] **Step 6: Run — expect failure**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py -v
```

Expected: 2 new fails for `delete`.

- [ ] **Step 7: Implement `delete`**

In `cards.py`, append after `update`:

```python
    def delete(self, card_id: str) -> None:
        """Remove `card_id`. Raises KeyError if missing."""
        with self._lock:
            if card_id not in self._cards:
                raise KeyError(card_id)
            new_cards = dict(self._cards)
            del new_cards[card_id]
            self._persist(new_cards)
            self._cards = new_cards
```

- [ ] **Step 8: Run — expect 4 passed**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py -v
```

- [ ] **Step 9: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/cards.py tests/live/test_cards_mutations.py
git commit -m "$(cat <<'EOF'
feat(live): CardRegistry.update + .delete with KeyError on missing

Both methods write through the existing atomic _persist() so the Slice 1
watchdog picks up the change and the receiver hot-reloads.

Validation lives in the handler (system boundary); the registry trusts
the caller to pass already-validated fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `CardRegistry.set_status` and `.set_quantity` convenience wrappers

**Files:**
- Modify: `tradelab/src/tradelab/live/cards.py` (append two methods)
- Modify: `tradelab/tests/live/test_cards_mutations.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/live/test_cards_mutations.py`:

```python
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
```

- [ ] **Step 2: Run — expect failure**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py::test_set_status_updates_in_place tests/live/test_cards_mutations.py::test_set_quantity_accepts_int_and_none -v
```

Expected: AttributeError on both.

- [ ] **Step 3: Implement convenience wrappers**

Append to `cards.py` after `delete`:

```python
    def set_status(self, card_id: str, status: str) -> None:
        """Convenience wrapper for the toggle case."""
        self.update(card_id, {"status": status})

    def set_quantity(self, card_id: str, quantity: int | None) -> None:
        """Convenience wrapper for inline-edit quantity."""
        self.update(card_id, {"quantity": quantity})
```

- [ ] **Step 4: Run — expect 6 total passed in test_cards_mutations.py**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_cards_mutations.py -v
```

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/cards.py tests/live/test_cards_mutations.py
git commit -m "$(cat <<'EOF'
feat(live): CardRegistry.set_status / .set_quantity convenience methods

Thin wrappers over update() — keep the handler readable and document
the two most common single-field mutations (toggle + qty edit).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: PATCH `/tradelab/cards/<id>` — handler + dispatcher

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `handle_patch_with_status` + validation helper)
- Modify: `tradelab/tests/web/test_cards_handlers.py` (add ~5 PATCH tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/web/test_cards_handlers.py`:

```python
def _seed_card(tmp_path: Path, monkeypatch, card_id: str, **fields) -> Path:
    """Test helper: write one-card cards.json + monkeypatch path."""
    cards_path = tmp_path / "cards.json"
    base = {
        "card_id": card_id, "secret": "x" * 32, "symbol": "AAPL",
        "status": "disabled", "quantity": 1,
    }
    base.update(fields)
    cards_path.write_text(json.dumps({card_id: base}), encoding="utf-8")
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")
    return cards_path


def test_patch_card_updates_status(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"status": "enabled"}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"error": None, "data": {"updated": "foo-v1"}}
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["status"] == "enabled"


def test_patch_card_404_when_missing(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/no-such-card",
        json.dumps({"status": "enabled"}).encode(),
    )
    assert status == 404
    assert json.loads(body)["error"] == "card not found"


def test_patch_card_rejects_unknown_field(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"secret": "new-secret", "status": "enabled"}).encode(),
    )
    assert status == 400
    assert "unknown field" in json.loads(body)["error"]


def test_patch_card_rejects_invalid_status(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"status": "garbage"}).encode(),
    )
    assert status == 400


def test_patch_card_rejects_negative_quantity(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"quantity": -1}).encode(),
    )
    assert status == 400


def test_patch_card_accepts_null_quantity(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1", quantity=5)
    body, status = handlers.handle_patch_with_status(
        "/tradelab/cards/foo-v1",
        json.dumps({"quantity": None}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["quantity"] is None
```

- [ ] **Step 2: Run — expect collection error or AttributeError**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py -v -k patch
```

Expected: 6 fails on `AttributeError: module 'tradelab.web.handlers' has no attribute 'handle_patch_with_status'`.

- [ ] **Step 3: Implement validation + handler**

Add to `handlers.py` near the other validation helpers (around `_validate_score_payload`):

```python
_ALLOWED_PATCH_FIELDS = {
    "status", "quantity", "cadence", "daily_limit",
    "cooldown_seconds", "allow_collision", "allow_naked_short",
}
_ALLOWED_STATUSES = {"enabled", "disabled"}
_ALLOWED_CADENCES = {"intraday", "daily", "weekly", "manual"}


def _validate_patch_card_payload(payload: dict) -> Optional[str]:
    """Returns error message string or None if valid."""
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    if not payload:
        return "no fields to update"
    unknown = set(payload.keys()) - _ALLOWED_PATCH_FIELDS
    if unknown:
        return f"unknown field: {sorted(unknown)[0]}"

    if "status" in payload and payload["status"] not in _ALLOWED_STATUSES:
        return f"status must be one of {sorted(_ALLOWED_STATUSES)}"
    if "quantity" in payload:
        q = payload["quantity"]
        if q is not None and (not isinstance(q, int) or isinstance(q, bool) or q < 1):
            return "quantity must be a positive int or null"
    if "cadence" in payload and payload["cadence"] not in _ALLOWED_CADENCES:
        return f"cadence must be one of {sorted(_ALLOWED_CADENCES)}"
    for k in ("daily_limit", "cooldown_seconds"):
        if k in payload:
            v = payload[k]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                return f"{k} must be a non-negative int"
    for k in ("allow_collision", "allow_naked_short"):
        if k in payload and not isinstance(payload[k], bool):
            return f"{k} must be a bool"
    return None
```

Then add the dispatcher (after `handle_post_with_status`):

```python
def handle_patch_with_status(path: str, body: bytes) -> Tuple[str, int]:
    """PATCH dispatcher with explicit status."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    m = re.match(r"^/tradelab/cards/([^/]+)$", path)
    if m:
        card_id = m.group(1)
        err = _validate_patch_card_payload(payload)
        if err:
            return _err(err), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("card not found"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        try:
            reg.update(card_id, payload)
        except KeyError:
            return _err("card not found"), 404
        return _ok({"updated": card_id}), 200

    return _err("not found"), 404
```

- [ ] **Step 4: Run PATCH tests — expect all green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py -v -k patch
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): PATCH /tradelab/cards/<id> with field allowlist + validation

Validation rejects unknown fields and bad values at the handler boundary
before touching the registry. CardRegistry.update is internal and trusts
the caller — single source of truth for what's mutable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire `do_PATCH` in `launch_dashboard.py`

**Files:**
- Modify: `C:/TradingScripts/launch_dashboard.py` (parent repo)

The parent repo's `BaseHTTPRequestHandler` doesn't dispatch PATCH out of the box. Add `do_PATCH` mirroring the existing `do_DELETE` (lines 119-152).

- [ ] **Step 1: Add `do_PATCH` method**

In `launch_dashboard.py`, after `do_DELETE` (line 152), add:

```python
    def do_PATCH(self):
        """Dispatch PATCH requests to the tradelab handler."""
        try:
            path = urlparse(self.path).path

            if not path.startswith("/tradelab/"):
                self._write_json(404, json.dumps({"error": "not found", "data": None}).encode())
                return

            if _handlers is None:
                self._write_json(503, json.dumps(
                    {"error": f"research offline: {_handlers_error}", "data": None}
                ).encode())
                return

            length = int(self.headers.get("Content-Length", 0))
            body_in = self.rfile.read(length) if length else b""

            try:
                body, status = _handlers.handle_patch_with_status(path, body_in)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._write_json(500, json.dumps(
                    {"error": f"server error: {type(e).__name__}", "data": None}
                ).encode())
                return

            self._write_json(status, body.encode() if body else b"")
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
```

- [ ] **Step 2: Restart dashboard and smoke-test PATCH against a real card**

Kill+restart pattern from Slice 1 smoke:

```bash
# Find dashboard PID
netstat -ano | grep "LISTENING.*8877"
# Kill it (replace <PID> with the listening PID)
powershell -Command "Stop-Process -Id <PID> -Force"
# Restart
cd C:/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py &
sleep 2
# Smoke
curl -s -X PATCH -d '{"quantity": 2}' http://127.0.0.1:8877/tradelab/cards/test-amzn-v1
```

Expected: `{"error": null, "data": {"updated": "test-amzn-v1"}}`. Then PATCH it back: `curl -s -X PATCH -d '{"quantity": 1}' http://127.0.0.1:8877/tradelab/cards/test-amzn-v1` to restore.

- [ ] **Step 3: Confirm receiver hot-reloaded**

```bash
curl -s http://127.0.0.1:8878/health
```

Expected: `cards_loaded` unchanged (3), but receiver log shows `cards.json reloaded; cards_loaded=3`. The atomic os.replace fired the watcher.

- [ ] **Step 4: Commit (parent repo, local-only)**

```bash
cd C:/TradingScripts && git add launch_dashboard.py
git commit -m "$(cat <<'EOF'
feat(launcher): do_PATCH dispatches to /tradelab/* handlers

Mirrors do_DELETE shape. Required for Slice 2 PATCH /tradelab/cards/<id>
which the FE will call from the toggle button + inline-edit quantity.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: DELETE `/tradelab/cards/<id>` with confirm

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` (extend `handle_delete_with_status`)
- Modify: `tradelab/tests/web/test_cards_handlers.py` (add 3 tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/web/test_cards_handlers.py`:

```python
def test_delete_card_removes_with_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/foo-v1",
        json.dumps({"confirm": "DELETE"}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "foo-v1" not in on_disk


def test_delete_card_rejects_without_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/foo-v1",
        json.dumps({}).encode(),
    )
    assert status == 400
    assert "confirm" in json.loads(body)["error"]
    # Card still on disk
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "foo-v1" in on_disk


def test_delete_card_404_when_missing(tmp_path: Path, monkeypatch):
    _seed_card(tmp_path, monkeypatch, "foo-v1")
    body, status = handlers.handle_delete_with_status_with_body(
        "/tradelab/cards/no-such-card",
        json.dumps({"confirm": "DELETE"}).encode(),
    )
    assert status == 404
```

- [ ] **Step 2: Run — expect 3 fails on AttributeError or routing 404**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py -v -k "delete_card"
```

- [ ] **Step 3: Add a body-aware DELETE dispatcher**

The existing `handle_delete_with_status` (handlers.py:798) takes only `path`, no body. Cards-delete needs body for the confirm token. Extend with a sibling:

```python
def handle_delete_with_status_with_body(path: str, body: bytes) -> Tuple[str, int]:
    """DELETE dispatcher that also accepts a body. Routes that need body
    confirmation (cards) call this; legacy DELETE (runs) keep using
    handle_delete_with_status."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    m = re.match(r"^/tradelab/cards/([^/]+)$", path)
    if m:
        card_id = m.group(1)
        if payload.get("confirm") != "DELETE":
            return _err("missing confirm: 'DELETE' to delete card"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("card not found"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        try:
            reg.delete(card_id)
        except KeyError:
            return _err("card not found"), 404
        return _ok({"deleted": card_id}), 200

    # Fall through to body-less variant for legacy routes
    return handle_delete_with_status(path)
```

- [ ] **Step 4: Update `launch_dashboard.py:do_DELETE` to read body and call the new dispatcher**

Replace lines 134-135 in `launch_dashboard.py`:

```python
            try:
                length = int(self.headers.get("Content-Length", 0))
                body_in = self.rfile.read(length) if length else b""
                body, status = _handlers.handle_delete_with_status_with_body(path, body_in)
```

(Falls through to the legacy run-archive path when no body and no card match.)

- [ ] **Step 5: Run delete tests + the existing run delete tests to confirm no regression**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py tests/web/test_runs_delete.py -v
```

Expected: all green. The legacy `test_runs_delete.py` calls `handle_delete_with_status` directly (no body), still works because that function is untouched.

- [ ] **Step 6: Commit (both repos)**

```bash
# Tradelab repo
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): DELETE /tradelab/cards/<id> with confirm:'DELETE' gate

Adds handle_delete_with_status_with_body so DELETE routes can require
a typed-confirm body. Legacy run-delete keeps using the bodyless
handle_delete_with_status (no behavior change for tests/runs_delete).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

# Parent repo
cd C:/TradingScripts && git add launch_dashboard.py
git commit -m "$(cat <<'EOF'
feat(launcher): do_DELETE reads body and forwards to body-aware dispatcher

Falls through to legacy bodyless behavior for /tradelab/runs/<id>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: POST `/tradelab/cards/bulk-toggle` and `/tradelab/cards/bulk-delete`

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` (add to `handle_post_with_status`)
- Modify: `tradelab/tests/web/test_cards_handlers.py` (add 4 tests)

- [ ] **Step 1: Failing tests**

Append to `tests/web/test_cards_handlers.py`:

```python
def _seed_n_cards(tmp_path, monkeypatch, ids):
    cards_path = tmp_path / "cards.json"
    cards = {
        cid: {"card_id": cid, "secret": "x" * 32, "symbol": "AAPL",
              "status": "disabled", "quantity": 1}
        for cid in ids
    }
    cards_path.write_text(json.dumps(cards), encoding="utf-8")
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_alerts_log_path", lambda: tmp_path / "no_alerts.jsonl")
    return cards_path


def test_bulk_toggle_enables_all(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1", "b-v1", "c-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-toggle",
        json.dumps({"ids": ["a-v1", "b-v1", "c-v1"], "status": "enabled"}).encode(),
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload == {"updated": ["a-v1", "b-v1", "c-v1"], "failed": []}
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert all(on_disk[cid]["status"] == "enabled" for cid in ["a-v1", "b-v1", "c-v1"])


def test_bulk_toggle_reports_failed_ids(tmp_path: Path, monkeypatch):
    _seed_n_cards(tmp_path, monkeypatch, ["a-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-toggle",
        json.dumps({"ids": ["a-v1", "ghost-v1"], "status": "enabled"}).encode(),
    )
    assert status == 200
    payload = json.loads(body)["data"]
    assert payload["updated"] == ["a-v1"]
    assert payload["failed"] == [{"id": "ghost-v1", "reason": "card not found"}]


def test_bulk_delete_removes_with_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1", "b-v1", "c-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-delete",
        json.dumps({"ids": ["a-v1", "b-v1"], "confirm": "DELETE"}).encode(),
    )
    assert status == 200
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert set(on_disk.keys()) == {"c-v1"}


def test_bulk_delete_rejects_without_confirm(tmp_path: Path, monkeypatch):
    cards_path = _seed_n_cards(tmp_path, monkeypatch, ["a-v1"])
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-delete",
        json.dumps({"ids": ["a-v1"]}).encode(),
    )
    assert status == 400
    on_disk = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    assert "a-v1" in on_disk  # untouched
```

- [ ] **Step 2: Run — expect 4 fails (404 not found from dispatcher)**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py -v -k bulk
```

- [ ] **Step 3: Implement bulk routes**

In `handlers.py`, inside `handle_post_with_status` (BEFORE the trailing `return _err("not found"), 404`-equivalent), add:

```python
    if path == "/tradelab/cards/bulk-toggle":
        ids = payload.get("ids")
        status_val = payload.get("status")
        if not isinstance(ids, list) or not ids:
            return _err("ids must be a non-empty list"), 400
        if status_val not in _ALLOWED_STATUSES:
            return _err(f"status must be one of {sorted(_ALLOWED_STATUSES)}"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("no cards.json"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        updated: list[str] = []
        failed: list[dict] = []
        for cid in ids:
            try:
                reg.set_status(str(cid), status_val)
                updated.append(str(cid))
            except KeyError:
                failed.append({"id": str(cid), "reason": "card not found"})
        return _ok({"updated": updated, "failed": failed}), 200

    if path == "/tradelab/cards/bulk-delete":
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids:
            return _err("ids must be a non-empty list"), 400
        if payload.get("confirm") != "DELETE":
            return _err("missing confirm: 'DELETE' to bulk-delete cards"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("no cards.json"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        deleted: list[str] = []
        failed: list[dict] = []
        for cid in ids:
            try:
                reg.delete(str(cid))
                deleted.append(str(cid))
            except KeyError:
                failed.append({"id": str(cid), "reason": "card not found"})
        return _ok({"deleted": deleted, "failed": failed}), 200
```

- [ ] **Step 4: Run — 4 passed**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_cards_handlers.py -v
```

Expected: ALL cards_handlers tests pass (~17 total now).

- [ ] **Step 5: Run full backend suite to confirm no regression**

```bash
cd C:/TradingScripts/tradelab && python -m pytest 2>&1 | tail -3
```

Expected: ~459-462 passed (449 + ~12 new − 1 deleted).

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_cards_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): POST /tradelab/cards/bulk-{toggle,delete}

Both report per-id success/failure so the FE can show partial-failure
banners. bulk-delete requires confirm:'DELETE' gate (matches single
DELETE).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: FE — checkbox column in row + group header

**Files:**
- Modify: `C:/TradingScripts/command_center.html` (Live Trading row template + group header)

The `.lt-row` grid already starts with a `24px` empty span (line 4282). Repurpose it as a checkbox cell. Group headers get a "select all in group" checkbox.

- [ ] **Step 1: Update `renderRow` to emit checkbox**

In `command_center.html`, replace `renderRow` (lines 4277-4295) with:

```javascript
      function renderRow(card) {
        const statusCls = card.status === 'enabled' ? 'enabled' : 'disabled';
        const lastStatusKey = card.last_status || 'none';
        return `
          <div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}">
            <span><input type="checkbox" class="lt-row-check" data-card-id="${escHtml(card.card_id)}"></span>
            <span>${escHtml(card.card_id)}</span>
            <span class="lt-pill lt-pill--${statusCls}">${escHtml(card.status)}</span>
            <span>${escHtml(card.symbol)}</span>
            <span class="lt-qty" data-card-id="${escHtml(card.card_id)}" data-qty="${card.quantity == null ? '' : escHtml(card.quantity)}">${card.quantity == null ? '—' : escHtml(card.quantity)}</span>
            <span>${escHtml(card.cadence || 'daily')}</span>
            <span>${fmtRelative(card.last_fired_at)}</span>
            <span class="lt-laststatus--${escHtml(lastStatusKey)}">
              ${card.last_status ? escHtml(card.last_status) : '—'}
            </span>
            <span>${card.fires_24h ?? 0}</span>
          </div>
        `;
      }
```

(Quantity span gets the `lt-qty` class + `data-qty` for Task 11. Other columns unchanged.)

- [ ] **Step 2: Add row-checkbox styling**

In the `<style>` block, after `.lt-row--disabled { opacity: 0.65; }` (line 427), add:

```css
    .lt-row-check { cursor: pointer; }
```

(No new column structure — the 24px span already accommodated this.)

- [ ] **Step 3: Reload the dashboard and visually confirm checkboxes render**

Restart dashboard (kill+relaunch), open browser to `http://127.0.0.1:8877/#tab=live-trading`, confirm each row has a checkbox in the leftmost column. Click one — should toggle without errors in the JS console.

- [ ] **Step 4: Commit (parent repo)**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "$(cat <<'EOF'
ui(command-center): add per-row checkboxes for bulk select

Repurposes the leading 24px slot in .lt-row (was empty span). Wires
data-card-id so the bulk handler in Task 14 can collect selections.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: FE — per-row toggle button + delete (trash) button

**Files:**
- Modify: `command_center.html` (extend `renderRow`, add CSS)

Adds two action buttons to the right side of each row. The grid template needs to widen to accommodate.

- [ ] **Step 1: Update grid template**

Change `.lt-row` grid (line 419) to add two trailing slots for the action buttons:

```css
    .lt-row {
      display: grid;
      grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px 80px 30px;
      gap: 10px; align-items: center;
      padding: 8px 14px;
      border-top: 1px solid #1c2330;
      font-size: 0.9em;
    }
```

(Two new columns: 80px for the toggle button, 30px for the trash button.)

- [ ] **Step 2: Add button styling**

Append to the styles block:

```css
    .lt-action-btn {
      background: transparent; border: 1px solid #2a3140; color: #c8d3e0;
      padding: 3px 8px; border-radius: 4px; font-size: 0.8em; cursor: pointer;
    }
    .lt-action-btn:hover { border-color: #3dd68c; color: #3dd68c; }
    .lt-action-btn--enable  { border-color: #2a5040; color: #3dd68c; }
    .lt-action-btn--disable { border-color: #5a4a1c; color: #ffe9a0; }
    .lt-trash-btn {
      background: transparent; border: none; color: #6b7684;
      cursor: pointer; font-size: 1.0em; padding: 0;
    }
    .lt-trash-btn:hover { color: #ff6b6b; }
```

- [ ] **Step 3: Update `renderRow` to emit the two buttons**

Replace the closing `</div>` (last span before close in `renderRow`) so the function body becomes:

```javascript
      function renderRow(card) {
        const statusCls = card.status === 'enabled' ? 'enabled' : 'disabled';
        const lastStatusKey = card.last_status || 'none';
        const toggleLabel = card.status === 'enabled' ? 'Disable' : 'Enable';
        const toggleCls = card.status === 'enabled' ? 'lt-action-btn--disable' : 'lt-action-btn--enable';
        return `
          <div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}">
            <span><input type="checkbox" class="lt-row-check" data-card-id="${escHtml(card.card_id)}"></span>
            <span>${escHtml(card.card_id)}</span>
            <span class="lt-pill lt-pill--${statusCls}">${escHtml(card.status)}</span>
            <span>${escHtml(card.symbol)}</span>
            <span class="lt-qty" data-card-id="${escHtml(card.card_id)}" data-qty="${card.quantity == null ? '' : escHtml(card.quantity)}">${card.quantity == null ? '—' : escHtml(card.quantity)}</span>
            <span>${escHtml(card.cadence || 'daily')}</span>
            <span>${fmtRelative(card.last_fired_at)}</span>
            <span class="lt-laststatus--${escHtml(lastStatusKey)}">
              ${card.last_status ? escHtml(card.last_status) : '—'}
            </span>
            <span>${card.fires_24h ?? 0}</span>
            <span><button class="lt-action-btn ${toggleCls}" data-action="toggle" data-card-id="${escHtml(card.card_id)}" data-current-status="${escHtml(card.status)}">${toggleLabel}</button></span>
            <span><button class="lt-trash-btn" data-action="delete" data-card-id="${escHtml(card.card_id)}" title="Delete card">🗑</button></span>
          </div>
        `;
      }
```

- [ ] **Step 4: Reload + visual smoke**

Reload dashboard, confirm Toggle button + trash icon render per row. Buttons don't do anything yet — that's Task 11.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "$(cat <<'EOF'
ui(command-center): add per-row toggle + trash buttons (no-op yet)

Wiring lands in the next task. Grid widens by two trailing columns
(80px toggle, 30px trash icon).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: FE — wire toggle button to PATCH and inline-edit quantity

**Files:**
- Modify: `command_center.html` (add event delegation in LT module)

Single delegated click handler on the cards list — no per-row listeners. Inline-edit quantity follows the click→input→Enter/blur→PATCH→Esc-cancel pattern.

- [ ] **Step 1: Add the PATCH helper + event handlers**

Inside the `LT` IIFE, after `bindDisclosureToggles` (around line 4340), add:

```javascript
      async function patchCard(cardId, fields) {
        const resp = await fetch(`/tradelab/cards/${encodeURIComponent(cardId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fields),
        });
        const json = await resp.json().catch(() => ({ error: 'bad response' }));
        if (!resp.ok || json.error) {
          throw new Error(json.error || `HTTP ${resp.status}`);
        }
        return json.data;
      }

      function bindRowActions() {
        $list().addEventListener('click', async (ev) => {
          const btn = ev.target.closest('[data-action]');
          if (!btn) return;
          const action = btn.dataset.action;
          const cardId = btn.dataset.cardId;

          if (action === 'toggle') {
            const current = btn.dataset.currentStatus;
            const next = current === 'enabled' ? 'disabled' : 'enabled';
            try {
              await patchCard(cardId, { status: next });
              await fetchAndRender();
            } catch (e) {
              toast(`Toggle failed: ${e.message}`, 'error');
            }
          } else if (action === 'delete') {
            openDeleteModal([cardId]);  // single-card uses bulk modal w/ one id
          }
        });
      }

      function bindQuantityEdit() {
        $list().addEventListener('click', (ev) => {
          const span = ev.target.closest('.lt-qty');
          if (!span || span.querySelector('input')) return;
          const cardId = span.dataset.cardId;
          const current = span.dataset.qty;  // empty string = null
          const input = document.createElement('input');
          input.type = 'number';
          input.min = '1';
          input.value = current;
          input.style.cssText = 'width: 60px; background: var(--card); color: var(--text); border: 1px solid var(--border); padding: 2px 4px;';
          span.textContent = '';
          span.appendChild(input);
          input.focus();
          input.select();

          let cancelled = false;
          input.addEventListener('keydown', (kev) => {
            if (kev.key === 'Escape') {
              cancelled = true;
              span.textContent = current === '' ? '—' : current;
              input.remove();
            } else if (kev.key === 'Enter') {
              input.blur();
            }
          });
          input.addEventListener('blur', async () => {
            if (cancelled) return;
            const raw = input.value.trim();
            const next = raw === '' ? null : parseInt(raw, 10);
            if (next !== null && (!Number.isFinite(next) || next < 1)) {
              toast('Quantity must be a positive integer or empty (=card default)', 'error');
              span.textContent = current === '' ? '—' : current;
              return;
            }
            try {
              await patchCard(cardId, { quantity: next });
              await fetchAndRender();
            } catch (e) {
              toast(`Quantity update failed: ${e.message}`, 'error');
              span.textContent = current === '' ? '—' : current;
            }
          });
        });
      }
```

- [ ] **Step 2: Call the new binders inside `fetchAndRender` after `bindDisclosureToggles()`**

Edit `fetchAndRender` (line 4342) — replace its inner `try` block:

```javascript
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
          // Note: bindRowActions and bindQuantityEdit attach to $list() once;
          // they survive innerHTML re-renders because the listener is on the
          // PARENT (not the children).
        } catch (err) {
          $list().innerHTML = `<p class="lt-loading">Failed to load: ${escHtml(err.message)}</p>`;
        }
      }
```

And update `activate` (line 4389):

```javascript
      function activate() {
        bindRowActions();
        bindQuantityEdit();
        fetchAndRender();
        refreshStatusChips();
        startStatusPolling();
      }
```

- [ ] **Step 3: Add `openDeleteModal` placeholder** (real impl in Task 12)

Just above `bindRowActions`, add:

```javascript
      let _pendingDelete = [];
      function openDeleteModal(ids) {
        _pendingDelete = ids.slice();
        // Real modal lands in Task 12; for now, log + abort safely.
        console.warn('Delete modal not yet implemented for ids:', ids);
        toast('Delete UI coming in Task 12', 'warn');
      }
```

- [ ] **Step 4: Reload + smoke**

Reload dashboard. Click a Toggle button on a disabled row → it flips to enabled, the row re-renders enabled, the receiver log shows hot-reload. Click the qty span on a row → input appears with current value selected → type a new number → Enter → row refreshes with new qty. Hit Esc on another row → reverts. Click trash → console warning + toast (placeholder).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): wire toggle + inline-edit quantity to PATCH

Single delegated click handler on lt-cards-list — survives innerHTML
re-renders because the listener is on the parent. Quantity edit
follows the click→input→Enter/blur→PATCH (Esc cancels) pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: FE — delete confirmation modal (per-row + bulk path)

**Files:**
- Modify: `command_center.html` (add modal markup + replace `openDeleteModal` placeholder)

Single modal handles both single-card delete and bulk-delete. When ≥7 cards selected, requires the user to type `DELETE` in an input.

- [ ] **Step 1: Add modal markup**

Inside the Live Trading tab content (after `<div id="lt-cards-list" ...>`, line 928), append:

```html
      <!-- Delete confirm modal -->
      <div class="dialog" id="ltDeleteDialog" hidden>
        <div class="dialog-box">
          <div class="dialog-title">Delete card<span id="ltDeleteCountSuffix"></span>?</div>
          <div class="dialog-message" id="ltDeleteMessage">This is permanent. Are you sure?</div>
          <div id="ltDeleteTypeGate" hidden style="margin-top: 10px;">
            <label style="font-size: 12px; color: #9aa5b1;">Type <code>DELETE</code> to confirm:</label>
            <input id="ltDeleteTypeInput" type="text" style="margin-top: 4px; width: 100%; padding: 6px; background: var(--card); color: var(--text); border: 1px solid var(--border);">
          </div>
          <div class="dialog-buttons">
            <button class="btn" id="ltDeleteCancel">Cancel</button>
            <button class="btn danger" id="ltDeleteConfirm" disabled>Delete</button>
          </div>
        </div>
      </div>
```

(Reuses the existing `.dialog` / `.dialog-box` / `.dialog-buttons` / `.btn.danger` classes from the Flatten dialog at line 937.)

- [ ] **Step 2: Replace the `openDeleteModal` placeholder with the real implementation**

Inside the LT module (replace the placeholder from Task 11):

```javascript
      const TYPE_GATE_THRESHOLD = 7;

      function openDeleteModal(ids) {
        _pendingDelete = ids.slice();
        const dialog = document.getElementById('ltDeleteDialog');
        const suffix = document.getElementById('ltDeleteCountSuffix');
        const msg = document.getElementById('ltDeleteMessage');
        const gate = document.getElementById('ltDeleteTypeGate');
        const gateInput = document.getElementById('ltDeleteTypeInput');
        const confirmBtn = document.getElementById('ltDeleteConfirm');

        if (ids.length === 1) {
          suffix.textContent = '';
          msg.textContent = `Permanently delete '${ids[0]}'? This cannot be undone.`;
        } else {
          suffix.textContent = `s (${ids.length})`;
          msg.textContent = `Permanently delete ${ids.length} cards? This cannot be undone.`;
        }

        if (ids.length >= TYPE_GATE_THRESHOLD) {
          gate.hidden = false;
          gateInput.value = '';
          confirmBtn.disabled = true;
          gateInput.oninput = () => {
            confirmBtn.disabled = (gateInput.value !== 'DELETE');
          };
        } else {
          gate.hidden = true;
          confirmBtn.disabled = false;
        }

        dialog.hidden = false;
      }

      function closeDeleteModal() {
        document.getElementById('ltDeleteDialog').hidden = true;
        _pendingDelete = [];
      }

      async function performDelete() {
        const ids = _pendingDelete.slice();
        if (ids.length === 0) return;
        try {
          if (ids.length === 1) {
            const resp = await fetch(`/tradelab/cards/${encodeURIComponent(ids[0])}`, {
              method: 'DELETE',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ confirm: 'DELETE' }),
            });
            const json = await resp.json();
            if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
          } else {
            const resp = await fetch('/tradelab/cards/bulk-delete', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ids, confirm: 'DELETE' }),
            });
            const json = await resp.json();
            if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
            const failed = json.data?.failed || [];
            if (failed.length > 0) {
              toast(`Deleted ${json.data.deleted.length}; failed ${failed.length}`, 'warn');
            }
          }
          closeDeleteModal();
          await fetchAndRender();
        } catch (e) {
          toast(`Delete failed: ${e.message}`, 'error');
        }
      }

      function bindDeleteModal() {
        document.getElementById('ltDeleteCancel').addEventListener('click', closeDeleteModal);
        document.getElementById('ltDeleteConfirm').addEventListener('click', performDelete);
      }
```

Wire the bind in `activate`:

```javascript
      function activate() {
        bindRowActions();
        bindQuantityEdit();
        bindDeleteModal();
        fetchAndRender();
        refreshStatusChips();
        startStatusPolling();
      }
```

- [ ] **Step 3: Reload + smoke**

Add a `disabled` test card via direct cards.json edit (or via a previous Score→Accept). Click trash on the row. Modal opens with single-card text. Cancel works. Confirm actually deletes (and the row disappears).

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): delete-card confirmation modal

Single modal serves both per-row and bulk paths. Requires typed
'DELETE' confirmation when ids.length >= 7. Reuses existing .dialog
styling.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: FE — bulk action strip (Enable / Disable / Delete Selected)

**Files:**
- Modify: `command_center.html` (add bulk strip markup + handlers)

The strip shows up when ≥1 row is checked. Clicking Enable/Disable calls bulk-toggle; clicking Delete opens the modal with all selected ids.

- [ ] **Step 1: Add bulk strip markup + styling**

After the `<div class="lt-status-strip">` block (line 925), insert before `<div id="lt-cards-list" ...>`:

```html
      <div id="lt-bulk-strip" class="lt-bulk-strip" hidden>
        <span id="lt-bulk-count">0 selected</span>
        <button class="btn" data-bulk-action="enable">Enable Selected</button>
        <button class="btn" data-bulk-action="disable">Disable Selected</button>
        <button class="btn danger" data-bulk-action="delete">Delete Selected</button>
        <button class="btn" data-bulk-action="clear" style="margin-left:auto">Clear</button>
      </div>
```

Add styling:

```css
    .lt-bulk-strip {
      display: flex; gap: 10px; align-items: center;
      padding: 8px 16px; background: #1c2330;
      border-bottom: 1px solid #2a3140; font-size: 0.9em;
    }
    .lt-bulk-strip[hidden] { display: none; }
    #lt-bulk-count { color: #c8d3e0; margin-right: 8px; }
```

- [ ] **Step 2: Wire selection tracking + bulk actions**

Inside the LT module, after `bindDeleteModal`:

```javascript
      function getSelectedIds() {
        return Array.from($list().querySelectorAll('.lt-row-check:checked'))
          .map(cb => cb.dataset.cardId);
      }

      function refreshBulkStrip() {
        const ids = getSelectedIds();
        const strip = document.getElementById('lt-bulk-strip');
        const count = document.getElementById('lt-bulk-count');
        if (ids.length === 0) {
          strip.hidden = true;
        } else {
          strip.hidden = false;
          count.textContent = `${ids.length} selected`;
        }
      }

      function bindBulkSelection() {
        $list().addEventListener('change', (ev) => {
          if (ev.target.classList.contains('lt-row-check')) {
            refreshBulkStrip();
          }
        });
      }

      async function bulkToggle(statusVal) {
        const ids = getSelectedIds();
        if (ids.length === 0) return;
        try {
          const resp = await fetch('/tradelab/cards/bulk-toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids, status: statusVal }),
          });
          const json = await resp.json();
          if (!resp.ok || json.error) throw new Error(json.error || `HTTP ${resp.status}`);
          const failed = json.data?.failed || [];
          if (failed.length > 0) {
            toast(`Updated ${json.data.updated.length}; failed ${failed.length}`, 'warn');
          }
          await fetchAndRender();
          refreshBulkStrip();
        } catch (e) {
          toast(`Bulk ${statusVal} failed: ${e.message}`, 'error');
        }
      }

      function bindBulkStrip() {
        document.getElementById('lt-bulk-strip').addEventListener('click', (ev) => {
          const btn = ev.target.closest('[data-bulk-action]');
          if (!btn) return;
          const action = btn.dataset.bulkAction;
          if (action === 'enable')      bulkToggle('enabled');
          else if (action === 'disable') bulkToggle('disabled');
          else if (action === 'delete')  openDeleteModal(getSelectedIds());
          else if (action === 'clear') {
            $list().querySelectorAll('.lt-row-check').forEach(cb => { cb.checked = false; });
            refreshBulkStrip();
          }
        });
      }
```

Update `activate`:

```javascript
      function activate() {
        bindRowActions();
        bindQuantityEdit();
        bindDeleteModal();
        bindBulkSelection();
        bindBulkStrip();
        fetchAndRender();
        refreshStatusChips();
        startStatusPolling();
      }
```

- [ ] **Step 3: Reload + smoke**

- Check 2 rows → strip appears showing "2 selected"
- Click "Disable Selected" → both rows flip to disabled, strip hides (selections clear after re-render)
- Check 7 rows → click "Delete Selected" → modal opens with type-DELETE gate; type DELETE → button enables → confirm → all gone

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): bulk action strip (enable/disable/delete selected)

Appears when >=1 row checked. Bulk delete reuses the per-row modal
which auto-applies the type-DELETE gate at >=7 ids.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Final smoke checklist + Slice 2 done doc

**Files:**
- Create: `C:/TradingScripts/2026-04-25-DIRECTION-A-SLICE-2-COMPLETE.md`

- [ ] **Step 1: Run the full backend suite one more time**

```bash
cd C:/TradingScripts/tradelab && python -m pytest 2>&1 | tail -3
```

Expected: ~462 passed (449 baseline + 6 mutations + 6 PATCH + 4 bulk + 3 delete + 1 deepcopy − 1 deleted-guardrail-test = 468; numbers may vary by 1-2 if any helper test consolidates).

- [ ] **Step 2: End-to-end manual smoke (user runs through these in the browser)**

- [ ] Toggle a disabled card to enabled via per-row button → row flips, receiver log shows `cards.json reloaded`
- [ ] Edit quantity inline (click number → input → Enter) → row updates, hits PATCH, receiver hot-reloads
- [ ] Press Esc during quantity edit → reverts to original, no PATCH fired
- [ ] Click trash on one card → modal opens with single-card text → confirm → card disappears
- [ ] Check 3 rows → bulk strip shows "3 selected" → "Disable Selected" → all 3 flip
- [ ] Check 8 rows → "Delete Selected" → modal shows type-DELETE input → confirm only enables after typing → confirm → all gone
- [ ] After every mutation, `curl http://127.0.0.1:8878/health` returns updated `cards_loaded`

- [ ] **Step 3: Write the done doc**

Create `C:/TradingScripts/2026-04-25-DIRECTION-A-SLICE-2-COMPLETE.md` mirroring the Slice 1 done doc structure:

```markdown
# Direction A Slice 2 — Complete & Handoff

**Date:** 2026-04-25
**Spec:** `tradelab/docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md`
**Plan:** `tradelab/docs/superpowers/plans/2026-04-25-direction-a-slice-2-mutations.md`

## What shipped
- PATCH /tradelab/cards/<id> with field allowlist + per-field validation
- DELETE /tradelab/cards/<id> with confirm:'DELETE' gate
- POST /tradelab/cards/bulk-toggle and bulk-delete (with per-id failure reporting)
- CardRegistry.update / .delete / .set_status / .set_quantity (atomic _persist → watcher fires)
- FE: per-row checkbox + toggle button + trash icon + inline-edit quantity (click/Enter/Esc)
- FE: bulk action strip (Enable / Disable / Delete Selected) with type-DELETE gate at >=7 ids
- FE: shared delete confirmation modal for per-row and bulk paths
- Carry-over: dropped Session 3a status='disabled' guardrail; switched list_cards_view to deepcopy

## Verified manually
[ ] Toggle works (per-row)
[ ] Inline-edit quantity persists across hot-reload
[ ] Single-card delete with confirm
[ ] Bulk-toggle (>=2 rows)
[ ] Bulk-delete with type-DELETE gate (>=7 rows)

## Pytest baseline
~462 passed (was 449)

## Known limitations (intentional - Slice 3+)
- No per-card overrides UI for guardrails — Slice 3
- No notification system — Slice 4
- No silence detection — Slice 5
- No panic panel — Slice 6

## Handoff for Slice 3
Slice 3 = position guardrails. Per spec section 5:
- 5 guardrails ON by default (no overlap, no naked short, daily limit, cooldown, fresh-data)
- Per-card overrides UI in expanded row drawer
- Pre-trade check pipeline in receiver
```

Then commit it (parent repo, local-only):

```bash
cd C:/TradingScripts && git add 2026-04-25-DIRECTION-A-SLICE-2-COMPLETE.md
git commit -m "$(cat <<'EOF'
docs: Slice 2 complete & handoff for Slice 3 (guardrails)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Tell Amit**

Message verbatim:

> Slice 2 complete. Smoke-test the mutation flows (checklist in `2026-04-25-DIRECTION-A-SLICE-2-COMPLETE.md`), then say go for Slice 3 (guardrails).

---

## Self-review checklist (run before declaring plan done)

- [ ] All 7 PATCH-allowed fields appear in `_validate_patch_card_payload` (Task 5) AND in the table at top
- [ ] CardRegistry method names consistent: `update`, `delete`, `set_status`, `set_quantity` (Tasks 3-4)
- [ ] Same names referenced in handler tasks (5, 7, 8) — no `update_card` vs `update`
- [ ] FE selectors match HTML: `lt-cards-list`, `lt-row`, `lt-row-check`, `lt-qty`, `lt-bulk-strip`
- [ ] Tab id is `live-trading` (not `tab-live-trading`) — verified line 920
- [ ] Modal id is `ltDeleteDialog` consistently in Tasks 12-13
- [ ] No "TBD" / "implement later" / placeholder steps
- [ ] Both repos addressed (tradelab + parent for HTML and launch_dashboard.py)
- [ ] Type-DELETE threshold value (7) is consistent with handoff §4.5

---

**End of plan.**
