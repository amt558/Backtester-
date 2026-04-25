# Direction A — Slice 3 (Position Guardrails) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse unsafe orders at the receiver. Five guardrails (cooldown, daily-limit, symbol-collision, naked-short, buying-power) run between symbol-match and Alpaca submit; per-card override fields surface in a drawer below each Live Trading row.

**Architecture:** Pure check functions in a new `tradelab/live/guardrails.py` module. Receiver maintains an in-memory `_card_state` dict (cooldown timestamps + daily fire counts; rebuilt from `alerts.jsonl` on startup). Alpaca state (positions/open-orders/account) is fetched through a 2-second-cached `AlpacaState` wrapper so 10 cards firing close together do not slam the API. On a successful order submit the receiver writes `last_fired_at` back to `cards.json` (the existing watcher absorbs the resulting reload). Frontend adds a collapsible drawer below each `.lt-row` exposing the four override fields the PATCH endpoint already accepts (`allow_collision`, `allow_naked_short`, `daily_limit`, `cooldown_seconds`).

**Tech Stack:** Python stdlib (`datetime`, `zoneinfo`, `dataclasses`, `threading.Lock`), `alpaca-py` (already a tradelab dep), watchdog (already wired Slice 1), vanilla JS (no framework).

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `tradelab/src/tradelab/live/alpaca_state.py` | `AlpacaState` wrapper with 2-s TTL cache for positions / open orders / account; manual invalidation hook |
| Create | `tradelab/src/tradelab/live/guardrails.py` | 5 pure check functions + `evaluate_guardrails()` composer + `BlockReason` dataclass |
| Modify | `tradelab/src/tradelab/live/receiver.py` | `_card_state` dict, `record_attempt`/`record_fire` helpers, hydrate-from-alerts-on-startup, guardrail pipeline integration, write `last_fired_at` on success |
| Create | `tradelab/tests/live/test_alpaca_state.py` | Cache hit/miss/TTL/manual-invalidate; alpaca-py client mocked |
| Create | `tradelab/tests/live/test_guardrails.py` | One test per check + override behaviour + ordering of `evaluate_guardrails` |
| Create | `tradelab/tests/live/test_receiver_guardrails.py` | Webhook → blocked → 403 + `guardrail_blocked` alert; webhook → submit → `last_fired_at` written; receiver hydrates state from `alerts.jsonl` on startup |
| Modify | `command_center.html` (parent repo) | Drawer markup + CSS; toggle button; form fields; PATCH wiring |
| Modify | `tradelab/tests/web/test_command_center_html.py` | Pin new JS function names + drawer DOM contracts |
| Create | parent repo: `2026-04-25-DIRECTION-A-SLICE-3-COMPLETE.md` | Done doc + smoke checklist + Slice 4 handoff |

Baseline: 483 tests passing at end of Slice 2. Target end-of-Slice-3: ~510+ (≈25–30 net-new across guardrails + alpaca_state + receiver wiring + FE pins).

---

## Conventions (load-bearing — Slices 1+2 validated these)

