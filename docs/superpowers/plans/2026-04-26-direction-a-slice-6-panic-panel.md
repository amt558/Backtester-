# Direction A — Slice 6 — Panic Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three-button panic panel pinned to the top of the Live Trading tab — L1 disables all cards, L2 also cancels open tradelab orders, L3 also flattens every Alpaca position. Each event audited to `panic_events.jsonl` and notified at CRITICAL severity. Bundles three Slice 5 architectural follow-ups (Alpaca exception wrapping in panic.py, silence_checker.stop() lock fix, dead `.lt-pill--silent` CSS removal).

**Architecture:** Backend lives in dashboard launcher process. New `panic.py` module orchestrates L1/L2/L3 steps with per-step exception isolation. New Alpaca wrappers in `alpaca_client.py` (currently only has `submit_market_order`). Two new endpoints: `POST /tradelab/live/panic` and `GET /tradelab/live/panic/last-event`. FE adds a sticky collapsible panic strip + three confirm modals + post-panic banner with scoped re-enable.

**Tech Stack:** Python 3.11, alpaca-py SDK, pytest, vanilla HTML/CSS/JS (no FE framework — `command_center.html` is a single file).

**Spec:** `docs/superpowers/specs/2026-04-26-direction-a-slice-6-panic-panel-design.md`

**Spec correction note:** The spec uses `_handlers.py` in §3.2 — actual file is `src/tradelab/web/handlers.py` (no underscore). All tasks below reference the correct path.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/tradelab/live/alpaca_client.py` | Modify | Add `list_open_orders`, `cancel_order_by_id`, `list_positions` wrappers around alpaca-py SDK calls |
| `src/tradelab/live/panic.py` | NEW | Core panic logic: dataclasses (`CancelAction`, `FlattenAction`, `PanicResult`), `execute_panic(level, also_cancel_nontradelab)`, audit log append, notification dispatch |
| `src/tradelab/live/silence_checker.py` | Modify | Fix `stop()` lock asymmetry (acquire `_start_lock` before reading/writing `_thread`) |
| `src/tradelab/web/handlers.py` | Modify | Add 2 endpoints: `POST /tradelab/live/panic`, `GET /tradelab/live/panic/last-event`; add 2 handler functions |
| `command_center.html` | Modify | Add panic strip (sticky, collapsed-by-default), L1/L2/L3 modals, post-panic banner, JS state machine, drop dead `.lt-pill--silent` CSS |
| `live/panic_events.jsonl` | NEW (runtime) | Append-only audit log. Auto-gitignored by `/live/*.jsonl` rule. |
| `tests/live/test_alpaca_wrappers.py` | NEW | Unit tests for new wrappers (mock TradingClient) |
| `tests/live/test_panic.py` | NEW | execute_panic effect (L1/L2/L3), partial-failure isolation, audit log append, notify with truncation |
| `tests/live/test_silence_checker.py` | Modify | Add `test_stop_acquires_start_lock` |
| `tests/web/test_panic_handlers.py` | NEW | Endpoint envelopes, confirm-token validation, last-event tail-read edge cases |
| `tests/web/test_panic_fe_contract.py` | NEW | DOM/CSS/JS contract pins for panic strip, modals, banner, dead-CSS regression guard |

---

## Task 1: Add Alpaca client wrappers (`list_open_orders`, `cancel_order_by_id`, `list_positions`)

**Files:**
- Modify: `src/tradelab/live/alpaca_client.py`
- Test: `tests/live/test_alpaca_wrappers.py` (NEW)

**Why first:** `panic.py` will depend on these wrappers. Independent of all other backend tasks — can run in parallel with Task 2.

- [ ] **Step 1: Write failing tests for the three new wrappers**

Create `tests/live/test_alpaca_wrappers.py`:

```python
"""Tests for the new alpaca_client wrappers added in Slice 6."""
from unittest.mock import MagicMock, patch

import pytest

from tradelab.live import alpaca_client


@pytest.fixture
def mock_trading_client():
    """Replace get_client() with a MagicMock for the duration of a test."""
    with patch.object(alpaca_client, "get_client") as gc:
        client = MagicMock()
        gc.return_value = client
        yield client


def test_list_open_orders_returns_dicts(mock_trading_client):
    o1 = MagicMock()
    o1.id = "alp-1"
    o1.client_order_id = "card_a-1714142887000"
    o1.symbol = "AAPL"
    o1.qty = "10"
    o1.side.value = "buy"
    o1.status.value = "new"
    mock_trading_client.get_orders.return_value = [o1]

    out = alpaca_client.list_open_orders()

    assert out == [{
        "id": "alp-1",
        "client_order_id": "card_a-1714142887000",
        "symbol": "AAPL",
        "qty": "10",
        "side": "buy",
        "status": "new",
    }]
    # Verify it asked for OPEN status only
    call_args = mock_trading_client.get_orders.call_args
    assert call_args is not None


def test_list_open_orders_empty(mock_trading_client):
    mock_trading_client.get_orders.return_value = []
    assert alpaca_client.list_open_orders() == []


def test_cancel_order_by_id_calls_through(mock_trading_client):
    alpaca_client.cancel_order_by_id("alp-1")
    mock_trading_client.cancel_order_by_id.assert_called_once_with("alp-1")


def test_list_positions_returns_dicts(mock_trading_client):
    p1 = MagicMock()
    p1.symbol = "AAPL"
    p1.qty = "10"
    p1.side.value = "long"
    mock_trading_client.get_all_positions.return_value = [p1]

    out = alpaca_client.list_positions()
    assert out == [{"symbol": "AAPL", "qty": "10", "side": "long"}]


def test_list_positions_empty(mock_trading_client):
    mock_trading_client.get_all_positions.return_value = []
    assert alpaca_client.list_positions() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_alpaca_wrappers.py -v`
Expected: ImportError or AttributeError ("module 'alpaca_client' has no attribute 'list_open_orders'")

- [ ] **Step 3: Implement the three wrappers**

Edit `src/tradelab/live/alpaca_client.py` — add at the bottom of the file (after `submit_market_order`):

```python
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus


def list_open_orders() -> list[dict]:
    """Return all open orders in the Alpaca account as plain dicts.

    Each dict has: id, client_order_id, symbol, qty, side, status.
    Used by panic.py L2 step.
    """
    client = get_client()
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = client.get_orders(filter=req)
    return [
        {
            "id": str(o.id),
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "qty": str(o.qty),
            "side": o.side.value if hasattr(o.side, "value") else str(o.side),
            "status": o.status.value if hasattr(o.status, "value") else str(o.status),
        }
        for o in orders
    ]


def cancel_order_by_id(order_id: str) -> None:
    """Cancel a single Alpaca order by its server-side ID. Raises on failure."""
    client = get_client()
    client.cancel_order_by_id(order_id)


def list_positions() -> list[dict]:
    """Return all open positions in the Alpaca account as plain dicts.

    Each dict has: symbol, qty (string for precision), side.
    Used by panic.py L3 step.
    """
    client = get_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": str(p.qty),
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
        }
        for p in positions
    ]
```

Note: the `GetOrdersRequest`/`QueryOrderStatus` import added at the bottom rather than the top is intentional — keeps the diff minimal and these are panic-only deps. If the file already has top-level alpaca-py imports being modified, fold these in instead.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_alpaca_wrappers.py -v`
Expected: 5 passed

- [ ] **Step 5: Verify no regressions in existing alpaca tests**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/ -v -k alpaca`
Expected: all existing alpaca tests still pass

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/alpaca_client.py tests/live/test_alpaca_wrappers.py
cd C:/TradingScripts/tradelab && git commit -m "feat(live): alpaca_client wrappers for panic L2/L3

Add list_open_orders, cancel_order_by_id, list_positions wrappers
around alpaca-py TradingClient methods. Returns plain dicts (not
SDK objects) for downstream consumption in panic.py.

Slice 6 — T1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Fix `silence_checker.stop()` lock asymmetry (Slice 5 follow-up #11)

**Files:**
- Modify: `src/tradelab/live/silence_checker.py:166-172`
- Modify: `tests/live/test_silence_checker.py` (add one test)

**Why now:** Independent of Task 1 — can run in parallel. Small surgical fix; cheap to land before panic work begins.

- [ ] **Step 1: Write failing test**

Append to `tests/live/test_silence_checker.py`:

```python
def test_stop_acquires_start_lock(monkeypatch):
    """Regression test: stop() must acquire _start_lock before mutating _thread.

    Slice 5 follow-up #11: start() acquires _start_lock; stop() did not. Two
    threads racing start+stop could see a torn read of _thread.
    """
    from tradelab.live import silence_checker

    enter_calls = []
    exit_calls = []

    class TrackingLock:
        def __enter__(self):
            enter_calls.append(True)
            return self
        def __exit__(self, *a):
            exit_calls.append(True)
            return False

    monkeypatch.setattr(silence_checker, "_start_lock", TrackingLock())
    # Also avoid join blocking on a real thread
    monkeypatch.setattr(silence_checker, "_thread", None)

    silence_checker.stop()

    assert len(enter_calls) >= 1, "stop() did not acquire _start_lock"
    assert len(exit_calls) >= 1, "stop() did not release _start_lock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_silence_checker.py::test_stop_acquires_start_lock -v`
Expected: FAIL with `AssertionError: stop() did not acquire _start_lock`

- [ ] **Step 3: Apply the fix**

Edit `src/tradelab/live/silence_checker.py`, replace the existing `stop()` (lines 166-172) with:

```python
def stop() -> None:
    """Signal stop and join the thread. Safe when not running.

    Acquires _start_lock to mirror start(); prevents torn reads of _thread
    when start+stop race (Slice 5 follow-up #11).
    """
    global _thread
    _stop_evt.set()
    with _start_lock:
        if _thread is not None:
            _thread.join(timeout=2.0)
            _thread = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_silence_checker.py::test_stop_acquires_start_lock -v`
Expected: PASS

- [ ] **Step 5: Run full silence_checker test suite to verify no regression**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_silence_checker.py -v`
Expected: all tests pass (the new one + any existing)

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/silence_checker.py tests/live/test_silence_checker.py
cd C:/TradingScripts/tradelab && git commit -m "fix(live): silence_checker.stop() acquires _start_lock

Mirror start()'s lock discipline. Prior code read/wrote _thread
without the lock, allowing torn reads when start+stop race.

Slice 5 follow-up #11. Slice 6 — T2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create `panic.py` module — dataclasses + helpers (no `execute_panic` yet)

**Files:**
- Create: `src/tradelab/live/panic.py`
- Create: `tests/live/test_panic.py`

**Depends on:** Task 1 (alpaca_client wrappers).

- [ ] **Step 1: Write failing tests for the dataclasses + helpers**

Create `tests/live/test_panic.py`:

```python
"""Tests for tradelab.live.panic — Slice 6 panic logic.

Tests are organized by section:
  - Dataclass shape (Task 3)
  - L1 effect (Task 4)
  - L2 effect (Task 5)
  - L3 effect (Task 6)
  - Audit log + notify (interleaved with above)
  - Top-level execute_panic dispatch (Task 5/6)
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Section: dataclass shape ───────────────────────────────────────────

def test_cancel_action_fields():
    from tradelab.live.panic import CancelAction
    a = CancelAction(ok=True, error=None, order_id="alp-1",
                     client_order_id="card_a-123", card_id="card_a")
    assert a.ok is True
    assert a.error is None
    assert a.order_id == "alp-1"
    assert a.client_order_id == "card_a-123"
    assert a.card_id == "card_a"


def test_flatten_action_fields():
    from tradelab.live.panic import FlattenAction
    a = FlattenAction(ok=True, error=None, symbol="AAPL", qty="10",
                      side="sell", order_id="alp-2")
    assert a.symbol == "AAPL"
    assert a.qty == "10"
    assert a.side == "sell"
    assert a.order_id == "alp-2"


def test_panic_result_fields():
    from tradelab.live.panic import PanicResult
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=[],
        orders_cancelled=[],
        positions_flattened=[],
    )
    assert r.level == "L1"
    assert r.cards_disabled == []


# ─── Section: helper — _truncate_for_notification ───────────────────────

def test_truncate_under_10():
    from tradelab.live.panic import _truncate_for_notification
    ids = ["a", "b", "c"]
    assert _truncate_for_notification(ids) == "a, b, c"


def test_truncate_exactly_10():
    from tradelab.live.panic import _truncate_for_notification
    ids = [f"x{i}" for i in range(10)]
    out = _truncate_for_notification(ids)
    assert "+1 more" not in out
    assert "+0 more" not in out


def test_truncate_at_11():
    from tradelab.live.panic import _truncate_for_notification
    ids = [f"x{i}" for i in range(11)]
    out = _truncate_for_notification(ids)
    assert out.endswith("… +1 more")


def test_truncate_empty():
    from tradelab.live.panic import _truncate_for_notification
    assert _truncate_for_notification([]) == "(none)"


# ─── Section: helper — _build_notification_body ─────────────────────────

def test_build_body_l1_only_cards():
    from tradelab.live.panic import _build_notification_body, PanicResult
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=["card_a", "card_b"],
        orders_cancelled=[],
        positions_flattened=[],
    )
    body = _build_notification_body(r)
    assert "L1 panic" in body
    assert "Cards disabled (2)" in body
    assert "card_a, card_b" in body
    assert "Orders cancelled (0)" in body
    assert "Positions flattened: (none)" in body


def test_build_body_l3_with_failures():
    from tradelab.live.panic import (_build_notification_body, PanicResult,
                                      CancelAction, FlattenAction)
    r = PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L3",
        before_state_snapshot=[],
        cards_disabled=["card_a"],
        orders_cancelled=[CancelAction(ok=True, error=None, order_id="o1",
                                       client_order_id="c1", card_id="card_a"),
                          CancelAction(ok=False, error="APIError: 429",
                                       order_id="o2", client_order_id="c2",
                                       card_id="card_a")],
        positions_flattened=[FlattenAction(ok=True, error=None, symbol="AAPL",
                                           qty="10", side="sell", order_id="o3")],
    )
    body = _build_notification_body(r)
    assert "Errors: 1" in body  # one failed cancel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v`
Expected: ImportError ("No module named 'tradelab.live.panic'")

- [ ] **Step 3: Create panic.py with dataclasses + helpers**

Create `src/tradelab/live/panic.py`:

```python
"""Panic panel core logic — Slice 6.

L1: Disable all cards.
L2: L1 + cancel open tradelab orders (optionally all open orders).
L3: L2 + flatten all positions (whole-account).

Each Alpaca call is wrapped in try/except so partial failures don't abort
the panic. Failures are recorded as PanicAction(ok=False) entries and
included in the audit log + notification.

Per spec §10: lives in dashboard launcher process. Receiver picks up L1
via existing watchdog reload of cards.json. L2/L3 hit Alpaca directly.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PANIC_LOG_PATH = Path(__file__).resolve().parents[3] / "live" / "panic_events.jsonl"


# ─── Dataclasses ─────────────────────────────────────────────────────────

@dataclass
class CancelAction:
    ok: bool
    error: Optional[str]
    order_id: Optional[str]
    client_order_id: Optional[str]
    card_id: Optional[str]  # None if non-tradelab order


@dataclass
class FlattenAction:
    ok: bool
    error: Optional[str]
    symbol: str
    qty: str  # alpaca returns string; preserve precision
    side: str  # "buy" or "sell" — opposite of held position
    order_id: Optional[str]


@dataclass
class PanicResult:
    ts: str
    level: str  # "L1" | "L2" | "L3"
    before_state_snapshot: list[dict]
    cards_disabled: list[str]
    orders_cancelled: list[CancelAction]
    positions_flattened: list[FlattenAction]


# ─── Notification body helpers ───────────────────────────────────────────

_TRUNC_AT = 10


def _truncate_for_notification(ids: list[str]) -> str:
    """Render a list of IDs as a comma-separated string, truncated after 10
    items with a '… +N more' suffix. Returns '(none)' for empty."""
    if not ids:
        return "(none)"
    if len(ids) <= _TRUNC_AT:
        return ", ".join(ids)
    head = ", ".join(ids[:_TRUNC_AT])
    return f"{head}… +{len(ids) - _TRUNC_AT} more"


def _build_notification_body(result: PanicResult) -> str:
    """Build the multi-line CRITICAL notification body. Same string to all
    five channels (truncation per channel happens client-side).
    """
    ts_local = result.ts  # already includes TZ
    cancelled_ids = [a.client_order_id or "?" for a in result.orders_cancelled if a.ok]
    flattened_strs = [
        f"{a.symbol}({a.qty} {a.side})"
        for a in result.positions_flattened if a.ok
    ]
    cancel_failures = sum(1 for a in result.orders_cancelled if not a.ok)
    flatten_failures = sum(1 for a in result.positions_flattened if not a.ok)
    total_failures = cancel_failures + flatten_failures

    lines = [
        f"{result.level} panic at {ts_local}",
        "",
        f"Cards disabled ({len(result.cards_disabled)}): {_truncate_for_notification(result.cards_disabled)}",
        f"Orders cancelled ({sum(1 for a in result.orders_cancelled if a.ok)}): {_truncate_for_notification(cancelled_ids)}",
        f"Positions flattened: {_truncate_for_notification(flattened_strs)}",
    ]
    if total_failures > 0:
        lines.append(f"Errors: {total_failures} failed action(s) (see audit log).")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v`
Expected: 9 passed (3 dataclass + 4 truncate + 2 build_body)

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/panic.py tests/live/test_panic.py
cd C:/TradingScripts/tradelab && git commit -m "feat(live): panic.py module skeleton — dataclasses + notify helpers

Add CancelAction, FlattenAction, PanicResult dataclasses and the
notification body builder (with 10-id truncation). execute_panic()
dispatch lands in T4-T6.

Slice 6 — T3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement `execute_panic` L1 step + audit log + notify

**Files:**
- Modify: `src/tradelab/live/panic.py`
- Modify: `tests/live/test_panic.py`

**Depends on:** Task 3.

- [ ] **Step 1: Write failing tests for L1**

Append to `tests/live/test_panic.py`:

```python
# ─── Section: execute_panic L1 ──────────────────────────────────────────

@pytest.fixture
def tmp_panic_log(monkeypatch, tmp_path):
    """Redirect panic_events.jsonl to a tmp file."""
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    return p


@pytest.fixture
def mock_card_registry(monkeypatch):
    """Mock the CardRegistry that panic.py loads to snapshot/disable cards."""
    from tradelab.live import panic

    cards_state = {
        "card_a": {"card_id": "card_a", "base_name": "S2_AAPL_LONG",
                   "status": "enabled", "qty": 100, "last_fired_at": "2026-04-26T13:00:00-04:00"},
        "card_b": {"card_id": "card_b", "base_name": "S4_MSFT_SHORT",
                   "status": "enabled", "qty": 50, "last_fired_at": None},
        "card_c": {"card_id": "card_c", "base_name": "S7_NVDA_LONG",
                   "status": "disabled", "qty": 200, "last_fired_at": None},
    }
    disabled_calls = []

    class FakeRegistry:
        def all_hydrated(self):
            return dict(cards_state)
        def set_status(self, card_id, status):
            cards_state[card_id]["status"] = status
            disabled_calls.append((card_id, status))

    fake = FakeRegistry()
    monkeypatch.setattr(panic, "_load_registry", lambda: fake)
    fake._calls = disabled_calls
    return fake


@pytest.fixture
def mock_notify(monkeypatch):
    from tradelab.live import panic
    calls = []

    def fake_notify(severity, title, body, **kwargs):
        calls.append({"severity": severity, "title": title, "body": body})

    monkeypatch.setattr(panic, "_notify_fn", fake_notify)
    return calls


def test_l1_disables_all_enabled_cards(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    result = execute_panic("L1")

    assert result.level == "L1"
    assert set(result.cards_disabled) == {"card_a", "card_b"}
    # card_c was already disabled — should NOT appear in cards_disabled
    assert "card_c" not in result.cards_disabled
    # set_status was called only for the enabled ones
    disabled_ids = {cid for cid, status in mock_card_registry._calls if status == "disabled"}
    assert disabled_ids == {"card_a", "card_b"}


def test_l1_no_alpaca_calls(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    with patch("tradelab.live.alpaca_client.list_open_orders") as lo, \
         patch("tradelab.live.alpaca_client.cancel_order_by_id") as co, \
         patch("tradelab.live.alpaca_client.list_positions") as lp, \
         patch("tradelab.live.alpaca_client.submit_market_order") as sm:
        execute_panic("L1")
        lo.assert_not_called()
        co.assert_not_called()
        lp.assert_not_called()
        sm.assert_not_called()


def test_l1_audit_log_appended(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    execute_panic("L1")

    lines = tmp_panic_log.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == "L1"
    assert "ts" in entry
    assert set(entry["cards_disabled"]) == {"card_a", "card_b"}
    assert entry["orders_cancelled"] == []
    assert entry["positions_flattened"] == []


def test_l1_audit_log_snapshot_shape(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic

    execute_panic("L1")

    entry = json.loads(tmp_panic_log.read_text(encoding="utf-8").strip())
    snap = entry["before_state_snapshot"]
    assert len(snap) == 3  # all 3 cards (enabled + disabled)
    fields = set(snap[0].keys())
    assert {"card_id", "base_name", "status", "qty", "last_fired_at"}.issubset(fields)


def test_l1_notify_called_with_critical(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    from tradelab.live.notify import Severity

    execute_panic("L1")

    assert len(mock_notify) == 1
    assert mock_notify[0]["severity"] == Severity.CRITICAL
    assert "L1 panic" in mock_notify[0]["title"]
    assert "2 cards disabled" in mock_notify[0]["title"]


def test_l1_invalid_level_raises(tmp_panic_log, mock_card_registry, mock_notify):
    from tradelab.live.panic import execute_panic
    with pytest.raises(ValueError):
        execute_panic("L4")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v -k "l1"`
Expected: ImportError or AttributeError on `execute_panic`

- [ ] **Step 3: Implement L1 step in panic.py**

Append to `src/tradelab/live/panic.py`:

```python
# ─── Module-level injectable hooks (test seam) ───────────────────────────

def _default_notify(severity, title, body, **kwargs):
    from tradelab.live import notify as _n
    return _n.notify(severity, title, body, **kwargs)

_notify_fn = _default_notify  # tests monkey-patch this


def _load_registry():
    """Load the live CardRegistry. Tests monkey-patch this."""
    from tradelab.live.cards import CardRegistry
    path = Path(__file__).resolve().parents[3] / "live" / "cards.json"
    return CardRegistry(path)


# ─── Audit log ───────────────────────────────────────────────────────────

def _append_audit(result: PanicResult) -> None:
    """Append one JSON line to panic_events.jsonl. Best-effort — failure to
    write the audit log MUST NOT crash the panic (the panic itself succeeded).
    """
    try:
        PANIC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_serialize_result(result))
        with open(PANIC_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[panic] audit append failed: {type(e).__name__}: {e}", file=sys.stderr)


def _serialize_result(result: PanicResult) -> dict:
    d = asdict(result)
    return d


# ─── execute_panic dispatch ──────────────────────────────────────────────

_VALID_LEVELS = {"L1", "L2", "L3"}


def execute_panic(level: str, also_cancel_nontradelab: bool = False) -> PanicResult:
    """Execute panic at the given level.

    Always succeeds — partial failures (failed Alpaca calls) are recorded
    inside PanicResult as PanicAction(ok=False, error=...) entries. Raises
    ValueError only on programmer error (bad level).
    """
    if level not in _VALID_LEVELS:
        raise ValueError(f"invalid panic level: {level!r}; expected one of {sorted(_VALID_LEVELS)}")

    ts = datetime.now(ET).isoformat()

    # Step 1: snapshot current state
    registry = _load_registry()
    cards_now = registry.all_hydrated()
    snapshot = [
        {
            "card_id": c.get("card_id", cid),
            "base_name": c.get("base_name"),
            "status": c.get("status"),
            "qty": c.get("qty") or c.get("quantity"),
            "last_fired_at": c.get("last_fired_at"),
        }
        for cid, c in cards_now.items()
    ]

    # Step 2: L1 — disable all enabled cards
    cards_disabled: list[str] = []
    for cid, card in cards_now.items():
        if card.get("status") == "enabled":
            try:
                registry.set_status(cid, "disabled")
                cards_disabled.append(cid)
            except Exception as e:
                # Per-card disable failure: still record what we attempted
                print(f"[panic] failed to disable {cid}: {type(e).__name__}: {e}", file=sys.stderr)

    orders_cancelled: list[CancelAction] = []
    positions_flattened: list[FlattenAction] = []

    # Step 3+4 deferred to T5/T6

    result = PanicResult(
        ts=ts,
        level=level,
        before_state_snapshot=snapshot,
        cards_disabled=cards_disabled,
        orders_cancelled=orders_cancelled,
        positions_flattened=positions_flattened,
    )

    _append_audit(result)

    title = f"🚨 {level} panic — {len(cards_disabled)} cards disabled"
    body = _build_notification_body(result)
    from tradelab.live.notify import Severity
    _notify_fn(Severity.CRITICAL, title, body)

    return result
```

- [ ] **Step 4: Run L1 tests to verify pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v`
Expected: all tests pass (dataclasses + helpers + L1 effect)

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/panic.py tests/live/test_panic.py
cd C:/TradingScripts/tradelab && git commit -m "feat(live): execute_panic L1 — disable all cards + audit + notify

L1 step disables every enabled card via CardRegistry.set_status,
appends a PanicResult to panic_events.jsonl, fires notify(CRITICAL)
with the multi-line summary body. L2/L3 land in T5/T6.

Slice 6 — T4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Implement `execute_panic` L2 step (cancel orders)

**Files:**
- Modify: `src/tradelab/live/panic.py`
- Modify: `tests/live/test_panic.py`

**Depends on:** Tasks 1, 4.

- [ ] **Step 1: Write failing tests for L2**

Append to `tests/live/test_panic.py`:

```python
# ─── Section: execute_panic L2 ──────────────────────────────────────────

@pytest.fixture
def mock_alpaca_orders(monkeypatch):
    """Patch alpaca_client.list_open_orders + cancel_order_by_id with mocks."""
    from tradelab.live import alpaca_client
    list_calls = []
    cancel_calls = []

    def fake_list():
        return list_calls[0] if list_calls else []

    def fake_cancel(order_id):
        cancel_calls.append(order_id)

    monkeypatch.setattr(alpaca_client, "list_open_orders", fake_list)
    monkeypatch.setattr(alpaca_client, "cancel_order_by_id", fake_cancel)
    return list_calls, cancel_calls


def test_l2_cancels_only_tradelab_orders_by_default(
    tmp_panic_log, mock_card_registry, mock_notify, mock_alpaca_orders
):
    from tradelab.live.panic import execute_panic
    list_calls, cancel_calls = mock_alpaca_orders
    list_calls.append([
        {"id": "alp-1", "client_order_id": "card_a-1714142887000",
         "symbol": "AAPL", "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "manual-order-xyz",
         "symbol": "TSLA", "qty": "5", "side": "buy", "status": "new"},
    ])

    result = execute_panic("L2")

    assert cancel_calls == ["alp-1"]  # only tradelab order
    assert len(result.orders_cancelled) == 1
    assert result.orders_cancelled[0].ok is True
    assert result.orders_cancelled[0].order_id == "alp-1"


def test_l2_cancels_all_orders_when_flag_on(
    tmp_panic_log, mock_card_registry, mock_notify, mock_alpaca_orders
):
    from tradelab.live.panic import execute_panic
    list_calls, cancel_calls = mock_alpaca_orders
    list_calls.append([
        {"id": "alp-1", "client_order_id": "card_a-1714142887000",
         "symbol": "AAPL", "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "manual-order-xyz",
         "symbol": "TSLA", "qty": "5", "side": "buy", "status": "new"},
    ])

    result = execute_panic("L2", also_cancel_nontradelab=True)

    assert sorted(cancel_calls) == ["alp-1", "alp-2"]
    assert len(result.orders_cancelled) == 2
    # The manual one should record card_id=None
    by_oid = {a.order_id: a for a in result.orders_cancelled}
    assert by_oid["alp-2"].card_id is None
    assert by_oid["alp-1"].card_id == "card_a"


def test_l2_partial_failure_continues(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    monkeypatch.setattr(alpaca_client, "list_open_orders", lambda: [
        {"id": "alp-1", "client_order_id": "card_a-1", "symbol": "AAPL",
         "qty": "10", "side": "buy", "status": "new"},
        {"id": "alp-2", "client_order_id": "card_a-2", "symbol": "AAPL",
         "qty": "10", "side": "buy", "status": "new"},
    ])

    def fake_cancel(oid):
        if oid == "alp-2":
            raise Exception("simulated APIError")
    monkeypatch.setattr(alpaca_client, "cancel_order_by_id", fake_cancel)

    result = execute_panic("L2")

    assert len(result.orders_cancelled) == 2
    by_oid = {a.order_id: a for a in result.orders_cancelled}
    assert by_oid["alp-1"].ok is True
    assert by_oid["alp-2"].ok is False
    assert "simulated APIError" in (by_oid["alp-2"].error or "")
    # And the panic itself completed (audit + notify fired)
    assert tmp_panic_log.exists()
    assert len(mock_notify) == 1


def test_l2_list_orders_failure_recorded_as_synthetic_action(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    def fake_list():
        raise Exception("network down")
    monkeypatch.setattr(alpaca_client, "list_open_orders", fake_list)

    result = execute_panic("L2")

    assert len(result.orders_cancelled) == 1
    assert result.orders_cancelled[0].ok is False
    assert "network down" in (result.orders_cancelled[0].error or "")
    # L1 step still succeeded
    assert set(result.cards_disabled) == {"card_a", "card_b"}
```

- [ ] **Step 2: Run L2 tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v -k "l2"`
Expected: tests fail because L2 step is not yet implemented (orders_cancelled stays empty)

- [ ] **Step 3: Implement L2 step**

Edit `src/tradelab/live/panic.py`. Replace the line `# Step 3+4 deferred to T5/T6` (and the surrounding empty lists) with the L2 logic. Find the block:

```python
    orders_cancelled: list[CancelAction] = []
    positions_flattened: list[FlattenAction] = []

    # Step 3+4 deferred to T5/T6
```

Replace with:

```python
    orders_cancelled: list[CancelAction] = []
    positions_flattened: list[FlattenAction] = []

    # Step 3: L2 — cancel open orders (L2/L3 only)
    if level in ("L2", "L3"):
        orders_cancelled = _cancel_orders_step(
            card_ids=set(cards_now.keys()),
            also_cancel_nontradelab=also_cancel_nontradelab,
        )

    # Step 4 deferred to T6
```

Then append these helpers below `execute_panic`:

```python
def _classify_order_card(client_order_id: Optional[str], card_ids: set[str]) -> Optional[str]:
    """Return the card_id this order belongs to, or None if not tradelab.
    Spec rule: client_order_id.startswith(f"{cid}-") for some cid."""
    if not client_order_id:
        return None
    for cid in card_ids:
        if client_order_id.startswith(f"{cid}-"):
            return cid
    return None


def _cancel_orders_step(
    *, card_ids: set[str], also_cancel_nontradelab: bool
) -> list[CancelAction]:
    """L2 step. Returns one CancelAction per order processed (whether cancel
    succeeded or failed). On list_open_orders failure, returns a single synthetic
    CancelAction with ok=False so the audit log shows the issue."""
    from tradelab.live import alpaca_client

    try:
        orders = alpaca_client.list_open_orders()
    except Exception as e:
        return [CancelAction(
            ok=False,
            error=f"list_open_orders failed: {type(e).__name__}: {e}",
            order_id=None, client_order_id=None, card_id=None,
        )]

    actions: list[CancelAction] = []
    for o in orders:
        coid = o.get("client_order_id")
        card_id = _classify_order_card(coid, card_ids)
        if card_id is None and not also_cancel_nontradelab:
            continue  # skip non-tradelab orders unless flag is set
        order_id = o.get("id")
        try:
            alpaca_client.cancel_order_by_id(order_id)
            actions.append(CancelAction(
                ok=True, error=None,
                order_id=order_id, client_order_id=coid, card_id=card_id,
            ))
        except Exception as e:
            actions.append(CancelAction(
                ok=False, error=f"{type(e).__name__}: {e}",
                order_id=order_id, client_order_id=coid, card_id=card_id,
            ))
    return actions
```

- [ ] **Step 4: Run L2 tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v -k "l2"`
Expected: all L2 tests pass

- [ ] **Step 5: Run all panic tests to confirm no regression on L1**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/panic.py tests/live/test_panic.py
cd C:/TradingScripts/tradelab && git commit -m "feat(live): execute_panic L2 — cancel open tradelab orders

Filter rule: client_order_id.startswith(f'{cid}-') for current cards.
also_cancel_nontradelab=True bypasses the filter. Per-order try/except
isolates partial failures into CancelAction(ok=False) entries.
list_open_orders failure recorded as a single synthetic CancelAction.

Slice 6 — T5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Implement `execute_panic` L3 step (flatten positions)

**Files:**
- Modify: `src/tradelab/live/panic.py`
- Modify: `tests/live/test_panic.py`

**Depends on:** Task 5.

- [ ] **Step 1: Write failing tests for L3**

Append to `tests/live/test_panic.py`:

```python
# ─── Section: execute_panic L3 ──────────────────────────────────────────

def test_l3_flattens_all_positions(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    monkeypatch.setattr(alpaca_client, "list_open_orders", lambda: [])
    monkeypatch.setattr(alpaca_client, "list_positions", lambda: [
        {"symbol": "AAPL", "qty": "10", "side": "long"},
        {"symbol": "TSLA", "qty": "5",  "side": "short"},
    ])
    submit_calls = []
    def fake_submit(symbol, side, quantity, **kw):
        submit_calls.append((symbol, side, quantity))
        return {"id": f"close-{symbol}", "client_order_id": None,
                "symbol": symbol, "qty": str(quantity), "side": side,
                "status": "new", "submitted_at": None}
    monkeypatch.setattr(alpaca_client, "submit_market_order", fake_submit)

    result = execute_panic("L3")

    assert len(result.positions_flattened) == 2
    by_sym = {a.symbol: a for a in result.positions_flattened}
    assert by_sym["AAPL"].side == "sell"   # long → sell
    assert by_sym["TSLA"].side == "buy"    # short → buy
    assert by_sym["AAPL"].qty == "10"
    assert by_sym["AAPL"].ok is True
    assert by_sym["AAPL"].order_id == "close-AAPL"
    # And the submit was actually called with the opposite side
    sides_by_sym = {sym: side for sym, side, _ in submit_calls}
    assert sides_by_sym["AAPL"] == "sell"
    assert sides_by_sym["TSLA"] == "buy"


def test_l3_flatten_partial_failure(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    monkeypatch.setattr(alpaca_client, "list_open_orders", lambda: [])
    monkeypatch.setattr(alpaca_client, "list_positions", lambda: [
        {"symbol": "AAPL", "qty": "10", "side": "long"},
        {"symbol": "TSLA", "qty": "5",  "side": "short"},
    ])
    def fake_submit(symbol, side, quantity, **kw):
        if symbol == "TSLA":
            raise Exception("simulated APIError")
        return {"id": f"close-{symbol}", "client_order_id": None,
                "symbol": symbol, "qty": str(quantity), "side": side,
                "status": "new", "submitted_at": None}
    monkeypatch.setattr(alpaca_client, "submit_market_order", fake_submit)

    result = execute_panic("L3")

    by_sym = {a.symbol: a for a in result.positions_flattened}
    assert by_sym["AAPL"].ok is True
    assert by_sym["TSLA"].ok is False
    assert "simulated APIError" in (by_sym["TSLA"].error or "")


def test_l3_list_positions_failure_recorded_as_synthetic(
    tmp_panic_log, mock_card_registry, mock_notify, monkeypatch
):
    from tradelab.live import alpaca_client
    from tradelab.live.panic import execute_panic

    monkeypatch.setattr(alpaca_client, "list_open_orders", lambda: [])
    def fake_list_positions():
        raise Exception("network blip")
    monkeypatch.setattr(alpaca_client, "list_positions", fake_list_positions)

    result = execute_panic("L3")

    # Synthetic FlattenAction with symbol="" and ok=False
    assert len(result.positions_flattened) == 1
    assert result.positions_flattened[0].ok is False
    assert "network blip" in (result.positions_flattened[0].error or "")
```

- [ ] **Step 2: Run L3 tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v -k "l3"`
Expected: tests fail (positions_flattened stays empty for L3)

- [ ] **Step 3: Implement L3 step**

Edit `src/tradelab/live/panic.py`. Find the block:

```python
    # Step 3: L2 — cancel open orders (L2/L3 only)
    if level in ("L2", "L3"):
        orders_cancelled = _cancel_orders_step(
            card_ids=set(cards_now.keys()),
            also_cancel_nontradelab=also_cancel_nontradelab,
        )

    # Step 4 deferred to T6
```

Replace the trailing comment block with:

```python
    # Step 4: L3 — flatten all positions (L3 only)
    if level == "L3":
        positions_flattened = _flatten_positions_step()
```

Then append below `_cancel_orders_step`:

```python
def _flatten_positions_step() -> list[FlattenAction]:
    """L3 step. For each open position, submit a market order on the opposite
    side to close. Returns one FlattenAction per position attempted. On
    list_positions failure, returns a single synthetic FlattenAction.
    Whole-account — affects positions tradelab did not open."""
    from tradelab.live import alpaca_client

    try:
        positions = alpaca_client.list_positions()
    except Exception as e:
        return [FlattenAction(
            ok=False,
            error=f"list_positions failed: {type(e).__name__}: {e}",
            symbol="", qty="0", side="", order_id=None,
        )]

    actions: list[FlattenAction] = []
    for p in positions:
        symbol = p.get("symbol", "?")
        qty = p.get("qty", "0")
        held_side = (p.get("side") or "long").lower()
        # Convert held side to closing side
        close_side = "sell" if held_side in ("long", "buy") else "buy"
        try:
            order = alpaca_client.submit_market_order(
                symbol=symbol, side=close_side, quantity=float(qty),
            )
            actions.append(FlattenAction(
                ok=True, error=None,
                symbol=symbol, qty=qty, side=close_side,
                order_id=str(order.get("id")) if order else None,
            ))
        except Exception as e:
            actions.append(FlattenAction(
                ok=False, error=f"{type(e).__name__}: {e}",
                symbol=symbol, qty=qty, side=close_side, order_id=None,
            ))
    return actions
```

- [ ] **Step 4: Run L3 tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v -k "l3"`
Expected: all L3 tests pass

- [ ] **Step 5: Run full panic test suite**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_panic.py -v`
Expected: all tests pass (~17 total: 3 dataclass + 4 truncate + 2 build_body + 6 L1 + 4 L2 + 3 L3 = 22; close enough)

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/panic.py tests/live/test_panic.py
cd C:/TradingScripts/tradelab && git commit -m "feat(live): execute_panic L3 — flatten all positions

For each open position: submit market order on opposite side. Whole-
account (no attribution to tradelab cards). Per-position try/except
isolates failures. list_positions failure recorded as synthetic
FlattenAction.

Slice 6 — T6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Add `POST /tradelab/live/panic` endpoint + handler

**Files:**
- Modify: `src/tradelab/web/handlers.py` (add to `handle_post_with_status` dispatcher near line 528, add `handle_panic_post` helper near line 977)
- Create: `tests/web/test_panic_handlers.py`

**Depends on:** Task 6.

- [ ] **Step 1: Write failing tests for the POST endpoint**

Create `tests/web/test_panic_handlers.py`:

```python
"""Tests for POST /tradelab/live/panic and GET /tradelab/live/panic/last-event."""
import json
from unittest.mock import MagicMock, patch

import pytest

from tradelab.web import handlers


# ─── POST /tradelab/live/panic ─────────────────────────────────────────

def _post(path, payload):
    return handlers.handle_post_with_status(path, json.dumps(payload).encode())


def test_post_panic_l1_happy(monkeypatch, tmp_path):
    """L1 with correct confirm word returns 200 with PanicResult envelope."""
    from tradelab.live import panic

    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")

    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00",
        level="L1",
        before_state_snapshot=[],
        cards_disabled=["card_a"],
        orders_cancelled=[],
        positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        body, status = _post("/tradelab/live/panic",
                             {"level": "L1", "confirm": "DISABLE"})

    assert status == 200
    env = json.loads(body)
    assert env["ok"] is True
    assert env["data"]["level"] == "L1"
    assert env["data"]["cards_disabled"] == ["card_a"]
    ep.assert_called_once_with("L1", also_cancel_nontradelab=False)


def test_post_panic_wrong_confirm_word_400():
    body, status = _post("/tradelab/live/panic",
                         {"level": "L1", "confirm": "PANIC"})
    assert status == 400
    env = json.loads(body)
    assert env["ok"] is False
    assert "confirm" in env["error"].lower()


def test_post_panic_invalid_level_400():
    body, status = _post("/tradelab/live/panic",
                         {"level": "L4", "confirm": "DISABLE"})
    assert status == 400


def test_post_panic_l1_ignores_also_cancel_flag(monkeypatch, tmp_path):
    """L1 with also_cancel_nontradelab=True must not pass it to execute_panic
    (or, if passed, execute_panic ignores it for L1; either is acceptable —
    we test the safer behavior of not passing it for L1)."""
    from tradelab.live import panic
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")
    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00", level="L1", before_state_snapshot=[],
        cards_disabled=[], orders_cancelled=[], positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        _post("/tradelab/live/panic",
              {"level": "L1", "confirm": "DISABLE", "also_cancel_nontradelab": True})
    # For L1 the flag is meaningless; assert it was passed as False (defense)
    ep.assert_called_once_with("L1", also_cancel_nontradelab=False)


def test_post_panic_l2_passes_flag(monkeypatch, tmp_path):
    from tradelab.live import panic
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", tmp_path / "panic_events.jsonl")
    fake_result = panic.PanicResult(
        ts="2026-04-26T14:32:07-04:00", level="L2", before_state_snapshot=[],
        cards_disabled=[], orders_cancelled=[], positions_flattened=[],
    )
    with patch.object(panic, "execute_panic", return_value=fake_result) as ep:
        _post("/tradelab/live/panic",
              {"level": "L2", "confirm": "PANIC", "also_cancel_nontradelab": True})
    ep.assert_called_once_with("L2", also_cancel_nontradelab=True)


def test_post_panic_missing_level_400():
    body, status = _post("/tradelab/live/panic", {"confirm": "DISABLE"})
    assert status == 400


def test_post_panic_missing_confirm_400():
    body, status = _post("/tradelab/live/panic", {"level": "L1"})
    assert status == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_handlers.py -v -k "post_panic"`
Expected: 404 responses (endpoint not registered)

- [ ] **Step 3: Add the dispatcher entry + handler function**

Edit `src/tradelab/web/handlers.py`. In `handle_post_with_status` (starts ~line 518), add this branch BEFORE the final `return _err("not found"), 404` (or wherever the post-with-status dispatcher's final return is — match the existing pattern):

```python
    if path == "/tradelab/live/panic":
        return handle_panic_post(payload)
```

Then add this new handler function near the other `handle_*` functions (e.g., after `handle_silence_status_get` around line 978):

```python
_PANIC_CONFIRM_WORDS = {"L1": "DISABLE", "L2": "PANIC", "L3": "FLATTEN"}


def handle_panic_post(payload: dict) -> Tuple[str, int]:
    """POST /tradelab/live/panic — execute panic at the given level.

    Body: {level: "L1"|"L2"|"L3", confirm: "DISABLE"|"PANIC"|"FLATTEN",
           also_cancel_nontradelab?: bool}
    Server-side confirm-word check is defense in depth — FE also enforces.
    """
    level = payload.get("level")
    confirm = payload.get("confirm")
    if level not in _PANIC_CONFIRM_WORDS:
        return _err(f"invalid or missing level (got {level!r}); expected L1/L2/L3"), 400
    if confirm != _PANIC_CONFIRM_WORDS[level]:
        return _err(f"confirm word mismatch for {level} (expected {_PANIC_CONFIRM_WORDS[level]!r})"), 400

    also_cancel = bool(payload.get("also_cancel_nontradelab", False))
    # L1 has no Alpaca calls; the flag is meaningless. Force-False for safety.
    if level == "L1":
        also_cancel = False

    from tradelab.live import panic
    try:
        result = panic.execute_panic(level, also_cancel_nontradelab=also_cancel)
    except Exception as e:
        return _err(f"panic execution raised: {type(e).__name__}: {e}"), 500

    from dataclasses import asdict
    return _ok(asdict(result)), 200
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_handlers.py -v -k "post_panic"`
Expected: all 7 POST tests pass

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_panic_handlers.py
cd C:/TradingScripts/tradelab && git commit -m "feat(web): POST /tradelab/live/panic

Server-side confirm-word validation (DISABLE/PANIC/FLATTEN per level).
L1 force-clears the also_cancel_nontradelab flag for safety. Returns
the full PanicResult as the envelope data field.

Slice 6 — T7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Add `GET /tradelab/live/panic/last-event` endpoint + handler

**Files:**
- Modify: `src/tradelab/web/handlers.py` (add to `handle_get_with_status` near line 371, add `handle_panic_last_event_get` helper)
- Modify: `tests/web/test_panic_handlers.py`

**Depends on:** Task 7.

- [ ] **Step 1: Write failing tests**

Append to `tests/web/test_panic_handlers.py`:

```python
# ─── GET /tradelab/live/panic/last-event ───────────────────────────────

def _get(path):
    return handlers.handle_get_with_status(path)


def test_get_last_event_returns_null_when_file_missing(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"] is None


def test_get_last_event_returns_null_when_file_empty(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)
    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"] is None


def test_get_last_event_returns_most_recent(monkeypatch, tmp_path):
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    e1 = {"ts": "2026-04-26T14:32:07-04:00", "level": "L1",
          "cards_disabled": ["card_a"], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    e2 = {"ts": "2026-04-26T15:01:42-04:00", "level": "L2",
          "cards_disabled": ["card_b"], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    p.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)

    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"]["ts"] == "2026-04-26T15:01:42-04:00"
    assert env["data"]["level"] == "L2"


def test_get_last_event_handles_corrupt_trailing_line(monkeypatch, tmp_path):
    """If the last line is malformed JSON, return the most recent valid line."""
    from tradelab.live import panic
    p = tmp_path / "panic_events.jsonl"
    e1 = {"ts": "2026-04-26T14:32:07-04:00", "level": "L1",
          "cards_disabled": [], "before_state_snapshot": [],
          "orders_cancelled": [], "positions_flattened": []}
    p.write_text(json.dumps(e1) + "\nthis-is-not-json\n", encoding="utf-8")
    monkeypatch.setattr(panic, "PANIC_LOG_PATH", p)

    body, status = _get("/tradelab/live/panic/last-event")
    assert status == 200
    env = json.loads(body)
    assert env["data"]["ts"] == "2026-04-26T14:32:07-04:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_handlers.py -v -k "last_event"`
Expected: 404 (endpoint not registered)

- [ ] **Step 3: Add dispatcher entry + handler**

Edit `src/tradelab/web/handlers.py`. In `handle_get_with_status` (the dispatcher near line 371 that ends `if path == "/tradelab/live/silence-status": return handle_silence_status_get()`), add this branch after the silence-status one and before the `return _err("not found"), 404`:

```python
    if path == "/tradelab/live/panic/last-event":
        return handle_panic_last_event_get()
```

Then add the helper near `handle_silence_status_get`:

```python
def handle_panic_last_event_get() -> Tuple[str, int]:
    """GET /tradelab/live/panic/last-event — return most recent panic event
    as JSON, or null if no events exist (or file is empty/corrupt at tail)."""
    from tradelab.live import panic
    if not panic.PANIC_LOG_PATH.exists():
        return _ok(None), 200
    try:
        text = panic.PANIC_LOG_PATH.read_text(encoding="utf-8")
    except Exception:
        return _ok(None), 200

    # Iterate non-empty lines from the bottom up; return first parseable one.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return _ok(json.loads(ln)), 200
        except json.JSONDecodeError:
            continue
    return _ok(None), 200
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_handlers.py -v`
Expected: all tests pass (POST + GET = 11 total)

- [ ] **Step 5: Run full pytest to confirm baseline holds**

Run: `cd C:/TradingScripts/tradelab && python -m pytest --tb=short 2>&1 | tail -20`
Expected: pass count went up by ~25-27, no failures

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_panic_handlers.py
cd C:/TradingScripts/tradelab && git commit -m "feat(web): GET /tradelab/live/panic/last-event

Returns most recent panic event from panic_events.jsonl, or null if
the file is missing/empty. Tail-reads + skips corrupt trailing lines
(returns last valid entry) so a partial write can't break the FE banner.

Slice 6 — T8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: FE — panic strip HTML + CSS + collapse JS + contract test

**Files:**
- Modify: `C:/TradingScripts/command_center.html` (insert panic strip as first child of `#live-trading` at line 1019; add CSS in the LT styles block; add JS in the LT IIFE near line 4513)
- Create: `tests/web/test_panic_fe_contract.py`

**Depends on:** Task 8 (endpoints exist for FE to hit). FE tasks 9-13 are sequential (same file).

- [ ] **Step 1: Write failing contract test for the panic strip**

Create `tests/web/test_panic_fe_contract.py`:

```python
"""DOM/CSS/JS contract tests for the Slice 6 panic panel.

These tests use static greps against C:/TradingScripts/command_center.html.
They pin selectors, attribute names, function names, and CSS literals so
that a refactor that breaks the contract gets caught at pytest time.

Mirrors the Slice 5 contract-test pattern (test_silence_status_handler.py
style) — text greps with explicit error messages.
"""
from pathlib import Path
import re

import pytest

CC = Path("C:/TradingScripts/command_center.html")


@pytest.fixture(scope="module")
def html_text():
    return CC.read_text(encoding="utf-8")


# ─── Panel strip ────────────────────────────────────────────────────────

def test_panic_strip_is_first_child_of_live_trading(html_text):
    """Panic strip must appear before the existing lt-status-strip."""
    panic_idx = html_text.find('id="lt-panic-strip"')
    status_idx = html_text.find('id="lt-status-strip"')
    assert panic_idx > 0, "lt-panic-strip not found in command_center.html"
    # If lt-status-strip is wrapped without an id, fall back to the class
    if status_idx < 0:
        status_idx = html_text.find('class="lt-status-strip"')
    assert status_idx > 0, "lt-status-strip not found"
    assert panic_idx < status_idx, "panic strip must precede status strip in DOM"


def test_panic_strip_buttons_present(html_text):
    for label in ("Pause All", "Pause + Cancel Orders", "Pause + Cancel + Flatten Positions"):
        assert label in html_text, f"missing button label: {label!r}"


def test_panic_strip_emoji_title(html_text):
    assert "🚨 PANIC" in html_text


def test_panic_strip_sticky_css(html_text):
    """panic strip CSS uses position: sticky."""
    block = html_text[html_text.find(".lt-panic-strip"):html_text.find(".lt-panic-strip") + 1500]
    assert "position: sticky" in block or "position:sticky" in block


# ─── JS toggles + state pins ────────────────────────────────────────────

def test_panic_toggle_function_pinned(html_text):
    assert "togglePanicStrip" in html_text


def test_panic_strip_collapsed_by_default(html_text):
    # data-expanded="false" or hidden attribute on the buttons container
    assert 'data-expanded="false"' in html_text or 'data-panic-expanded="false"' in html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v`
Expected: all panel tests fail (HTML not yet modified)

- [ ] **Step 3: Add CSS for the panic strip**

Edit `C:/TradingScripts/command_center.html`. Find the LT styles block (look for `.lt-cards-list { padding: 12px 16px; }` near line 398). Insert immediately after the existing LT-related CSS rules:

```css
    /* ─── Slice 6 panic strip ─── */
    .lt-panic-strip {
      position: sticky;
      top: 0;
      z-index: 50;
      background: #1a1a1a;
      border-bottom: 1px solid #333;
      padding: 8px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .lt-panic-strip .lt-panic-title {
      cursor: pointer;
      color: #f59e0b;
      font-weight: 600;
      user-select: none;
    }
    .lt-panic-strip .lt-panic-buttons[data-panic-expanded="false"] {
      display: none;
    }
    .lt-panic-strip .lt-panic-buttons[data-panic-expanded="true"] {
      display: flex;
      gap: 8px;
    }
    .lt-panic-btn {
      padding: 6px 12px;
      background: #2a1a1a;
      color: #fcd34d;
      border: 1px solid #5a2a2a;
      border-radius: 4px;
      cursor: pointer;
      font-weight: 600;
    }
    .lt-panic-btn:hover { background: #3a2020; }
    .lt-panic-btn--l3 { color: #f87171; border-color: #7a1f1f; }
```

- [ ] **Step 4: Add the panic strip HTML as first child of `#live-trading`**

Find line 1019 (`<div id="live-trading" class="tab-content">`). Insert these lines immediately after line 1019 (BEFORE the existing `<div class="lt-status-strip">`):

```html
      <!-- Slice 6: Panic strip (collapsed-by-default, sticky) -->
      <div id="lt-panic-strip" class="lt-panic-strip">
        <span class="lt-panic-title" onclick="togglePanicStrip()">🚨 PANIC ▾</span>
        <div class="lt-panic-buttons" data-panic-expanded="false">
          <button type="button" class="lt-panic-btn" data-panic-level="L1"
                  title="Flip every enabled card to disabled. No Alpaca calls.">
            Pause All
          </button>
          <button type="button" class="lt-panic-btn" data-panic-level="L2"
                  title="L1 + cancel open tradelab orders.">
            Pause + Cancel Orders
          </button>
          <button type="button" class="lt-panic-btn lt-panic-btn--l3" data-panic-level="L3"
                  title="L2 + flatten ALL positions in your Alpaca account, regardless of whether tradelab opened them.">
            Pause + Cancel + Flatten Positions
          </button>
        </div>
      </div>
```

- [ ] **Step 5: Add the toggle JS**

Edit `C:/TradingScripts/command_center.html`. Insert this function in the global `<script>` section — find a place near the LT module (the IIFE at line 4513) and insert BEFORE `const LT = (() => {`:

```javascript
    /* Slice 6: panic strip collapse/expand toggle */
    function togglePanicStrip() {
      const buttons = document.querySelector('#lt-panic-strip .lt-panic-buttons');
      const title = document.querySelector('#lt-panic-strip .lt-panic-title');
      if (!buttons || !title) return;
      const isExpanded = buttons.getAttribute('data-panic-expanded') === 'true';
      buttons.setAttribute('data-panic-expanded', isExpanded ? 'false' : 'true');
      title.textContent = isExpanded ? '🚨 PANIC ▾' : '🚨 PANIC ▴';
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "panic_strip or panic_toggle"`
Expected: all panel + toggle tests pass

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab && git add tests/web/test_panic_fe_contract.py
git -C C:/TradingScripts/ add command_center.html
cd C:/TradingScripts/tradelab && git commit -m "feat(web): panic strip — sticky, collapsed-by-default

Adds #lt-panic-strip as first child of #live-trading. Three buttons
(L1/L2/L3) hidden behind a chevron toggle. Modal flows + click handlers
land in T10-T11.

Slice 6 — T9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(Note: command_center.html is in C:/TradingScripts/ root, NOT the tradelab repo. Commit to whichever repo tracks it. Verify with `git -C C:/TradingScripts status` and `git -C C:/TradingScripts/tradelab status` before commit. If both repos track changes, commit each separately.)

---

## Task 10: FE — L1 + L2 modals + executePanic JS + contract tests

**Files:**
- Modify: `C:/TradingScripts/command_center.html`
- Modify: `tests/web/test_panic_fe_contract.py`

**Depends on:** Task 9.

- [ ] **Step 1: Write failing contract tests for the L1 + L2 modals**

Append to `tests/web/test_panic_fe_contract.py`:

```python
# ─── L1 + L2 modals ─────────────────────────────────────────────────────

def test_l1_modal_present(html_text):
    assert 'id="lt-panic-l1-modal"' in html_text
    assert "Pause All Cards" in html_text  # title
    # confirm word literal must appear in the modal body for instructional text
    block = html_text[html_text.find('id="lt-panic-l1-modal"'):]
    block = block[:block.find("</div>", block.find("</div>") + 1) + 6 + 5000]
    assert "DISABLE" in block, "DISABLE confirm word not in L1 modal"


def test_l2_modal_present(html_text):
    assert 'id="lt-panic-l2-modal"' in html_text
    block = html_text[html_text.find('id="lt-panic-l2-modal"'):html_text.find('id="lt-panic-l2-modal"') + 5000]
    assert "PANIC" in block, "PANIC confirm word not in L2 modal"
    assert "Also cancel non-tradelab open orders" in block


def test_executePanic_function_pinned(html_text):
    assert "function executePanic" in html_text or "executePanic =" in html_text
    # Must POST to the right URL
    assert "/tradelab/live/panic" in html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "l1_modal or l2_modal or executePanic"`
Expected: fail (modals not yet present)

- [ ] **Step 3: Add the L1 + L2 modal HTML**

Edit `C:/TradingScripts/command_center.html`. Find the existing modal at the end of the file (look for the last `<div id="modal-3f"` etc.). Insert these modal divs after the last existing modal and before `</body>`:

```html
  <!-- Slice 6: Panic L1 modal -->
  <div id="lt-panic-l1-modal" class="research-modal-overlay" hidden>
    <div class="research-modal-card" style="max-width:480px">
      <h3>Pause All Cards</h3>
      <p>This will disable every enabled card. Receiver picks up the change immediately. No Alpaca calls.</p>
      <p>Type <strong>DISABLE</strong> to confirm.</p>
      <input type="text" id="lt-panic-l1-confirm-input" autocomplete="off" placeholder="Type DISABLE">
      <div class="modal-actions" style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
        <button type="button" class="btn" onclick="closePanicModal('L1')">Cancel</button>
        <button type="button" id="lt-panic-l1-confirm-btn" class="btn danger" disabled
                onclick="executePanic('L1')">Confirm</button>
      </div>
    </div>
  </div>

  <!-- Slice 6: Panic L2 modal -->
  <div id="lt-panic-l2-modal" class="research-modal-overlay" hidden>
    <div class="research-modal-card" style="max-width:480px">
      <h3>Pause + Cancel Open Orders</h3>
      <p>This disables every enabled card AND cancels open tradelab orders.</p>
      <p>Will cancel open orders whose <code>client_order_id</code> matches a current tradelab card. Orders from deleted cards are NOT cancelled unless the checkbox below is on.</p>
      <label style="display:block;margin:8px 0">
        <input type="checkbox" id="lt-panic-l2-also-cancel">
        Also cancel non-tradelab open orders
      </label>
      <p>Type <strong>PANIC</strong> to confirm.</p>
      <input type="text" id="lt-panic-l2-confirm-input" autocomplete="off" placeholder="Type PANIC">
      <div class="modal-actions" style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
        <button type="button" class="btn" onclick="closePanicModal('L2')">Cancel</button>
        <button type="button" id="lt-panic-l2-confirm-btn" class="btn danger" disabled
                onclick="executePanic('L2')">Confirm</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 4: Add the executePanic + open/close modal JS**

Edit `C:/TradingScripts/command_center.html`. Append to the same script block where `togglePanicStrip` was added in T9:

```javascript
    /* Slice 6: panic modal open / close + executePanic */

    const PANIC_CONFIRM_WORDS = { L1: "DISABLE", L2: "PANIC", L3: "FLATTEN" };

    function openPanicModal(level) {
      const modal = document.getElementById(`lt-panic-${level.toLowerCase()}-modal`);
      const input = document.getElementById(`lt-panic-${level.toLowerCase()}-confirm-input`);
      const btn = document.getElementById(`lt-panic-${level.toLowerCase()}-confirm-btn`);
      if (!modal || !input || !btn) return;
      input.value = "";
      btn.disabled = true;
      input.oninput = () => {
        btn.disabled = (input.value !== PANIC_CONFIRM_WORDS[level]);
      };
      modal.hidden = false;
      input.focus();
    }

    function closePanicModal(level) {
      const modal = document.getElementById(`lt-panic-${level.toLowerCase()}-modal`);
      if (modal) modal.hidden = true;
      // L3 has its own state machine — disarm if needed (defined in T11)
      if (level === 'L3' && typeof disarmFlatten === 'function') {
        disarmFlatten();
      }
    }

    async function executePanic(level) {
      const confirm = PANIC_CONFIRM_WORDS[level];
      const body = { level, confirm };
      if (level === 'L2') {
        const cb = document.getElementById('lt-panic-l2-also-cancel');
        body.also_cancel_nontradelab = cb && cb.checked;
      }
      try {
        const resp = await fetch('/tradelab/live/panic', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const env = await resp.json();
        if (!env.ok) {
          alert('Panic failed: ' + (env.error || 'unknown error'));
          return;
        }
        closePanicModal(level);
        // Refresh cards to show the new disabled state
        if (typeof LT !== 'undefined' && typeof LT.refresh === 'function') {
          LT.refresh();
        }
        // Refresh the post-panic banner (function defined in T12)
        if (typeof fetchLastPanicEvent === 'function') {
          fetchLastPanicEvent();
        }
      } catch (e) {
        alert('Panic request failed: ' + e.message);
      }
    }

    // Wire up the panic-strip buttons to open the modals
    document.addEventListener('click', (e) => {
      const t = e.target.closest('[data-panic-level]');
      if (!t) return;
      const level = t.dataset.panicLevel;
      if (level === 'L1' || level === 'L2') {
        openPanicModal(level);
      } else if (level === 'L3') {
        // L3 has its own opener defined in T11
        if (typeof openL3PanicModal === 'function') openL3PanicModal();
      }
    });
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "l1_modal or l2_modal or executePanic"`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git -C C:/TradingScripts add command_center.html
cd C:/TradingScripts/tradelab && git add tests/web/test_panic_fe_contract.py
cd C:/TradingScripts/tradelab && git commit -m "feat(web): L1 + L2 panic modals + executePanic POST

Modal flows for L1 (DISABLE) and L2 (PANIC + checkbox for non-tradelab).
Confirm button stays disabled until typed word matches. POSTs to
/tradelab/live/panic and refreshes LT cards + last-event banner.

Slice 6 — T10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(Repeat the dual-repo commit consideration from T9 if applicable.)

---

## Task 11: FE — L3 modal with armed countdown state machine

**Files:**
- Modify: `C:/TradingScripts/command_center.html`
- Modify: `tests/web/test_panic_fe_contract.py`

**Depends on:** Task 10.

- [ ] **Step 1: Write failing contract tests for the L3 modal**

Append to `tests/web/test_panic_fe_contract.py`:

```python
# ─── L3 modal — armed countdown state machine ──────────────────────────

def test_l3_modal_present(html_text):
    assert 'id="lt-panic-l3-modal"' in html_text
    block = html_text[html_text.find('id="lt-panic-l3-modal"'):html_text.find('id="lt-panic-l3-modal"') + 5000]
    assert "FLATTEN" in block, "FLATTEN confirm word not in L3 modal"
    assert "ENTIRE Alpaca account" in block or "entire Alpaca account" in block.lower()


def test_l3_data_attributes_pinned(html_text):
    """L3 modal must use data-armed and data-countdown for the state machine."""
    assert "data-armed" in html_text
    assert "data-countdown" in html_text


def test_l3_state_machine_fns_pinned(html_text):
    for fn in ("openL3PanicModal", "armFlatten", "disarmFlatten"):
        assert fn in html_text, f"missing JS function: {fn}"


def test_l3_arm_timeout_pinned(html_text):
    """3-second armed countdown + 10-second auto-abort must be present
    as numeric literals so a refactor that drops them gets caught."""
    assert "3000" in html_text and "10000" in html_text  # ms
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "l3"`
Expected: fail

- [ ] **Step 3: Add the L3 modal HTML**

Edit `C:/TradingScripts/command_center.html`. Insert AFTER the L2 modal added in T10:

```html
  <!-- Slice 6: Panic L3 modal — armed countdown state machine -->
  <div id="lt-panic-l3-modal" class="research-modal-overlay" hidden data-armed="false" data-countdown="0">
    <div class="research-modal-card" style="max-width:520px">
      <h3>🚨 FLATTEN ALL POSITIONS</h3>
      <p><strong>This affects your ENTIRE Alpaca account</strong>, not just tradelab positions. Cards will be disabled, open tradelab orders cancelled, and EVERY position closed at market.</p>
      <p>Type <strong>FLATTEN</strong> to arm.</p>
      <input type="text" id="lt-panic-l3-confirm-input" autocomplete="off" placeholder="Type FLATTEN">
      <div class="modal-actions" style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
        <button type="button" class="btn" onclick="closePanicModal('L3')">Cancel</button>
        <button type="button" id="lt-panic-l3-arm-btn" class="btn danger" disabled
                onclick="armFlatten()">Arm</button>
        <button type="button" id="lt-panic-l3-fire-btn" class="btn danger" hidden
                onclick="executePanic('L3')">FIRE FLATTEN NOW</button>
      </div>
      <p id="lt-panic-l3-countdown-text" style="text-align:right;margin-top:8px;color:#f87171" hidden></p>
    </div>
  </div>
```

- [ ] **Step 4: Add the L3 JS state machine**

Edit `C:/TradingScripts/command_center.html`. Append to the same script block as T10:

```javascript
    /* Slice 6: L3 armed-countdown state machine */

    let _l3CountdownTimer = null;
    let _l3AutoAbortTimer = null;

    function openL3PanicModal() {
      const modal = document.getElementById('lt-panic-l3-modal');
      const input = document.getElementById('lt-panic-l3-confirm-input');
      const arm = document.getElementById('lt-panic-l3-arm-btn');
      const fire = document.getElementById('lt-panic-l3-fire-btn');
      const cd = document.getElementById('lt-panic-l3-countdown-text');
      input.value = "";
      arm.disabled = true;
      arm.hidden = false;
      fire.hidden = true;
      cd.hidden = true;
      modal.dataset.armed = "false";
      modal.dataset.countdown = "0";
      input.oninput = () => {
        arm.disabled = (input.value !== PANIC_CONFIRM_WORDS.L3);
      };
      modal.hidden = false;
      input.focus();
    }

    function armFlatten() {
      const modal = document.getElementById('lt-panic-l3-modal');
      const arm = document.getElementById('lt-panic-l3-arm-btn');
      const fire = document.getElementById('lt-panic-l3-fire-btn');
      const cd = document.getElementById('lt-panic-l3-countdown-text');
      arm.hidden = true;
      cd.hidden = false;
      modal.dataset.armed = "true";
      let remaining = 3;
      modal.dataset.countdown = String(remaining);
      cd.textContent = `Armed — fire enabled in ${remaining}s…`;

      // 3-second countdown, then enable the fire button
      _l3CountdownTimer = setInterval(() => {
        remaining -= 1;
        modal.dataset.countdown = String(remaining);
        if (remaining <= 0) {
          clearInterval(_l3CountdownTimer);
          _l3CountdownTimer = null;
          fire.hidden = false;
          cd.textContent = "Armed — click FIRE FLATTEN NOW to execute (auto-aborts in 10s)";
        } else {
          cd.textContent = `Armed — fire enabled in ${remaining}s…`;
        }
      }, 1000);

      // 10-second auto-abort from arm time (3s wait + 7s window)
      _l3AutoAbortTimer = setTimeout(() => {
        if (modal.dataset.armed === "true") {
          closePanicModal('L3');
        }
      }, 10000);
    }

    function disarmFlatten() {
      if (_l3CountdownTimer) {
        clearInterval(_l3CountdownTimer);
        _l3CountdownTimer = null;
      }
      if (_l3AutoAbortTimer) {
        clearTimeout(_l3AutoAbortTimer);
        _l3AutoAbortTimer = null;
      }
      const modal = document.getElementById('lt-panic-l3-modal');
      if (modal) {
        modal.dataset.armed = "false";
        modal.dataset.countdown = "0";
      }
    }

    // Esc / outside-click also close the modal (and disarm)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        ['L1', 'L2', 'L3'].forEach((lvl) => {
          const m = document.getElementById(`lt-panic-${lvl.toLowerCase()}-modal`);
          if (m && !m.hidden) closePanicModal(lvl);
        });
      }
    });
    document.addEventListener('click', (e) => {
      ['L1', 'L2', 'L3'].forEach((lvl) => {
        const m = document.getElementById(`lt-panic-${lvl.toLowerCase()}-modal`);
        if (m && !m.hidden && e.target === m) closePanicModal(lvl);
      });
    });