- **TDD strict:** failing test → verify it fails for the right reason → minimal impl → green → commit.
- **Test layout:** `from __future__ import annotations` at top; pytest `tmp_path` fixture; mock alpaca-py `TradingClient` at the boundary, never the network. Use `monkeypatch.setattr(receiver, "ALERT_LOG", path)` and `monkeypatch.setattr(receiver, "cards", registry)` to override module-level singletons in receiver tests.
- **Response envelope at the receiver:** receiver returns `JSONResponse({"error": "<msg>"}, status_code=...)` for failures (existing pattern at receiver.py:185-227 — do NOT switch to the dashboard's `_ok`/`_err` envelope).
- **Validation lives in the handler/receiver (system boundary).** `CardRegistry.update` is internal — it trusts callers. Guardrail check functions trust their inputs (cards have already been hydrated).
- **Atomic write:** `last_fired_at` writes go through `CardRegistry.update` which uses the existing `_persist()` (`tmp.write_text → os.replace`). This fires the Slice 1 watchdog → receiver reloads — that is fine; the in-memory `_card_state` is the source of truth for cooldown/daily-limit, not the just-reloaded card dict.
- **Commits:** Direct to `master` in tradelab repo (no branches). Conventional `feat(layer): …`, `fix(layer): …`, `test(live): …`, `ui(command-center): …`. Footer required:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **HTML selectors (verified against current `command_center.html`):**
  - Live Trading tab content is `<div id="live-trading" class="tab-content">` (NOT `id="tab-live-trading"`).
  - Row grid is `.lt-row { grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px 80px 30px; }` — 11 columns. Slice 3 will add a 12th 30px column for the ⚙ overrides toggle button.
  - The drawer is rendered as a sibling `<div>` between groups, NOT inside `.lt-row` — `grid-column: 1/-1` would require nested grid; simpler is a separate `.lt-overrides-drawer` element rendered immediately after its row when expanded.
- **DO NOT** introduce a separate FastAPI app, framework, or rebuild the LT module. Extend the existing `LT = (() => { ... })()` IIFE at `command_center.html:4298`.
- **DO NOT** add a new PATCH endpoint — `_ALLOWED_PATCH_FIELDS` already includes all four override fields (`handlers.py:818-821`).
- **DO NOT** add a notification hook for `guardrail_blocked` — that's Slice 4. Slice 3 only logs to `alerts.jsonl`.

---

## Guardrail check order (single source of truth)

Per spec §9.1, checks run in this order between symbol-match and Alpaca submit. **Cheapest first, fail-fast.** First failure short-circuits; later checks do not run.

| # | Check | Reads | Reject reason string |
|---|---|---|---|
| 1 | Cooldown | `_card_state[card_id].last_attempted_at` | `cooldown_active` |
| 2 | Daily limit | `_card_state[card_id].fires_today` (window-aware) | `daily_limit_exceeded` |
| 3 | Symbol collision | All `_card_state` entries (other cards same symbol fired in last 30 s) | `symbol_collision` |
| 4 | Naked short | `alpaca_state.positions` (only when `alert.action == "sell"`) | `no_position_to_sell` |
| 5 | Buying power | `alpaca_state.account.buying_power` + open-orders notional | `insufficient_buying_power` |

**Important:** check #1 reads `last_attempted_at`, NOT `last_fired_at`. `last_attempted_at` is recorded BEFORE guardrails run (every webhook that passes secret + status + symbol-match increments it). This debounces a flood of attempts even if every one is blocking — without this, a TradingView misconfig sending 100 alerts/sec would each pass the cooldown check until one finally fired.

---

## Per-card runtime state (single source of truth)

```python
@dataclass
class CardRuntimeState:
    last_attempted_at: Optional[datetime] = None  # set on every webhook past symbol-match
    last_fired_at: Optional[datetime] = None       # set only on successful Alpaca submit
    fires_today: int = 0                           # count within current RTH window
    fire_window_start: Optional[datetime] = None   # most recent 9:30 ET <= now AT TIME OF LAST FIRE
```

`fires_today` resets lazily: when a fire is recorded and `now`'s current RTH window start differs from `fire_window_start`, count resets to 1 and window_start updates.

`get_current_rth_window_start(now)`: returns the most recent 9:30 America/New_York timestamp ≤ `now`. If `now` is before 9:30 ET on a weekday, returns the previous business day's 9:30 ET. Holidays are NOT special-cased in v1 — daily limit on a holiday simply uses the previous trading day's window, which is fine because no orders should fire on a closed market anyway.

State is kept entirely in memory. On receiver startup, `_hydrate_card_state_from_alerts_log()` scans the last N=500 entries of `alerts.jsonl` and rebuilds `last_fired_at` / `fires_today` for each card so a receiver restart mid-day does not reset everyone's counters to zero.

---

## Task 1: AlpacaState wrapper with 2-second cache

**Files:**
- Create: `tradelab/src/tradelab/live/alpaca_state.py`
- Create: `tradelab/tests/live/test_alpaca_state.py`

The wrapper isolates Alpaca-py interaction so guardrail tests can pass plain dataclass-shaped fakes without monkey-patching `TradingClient`. The 2-second TTL prevents 10 cards firing close together from each making 3 Alpaca round trips (positions + orders + account).

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_alpaca_state.py`:

```python
"""AlpacaState — 2-second cache around alpaca-py boundary."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from tradelab.live.alpaca_state import AlpacaState


def _client_with_returns(positions=None, orders=None, account=None):
    client = MagicMock()
    client.get_all_positions.return_value = positions or []
    client.get_orders.return_value = orders or []
    client.get_account.return_value = account or MagicMock(buying_power="100000")
    return client


def test_first_call_hits_alpaca():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=2.0)
    assert state.positions() == ["pos-A"]
    assert client.get_all_positions.call_count == 1


def test_second_call_within_ttl_uses_cache():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=2.0)
    state.positions()
    state.positions()
    assert client.get_all_positions.call_count == 1


def test_call_after_ttl_refetches():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=0.05)
    state.positions()
    time.sleep(0.1)
    state.positions()
    assert client.get_all_positions.call_count == 2


def test_invalidate_forces_refetch():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.positions()
    state.invalidate()
    state.positions()
    assert client.get_all_positions.call_count == 2


def test_positions_orders_account_caches_are_independent():
    client = _client_with_returns()
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.positions()
    state.open_orders()
    state.account()
    state.positions()
    state.open_orders()
    state.account()
    assert client.get_all_positions.call_count == 1
    assert client.get_orders.call_count == 1
    assert client.get_account.call_count == 1


def test_open_orders_filters_to_open_status():
    """get_orders is called with status='open' so we never see filled/cancelled."""
    client = _client_with_returns(orders=[MagicMock(status="open")])
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.open_orders()
    args, kwargs = client.get_orders.call_args
    # alpaca-py expects a GetOrdersRequest object; assert status hint is present
    # in either args or kwargs
    request = (args[0] if args else kwargs.get("filter") or kwargs.get("request"))
    assert request is not None, "expected a request arg"
```

- [ ] **Step 2: Run — expect ImportError on `tradelab.live.alpaca_state`**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_alpaca_state.py -v
```

Expected: ImportError / ModuleNotFoundError on `tradelab.live.alpaca_state`.

- [ ] **Step 3: Implement `alpaca_state.py`**

Create `tradelab/src/tradelab/live/alpaca_state.py`:

```python
"""2-second-cached read view over the Alpaca trading account.

Guardrails poll positions / open orders / buying-power frequently when many
cards fire at once. A short TTL makes 10 webhooks landing in the same second
do at most one fetch per resource, while still being fresh enough that a
just-submitted order's working notional is reflected on the next webhook
(callers invalidate after each successful submit).
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest


class AlpacaState:
    def __init__(self, client: Any, ttl_seconds: float = 2.0) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._lock = Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_cached(self, key: str, fetch):
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry and (now - entry[0]) < self._ttl:
                return entry[1]
        value = fetch()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def positions(self) -> list:
        return self._get_cached("positions", self._client.get_all_positions)

    def open_orders(self) -> list:
        def fetch():
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            return self._client.get_orders(filter=req)
        return self._get_cached("orders", fetch)

    def account(self):
        return self._get_cached("account", self._client.get_account)

    def invalidate(self) -> None:
        """Clear all caches. Call after any change that would invalidate
        positions / orders / buying-power (e.g., a successful submit)."""
        with self._lock:
            self._cache.clear()
```

- [ ] **Step 4: Run — all 6 tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_alpaca_state.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/alpaca_state.py tests/live/test_alpaca_state.py
git commit -m "$(cat <<'EOF'
feat(live): AlpacaState with 2-s cached positions/orders/account

Guardrails poll positions and buying power on every webhook; without a
cache, 10 cards firing close together would each round-trip Alpaca three
times. 2-s TTL is short enough that a just-submitted order's working
notional shows up on the next webhook (callers invalidate after submit).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Cooldown check + RTH-window helper

**Files:**
- Create: `tradelab/src/tradelab/live/guardrails.py`
- Create: `tradelab/tests/live/test_guardrails.py`

The `BlockReason` dataclass is the contract every check returns (or `None` to pass).

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/live/test_guardrails.py`:

```python
"""Position guardrails — pure functions returning Optional[BlockReason]."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradelab.live.guardrails import (
    BlockReason,
    CardRuntimeState,
    check_cooldown,
    get_rth_window_start,
)


# ── RTH window helper ────────────────────────────────────────────────

def test_rth_window_during_market_returns_today_930_et():
    # 2026-03-04 (Wed) 11:00 America/New_York == 16:00 UTC
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # 9:30 ET = 14:30 UTC on 2026-03-04
    assert start == datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc)


def test_rth_window_pre_market_returns_previous_business_day():
    # 2026-03-04 (Wed) 09:00 ET == 14:00 UTC (before 9:30)
    now = datetime(2026, 3, 4, 14, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # Previous business day = 2026-03-03 (Tue) 9:30 ET = 14:30 UTC
    assert start == datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)


def test_rth_window_monday_premarket_returns_friday():
    # 2026-03-09 (Mon) 06:00 ET == 11:00 UTC (before 9:30)
    now = datetime(2026, 3, 9, 11, 0, tzinfo=timezone.utc)
    start = get_rth_window_start(now)
    # Friday 2026-03-06 9:30 ET = 14:30 UTC
    assert start == datetime(2026, 3, 6, 14, 30, tzinfo=timezone.utc)


# ── Cooldown ─────────────────────────────────────────────────────────

def _card(cooldown_seconds=30, **overrides):
    base = {
        "card_id": "foo-v1", "symbol": "AAPL", "status": "enabled",
        "quantity": 1, "secret": "s" * 32,
        "cooldown_seconds": cooldown_seconds, "daily_limit": 5,
        "allow_collision": False, "allow_naked_short": False,
    }
    base.update(overrides)
    return base


def test_cooldown_no_prior_attempt_passes():
    state = CardRuntimeState()
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    assert check_cooldown(_card(), state, now) is None


def test_cooldown_within_window_blocks():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=10))
    reason = check_cooldown(_card(cooldown_seconds=30), state, now)
    assert reason is not None
    assert reason.code == "cooldown_active"


def test_cooldown_at_boundary_passes():
    """Exactly cooldown_seconds elapsed → allowed."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=30))
    assert check_cooldown(_card(cooldown_seconds=30), state, now) is None


def test_cooldown_zero_disables_check():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(milliseconds=1))
    assert check_cooldown(_card(cooldown_seconds=0), state, now) is None


def test_blockreason_carries_details():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(last_attempted_at=now - timedelta(seconds=5))
    reason = check_cooldown(_card(cooldown_seconds=30), state, now)
    assert reason.details["seconds_remaining"] == pytest.approx(25, abs=0.5)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

- [ ] **Step 3: Implement `guardrails.py` (just `BlockReason`, `CardRuntimeState`, `get_rth_window_start`, `check_cooldown`)**

Create `tradelab/src/tradelab/live/guardrails.py`:

```python
"""Position guardrails — pure check functions + composer.

Every check returns Optional[BlockReason]. None == pass; a value == reject.

Composer evaluate_guardrails() runs them in cheapest-first order and
short-circuits on first failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo


_NY = ZoneInfo("America/New_York")
_RTH_OPEN = time(9, 30)


@dataclass
class BlockReason:
    """Returned by a guardrail when an order must be rejected."""
    code: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class CardRuntimeState:
    """In-memory per-card runtime state held by the receiver."""
    last_attempted_at: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None
    fires_today: int = 0
    fire_window_start: Optional[datetime] = None


def get_rth_window_start(now: datetime) -> datetime:
    """Most recent 9:30 America/New_York <= now, returned in `now`'s tz.

    If `now` is before 9:30 ET on a weekday (or any time on Sat/Sun),
    walks back to the previous business day's 9:30 ET. US holidays are
    not special-cased in v1 — fires don't happen on closed markets so
    the previous-business-day window is harmless when one applies.
    """
    now_ny = now.astimezone(_NY)
    candidate = datetime.combine(now_ny.date(), _RTH_OPEN, tzinfo=_NY)
    while candidate > now_ny or candidate.weekday() >= 5:  # Sat=5, Sun=6
        candidate -= timedelta(days=1)
        candidate = candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    return candidate.astimezone(now.tzinfo or timezone.utc)


def check_cooldown(card: dict, state: CardRuntimeState, now: datetime) -> Optional[BlockReason]:
    cooldown = int(card.get("cooldown_seconds", 30))
    if cooldown <= 0 or state.last_attempted_at is None:
        return None
    elapsed = (now - state.last_attempted_at).total_seconds()
    if elapsed >= cooldown:
        return None
    return BlockReason(
        code="cooldown_active",
        message=f"cooldown active: {cooldown - elapsed:.1f}s remaining",
        details={"cooldown_seconds": cooldown, "seconds_remaining": cooldown - elapsed},
    )
```

- [ ] **Step 4: Run — all 7 tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): guardrails skeleton + cooldown check

BlockReason / CardRuntimeState dataclasses, RTH-window helper, and the
first guardrail (cooldown). Cooldown reads last_attempted_at (set on
every webhook past symbol-match) so a flood of attempts is debounced
even if every one is blocking.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Daily-limit check (RTH-window-aware)

**Files:**
- Modify: `tradelab/src/tradelab/live/guardrails.py` (append `check_daily_limit`)
- Modify: `tradelab/tests/live/test_guardrails.py` (append daily-limit tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/live/test_guardrails.py`:

```python
# ── Daily limit ──────────────────────────────────────────────────────

from tradelab.live.guardrails import check_daily_limit


def test_daily_limit_under_count_passes():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    window = datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc)  # today 9:30 ET
    state = CardRuntimeState(fires_today=2, fire_window_start=window)
    assert check_daily_limit(_card(daily_limit=5), state, now) is None


def test_daily_limit_at_count_blocks():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    window = datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc)
    state = CardRuntimeState(fires_today=5, fire_window_start=window)
    reason = check_daily_limit(_card(daily_limit=5), state, now)
    assert reason is not None
    assert reason.code == "daily_limit_exceeded"
    assert reason.details["fires_today"] == 5
    assert reason.details["daily_limit"] == 5


def test_daily_limit_over_count_blocks():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    window = datetime(2026, 3, 4, 14, 30, tzinfo=timezone.utc)
    state = CardRuntimeState(fires_today=10, fire_window_start=window)
    assert check_daily_limit(_card(daily_limit=5), state, now).code == "daily_limit_exceeded"


def test_daily_limit_zero_blocks_first_fire():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState()
    reason = check_daily_limit(_card(daily_limit=0), state, now)
    assert reason is not None
    assert reason.code == "daily_limit_exceeded"


def test_daily_limit_resets_when_window_changed():
    """fires_today from yesterday's window does not block today's first fire."""
    yesterday_open = datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)
    today = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(fires_today=99, fire_window_start=yesterday_open)
    assert check_daily_limit(_card(daily_limit=5), state, today) is None


def test_daily_limit_no_window_recorded_treated_as_zero_count():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    state = CardRuntimeState(fires_today=3, fire_window_start=None)
    # No window means we have no record of which RTH the count belongs to,
    # so we treat it as fresh (do NOT block on a stale-but-windowless count)
    assert check_daily_limit(_card(daily_limit=5), state, now) is None
```

- [ ] **Step 2: Run — 6 tests fail with ImportError on `check_daily_limit`**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

- [ ] **Step 3: Implement `check_daily_limit`**

Append to `tradelab/src/tradelab/live/guardrails.py`:

```python
def check_daily_limit(card: dict, state: CardRuntimeState, now: datetime) -> Optional[BlockReason]:
    limit = int(card.get("daily_limit", 5))
    current_window = get_rth_window_start(now)
    # Stale or absent window means the count cannot be attributed to today
    fires_today = (
        state.fires_today
        if state.fire_window_start is not None
        and state.fire_window_start >= current_window
        else 0
    )
    if fires_today < limit:
        return None
    return BlockReason(
        code="daily_limit_exceeded",
        message=f"daily limit reached: {fires_today}/{limit}",
        details={"fires_today": fires_today, "daily_limit": limit},
    )
```

- [ ] **Step 4: Run — all guardrail tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): daily-limit guardrail with RTH-window reset

Counts only fires whose recorded fire_window_start matches today's
9:30 ET window; stale or absent windows are treated as zero-count so a
receiver restart mid-day plus a 9pm-yesterday count never blocks today.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Symbol-collision check

**Files:**
- Modify: `tradelab/src/tradelab/live/guardrails.py`
- Modify: `tradelab/tests/live/test_guardrails.py`

Scans every other card's `last_fired_at` for collisions. Spec §9.1 puts the window at 30 s. The check needs the registry (so it can resolve `card_id → symbol` for other cards) and the `_card_state` dict.

- [ ] **Step 1: Append failing tests**

Append to `tests/live/test_guardrails.py`:

```python
# ── Symbol collision ────────────────────────────────────────────────

from tradelab.live.guardrails import check_symbol_collision


def _registry_dict(*cards):
    """Build the {card_id: card_dict} shape `cards.all_hydrated()` returns."""
    return {c["card_id"]: c for c in cards}


def test_collision_no_other_fires_passes():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    registry = _registry_dict(me)
    states = {"foo-v1": CardRuntimeState()}
    assert check_symbol_collision(me, registry, states, now) is None


def test_collision_other_card_same_symbol_within_window_blocks():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    other = _card(card_id="bar-v1", symbol="AAPL")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=10)),
    }
    reason = check_symbol_collision(me, registry, states, now)
    assert reason is not None
    assert reason.code == "symbol_collision"
    assert reason.details["other_card_id"] == "bar-v1"


def test_collision_other_card_different_symbol_passes():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    other = _card(card_id="bar-v1", symbol="MSFT")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=10)),
    }
    assert check_symbol_collision(me, registry, states, now) is None


def test_collision_outside_30s_window_passes():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    other = _card(card_id="bar-v1", symbol="AAPL")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=45)),
    }
    assert check_symbol_collision(me, registry, states, now) is None


def test_collision_self_fire_does_not_collide_with_itself():
    """My own last_fired_at must not block me — that's the cooldown's job."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    registry = _registry_dict(me)
    states = {"foo-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=5))}
    assert check_symbol_collision(me, registry, states, now) is None


def test_collision_disabled_other_card_does_not_block():
    """A disabled card whose state still has a recent last_fired_at must
    not block — disabled cards cannot have just fired (only stale state)."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    other = _card(card_id="bar-v1", symbol="AAPL", status="disabled")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=5)),
    }
    assert check_symbol_collision(me, registry, states, now) is None


def test_collision_allow_collision_override_passes():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL", allow_collision=True)
    other = _card(card_id="bar-v1", symbol="AAPL")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=5)),
    }
    assert check_symbol_collision(me, registry, states, now) is None
```

- [ ] **Step 2: Run — 7 ImportError-style failures**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

- [ ] **Step 3: Implement `check_symbol_collision`**

Append to `tradelab/src/tradelab/live/guardrails.py`:

```python
_COLLISION_WINDOW_SECONDS = 30


def check_symbol_collision(
    card: dict,
    registry: dict[str, dict],
    states: dict[str, CardRuntimeState],
    now: datetime,
) -> Optional[BlockReason]:
    if card.get("allow_collision"):
        return None
    my_id = card["card_id"]
    my_symbol = str(card.get("symbol", "")).upper()
    cutoff = now - timedelta(seconds=_COLLISION_WINDOW_SECONDS)
    for other_id, other_card in registry.items():
        if other_id == my_id:
            continue
        if other_card.get("status") != "enabled":
            continue
        if str(other_card.get("symbol", "")).upper() != my_symbol:
            continue
        other_state = states.get(other_id)
        if other_state is None or other_state.last_fired_at is None:
            continue
        if other_state.last_fired_at < cutoff:
            continue
        return BlockReason(
            code="symbol_collision",
            message=f"another card ({other_id}) fired {my_symbol} within {_COLLISION_WINDOW_SECONDS}s",
            details={
                "other_card_id": other_id,
                "symbol": my_symbol,
                "window_seconds": _COLLISION_WINDOW_SECONDS,
            },
        )
    return None
```

- [ ] **Step 4: Run — all guardrail tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): symbol-collision guardrail with allow_collision override

Blocks an order if any OTHER enabled card fired the same symbol in the
last 30 s. Self-fires never collide (that's the cooldown's job), disabled
cards' stale state never collides, and the per-card allow_collision flag
opts a hedge-pair card out entirely.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Naked-short check

**Files:**
- Modify: `tradelab/src/tradelab/live/guardrails.py`
- Modify: `tradelab/tests/live/test_guardrails.py`

A "naked short" is a sell with no inventory. The guardrail blocks any `action == "sell"` whose symbol has zero open positions in the Alpaca account, unless the per-card `allow_naked_short` override is true.

- [ ] **Step 1: Append failing tests**

Append to `tests/live/test_guardrails.py`:

```python
# ── Naked short ─────────────────────────────────────────────────────

from tradelab.live.guardrails import check_naked_short


class _Position:
    def __init__(self, symbol: str, qty: str = "10"):
        self.symbol = symbol
        self.qty = qty


class _AlpacaStateStub:
    def __init__(self, positions=None):
        self._positions = positions or []
    def positions(self):
        return self._positions


def test_naked_short_buy_action_passes_regardless():
    state = _AlpacaStateStub(positions=[])
    assert check_naked_short(_card(), "buy", state) is None


def test_naked_short_sell_with_position_passes():
    state = _AlpacaStateStub(positions=[_Position("AAPL", "10")])
    assert check_naked_short(_card(symbol="AAPL"), "sell", state) is None


def test_naked_short_sell_without_position_blocks():
    state = _AlpacaStateStub(positions=[_Position("MSFT", "5")])
    reason = check_naked_short(_card(symbol="AAPL"), "sell", state)
    assert reason is not None
    assert reason.code == "no_position_to_sell"
    assert reason.details["symbol"] == "AAPL"


def test_naked_short_sell_zero_qty_position_blocks():
    """A position record with qty=0 still means no inventory to sell."""
    state = _AlpacaStateStub(positions=[_Position("AAPL", "0")])
    reason = check_naked_short(_card(symbol="AAPL"), "sell", state)
    assert reason is not None
    assert reason.code == "no_position_to_sell"


def test_naked_short_allow_override_passes():
    state = _AlpacaStateStub(positions=[])
    card = _card(symbol="AAPL", allow_naked_short=True)
    assert check_naked_short(card, "sell", state) is None


def test_naked_short_symbol_match_is_case_insensitive():
    state = _AlpacaStateStub(positions=[_Position("aapl", "10")])
    assert check_naked_short(_card(symbol="AAPL"), "sell", state) is None
```

- [ ] **Step 2: Run — 6 ImportError-style failures**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

- [ ] **Step 3: Implement `check_naked_short`**

Append to `tradelab/src/tradelab/live/guardrails.py`:

```python
def check_naked_short(card: dict, action: str, alpaca_state) -> Optional[BlockReason]:
    if action != "sell":
        return None
    if card.get("allow_naked_short"):
        return None
    target = str(card.get("symbol", "")).upper()
    for pos in alpaca_state.positions():
        if str(getattr(pos, "symbol", "")).upper() != target:
            continue
        try:
            qty = float(getattr(pos, "qty", 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty > 0:
            return None
    return BlockReason(
        code="no_position_to_sell",
        message=f"sell rejected: no open position in {target}",
        details={"symbol": target},
    )
```

- [ ] **Step 4: Run — all guardrail tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): naked-short guardrail with allow_naked_short override

Blocks any sell whose symbol has no open Alpaca position. Buys are
unaffected. Per-card allow_naked_short flag opts a deliberate short
strategy out. Symbol comparison is case-insensitive; zero-qty position
records do not count as inventory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Buying-power check

**Files:**
- Modify: `tradelab/src/tradelab/live/guardrails.py`
- Modify: `tradelab/tests/live/test_guardrails.py`

Computes `(working_orders_notional + this_order_notional) > buying_power × max_exposure_pct`. Working notional sums each open order's `qty × price` where `price = limit_price or filled_avg_price or 0`. The new order's price is provided by the caller (the receiver pulls last-trade price from Alpaca and falls back to skipping the check on data unavailability).

- [ ] **Step 1: Append failing tests**

Append to `tests/live/test_guardrails.py`:

```python
# ── Buying power ────────────────────────────────────────────────────

from tradelab.live.guardrails import check_buying_power


class _Account:
    def __init__(self, buying_power: str):
        self.buying_power = buying_power


class _Order:
    def __init__(self, symbol: str, qty: str, limit_price: str | None = None,
                 filled_avg_price: str | None = None):
        self.symbol = symbol
        self.qty = qty
        self.limit_price = limit_price
        self.filled_avg_price = filled_avg_price


class _AlpacaStateStubBP:
    def __init__(self, buying_power: str = "100000", open_orders=None):
        self._account = _Account(buying_power)
        self._orders = open_orders or []
    def account(self):
        return self._account
    def open_orders(self):
        return self._orders


def test_buying_power_under_cap_passes():
    state = _AlpacaStateStubBP(buying_power="100000", open_orders=[])
    # 10 * $100 = $1k order against $100k bp * 0.9 = $90k cap -> pass
    assert check_buying_power(_card(), state, qty=10, last_price=100.0, max_exposure_pct=0.9) is None


def test_buying_power_over_cap_blocks():
    state = _AlpacaStateStubBP(buying_power="100000", open_orders=[])
    # 1000 * $100 = $100k order against $90k cap -> block
    reason = check_buying_power(_card(), state, qty=1000, last_price=100.0, max_exposure_pct=0.9)
    assert reason is not None
    assert reason.code == "insufficient_buying_power"
    assert reason.details["new_notional"] == pytest.approx(100000)
    assert reason.details["cap"] == pytest.approx(90000)


def test_buying_power_includes_open_orders_notional():
    """Working orders consume the same cap as the candidate."""
    state = _AlpacaStateStubBP(
        buying_power="100000",
        open_orders=[_Order("MSFT", qty="100", limit_price="500")],  # $50k working
    )
    # Candidate: 500 * $100 = $50k. 50k + 50k = 100k > 90k cap -> block
    reason = check_buying_power(_card(), state, qty=500, last_price=100.0, max_exposure_pct=0.9)
    assert reason is not None
    assert reason.code == "insufficient_buying_power"
    assert reason.details["working_notional"] == pytest.approx(50000)


def test_buying_power_open_order_uses_filled_avg_when_no_limit():
    state = _AlpacaStateStubBP(
        buying_power="100000",
        open_orders=[_Order("MSFT", qty="100", limit_price=None, filled_avg_price="400")],
    )
    # Working = 100 * 400 = 40k; cap = 90k; candidate 50k -> 90k <= 90k pass
    assert check_buying_power(_card(), state, qty=500, last_price=100.0, max_exposure_pct=0.9) is None


def test_buying_power_open_order_with_no_price_treated_as_zero():
    state = _AlpacaStateStubBP(
        buying_power="100000",
        open_orders=[_Order("MSFT", qty="100", limit_price=None, filled_avg_price=None)],
    )
    # Working = 0; candidate 50k against 90k cap -> pass
    assert check_buying_power(_card(), state, qty=500, last_price=100.0, max_exposure_pct=0.9) is None


def test_buying_power_at_boundary_passes():
    """Exactly at cap is allowed (>, not >=)."""
    state = _AlpacaStateStubBP(buying_power="100000", open_orders=[])
    # 900 * 100 = 90k; cap = 90k -> pass (not > cap)
    assert check_buying_power(_card(), state, qty=900, last_price=100.0, max_exposure_pct=0.9) is None
```

- [ ] **Step 2: Run — 6 ImportError-style failures**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

- [ ] **Step 3: Implement `check_buying_power`**

Append to `tradelab/src/tradelab/live/guardrails.py`:

```python
def _coerce_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def check_buying_power(
    card: dict,
    alpaca_state,
    qty: float,
    last_price: float,
    max_exposure_pct: float = 0.90,
) -> Optional[BlockReason]:
    bp = _coerce_float(alpaca_state.account().buying_power)
    cap = bp * max_exposure_pct
    working = 0.0
    for o in alpaca_state.open_orders():
        o_qty = _coerce_float(getattr(o, "qty", 0))
        o_price = _coerce_float(getattr(o, "limit_price", None)) \
            or _coerce_float(getattr(o, "filled_avg_price", None))
        working += o_qty * o_price
    new_notional = qty * last_price
    if working + new_notional <= cap:
        return None
    return BlockReason(
        code="insufficient_buying_power",
        message=f"buying-power cap exceeded: working ${working:.0f} + new ${new_notional:.0f} > cap ${cap:.0f}",
        details={
            "buying_power": bp,
            "max_exposure_pct": max_exposure_pct,
            "cap": cap,
            "working_notional": working,
            "new_notional": new_notional,
        },
    )
```

- [ ] **Step 4: Run — all guardrail tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 32 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): buying-power guardrail with global max_exposure_pct

(working_orders_notional + new_order_notional) must stay within
buying_power * max_exposure_pct. Open orders without an explicit
limit_price fall back to filled_avg_price; a missing price is treated
as $0 (the guardrail is conservative against the candidate, not the
backlog).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `evaluate_guardrails` composer

**Files:**
- Modify: `tradelab/src/tradelab/live/guardrails.py`
- Modify: `tradelab/tests/live/test_guardrails.py`

Runs the five checks in fixed order, short-circuits on first failure. Tests verify ordering by stacking multiple violations and asserting the cheapest one fires.

- [ ] **Step 1: Append failing tests**

Append to `tests/live/test_guardrails.py`:

```python
# ── evaluate_guardrails composer ────────────────────────────────────

from tradelab.live.guardrails import evaluate_guardrails


def test_evaluate_returns_none_when_all_pass():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    registry = _registry_dict(me)
    states = {"foo-v1": CardRuntimeState()}
    alpaca = _AlpacaStateStubBP(buying_power="100000",
                                 open_orders=[],
                                 )
    # naked-short check needs positions; use a fresh stub that has both
    class FullStub:
        def positions(self): return [_Position("AAPL", "100")]
        def account(self): return _Account("100000")
        def open_orders(self): return []
    result = evaluate_guardrails(
        card=me, action="sell", qty=1, last_price=100.0,
        registry=registry, states=states, alpaca_state=FullStub(), now=now,
    )
    assert result is None


def test_evaluate_short_circuits_at_cooldown_first():
    """Cooldown is cheapest — must fire even if daily_limit also tripped."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL", daily_limit=2)
    registry = _registry_dict(me)
    states = {"foo-v1": CardRuntimeState(
        last_attempted_at=now - timedelta(seconds=5),  # cooldown trips
        fires_today=99,                                  # daily_limit trips too
        fire_window_start=get_rth_window_start(now),
    )}
    class FullStub:
        def positions(self): return []
        def account(self): return _Account("100000")
        def open_orders(self): return []
    result = evaluate_guardrails(
        card=me, action="buy", qty=1, last_price=100.0,
        registry=registry, states=states, alpaca_state=FullStub(), now=now,
    )
    assert result.code == "cooldown_active"


def test_evaluate_short_circuits_daily_before_collision():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL", daily_limit=1)
    other = _card(card_id="bar-v1", symbol="AAPL")
    registry = _registry_dict(me, other)
    states = {
        "foo-v1": CardRuntimeState(fires_today=5, fire_window_start=get_rth_window_start(now)),
        "bar-v1": CardRuntimeState(last_fired_at=now - timedelta(seconds=5)),
    }
    class FullStub:
        def positions(self): return []
        def account(self): return _Account("100000")
        def open_orders(self): return []
    result = evaluate_guardrails(
        card=me, action="buy", qty=1, last_price=100.0,
        registry=registry, states=states, alpaca_state=FullStub(), now=now,
    )
    assert result.code == "daily_limit_exceeded"


def test_evaluate_runs_naked_short_only_for_sells():
    """A 'buy' must never trip naked_short even with empty positions."""
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    me = _card(card_id="foo-v1", symbol="AAPL")
    registry = _registry_dict(me)
    states = {"foo-v1": CardRuntimeState()}
    class FullStub:
        def positions(self): return []
        def account(self): return _Account("100000")
        def open_orders(self): return []
    result = evaluate_guardrails(
        card=me, action="buy", qty=1, last_price=100.0,
        registry=registry, states=states, alpaca_state=FullStub(), now=now,
    )
    assert result is None
```

- [ ] **Step 2: Run — 4 ImportError-style failures**

- [ ] **Step 3: Implement `evaluate_guardrails`**

Append to `tradelab/src/tradelab/live/guardrails.py`:

```python
def evaluate_guardrails(
    *,
    card: dict,
    action: str,
    qty: float,
    last_price: float,
    registry: dict[str, dict],
    states: dict[str, CardRuntimeState],
    alpaca_state,
    now: datetime,
    max_exposure_pct: float = 0.90,
) -> Optional[BlockReason]:
    """Run the 5 checks in fixed cheapest-first order. First failure wins.

    Order matters:
      1. cooldown      — cheap, in-memory
      2. daily_limit   — cheap, in-memory
      3. collision     — in-memory scan over <=50 cards
      4. naked_short   — Alpaca positions (cached)
      5. buying_power  — Alpaca account+orders (cached)
    """
    state = states.get(card["card_id"], CardRuntimeState())

    if (br := check_cooldown(card, state, now)) is not None:
        return br
    if (br := check_daily_limit(card, state, now)) is not None:
        return br
    if (br := check_symbol_collision(card, registry, states, now)) is not None:
        return br
    if (br := check_naked_short(card, action, alpaca_state)) is not None:
        return br
    if (br := check_buying_power(card, alpaca_state, qty, last_price, max_exposure_pct)) is not None:
        return br
    return None
```

- [ ] **Step 4: Run — all guardrail tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_guardrails.py -v
```

Expected: 36 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/guardrails.py tests/live/test_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): evaluate_guardrails composer with cheapest-first ordering

Runs cooldown → daily_limit → collision → naked_short → buying_power
and short-circuits on first BlockReason. Order is cheapest-first so
a card under cooldown never pays for an Alpaca round trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Receiver-side `_card_state` + alerts-log hydration

**Files:**
- Modify: `tradelab/src/tradelab/live/receiver.py`
- Create: `tradelab/tests/live/test_receiver_state.py`

Two helpers and one startup hydrator. State is a module-level `dict[str, CardRuntimeState]` so the existing `cards = CardRegistry(...)` pattern is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_receiver_state.py`:

```python
"""Receiver per-card runtime state: record_attempt / record_fire /
hydrate_card_state_from_alerts_log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradelab.live.guardrails import CardRuntimeState, get_rth_window_start
from tradelab.live import receiver as rec


def _alert(ts: str, card_id: str, status: str) -> dict:
    return {"ts": ts, "card_id": card_id, "status": status,
            "payload": {}, "details": {}}


def test_record_attempt_sets_last_attempted_at():
    states: dict[str, CardRuntimeState] = {}
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    rec.record_attempt(states, "foo-v1", now)
    assert states["foo-v1"].last_attempted_at == now


def test_record_attempt_updates_existing():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    earlier = now - timedelta(seconds=30)
    states = {"foo-v1": CardRuntimeState(last_attempted_at=earlier, fires_today=2)}
    rec.record_attempt(states, "foo-v1", now)
    assert states["foo-v1"].last_attempted_at == now
    # Other fields untouched
    assert states["foo-v1"].fires_today == 2


def test_record_fire_increments_count_in_same_window():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    window = get_rth_window_start(now)
    states = {"foo-v1": CardRuntimeState(fires_today=2, fire_window_start=window)}
    rec.record_fire(states, "foo-v1", now)
    assert states["foo-v1"].fires_today == 3
    assert states["foo-v1"].last_fired_at == now
    assert states["foo-v1"].fire_window_start == window


def test_record_fire_resets_count_in_new_window():
    yesterday_window = datetime(2026, 3, 3, 14, 30, tzinfo=timezone.utc)
    today = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states = {"foo-v1": CardRuntimeState(fires_today=99, fire_window_start=yesterday_window)}
    rec.record_fire(states, "foo-v1", today)
    assert states["foo-v1"].fires_today == 1
    assert states["foo-v1"].fire_window_start == get_rth_window_start(today)


def test_record_fire_first_time_starts_window():
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states: dict[str, CardRuntimeState] = {}
    rec.record_fire(states, "foo-v1", now)
    assert states["foo-v1"].fires_today == 1
    assert states["foo-v1"].fire_window_start == get_rth_window_start(now)
    assert states["foo-v1"].last_fired_at == now


def test_hydrate_from_alerts_log_rebuilds_state(tmp_path: Path):
    log = tmp_path / "alerts.jsonl"
    today_open = get_rth_window_start(datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc))
    yesterday = (today_open - timedelta(days=1)).isoformat()
    today_t1 = (today_open + timedelta(hours=1)).isoformat()
    today_t2 = (today_open + timedelta(hours=2)).isoformat()
    log.write_text(
        "\n".join([
            json.dumps(_alert(yesterday, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t1, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t2, "foo-v1", "order_submitted")),
            json.dumps(_alert(today_t2, "bar-v1", "guardrail_blocked")),
        ]),
        encoding="utf-8",
    )
    now = datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc)
    states = rec.hydrate_card_state_from_alerts_log(log, now)
    foo = states["foo-v1"]
    assert foo.fires_today == 2  # only today's order_submitted entries
    assert foo.last_fired_at.isoformat() == today_t2
    # bar-v1 had only a guardrail_blocked, not an order_submitted; it
    # should NOT have a last_fired_at — but record_attempt-style entries
    # are not the responsibility of hydration (we only restore fire stats)
    assert "bar-v1" not in states or states["bar-v1"].fires_today == 0


def test_hydrate_handles_missing_log_file(tmp_path: Path):
    states = rec.hydrate_card_state_from_alerts_log(
        tmp_path / "missing.jsonl", datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert states == {}


def test_hydrate_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "alerts.jsonl"
    today = (get_rth_window_start(datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc))
             + timedelta(hours=1)).isoformat()
    log.write_text(
        "\n".join([
            "not-json",
            json.dumps(_alert(today, "foo-v1", "order_submitted")),
            "{",
        ]),
        encoding="utf-8",
    )
    states = rec.hydrate_card_state_from_alerts_log(
        log, datetime(2026, 3, 4, 16, 0, tzinfo=timezone.utc),
    )
    assert states["foo-v1"].fires_today == 1
```

- [ ] **Step 2: Run — 8 ImportError-style failures (or AttributeError on receiver.record_attempt etc)**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_receiver_state.py -v
```

- [ ] **Step 3: Implement helpers and hydration in receiver.py**

Add at the top of `tradelab/src/tradelab/live/receiver.py` (after the existing `cards = CardRegistry(CARDS_PATH)` line at ~122):

```python
from tradelab.live.guardrails import (
    CardRuntimeState,
    get_rth_window_start,
    evaluate_guardrails,
)

_card_state: dict[str, CardRuntimeState] = {}


def record_attempt(states: dict[str, CardRuntimeState], card_id: str, now: datetime) -> None:
    state = states.setdefault(card_id, CardRuntimeState())
    state.last_attempted_at = now


def record_fire(states: dict[str, CardRuntimeState], card_id: str, now: datetime) -> None:
    state = states.setdefault(card_id, CardRuntimeState())
    current_window = get_rth_window_start(now)
    if state.fire_window_start is None or state.fire_window_start < current_window:
        state.fires_today = 1
        state.fire_window_start = current_window
    else:
        state.fires_today += 1
    state.last_fired_at = now


def hydrate_card_state_from_alerts_log(
    log_path: Path, now: datetime, max_lines: int = 500,
) -> dict[str, CardRuntimeState]:
    """Replay the last `max_lines` of alerts.jsonl to rebuild fire state.

    Only `order_submitted` records contribute. fires_today counts only
    submissions whose ts falls within the current RTH window.
    """
    states: dict[str, CardRuntimeState] = {}
    if not log_path.exists():
        return states
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()[-max_lines:]
    except OSError:
        return states
    current_window = get_rth_window_start(now)
    for line in lines:
        try:
            rec_obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec_obj.get("status") != "order_submitted":
            continue
        cid = rec_obj.get("card_id")
        ts_str = rec_obj.get("ts")
        if not cid or not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        state = states.setdefault(cid, CardRuntimeState())
        # Always update last_fired_at to the most recent fire we see
        if state.last_fired_at is None or ts > state.last_fired_at:
            state.last_fired_at = ts
        if ts >= current_window:
            if state.fire_window_start is None or state.fire_window_start < current_window:
                state.fires_today = 1
                state.fire_window_start = current_window
            else:
                state.fires_today += 1
    return states
```

Update the `_on_startup` hook (currently at receiver.py:127-130) to also hydrate state:

```python
@app.on_event("startup")
def _on_startup() -> None:
    global _cards_observer, _card_state
    _cards_observer = _start_cards_watcher(cards, polling=False)
    logger.info("cards.json watcher started on %s", cards.path)
    _card_state = hydrate_card_state_from_alerts_log(
        ALERT_LOG, datetime.now(timezone.utc),
    )
    logger.info("hydrated runtime state for %d cards", len(_card_state))
```

- [ ] **Step 4: Run — all 8 tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_receiver_state.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Run the full live + web suites**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/ tests/web/ -v
```

Expected: existing tests still green; +8 new from this task.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/receiver.py tests/live/test_receiver_state.py
git commit -m "$(cat <<'EOF'
feat(live): receiver _card_state + alerts.jsonl hydration on startup

In-memory CardRuntimeState dict drives cooldown/daily-limit. record_attempt
fires before guardrails (so a flood debounces correctly), record_fire fires
after a successful Alpaca submit, and on startup the last 500 alerts.jsonl
lines are replayed so a mid-day restart keeps today's fire counts intact.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Wire guardrails into `webhook` + write last_fired_at + log guardrail_blocked

**Files:**
- Modify: `tradelab/src/tradelab/live/receiver.py`
- Create: `tradelab/tests/live/test_receiver_guardrails.py`

This is the integration. The webhook flow becomes:

1. Parse + validate (unchanged)
2. Card lookup (unchanged)
3. Secret check (unchanged)
4. Status==enabled check (unchanged)
5. Symbol-match check (unchanged)
6. Quantity computation + validation (unchanged)
7. **Fetch last_price (NEW)** — Alpaca's `StockHistoricalDataClient.get_stock_latest_trade(symbol)`. On any error, fall back to `last_price=0` and skip the buying-power check.
8. **`record_attempt(card_id, now)`** (NEW)
9. **`evaluate_guardrails(...)`** (NEW). On block → log `guardrail_blocked` + return 403.
10. Submit market order (unchanged)
11. On success: **`record_fire(card_id, now)`** (NEW), **`alpaca_state.invalidate()`** (NEW), **persist `last_fired_at` to cards.json via `cards.update(card_id, {"last_fired_at": now.isoformat()})`** (NEW).
12. Log `order_submitted` / `order_failed` (unchanged).

The `last_price` fetch must be tolerant of: alpaca-py StockHistoricalDataClient not being configured for paper accounts, network errors, missing market-data subscription. When unavailable, the buying-power check effectively passes (its `new_notional` becomes 0, which always satisfies the cap unless the cap itself is 0).

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_receiver_guardrails.py`:

```python
"""End-to-end webhook → guardrail pipeline → alpaca submit / block."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tradelab.live.cards import CardRegistry
from tradelab.live.guardrails import CardRuntimeState
from tradelab.live import receiver as rec