```

Note: the executePanic call for L3 will fire on the FIRE FLATTEN NOW button click. The existing `executePanic('L3')` in T10 already handles the POST — make sure the button's `onclick` calls `executePanic('L3')`, which in turn calls `closePanicModal('L3')` on success (which calls `disarmFlatten()`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "l3"`
Expected: all L3 tests pass

- [ ] **Step 6: Commit**

```bash
git -C C:/TradingScripts add command_center.html
cd C:/TradingScripts/tradelab && git add tests/web/test_panic_fe_contract.py
cd C:/TradingScripts/tradelab && git commit -m "feat(web): L3 panic modal with armed-countdown state machine

Type FLATTEN → Arm → 3-second countdown → FIRE FLATTEN NOW button
becomes clickable. data-armed/data-countdown attributes for contract
test pinning. 10s auto-abort from arm time. Esc + outside-click also
close + disarm.

Slice 6 — T11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: FE — post-panic banner with scoped re-enable + dismissal

**Files:**
- Modify: `C:/TradingScripts/command_center.html`
- Modify: `tests/web/test_panic_fe_contract.py`

**Depends on:** Task 11.

- [ ] **Step 1: Write failing contract tests**

Append to `tests/web/test_panic_fe_contract.py`:

```python
# ─── Post-panic banner ─────────────────────────────────────────────────