CARD = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AAPL",
    "status": "enabled", "quantity": 10,
    "cooldown_seconds": 30, "daily_limit": 5,
    "allow_collision": False, "allow_naked_short": False,
}


@pytest.fixture
def patched_receiver(tmp_path, monkeypatch):
    cards_path = tmp_path / "cards.json"
    cards_path.write_text(json.dumps({"foo-v1": CARD}), encoding="utf-8")
    alerts_path = tmp_path / "alerts.jsonl"

    monkeypatch.setattr(rec, "ALERT_LOG", alerts_path)
    monkeypatch.setattr(rec, "cards", CardRegistry(cards_path))
    monkeypatch.setattr(rec, "_card_state", {})

    # Stub AlpacaState so guardrails see a fully-stocked account
    class _Acct:
        buying_power = "1000000"
    class _Pos:
        symbol = "AAPL"
        qty = "100"
    fake_state = MagicMock()
    fake_state.positions.return_value = [_Pos()]
    fake_state.account.return_value = _Acct()
    fake_state.open_orders.return_value = []
    fake_state.invalidate = MagicMock()
    monkeypatch.setattr(rec, "_alpaca_state", fake_state, raising=False)

    # Stub last-price fetch
    monkeypatch.setattr(rec, "_fetch_last_price", lambda symbol: 200.0)

    # Stub Alpaca submit
    monkeypatch.setattr(
        rec, "submit_market_order",
        lambda symbol, action, qty, coid: {"id": "ORD-1", "status": "accepted"},
    )

    return {
        "cards_path": cards_path,
        "alerts_path": alerts_path,
        "fake_state": fake_state,
        "client": TestClient(rec.app),
    }


def _alert_payload(action="buy", **overrides):
    base = {
        "card_id": "foo-v1", "secret": "s" * 32,
        "symbol": "AAPL", "action": action, "contracts": 1,
    }
    base.update(overrides)
    return base


def test_webhook_passes_guardrails_and_submits(patched_receiver):
    resp = patched_receiver["client"].post("/webhook", json=_alert_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # last_fired_at written to cards.json
    on_disk = json.loads(patched_receiver["cards_path"].read_text(encoding="utf-8-sig"))
    assert on_disk["foo-v1"]["last_fired_at"] is not None
    # alpaca_state invalidated after submit
    assert patched_receiver["fake_state"].invalidate.call_count >= 1
    # alert log written with order_submitted
    log = patched_receiver["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    statuses = [json.loads(l)["status"] for l in log]
    assert "order_submitted" in statuses


def test_webhook_blocked_by_cooldown_returns_403(patched_receiver):
    """Two webhooks within cooldown_seconds — second must be blocked."""
    p = patched_receiver
    # First webhook fires successfully
    r1 = p["client"].post("/webhook", json=_alert_payload())
    assert r1.status_code == 200
    # Second webhook immediately after — cooldown trips
    r2 = p["client"].post("/webhook", json=_alert_payload())
    assert r2.status_code == 403
    body = r2.json()
    assert "cooldown" in body["error"].lower()
    log = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "cooldown_active"


def test_webhook_blocked_logs_guardrail_blocked_with_reason_field(patched_receiver):
    p = patched_receiver
    # Pre-load state so daily_limit trips
    rec._card_state["foo-v1"] = CardRuntimeState(
        fires_today=999,
        fire_window_start=rec.get_rth_window_start(datetime.now(timezone.utc)),
    )
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 403
    log = p["alerts_path"].read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(log[-1])
    assert last["status"] == "guardrail_blocked"
    assert last["details"]["reason"] == "daily_limit_exceeded"


def test_webhook_naked_short_blocked_when_no_position(patched_receiver):
    p = patched_receiver
    p["fake_state"].positions.return_value = []  # no inventory
    r = p["client"].post("/webhook", json=_alert_payload(action="sell"))
    assert r.status_code == 403
    body = r.json()
    assert "no_position_to_sell" in body["error"] or "no position" in body["error"].lower()


def test_webhook_records_fire_only_on_successful_submit(patched_receiver, monkeypatch):
    """If Alpaca submit fails, fires_today must NOT increment."""
    p = patched_receiver
    monkeypatch.setattr(
        rec, "submit_market_order",
        MagicMock(side_effect=RuntimeError("alpaca down")),
    )
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 500
    state = rec._card_state.get("foo-v1")
    assert state is None or state.fires_today == 0
    # last_attempted_at still set (we made an attempt)
    if state is not None:
        assert state.last_attempted_at is not None


def test_webhook_attempts_recorded_even_when_blocked(patched_receiver):
    """A blocked webhook must still update last_attempted_at — that's how
    a flood gets debounced even when every attempt is blocking."""
    p = patched_receiver
    # Prime state so the first webhook is blocked by cooldown
    primed = datetime.now(timezone.utc) - timedelta(seconds=1)
    rec._card_state["foo-v1"] = CardRuntimeState(last_attempted_at=primed)
    r = p["client"].post("/webhook", json=_alert_payload())
    assert r.status_code == 403
    state = rec._card_state["foo-v1"]
    # last_attempted_at advanced from the primed value
    assert state.last_attempted_at is not None
    assert state.last_attempted_at > primed
```

- [ ] **Step 2: Run — most fail (record_fire wired wrong, blocked path missing, etc.)**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_receiver_guardrails.py -v
```

- [ ] **Step 3: Implement the integration in `receiver.py`**

Add the price-fetch helper and Alpaca-state singleton at the top of receiver.py (just after the `_card_state` declaration from Task 8):

```python
from tradelab.live.alpaca_state import AlpacaState
from tradelab.live.alpaca_client import get_client

_alpaca_state: Optional[AlpacaState] = None


def _ensure_alpaca_state() -> AlpacaState:
    global _alpaca_state
    if _alpaca_state is None:
        _alpaca_state = AlpacaState(client=get_client(), ttl_seconds=2.0)
    return _alpaca_state


def _fetch_last_price(symbol: str) -> float:
    """Best-effort last-trade price for buying-power check.

    Returns 0.0 on any failure (paper accounts without market data, network
    errors, missing subscriptions). 0.0 makes the buying-power candidate
    notional 0, which always passes (the check is intentionally lenient on
    data unavailability — a flat-out cap miss is more user-hostile than
    a missed check).
    """
    try:
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        from tradelab.live.alpaca_client import CONFIG_PATH
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        client = StockHistoricalDataClient(
            cfg["alpaca"]["api_key"], cfg["alpaca"]["secret_key"],
        )
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        trade = client.get_stock_latest_trade(req)[symbol]
        return float(trade.price)
    except Exception as e:
        logger.warning("last-price fetch failed for %s: %s", symbol, e)
        return 0.0
```

Now wire the guardrail pipeline into `webhook` (replace the body from line 195 onwards — the symbol-match block and the order-submit block — with the version below):

```python
    card_symbol = str(card.get("symbol", "")).upper()
    alert_symbol = alert.symbol.upper()
    if card_symbol != alert_symbol:
        _log_alert(
            payload_dict, alert.card_id, "symbol_mismatch",
            {"card_symbol": card_symbol, "alert_symbol": alert_symbol},
        )
        return JSONResponse(
            {"error": f"symbol mismatch: card={card_symbol} alert={alert_symbol}"},
            status_code=422,
        )

    if card.get("quantity") is not None:
        qty = float(card["quantity"])
    else:
        qty = float(alert.contracts or 0)

    if qty <= 0:
        _log_alert(payload_dict, alert.card_id, "bad_quantity", {"qty": qty})
        return JSONResponse({"error": f"bad quantity: {qty}"}, status_code=422)

    # ── Guardrail pipeline ───────────────────────────────────────────
    # Order matters: evaluate FIRST (reading the prior last_attempted_at),
    # THEN record this attempt. Recording first would self-block every
    # card's first webhook on cooldown (elapsed = 0 < cooldown_seconds).
    now = datetime.now(timezone.utc)
    last_price = _fetch_last_price(alert_symbol)
    alpaca_state = _ensure_alpaca_state()
    hydrated_card = {**card, "card_id": alert.card_id}
    block = evaluate_guardrails(
        card=hydrated_card,
        action=alert.action,
        qty=qty,
        last_price=last_price,
        registry=cards.all_hydrated(),
        states=_card_state,
        alpaca_state=alpaca_state,
        now=now,
    )
    # Record the attempt regardless of outcome (debounces a flood of
    # blocked webhooks — each one pushes the cooldown forward).
    record_attempt(_card_state, alert.card_id, now)

    if block is not None:
        _log_alert(
            payload_dict, alert.card_id, "guardrail_blocked",
            {"reason": block.code, "message": block.message, **block.details},
        )
        return JSONResponse(
            {"error": f"{block.code}: {block.message}"},
            status_code=403,
        )

    client_order_id = f"{alert.card_id}-{int(now.timestamp() * 1000)}"
    try:
        result = await asyncio.to_thread(
            submit_market_order, alert_symbol, alert.action, qty, client_order_id
        )
        record_fire(_card_state, alert.card_id, now)
        alpaca_state.invalidate()
        try:
            cards.update(alert.card_id, {"last_fired_at": now.isoformat()})
        except Exception as e:
            logger.warning("failed to persist last_fired_at: %s", e)
        _log_alert(payload_dict, alert.card_id, "order_submitted", result)
        return {"ok": True, "order": result}
    except Exception as e:
        _log_alert(payload_dict, alert.card_id, "order_failed", {"error": str(e)})
        return JSONResponse({"error": f"order placement failed: {e}"}, status_code=500)
```

- [ ] **Step 4: Run — all guardrail-integration tests green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/test_receiver_guardrails.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run all live tests + web tests**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/live/ tests/web/ 2>&1 | tail -20
```

Expected: green; net new ~6.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/receiver.py tests/live/test_receiver_guardrails.py
git commit -m "$(cat <<'EOF'
feat(live): wire guardrail pipeline into webhook + persist last_fired_at

Receiver now runs evaluate_guardrails between symbol-match and Alpaca
submit. Blocked webhooks return 403 + log status='guardrail_blocked' with
the reason code in details. Successful submits record_fire, invalidate
the Alpaca state cache, and persist last_fired_at to cards.json (the
existing watcher absorbs the resulting reload).

Last-price fetch via StockHistoricalDataClient is best-effort; failure
returns 0.0 which makes the buying-power candidate notional 0 (lenient
on data unavailability is preferable to false rejections).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: FE — drawer markup + CSS

**Files:**
- Modify: `command_center.html` (parent repo) — CSS block around line 462, row markup at line 4463-4485, render container after line 4513

The drawer is a sibling element rendered immediately after each `.lt-row`. It is hidden by default and toggled via a new `data-action="overrides"` button added to the row (12th column, 30px). When expanded, it shows four labelled controls:

- **Allow collision** — checkbox bound to `allow_collision`
- **Allow naked short** — checkbox bound to `allow_naked_short`
- **Daily limit** — number input bound to `daily_limit` (0+)
- **Cooldown (sec)** — number input bound to `cooldown_seconds` (0+)

Plus a **Save** button that PATCHes all four.

- [ ] **Step 1: Update the row grid CSS to add the 12th column (parent repo)**

In `command_center.html`, replace line 419:

```css
      grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px 80px 30px;
```

with:

```css
      grid-template-columns: 24px minmax(160px, 1.5fr) 90px 70px 70px 90px 110px 110px 60px 80px 30px 30px;
```

And append the drawer CSS at the end of the LT styles block (just before line 467 `</style>`):

```css
    .lt-overrides-btn {
      background: transparent; border: none; color: #9aa5b1;
      cursor: pointer; font-size: 0.95em; padding: 0;
    }
    .lt-overrides-btn:hover { color: #e6edf3; }
    .lt-overrides-drawer {
      padding: 10px 14px 12px 48px;
      background: #131820;
      border-top: 1px solid #1c2330;
      display: none;
      gap: 14px;
      align-items: center;
      flex-wrap: wrap;
      font-size: 0.85em;
    }
    .lt-overrides-drawer.open { display: flex; }
    .lt-overrides-field { display: flex; align-items: center; gap: 6px; }
    .lt-overrides-field label { color: #9aa5b1; }
    .lt-overrides-field input[type="number"] {
      width: 60px; background: var(--card); color: var(--text);
      border: 1px solid var(--border); padding: 2px 4px;
      border-radius: 3px;
    }
    .lt-overrides-field input[type="checkbox"] { cursor: pointer; }
    .lt-overrides-save {
      background: transparent; border: 1px solid #2a5040;
      color: #3dd68c; padding: 3px 10px; border-radius: 4px;
      cursor: pointer; font-size: 0.85em;
    }
    .lt-overrides-save:hover { background: #162a23; }
    .lt-overrides-save:disabled { opacity: 0.5; cursor: wait; }
```

- [ ] **Step 2: Add the gear button to `renderRow` (line 4482 area)**

In `renderRow` (line 4463-4485), add a new column between the toggle and the trash:

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
            <span><button class="lt-overrides-btn" data-action="overrides" data-card-id="${escHtml(card.card_id)}" title="Per-card overrides">⚙</button></span>
            <span><button class="lt-trash-btn" data-action="delete" data-card-id="${escHtml(card.card_id)}" title="Delete card">🗑</button></span>
          </div>
          ${renderOverridesDrawer(card)}
        `;
      }
```

- [ ] **Step 3: Add `renderOverridesDrawer` helper above `renderRow` (line 4462)**

```javascript
      function renderOverridesDrawer(card) {
        const cid = escHtml(card.card_id);
        const ac = card.allow_collision ? 'checked' : '';
        const ans = card.allow_naked_short ? 'checked' : '';
        const dl = card.daily_limit ?? 5;
        const cs = card.cooldown_seconds ?? 30;
        return `
          <div class="lt-overrides-drawer" data-card-id="${cid}">
            <div class="lt-overrides-field">
              <input type="checkbox" id="lt-ovr-ac-${cid}" data-field="allow_collision" ${ac}>
              <label for="lt-ovr-ac-${cid}">Allow collision</label>
            </div>
            <div class="lt-overrides-field">
              <input type="checkbox" id="lt-ovr-ans-${cid}" data-field="allow_naked_short" ${ans}>
              <label for="lt-ovr-ans-${cid}">Allow naked short</label>
            </div>
            <div class="lt-overrides-field">
              <label for="lt-ovr-dl-${cid}">Daily limit</label>
              <input type="number" id="lt-ovr-dl-${cid}" min="0" data-field="daily_limit" value="${escHtml(dl)}">
            </div>
            <div class="lt-overrides-field">
              <label for="lt-ovr-cs-${cid}">Cooldown (s)</label>
              <input type="number" id="lt-ovr-cs-${cid}" min="0" data-field="cooldown_seconds" value="${escHtml(cs)}">
            </div>
            <button class="lt-overrides-save" data-action="overrides-save" data-card-id="${cid}">Save</button>
          </div>
        `;
      }
```

- [ ] **Step 4: Verify via browser** *(controller-side)*

Restart dashboard:
```bash
netstat -ano | grep ":8877" | grep LISTENING | head -1
# kill old PID, then:
cd C:/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py
```
Open `http://127.0.0.1:8877` → Live Trading tab. Confirm:
- ⚙ button visible between toggle and trash on every row
- Clicking ⚙ does nothing yet (no handler) — that's Task 11
- Drawer markup is in DOM but `display:none` (visible via DevTools)

- [ ] **Step 5: Commit**

```bash
git add command_center.html
git commit -m "$(cat <<'EOF'
ui(command-center): per-card overrides drawer markup + CSS

Adds a 12th 30px column to .lt-row for the ⚙ button and renders a
sibling .lt-overrides-drawer immediately after each row. Drawer is
hidden by default; Task 11 will wire the toggle handler and PATCH save.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: FE — drawer toggle + Save handler

**Files:**
- Modify: `command_center.html` — `bindRowActions` and add `bindOverridesSave`

- [ ] **Step 1: Extend `bindRowActions` to handle `data-action="overrides"`**

In `command_center.html`, modify the `bindRowActions` body (around line 4545-4565) to add an `else if` clause:

```javascript
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
            openDeleteModal([cardId]);
          } else if (action === 'overrides') {
            const drawer = $list().querySelector(
              `.lt-overrides-drawer[data-card-id="${CSS.escape(cardId)}"]`
            );
            if (drawer) drawer.classList.toggle('open');
          } else if (action === 'overrides-save') {
            await saveOverrides(btn, cardId);
          }
        });
      }