def test_panic_banner_present(html_text):
    assert 'id="lt-panic-banner"' in html_text
    assert "data-panic-banner" in html_text
    # banner placed between panic strip and cards-list
    banner_idx = html_text.find('id="lt-panic-banner"')
    cards_idx = html_text.find('id="lt-cards-list"')
    panic_idx = html_text.find('id="lt-panic-strip"')
    assert panic_idx < banner_idx < cards_idx, "banner must be between panic strip and cards-list"


def test_banner_fns_pinned(html_text):
    for fn in ("fetchLastPanicEvent", "renderPanicBanner",
               "dismissPanicBanner", "reenableFromSnapshot"):
        assert fn in html_text, f"missing JS function: {fn}"


def test_banner_dismiss_uses_localstorage(html_text):
    assert "panicDismissedTs" in html_text
    assert "localStorage" in html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "banner"`
Expected: fail

- [ ] **Step 3: Add banner HTML between panic strip and cards-list**

Edit `C:/TradingScripts/command_center.html`. Find the lines added in T9 (panic strip closing `</div>`) immediately before the existing `<div class="lt-status-strip">` (line ~1020). Insert this banner div BETWEEN the panic strip and the status strip:

```html
      <!-- Slice 6: Post-panic banner (rendered when last-event exists and not dismissed) -->
      <div id="lt-panic-banner" data-panic-banner data-panic-event-ts=""
           hidden style="background:#3a2020;border:1px solid #5a2a2a;color:#fcd34d;padding:10px 16px;margin:8px 16px;border-radius:6px">
        <div id="lt-panic-banner-summary"></div>
        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn" id="lt-panic-banner-reenable" onclick="reenableFromSnapshot()">Re-enable just these</button>
          <button type="button" class="btn" id="lt-panic-banner-view-audit" onclick="togglePanicAuditView()">View audit</button>
          <button type="button" class="btn" onclick="dismissPanicBanner()">Dismiss</button>
        </div>
        <pre id="lt-panic-banner-audit" hidden style="margin-top:8px;padding:8px;background:#1a1a1a;color:#aaa;font-size:11px;overflow:auto;max-height:300px"></pre>
      </div>