```

- [ ] **Step 2: Add `saveOverrides` function above `bindRowActions`**

```javascript
      async function saveOverrides(saveBtn, cardId) {
        const drawer = $list().querySelector(
          `.lt-overrides-drawer[data-card-id="${CSS.escape(cardId)}"]`
        );
        if (!drawer) return;
        const fields = {};
        drawer.querySelectorAll('[data-field]').forEach(el => {
          const name = el.dataset.field;
          if (el.type === 'checkbox') {
            fields[name] = el.checked;
          } else {
            const n = parseInt(el.value, 10);
            if (Number.isFinite(n) && n >= 0) fields[name] = n;
          }
        });
        if (Object.keys(fields).length === 0) {
          toast('Nothing to save', 'warn');
          return;
        }
        saveBtn.disabled = true;
        try {
          await patchCard(cardId, fields);
          toast('Overrides saved', 'info');
          await fetchAndRender();
        } catch (e) {
          toast(`Save failed: ${e.message}`, 'error');
          saveBtn.disabled = false;
        }
      }
```

- [ ] **Step 3: Smoke via browser** *(controller-side)*

After dashboard restart:
1. Open Live Trading tab. Click ⚙ on a card → drawer expands below the row.
2. Toggle "Allow collision" checkbox + change Daily limit to 7 + Cooldown to 60.
3. Click Save → "Overrides saved" toast.
4. Reload the page. Open the same drawer. Confirm checkbox + values persisted.
5. On disk: `cat C:/TradingScripts/tradelab/live/cards.json` shows the 4 fields written.

- [ ] **Step 4: Commit**

```bash
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): per-card overrides drawer toggle + PATCH save

⚙ button toggles the drawer's .open class; Save reads the four bound
inputs (allow_collision, allow_naked_short, daily_limit, cooldown_seconds)
and PATCHes them through the existing endpoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Pin new JS function names + drawer DOM contracts

**Files:**
- Modify: `tradelab/tests/web/test_command_center_html.py:67-82`

`REQUIRED_JS_FUNCTIONS` is the safety net that catches any future refactor that silently deletes a Slice 3 function (the pattern that bit Slice 2 in T11).

- [ ] **Step 1: Append the new functions to `REQUIRED_JS_FUNCTIONS`**

In `tradelab/tests/web/test_command_center_html.py`, replace the list (line 67-82):

```python
REQUIRED_JS_FUNCTIONS = [
    "researchLoadPreflight",
    "renderPreflightInModal",
    "verdictHeatClass",
    "renderSparkline",
    "getSparklineRuns",
    "updateCompareButton",
    "renderLiveCard",
    "escapeHtml",
    "researchLoadLiveCards",
    "researchLoadPipeline",
    "patchCard",
    "bindRowActions",
    "bindQuantityEdit",
    "openDeleteModal",
    "renderOverridesDrawer",
    "saveOverrides",
]
```

- [ ] **Step 2: Add a DOM-contract test for the drawer wiring**