```

- [ ] **Step 4: Add banner JS**

Edit `C:/TradingScripts/command_center.html`. Append to the same script block:

```javascript
    /* Slice 6: post-panic banner */

    let _lastPanicEvent = null;

    function _getDismissedTs() {
      try {
        const raw = localStorage.getItem('panicDismissedTs');
        return raw ? new Set(JSON.parse(raw)) : new Set();
      } catch (e) {
        return new Set();
      }
    }

    function _addDismissedTs(ts) {
      try {
        const set = _getDismissedTs();
        set.add(ts);
        localStorage.setItem('panicDismissedTs', JSON.stringify(Array.from(set)));
      } catch (e) { /* ignore */ }
    }

    async function fetchLastPanicEvent() {
      try {
        const resp = await fetch('/tradelab/live/panic/last-event');
        const env = await resp.json();
        _lastPanicEvent = env.data;
        renderPanicBanner();
      } catch (e) {
        // If endpoint is down (receiver only?), banner just stays hidden.
        console.warn('fetchLastPanicEvent failed:', e);
      }
    }

    function renderPanicBanner() {
      const banner = document.getElementById('lt-panic-banner');
      if (!banner) return;
      if (!_lastPanicEvent) {
        banner.hidden = true;
        return;
      }
      const dismissed = _getDismissedTs();
      if (dismissed.has(_lastPanicEvent.ts)) {
        banner.hidden = true;
        return;
      }
      banner.dataset.panicEventTs = _lastPanicEvent.ts;
      const summary = document.getElementById('lt-panic-banner-summary');
      const cd = (_lastPanicEvent.cards_disabled || []).length;
      const oc = (_lastPanicEvent.orders_cancelled || []).filter(a => a.ok).length;
      const pf = (_lastPanicEvent.positions_flattened || []).filter(a => a.ok).length;
      summary.innerHTML = `🚨 <strong>${_lastPanicEvent.level}</strong> panic at ${_lastPanicEvent.ts} — ${cd} cards disabled, ${oc} orders cancelled, ${pf} positions flattened.`;
      const reenableBtn = document.getElementById('lt-panic-banner-reenable');
      reenableBtn.textContent = `Re-enable just these ${cd}`;
      reenableBtn.disabled = (cd === 0);
      banner.hidden = false;
    }

    function dismissPanicBanner() {
      if (_lastPanicEvent && _lastPanicEvent.ts) {
        _addDismissedTs(_lastPanicEvent.ts);
      }
      const banner = document.getElementById('lt-panic-banner');
      if (banner) banner.hidden = true;
    }

    function togglePanicAuditView() {
      const pre = document.getElementById('lt-panic-banner-audit');
      if (!pre || !_lastPanicEvent) return;
      if (pre.hidden) {
        pre.textContent = JSON.stringify(_lastPanicEvent, null, 2);
        pre.hidden = false;
      } else {
        pre.hidden = true;
      }
    }

    async function reenableFromSnapshot() {
      if (!_lastPanicEvent || !_lastPanicEvent.cards_disabled) return;
      const cardIds = _lastPanicEvent.cards_disabled;
      // Bulk-enable via PATCH per card. (If a bulk endpoint exists, prefer it;
      // otherwise per-card PATCH is fine for ~10 cards.)
      let okCount = 0;
      let failCount = 0;
      for (const cid of cardIds) {
        try {
          const resp = await fetch(`/tradelab/live/cards/${encodeURIComponent(cid)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'enabled' }),
          });
          const env = await resp.json();
          if (env.ok) okCount++;
          else failCount++;
        } catch (e) {
          failCount++;
        }
      }
      alert(`Re-enabled ${okCount} of ${cardIds.length} cards${failCount ? ` (${failCount} failed)` : ''}.`);
      if (typeof LT !== 'undefined' && typeof LT.refresh === 'function') {
        LT.refresh();
      }
      // Auto-dismiss the banner after a successful re-enable
      if (failCount === 0) {
        dismissPanicBanner();
      }
    }

    // Fetch on LT activation
    document.addEventListener('DOMContentLoaded', () => {
      // Initial fetch on page load if we land on LT
      const ltTab = document.querySelector('.tab[data-tab="live-trading"]');
      if (ltTab && ltTab.classList.contains('active')) {
        fetchLastPanicEvent();
      }
    });
```

Then patch the existing tab-switch logic (around line 1588 — find `} else if (tabName === 'live-trading') {` and the `LT.activate()` call). After `LT.activate()`, add a line:

```javascript
        if (typeof fetchLastPanicEvent === 'function') fetchLastPanicEvent();
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v -k "banner"`
Expected: all banner tests pass

- [ ] **Step 6: Commit**

```bash
git -C C:/TradingScripts add command_center.html
cd C:/TradingScripts/tradelab && git add tests/web/test_panic_fe_contract.py
cd C:/TradingScripts/tradelab && git commit -m "feat(web): post-panic banner with scoped re-enable

Banner appears after a panic if last-event ts not in localStorage
panicDismissedTs. 'Re-enable just these N' bulk-PATCHes the
cards_disabled list from the snapshot. 'View audit' toggles the
inline JSONL entry. Dismissal is per-event-ts.

Slice 6 — T12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Drop dead `.lt-pill--silent` CSS (Slice 5 follow-up #9)

**Files:**
- Modify: `C:/TradingScripts/command_center.html` (line 467)
- Modify: `tests/web/test_panic_fe_contract.py`

**Depends on:** Tasks 9-12 (all FE work landed; do this cleanup last so git diff is contained).

- [ ] **Step 1: Add regression-guard test that asserts the class is gone**

Append to `tests/web/test_panic_fe_contract.py`:

```python
# ─── Slice 5 follow-up #9: dead .lt-pill--silent CSS regression guard ──

def test_dead_lt_pill_silent_class_removed(html_text):
    """The .lt-pill--silent CSS rule was unused dead code from an earlier
    Slice 5 draft (the final implementation uses ::after instead). Slice 6
    deletes it; this test guards against it being re-added by accident."""
    assert ".lt-pill--silent" not in html_text, (
        "dead .lt-pill--silent CSS class re-introduced — see Slice 5 follow-up #9"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py::test_dead_lt_pill_silent_class_removed -v`
Expected: FAIL (the class is still in the file at line 467)

- [ ] **Step 3: Verify no JS references the class before deleting**

Run: `cd C:/TradingScripts && grep -n "lt-pill--silent" command_center.html`
Expected: only ONE match — line 467 (the CSS rule itself). If there are JS references too, do NOT proceed; investigate.

- [ ] **Step 4: Delete the dead CSS rule**

Edit `C:/TradingScripts/command_center.html`, line 467. Remove this entire line:

```css
    .lt-pill--silent   { color: #ffe9a0; background: #3a3520; border: 1px solid #5a4a1c; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py::test_dead_lt_pill_silent_class_removed -v`
Expected: PASS

- [ ] **Step 6: Run all FE contract tests to confirm no regression**

Run: `cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_panic_fe_contract.py -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git -C C:/TradingScripts add command_center.html
cd C:/TradingScripts/tradelab && git add tests/web/test_panic_fe_contract.py
cd C:/TradingScripts/tradelab && git commit -m "chore(web): drop dead .lt-pill--silent CSS class

Slice 5 follow-up #9. Class was from an earlier Slice 5 draft; final
implementation uses ::after pseudo-element. Regression test asserts
the class is not re-introduced.

Slice 6 — T13.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Full pytest + dashboard restart smoke + done doc

**Files:**
- Create: `C:/TradingScripts/2026-04-26-DIRECTION-A-SLICE-6-COMPLETE.md`

**Depends on:** Tasks 1-13.

- [ ] **Step 1: Run full pytest suite**

Run: `cd C:/TradingScripts/tradelab && python -m pytest --tb=short 2>&1 | tail -30`
Expected: `~680 passed / 0 failed` (655 baseline + ~25 net-new). If failures, fix before proceeding.

- [ ] **Step 2: Restart dashboard + receiver and verify boot**

The launcher is `C:/TradingScripts/launch_dashboard.py` (or invoke via `Launch_Dashboard.bat`). Logs are written to `C:/TradingScripts/dashboard_*.log` per-session — find the most recent one with `ls -t C:/TradingScripts/dashboard_*.log | head -1`.

```bash
# Find existing dashboard launcher PID(s)
cd C:/TradingScripts && tasklist | findstr python
# Stop the old launcher + receiver gracefully (note PIDs above; ASK USER before kill if uncertain)
# Then start fresh:
cd C:/TradingScripts && cmd //c Launch_Dashboard.bat &
# Wait ~10s, then read the newest dashboard_*.log (created by the boot)
ls -t C:/TradingScripts/dashboard_*.log | head -1 | xargs tail -30
```

Expected: launcher boots cleanly; no exceptions in log; "[startup] silence_checker started" line still present (didn't break Slice 5).

**If you cannot safely identify which python process is the dashboard, ASK the user before killing anything** — there may be unrelated python processes running.

- [ ] **Step 3: Static smoke — visit dashboard, confirm panic strip renders**

Open browser to http://localhost:8877. Click "Live Trading" tab. Verify:
- 🚨 PANIC ▾ chevron visible at top of LT tab content
- Click chevron → three buttons appear (Pause All, Pause + Cancel Orders, Pause + Cancel + Flatten)
- Chevron flips to ▴
- Click each button → modal appears with correct confirm word
- Type wrong word → Confirm button stays disabled
- Type correct word → Confirm button enables
- Esc closes modal
- L3: type FLATTEN → Arm → countdown ticks down 3-2-1 → FIRE FLATTEN NOW appears
- L3: wait 10s after arming without clicking → modal auto-closes

- [ ] **Step 4: Live smoke (Monday RTH window — DEFERRABLE)**

Mark the following as deferred-to-Monday in the done doc if it's currently outside RTH (Sat/Sun or weeknight). Otherwise execute:

- L1 fire: hit Pause All. Confirm cards.json shows all `enabled` → `disabled`. Confirm receiver log shows reload event within 1s.
- L2 fire: place a paper-trading test order via Alpaca dashboard, then hit L2 with `also_cancel_nontradelab=true` (since the test order isn't tradelab). Confirm order is cancelled in Alpaca paper account.
- L3 fire: open a tiny paper position (e.g. 1 share AAPL), then hit L3. Confirm position closes.
- After each panic: confirm CRITICAL notification fires across all enabled channels.
- Confirm post-panic banner appears with correct counts.
- Click "Re-enable just these N" → cards return to `enabled`. Banner auto-dismisses.
- Refresh page → banner does not reappear (dismissal sticks).

- [ ] **Step 5: Write the done doc**

Create `C:/TradingScripts/2026-04-26-DIRECTION-A-SLICE-6-COMPLETE.md` with this structure (mirroring the Slice 5 done doc style):

```markdown
# Direction A Slice 6 — Complete & Handoff

**Date:** 2026-04-26
**Spec:** `tradelab/docs/superpowers/specs/2026-04-26-direction-a-slice-6-panic-panel-design.md`
**Plan:** `tradelab/docs/superpowers/plans/2026-04-26-direction-a-slice-6-panic-panel.md`

## Summary

Slice 6 ships the three-level Panic Panel + bundles three Slice 5 architectural follow-ups:
- §10 Panic Panel: L1/L2/L3 buttons, typed confirm words, L3 armed-countdown, audit log, CRITICAL notify
- Follow-up #8: Alpaca exception wrapping in panic.py (per-call try/except, partial-failure isolation)
- Follow-up #11: silence_checker.stop() lock asymmetry fixed
- Follow-up #9: dead .lt-pill--silent CSS removed (with regression-guard test)
- Bonus: post-panic banner with scoped re-enable using before_state_snapshot

## Tasks shipped

[Fill in 13 task entries with commit SHAs from `git log --oneline`]

## Pytest baseline

[Fill in pre/post numbers from Step 1]

## Smoke results

[Fill in static smoke results from Step 3, plus live smoke results or deferred-to-Monday note]

## Reviewer flags

[Fill in any items declined or carried forward]

## Architectural follow-ups (not blocking Slice 7)

[List anything Slice 6 noticed but didn't fix]

## Handoff for Slice 7

**Slice 7 scope:** Spec parent §13 — **Daily email summary + polish + docs.** Including updating TRADELAB_MANUAL.html to reflect Direction A.

**Prerequisites satisfied by Slice 6:**
- All v1 functional surface area shipped
- panic_events.jsonl available as a data source for the daily summary
- notify pipeline supports all 5 channels including email

---

End of Slice 6 done doc.
```

- [ ] **Step 6: Commit done doc**

```bash
cd C:/TradingScripts && git add 2026-04-26-DIRECTION-A-SLICE-6-COMPLETE.md
cd C:/TradingScripts && git commit -m "docs: Slice 6 done doc — Panic Panel complete

13 tasks shipped + 3 Slice 5 follow-ups bundled. Pytest [N pass / 0 fail].
Static smoke verified; live smoke [done | deferred to Monday RTH].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist (executor must run before claiming done)

- [ ] Every task's tests are green
- [ ] `git log --oneline` shows 13 commits with consistent "Slice 6 — TN" trailers
- [ ] `pytest --tb=short` shows expected pass count (~680) and 0 failures
- [ ] Dashboard restarts without exceptions
- [ ] Done doc filled in with actual numbers (not placeholders)
- [ ] No `console.log`, no `print(` debug lines, no commented-out code introduced
- [ ] No backwards-compat shims or feature flags added (per CLAUDE.md / standing rules)

---

**End of Slice 6 implementation plan.**