Append to the bottom of `test_command_center_html.py`:

```python
def test_overrides_drawer_has_all_four_fields(html: str) -> None:
    """The 4 fields the PATCH endpoint accepts must each be bound by
    data-field=. A silent rename in renderOverridesDrawer breaks PATCH
    silently; pin the contract."""
    for field in ("allow_collision", "allow_naked_short",
                  "daily_limit", "cooldown_seconds"):
        assert f'data-field="{field}"' in html, \
            f"renderOverridesDrawer missing data-field={field!r}"


def test_overrides_drawer_uses_open_class_pattern(html: str) -> None:
    """saveOverrides toggles the .open class — same pattern as the
    delete modal's .show class. Pin that the CSS rule + the toggle
    name still agree (regression on Slice 2 modal-CSS bug)."""
    assert ".lt-overrides-drawer.open" in html, \
        "lt-overrides-drawer.open CSS rule missing"
    assert "classList.toggle('open')" in html, \
        "drawer toggle handler not using .open class"
```

- [ ] **Step 3: Run — all green**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_command_center_html.py -v
```

Expected: 16 parametrized JS-function tests + 10 DOM-id tests + 2 new drawer tests = all green.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab && git add tests/web/test_command_center_html.py
git commit -m "$(cat <<'EOF'
test(web): pin Slice 3 LT overrides JS functions + drawer DOM contract

Adds renderOverridesDrawer + saveOverrides to REQUIRED_JS_FUNCTIONS so
silent deletion fails. Two new contract tests pin the four data-field=
binders and the .open toggle pattern (matches the modal CSS regression
caught in Slice 2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Smoke-test cleanup of test card + write the done doc

**Files:**
- Create: parent `2026-04-25-DIRECTION-A-SLICE-3-COMPLETE.md`
- (No code changes — this is the closing doc)

- [ ] **Step 1: Run the full suite one final time**

```bash
cd C:/TradingScripts/tradelab && python -m pytest 2>&1 | tail -5
```

Expected: ≥510 passed / 0 failed. Record the final number for the done doc.

- [ ] **Step 2: Restart receiver and dashboard from scratch**

```bash
# Kill receiver (port 8878)
netstat -ano | grep ":8878" | grep LISTENING | head -1
powershell -Command "Stop-Process -Id <PID> -Force"
# Relaunch receiver (controller-side, run_in_background:true)
cd C:/TradingScripts/tradelab && PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m uvicorn tradelab.live.receiver:app --host 127.0.0.1 --port 8878 --log-level info

# Same for dashboard (port 8877)
netstat -ano | grep ":8877" | grep LISTENING | head -1
powershell -Command "Stop-Process -Id <PID> -Force"
cd C:/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py
```

- [ ] **Step 3: Hand to user with the smoke checklist**

Create `C:/TradingScripts/2026-04-25-DIRECTION-A-SLICE-3-COMPLETE.md` (parent repo) with:

```markdown
# Direction A Slice 3 — Complete & Handoff

**Date:** 2026-04-25
**Spec:** `tradelab/docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md`
**Plan:** `tradelab/docs/superpowers/plans/2026-04-25-direction-a-slice-3-guardrails.md`

## What shipped

- 5 receiver-side guardrails — cooldown / daily_limit / symbol_collision / naked_short / buying_power — running between symbol-match and Alpaca submit, cheapest-first, fail-fast
- Per-card runtime state (`CardRuntimeState`): cooldown timestamps + daily fire counts, hydrated from the last 500 alerts.jsonl entries on receiver startup
- Per-RTH-window daily-limit reset (9:30 ET; previous business day before that)
- 2-second cached `AlpacaState` wrapper around alpaca-py — invalidated on every successful submit
- `last_fired_at` written back to cards.json after a successful submit (existing watcher absorbs the reload)
- `guardrail_blocked` alerts logged to alerts.jsonl with reason code + details
- FE per-card ⚙ Overrides drawer exposing the 4 PATCH fields (`allow_collision`, `allow_naked_short`, `daily_limit`, `cooldown_seconds`) — Slice 2 already accepted these, the drawer just exposes them

## To smoke (user)

API + receiver:
- [ ] First webhook fires successfully (returns 200, alerts.jsonl shows `order_submitted`, cards.json `last_fired_at` populated)
- [ ] Second identical webhook within 30s returns 403 with `cooldown_active` (alerts.jsonl shows `guardrail_blocked` with reason `cooldown_active`)
- [ ] Set `daily_limit: 1` via the drawer; first webhook fires, second returns 403 with `daily_limit_exceeded`
- [ ] Two cards on same symbol, both enabled, both fire within 30s — second one returns 403 `symbol_collision`; setting `allow_collision: true` on the second clears it
- [ ] Sell webhook on a symbol with no Alpaca position returns 403 `no_position_to_sell`; setting `allow_naked_short: true` clears it
- [ ] Receiver restart at 11:00 ET — fires_today survives because hydration replays alerts.jsonl

FE drawer:
- [ ] ⚙ button visible on every row between toggle and trash
- [ ] Clicking ⚙ expands the drawer below the row
- [ ] Save persists all 4 fields to cards.json (verify on disk + reload page)
- [ ] Save with no changes still toasts "Overrides saved"
- [ ] Drawer state survives a fetchAndRender refresh

## Commits

(filled in by execution)

## Pytest baseline

(filled in by execution — target ≥510)

## Known limitations (intentional — Slice 4+)

- No notification channels (browser/Windows toast/audible/ntfy.sh/email) for `guardrail_blocked` — Slice 4
- No global settings panel for `max_exposure_pct` — Slice 4
- Last-price fetch returns 0.0 on failure → buying-power check passes leniently. A future hardening could surface a `last_price_unavailable` warning in the UI.
- Daily-limit window resets at 9:30 ET only; intraday cards trading session opens are not special-cased

## Handoff for Slice 4

Slice 4 = notifications + settings panel. Per spec §7:
- ntfy.sh + email + browser toast + Windows toast + audible — severity-routed (CRITICAL/WARNING/INFO + daily summary)
- Channel modules: `notify.py`, `notify.browser`, `notify.windows_toast`, `notify.audible`, `notify.ntfy`, `notify.email`
- New gitignored `live_config.json` for channel toggles + SMTP creds + ntfy topic
- Settings panel at the bottom of the Live Trading tab with per-channel test buttons + per-severity routing matrix
- `guardrail_blocked` (Slice 3) becomes the first event Slice 4 wires up: severity=CRITICAL → all channels by default

---

**End of Slice 3 done doc.**
```

- [ ] **Step 4: Commit done doc**

```bash
git add 2026-04-25-DIRECTION-A-SLICE-3-COMPLETE.md
git commit -m "$(cat <<'EOF'
docs: Slice 3 done doc + Slice 4 handoff (post user smoke)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Note: leave the `## Commits` and `## Pytest baseline` placeholder for the controller to fill in after a final `git log --oneline` + pytest run.)

---

## Definition of done — Slice 3

After Slice 3 lands:

1. ✅ A misconfigured TradingView alert source firing 100 webhooks/sec only fires once per cooldown window
2. ✅ A card with `daily_limit: 5` cannot fire more than 5 times in one RTH session, even with manual webhook spam
3. ✅ Two cards on the same symbol cannot both fire in the same 30s window unless one has `allow_collision: true`
4. ✅ A sell signal on a symbol with no inventory is rejected unless `allow_naked_short: true`
5. ✅ A live trade that would push working+new exposure over 90% of buying power is rejected
6. ✅ Every block writes a `guardrail_blocked` line to alerts.jsonl with the reason code so the dashboard's "Last status" column lights up amber
7. ✅ The 4 override fields are editable inline via the drawer with no JSON edit
8. ✅ Receiver restart mid-day preserves today's fire counts via alerts.jsonl replay
9. ✅ All 510+ tests pass

---

**End of Slice 3 plan.**
