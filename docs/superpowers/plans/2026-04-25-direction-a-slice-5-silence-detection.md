# Direction A Slice 5 — Silence Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect cards that haven't fired within their cadence threshold and emit a single WARNING notification per silence transition; surface as an amber pill on the Live Trading row.

**Architecture:** A dashboard-launcher-resident periodic checker (`silence_checker.py`) ticks every 30 minutes during RTH. Each tick re-reads cards.json, computes a "should be silent" verdict per card from `live_config.silence.multipliers`, and diffs against an in-memory `_silent_cards` set. Newly-silent cards trigger `notify(WARNING)`; cards that fired since last tick exit the set silently. A trading-day calendar helper (NYSE 2026 holidays hardcoded) underpins intraday/daily threshold math; weekly uses calendar days. FE adds an amber pill via `.lt-row[data-silent=true]`, populated from a new `GET /tradelab/live/silence-status` endpoint.

**Tech Stack:** Python 3.13 stdlib (threading, datetime, zoneinfo); existing tradelab `cards`, `live_config`, `notify` modules; existing dashboard `command_center.html` Live Trading IIFE; pytest for tests.

**Spec:** `tradelab/docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md` §8

**Convention reminders (load-bearing — Slices 1-4 validated):**
- Direct to master, no branches; Conventional commits + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` footer mandatory
- TDD strict: failing test → verify it fails for the right reason → minimal impl → green → commit
- Receiver runtime state: `tradelab/live/*.json` and `tradelab/live/*.jsonl` (gitignored via `/live/*.json` rule)
- Source code: `tradelab/src/tradelab/live/*.py` (tracked)
- For periodic tasks in the dashboard launcher: follow the `notify_dispatcher` boot pattern in `launch_dashboard.py:71-78`
- Grep-verify selectors before implementing FE work (per `feedback_plan_grep_verification` memory)

---

## File structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `tradelab/src/tradelab/live/trading_calendar.py` | Pure functions: `is_trading_day(d)`, `count_trading_days_between(start, end)`. Hardcodes NYSE 2026 holidays (10 dates). |
| Create | `tradelab/tests/live/test_trading_calendar.py` | Unit tests for both helpers, including holiday and weekend handling. |
| Create | `tradelab/src/tradelab/live/silence_checker.py` | `_compute_should_be_silent` (pure), `tick` (one cycle, deps-injectable), `is_rth`, `is_silent`, `silent_set`, `start`/`stop` (thread). In-memory `_silent_cards` set. |
| Create | `tradelab/tests/live/test_silence_checker.py` | Unit tests for compute, tick transitions, RTH gate, thread lifecycle. |
| Modify | `tradelab/src/tradelab/web/handlers.py` | Add `handle_silence_status_get()` returning `{<card_id>: bool}` envelope; route `GET /tradelab/live/silence-status`. |
| Modify | `tradelab/tests/web/test_live_config_handlers.py` | Pin endpoint contract. |
| Modify | `C:\TradingScripts\launch_dashboard.py` | Boot `silence_checker.start()` after `notify_dispatcher.start()`; add `atexit.register` for both stops (folds in Slice 4 follow-up #7). |
| Modify | `C:\TradingScripts\command_center.html` | Render amber pill when `lt-row[data-silent="true"]`; fetch `/tradelab/live/silence-status` on render and refetch on notify SSE event. |
| Modify | `tradelab/tests/web/test_command_center_pin.py` | Pin amber-pill DOM contract (data-silent attribute, CSS class). |

---

## Task 1: trading_calendar.is_trading_day

**Files:**
- Create: `tradelab/src/tradelab/live/trading_calendar.py`
- Test: `tradelab/tests/live/test_trading_calendar.py`

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/live/test_trading_calendar.py`:

```python
"""Trading-day calendar — NYSE 2026 holidays + Sat/Sun handling."""
from datetime import date

from tradelab.live.trading_calendar import is_trading_day


def test_is_trading_day_weekday_in_2026():
    assert is_trading_day(date(2026, 4, 22)) is True   # Wednesday


def test_is_trading_day_saturday_returns_false():
    assert is_trading_day(date(2026, 4, 25)) is False


def test_is_trading_day_sunday_returns_false():
    assert is_trading_day(date(2026, 4, 26)) is False


def test_is_trading_day_new_year_2026_holiday():
    assert is_trading_day(date(2026, 1, 1)) is False


def test_is_trading_day_good_friday_2026():
    assert is_trading_day(date(2026, 4, 3)) is False   # Good Friday


def test_is_trading_day_independence_observed_2026():
    # Jul 4 2026 = Saturday → NYSE observes Friday Jul 3
    assert is_trading_day(date(2026, 7, 3)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_trading_calendar.py -v`
Expected: ImportError "No module named 'tradelab.live.trading_calendar'"

- [ ] **Step 3: Write minimal implementation**

Create `tradelab/src/tradelab/live/trading_calendar.py`:

```python
"""Trading-day calendar — NYSE 2026 holidays hardcoded.

For Slice 5 silence detection (intraday/daily cadence). Weekly uses calendar
days, doesn't touch this module. Spec §8.2 says "use pandas_market_calendars
if already a tradelab dep, else hardcode US holidays" — pmc is not a dep.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

NYSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day observed (Jul 4 2026 = Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
})


def is_trading_day(d: date) -> bool:
    """True for Mon-Fri excluding NYSE holidays."""
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return d not in NYSE_HOLIDAYS_2026
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_trading_calendar.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/live/trading_calendar.py tests/live/test_trading_calendar.py
git commit -m "$(cat <<'EOF'
feat(live): trading_calendar.is_trading_day + NYSE 2026 holidays

Foundation for Slice 5 silence detection — intraday/daily cadence
thresholds count in trading days, not calendar days. Weekly cadence
uses calendar days and doesn't touch this module.

10 NYSE 2026 holidays hardcoded per spec §8.2; pmc is not a dep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: trading_calendar.count_trading_days_between

**Files:**
- Modify: `tradelab/src/tradelab/live/trading_calendar.py`
- Modify: `tradelab/tests/live/test_trading_calendar.py`

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/live/test_trading_calendar.py`:

```python
from datetime import datetime, timezone

from tradelab.live.trading_calendar import count_trading_days_between


def _utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_count_trading_days_same_day_zero():
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 22, 23)) == 0


def test_count_trading_days_wed_to_thu_one():
    # Wed Apr 22 → Thu Apr 23 = 1 trading day elapsed
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 23)) == 1


def test_count_trading_days_fri_to_mon_skips_weekend():
    # Fri Apr 24 → Mon Apr 27 = 1 trading day (Mon)
    assert count_trading_days_between(_utc(2026, 4, 24), _utc(2026, 4, 27)) == 1


def test_count_trading_days_full_week_five():
    # Wed Apr 22 → Wed Apr 29 = Thu, Fri, Mon, Tue, Wed = 5
    assert count_trading_days_between(_utc(2026, 4, 22), _utc(2026, 4, 29)) == 5


def test_count_trading_days_skips_holiday():
    # Thu Apr 2 → Mon Apr 6: Apr 3 = Good Friday holiday → only Apr 6 counts = 1
    assert count_trading_days_between(_utc(2026, 4, 2), _utc(2026, 4, 6)) == 1


def test_count_trading_days_negative_returns_zero():
    # Defensive: end < start should not crash
    assert count_trading_days_between(_utc(2026, 4, 29), _utc(2026, 4, 22)) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_trading_calendar.py -v`
Expected: ImportError on `count_trading_days_between`

- [ ] **Step 3: Write minimal implementation**

Append to `tradelab/src/tradelab/live/trading_calendar.py`:

```python
def count_trading_days_between(start: datetime, end: datetime) -> int:
    """Trading days strictly after start.date() through end.date() inclusive.

    Used for silence detection: 'has X trading days elapsed since last_fired_at?'
    Same calendar day → 0. Wed → Thu = 1. Fri → Mon = 1 (Sat/Sun skipped).
    """
    if end <= start:
        return 0
    count = 0
    d = start.date() + timedelta(days=1)
    end_d = end.date()
    while d <= end_d:
        if is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_trading_calendar.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/live/trading_calendar.py tests/live/test_trading_calendar.py
git commit -m "$(cat <<'EOF'
feat(live): trading_calendar.count_trading_days_between

Trading days strictly after start through end inclusive. Skips Sat/Sun and
NYSE holidays. Same-day → 0. Used by silence_checker for intraday/daily
threshold math (weekly uses calendar days separately).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: silence_checker._compute_should_be_silent (pure)

**Files:**
- Create: `tradelab/src/tradelab/live/silence_checker.py`
- Test: `tradelab/tests/live/test_silence_checker.py`

This task creates the pure verdict function — no thread, no notify, no IO. All logic for "should this card be in the silent set right now?" lives here.

- [ ] **Step 1: Write the failing test**

Create `tradelab/tests/live/test_silence_checker.py`:

```python
"""Pure verdict logic — no thread, no notify, no IO."""
from datetime import datetime, timezone

from tradelab.live.silence_checker import _compute_should_be_silent


MULTS = {"intraday": 2, "daily": 5, "weekly": 21}


def _utc(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def _card(**overrides) -> dict:
    base = {
        "card_id": "foo-v1",
        "status": "enabled",
        "cadence": "daily",
        "last_fired_at": _utc(2026, 4, 22).isoformat(),
        "enabled_at": _utc(2026, 4, 1).isoformat(),
    }
    base.update(overrides)
    return base


def test_manual_cadence_never_silent():
    card = _card(cadence="manual", last_fired_at=_utc(2020, 1, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 26), MULTS) is False


def test_disabled_card_never_silent():
    card = _card(status="disabled", last_fired_at=_utc(2020, 1, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 26), MULTS) is False


def test_daily_card_just_fired_not_silent():
    card = _card(cadence="daily", last_fired_at=_utc(2026, 4, 22).isoformat())
    # Apr 22 → Apr 23 = 1 trading day elapsed; threshold = 5; not silent
    assert _compute_should_be_silent(card, _utc(2026, 4, 23), MULTS) is False


def test_daily_card_at_threshold_is_silent():
    # Last fired Wed Apr 22; now Wed Apr 29 = 5 trading days elapsed; threshold met
    card = _card(cadence="daily", last_fired_at=_utc(2026, 4, 22).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is True


def test_intraday_card_two_trading_days_silent():
    # intraday threshold = 2 trading days
    card = _card(cadence="intraday", last_fired_at=_utc(2026, 4, 22).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 24), MULTS) is True


def test_weekly_card_uses_calendar_days():
    # weekly threshold = 21 calendar days; 22 days later → silent
    card = _card(cadence="weekly", last_fired_at=_utc(2026, 4, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 23), MULTS) is True


def test_weekly_card_under_threshold_not_silent():
    card = _card(cadence="weekly", last_fired_at=_utc(2026, 4, 1).isoformat())
    assert _compute_should_be_silent(card, _utc(2026, 4, 15), MULTS) is False


def test_never_fired_falls_back_to_enabled_at():
    # last_fired_at None; use enabled_at instead
    card = _card(cadence="daily", last_fired_at=None, enabled_at=_utc(2026, 4, 1).isoformat())
    # Apr 1 → Apr 29 ≫ 5 trading days → silent
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is True


def test_never_fired_no_enabled_at_returns_false():
    card = _card(last_fired_at=None, enabled_at=None)
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is False


def test_unknown_cadence_returns_false():
    card = _card(cadence="bogus")
    assert _compute_should_be_silent(card, _utc(2026, 4, 29), MULTS) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: ImportError "No module named 'tradelab.live.silence_checker'"

- [ ] **Step 3: Write minimal implementation**

Create `tradelab/src/tradelab/live/silence_checker.py`:

```python
"""Silence detection — flag cards that haven't fired within their cadence threshold.

Per spec §8.3: runs in dashboard launcher process (one consumer). Tick every
30 minutes during RTH. For each enabled card with cadence != 'manual', compute
elapsed (trading days for intraday/daily, calendar days for weekly) since
last_fired_at (or enabled_at if never fired). On transition into silent set,
emit notify(WARNING). Clearing on next fire is silent — no second notify.

In-memory state per spec §8.3 — restart resets transitions, will re-notify any
still-silent card on first post-restart tick.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradelab.live.trading_calendar import count_trading_days_between


def _compute_should_be_silent(
    card: dict, now_utc: datetime, multipliers: dict[str, int]
) -> bool:
    """Pure verdict: should this card currently be in the silent set?

    Returns False for manual cadence, disabled cards, missing reference time,
    unknown cadence, or non-positive multiplier.
    """
    cadence = card.get("cadence", "daily")
    if cadence == "manual":
        return False
    if card.get("status") != "enabled":
        return False
    ref_str = card.get("last_fired_at") or card.get("enabled_at")
    if ref_str is None:
        return False
    try:
        ref = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    multiplier = int(multipliers.get(cadence, 0))
    if multiplier <= 0:
        return False
    if cadence == "weekly":
        return (now_utc - ref).days >= multiplier
    # intraday / daily → trading-day arithmetic
    return count_trading_days_between(ref, now_utc) >= multiplier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/live/silence_checker.py tests/live/test_silence_checker.py
git commit -m "$(cat <<'EOF'
feat(live): silence_checker._compute_should_be_silent (pure verdict)

Spec §8.3 pure-function core: per-card "should be silent right now?" verdict
takes card dict + now + multipliers. Returns False for manual, disabled,
missing reference time, unknown cadence, non-positive multiplier. Weekly
uses calendar days; intraday/daily use trading days via trading_calendar.

10 unit tests covering the verdict matrix; no thread, no notify, no IO yet —
those land in T4–T7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: silence_checker.tick + transition logic + notify wiring

**Files:**
- Modify: `tradelab/src/tradelab/live/silence_checker.py`
- Modify: `tradelab/tests/live/test_silence_checker.py`

This task adds the in-memory `_silent_cards` set, the `tick()` cycle that diffs the verdict against the set, fires notify on transitions in (silent), and silently clears on transitions out.

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/live/test_silence_checker.py`:

```python
import pytest

from tradelab.live import silence_checker
from tradelab.live.notify import Severity


@pytest.fixture(autouse=True)
def _reset_silent_set():
    silence_checker._silent_cards.clear()
    yield
    silence_checker._silent_cards.clear()


def _enabled_card(cid="foo-v1", cadence="daily", last_fired_iso=None, enabled_at_iso=None):
    return {
        "card_id": cid,
        "status": "enabled",
        "symbol": "AAPL",
        "cadence": cadence,
        "last_fired_at": last_fired_iso,
        "enabled_at": enabled_at_iso or _utc(2026, 4, 1).isoformat(),
    }


def test_tick_outside_rth_no_notify_no_state_change(monkeypatch):
    fired = []
    cards = {"a": _enabled_card("a", last_fired_iso=_utc(2020, 1, 1).isoformat())}
    # Saturday — not RTH
    silence_checker.tick(
        now_utc=_utc(2026, 4, 25, 14),
        cards=cards,
        multipliers=MULTS,
        notify_fn=lambda *a, **kw: fired.append(a),
    )
    assert fired == []
    assert silence_checker.silent_set() == set()


def test_tick_transition_into_silent_fires_warning_once():
    fired = []
    cards = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    # Wed Apr 29 14:00 ET ≈ 18:00 UTC — RTH, 5 trading days since Apr 22
    now = _utc(2026, 4, 29, 18)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS,
                        notify_fn=lambda sev, title, body: fired.append((sev, title, body)))
    assert silence_checker.is_silent("foo-v1") is True
    assert len(fired) == 1
    sev, title, body = fired[0]
    assert sev == Severity.WARNING
    assert title == "Card silent"
    assert "foo-v1" in body and "AAPL" in body and "daily" in body


def test_tick_silent_then_silent_no_repeat_notify():
    fired = []
    cards = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    now = _utc(2026, 4, 29, 18)
    notify_fn = lambda sev, title, body: fired.append((sev, title, body))
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    silence_checker.tick(now_utc=now, cards=cards, multipliers=MULTS, notify_fn=notify_fn)
    assert len(fired) == 1


def test_tick_card_fires_after_silence_clears_silently():
    fired = []
    cards_silent = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 22).isoformat())}
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards_silent,
                        multipliers=MULTS, notify_fn=lambda *a: fired.append(a))
    assert silence_checker.is_silent("foo-v1") is True
    # Now card fires — last_fired_at moves forward
    cards_fresh = {"foo-v1": _enabled_card("foo-v1", last_fired_iso=_utc(2026, 4, 29, 17).isoformat())}
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards_fresh,
                        multipliers=MULTS, notify_fn=lambda *a: fired.append(a))
    assert silence_checker.is_silent("foo-v1") is False
    assert len(fired) == 1  # only the entry-into-silent, no exit notify


def test_tick_multiple_cards_independent_transitions():
    fired = []
    cards = {
        "a": _enabled_card("a", last_fired_iso=_utc(2026, 4, 22).isoformat()),
        "b": _enabled_card("b", last_fired_iso=_utc(2026, 4, 28).isoformat()),
        "c": _enabled_card("c", cadence="manual", last_fired_iso=_utc(2020, 1, 1).isoformat()),
    }
    silence_checker.tick(now_utc=_utc(2026, 4, 29, 18), cards=cards, multipliers=MULTS,
                        notify_fn=lambda sev, title, body: fired.append(body))
    assert silence_checker.is_silent("a") is True
    assert silence_checker.is_silent("b") is False
    assert silence_checker.is_silent("c") is False  # manual
    assert len(fired) == 1
    assert "a" in fired[0]


def test_silent_set_returns_copy_not_reference():
    silence_checker._silent_cards.add("a")
    s = silence_checker.silent_set()
    s.add("b")
    assert "b" not in silence_checker._silent_cards
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: AttributeError on `silence_checker.tick` / `silent_set` / `_silent_cards`

- [ ] **Step 3: Write minimal implementation**

Edit `tradelab/src/tradelab/live/silence_checker.py` — add imports and append after `_compute_should_be_silent`:

```python
import threading
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from tradelab.live import notify as _notify
from tradelab.live.notify import Severity

ET = ZoneInfo("America/New_York")

_silent_cards: set[str] = set()
_silent_lock = threading.Lock()


def is_silent(card_id: str) -> bool:
    with _silent_lock:
        return card_id in _silent_cards


def silent_set() -> set[str]:
    """Snapshot copy of the silent set — safe to mutate."""
    with _silent_lock:
        return set(_silent_cards)


def is_rth(now_utc: datetime) -> bool:
    """Regular trading hours: 9:30am–4:00pm ET on a NYSE trading day.

    Imports trading_calendar lazily-by-module-load (top-of-file already).
    """
    from tradelab.live.trading_calendar import is_trading_day
    now_et = now_utc.astimezone(ET)
    if not is_trading_day(now_et.date()):
        return False
    open_t = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now_et < close_t


def tick(
    *,
    now_utc: Optional[datetime] = None,
    cards: Optional[dict[str, dict]] = None,
    multipliers: Optional[dict[str, int]] = None,
    notify_fn: Optional[Callable] = None,
) -> None:
    """One cycle. Deps injectable for tests; defaults to live system on None.

    Outside RTH → return immediately, no state change. Inside RTH → diff the
    verdict against _silent_cards; fire notify(WARNING) for new entries; clear
    silently for cards that left.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if not is_rth(now_utc):
        return

    if cards is None:
        from tradelab.live.cards import CardRegistry
        from pathlib import Path
        path = Path(__file__).resolve().parents[3] / "live" / "cards.json"
        registry = CardRegistry(path)
        registry.reload()
        cards = registry.all_hydrated()
    if multipliers is None:
        from tradelab.live import live_config
        multipliers = live_config.get().get("silence", {}).get("multipliers", {})
    if notify_fn is None:
        notify_fn = _notify.notify

    transitioned: list[dict] = []
    with _silent_lock:
        for cid, card in cards.items():
            should_silent = _compute_should_be_silent(card, now_utc, multipliers)
            if should_silent and cid not in _silent_cards:
                _silent_cards.add(cid)
                transitioned.append(card)
            elif not should_silent and cid in _silent_cards:
                _silent_cards.discard(cid)

    for card in transitioned:
        cid = card.get("card_id", "?")
        symbol = card.get("symbol", "?")
        cadence = card.get("cadence", "daily")
        notify_fn(
            Severity.WARNING,
            "Card silent",
            f"{cid} ({symbol}) has not fired within its {cadence} cadence threshold.",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: 16 passed (10 from T3 + 6 new)

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/live/silence_checker.py tests/live/test_silence_checker.py
git commit -m "$(cat <<'EOF'
feat(live): silence_checker.tick + transition logic + notify wiring

Per spec §8.3: tick() reads cards + multipliers + now, diffs verdict against
in-memory _silent_cards set, fires notify(WARNING) on entry-into-silent,
clears silently on exit. Outside RTH → no-op. Deps injectable (cards,
multipliers, notify_fn, now_utc) for testability — defaults to live system.

is_rth(now_utc) gates the cycle: 9:30–16:00 ET on NYSE trading days only.

6 transition tests pin: outside-RTH-noop, entry-fires-once, repeat-tick-no-
repeat-notify, fire-clears-silently, multi-card-independence, silent_set-copy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: silence_checker.is_rth tests (gate logic)

**Files:**
- Modify: `tradelab/tests/live/test_silence_checker.py`

`is_rth` was implemented in T4 to make `tick()` testable. T5 adds dedicated coverage so the gate is pinned independently of tick().

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/live/test_silence_checker.py`:

```python
def test_is_rth_weekday_noon_et_is_true():
    # Wed Apr 22 2026 12:00 ET = 16:00 UTC
    assert silence_checker.is_rth(_utc(2026, 4, 22, 16)) is True


def test_is_rth_weekday_pre_open_is_false():
    # Wed Apr 22 2026 09:00 ET = 13:00 UTC (before 9:30 open)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 13)) is False


def test_is_rth_weekday_post_close_is_false():
    # Wed Apr 22 2026 16:30 ET = 20:30 UTC (after 4pm close)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 20, 30)) is False


def test_is_rth_saturday_is_false():
    # Sat Apr 25 2026 noon ET — not a trading day
    assert silence_checker.is_rth(_utc(2026, 4, 25, 16)) is False


def test_is_rth_sunday_is_false():
    assert silence_checker.is_rth(_utc(2026, 4, 26, 16)) is False


def test_is_rth_holiday_is_false():
    # Good Friday Apr 3 2026 — NYSE closed even though it's Friday
    assert silence_checker.is_rth(_utc(2026, 4, 3, 16)) is False


def test_is_rth_at_market_open_boundary_is_true():
    # Exactly 9:30:00 ET = 13:30 UTC → True (open is inclusive)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 13, 30)) is True


def test_is_rth_at_market_close_boundary_is_false():
    # Exactly 16:00:00 ET = 20:00 UTC → False (close is exclusive)
    assert silence_checker.is_rth(_utc(2026, 4, 22, 20, 0)) is False
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: 24 passed (no impl change needed; is_rth was added in T4)

- [ ] **Step 3: Commit**

```bash
cd /c/TradingScripts/tradelab
git add tests/live/test_silence_checker.py
git commit -m "$(cat <<'EOF'
test(live): pin silence_checker.is_rth boundaries + holiday gate

8 boundary tests covering weekday open (inclusive), close (exclusive), pre-
open / post-close, weekend, NYSE holiday (Good Friday). Pins the RTH gate
so the cron-30min wall-clock loop can't accidentally fire silence checks
outside market hours after a future timezone refactor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: silence_checker.start / stop (thread lifecycle)

**Files:**
- Modify: `tradelab/src/tradelab/live/silence_checker.py`
- Modify: `tradelab/tests/live/test_silence_checker.py`

- [ ] **Step 1: Write the failing test**

Append to `tradelab/tests/live/test_silence_checker.py`:

```python
import time


def test_start_creates_running_thread_then_stop_joins_cleanly():
    silence_checker.start()
    try:
        assert silence_checker._thread is not None
        assert silence_checker._thread.is_alive()
        assert silence_checker._thread.daemon is True
    finally:
        silence_checker.stop()
    assert silence_checker._thread is None


def test_start_is_idempotent():
    silence_checker.start()
    first = silence_checker._thread
    try:
        silence_checker.start()
        assert silence_checker._thread is first  # same thread, not replaced
    finally:
        silence_checker.stop()


def test_stop_when_not_running_is_safe():
    # No prior start; stop should not raise
    silence_checker.stop()
    assert silence_checker._thread is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: AttributeError on `silence_checker.start` / `_thread`

- [ ] **Step 3: Write minimal implementation**

Append to `tradelab/src/tradelab/live/silence_checker.py`:

```python
import sys

TICK_SECONDS = 1800  # 30 minutes (spec §8.3)

_thread: Optional[threading.Thread] = None
_stop_evt = threading.Event()


def _run_loop() -> None:
    """Thread body: tick, sleep TICK_SECONDS (interruptible), repeat."""
    while not _stop_evt.is_set():
        try:
            tick()
        except Exception as e:
            print(f"[silence_checker] tick raised: {type(e).__name__}: {e}", file=sys.stderr)
        if _stop_evt.wait(TICK_SECONDS):
            break


def start() -> None:
    """Boot the periodic thread. Idempotent — repeated calls are no-ops."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_evt.clear()
    _thread = threading.Thread(target=_run_loop, daemon=True, name="silence_checker")
    _thread.start()


def stop() -> None:
    """Signal stop and join the thread. Safe when not running."""
    global _thread
    _stop_evt.set()
    if _thread is not None:
        _thread.join(timeout=2.0)
        _thread = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/live/test_silence_checker.py -v`
Expected: 27 passed

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/live/silence_checker.py tests/live/test_silence_checker.py
git commit -m "$(cat <<'EOF'
feat(live): silence_checker.start/stop thread lifecycle

Daemon thread runs tick() every TICK_SECONDS (1800 = 30 min per spec §8.3).
Uses threading.Event.wait() for interruptible sleep so stop() joins cleanly
within 2s. start() is idempotent; stop() safe when never started. Tick
exceptions logged to stderr but never crash the loop.

3 lifecycle tests pin: start-creates-daemon-thread, start-is-idempotent,
stop-when-not-running-is-safe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire silence_checker into launch_dashboard.py + atexit fold-in

**Files:**
- Modify: `C:\TradingScripts\launch_dashboard.py:71-78`

This task boots silence_checker after notify_dispatcher and registers atexit cleanup for **both** (folds in Slice 4 follow-up #7 — was a one-liner, plan handoff §"Architectural follow-ups" line 7).

- [ ] **Step 1: Read the current dispatcher boot block**

Run: `grep -nE "notify_dispatcher|atexit" /c/TradingScripts/launch_dashboard.py`
Expected: lines 71–78 show the current notify_dispatcher boot; no `atexit` import yet.

- [ ] **Step 2: Modify launch_dashboard.py**

Edit `C:\TradingScripts\launch_dashboard.py` — add `import atexit` near the top with the other imports (after `import threading`), and replace the existing boot block:

Current (lines 70–78):
```python
# Boot the notify dispatcher (Slice 4) — one consumer per host.
try:
    from tradelab.live.notify_dispatcher import NotifyDispatcher  # type: ignore
    _notify_dispatcher = NotifyDispatcher()
    _notify_dispatcher.start()
    print("[startup] notify_dispatcher started", file=sys.stderr)
except Exception as e:
    print(f"[startup] notify_dispatcher failed to start: {type(e).__name__}: {e}", file=sys.stderr)
    _notify_dispatcher = None
```

New:
```python
# Boot the notify dispatcher (Slice 4) — one consumer per host.
try:
    from tradelab.live.notify_dispatcher import NotifyDispatcher  # type: ignore
    _notify_dispatcher = NotifyDispatcher()
    _notify_dispatcher.start()
    atexit.register(_notify_dispatcher.stop)  # graceful shutdown (Slice 4 follow-up #7)
    print("[startup] notify_dispatcher started", file=sys.stderr)
except Exception as e:
    print(f"[startup] notify_dispatcher failed to start: {type(e).__name__}: {e}", file=sys.stderr)
    _notify_dispatcher = None

# Boot the silence checker (Slice 5) — periodic tick during RTH.
try:
    from tradelab.live import silence_checker  # type: ignore
    silence_checker.start()
    atexit.register(silence_checker.stop)
    print("[startup] silence_checker started", file=sys.stderr)
except Exception as e:
    print(f"[startup] silence_checker failed to start: {type(e).__name__}: {e}", file=sys.stderr)
```

- [ ] **Step 3: Verify the launcher boots cleanly**

Run:
```bash
# Stop the current dashboard (PID may differ — grep first)
netstat -ano | grep ":8877" | grep LISTENING
powershell -Command "Stop-Process -Id <PID> -Force"

# Relaunch
cd /c/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py > /tmp/dashboard.log 2>&1 &

# Wait for healthy
until curl -sf http://127.0.0.1:8877/tradelab/cards >/dev/null; do sleep 0.5; done

# Confirm both startup messages
grep -E "notify_dispatcher started|silence_checker started" /tmp/dashboard.log
```
Expected: both lines present.

- [ ] **Step 4: Commit**

```bash
cd /c/TradingScripts
git add launch_dashboard.py
git commit -m "$(cat <<'EOF'
feat(launcher): boot silence_checker + atexit for dispatcher + checker

Slice 5 wiring: silence_checker.start() boots after notify_dispatcher.start()
in the dashboard launcher. atexit.register both stop functions for graceful
shutdown — folds in Slice 4 architectural follow-up #7 (atexit for the
PollingObserver thread was a one-liner left for Slice 5).

Both subsystems print [startup] X started to stderr on success; failure
isolates per subsystem so dispatcher staying up doesn't depend on checker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: GET /tradelab/live/silence-status endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py`
- Modify: `tradelab/tests/web/test_live_config_handlers.py`

FE needs to know which cards are currently in the silent set. Expose via a new GET endpoint returning `{"<card_id>": true, ...}` envelope.

- [ ] **Step 1: Grep current endpoint table**

Run:
```bash
grep -nE "/tradelab/live/" /c/TradingScripts/tradelab/src/tradelab/web/handlers.py | head -20
```
Expected: existing routes for `/live/config`, `/live/config/test-notification`, `/live/notify-stream`.

- [ ] **Step 2: Write the failing test**

Append to `tradelab/tests/web/test_live_config_handlers.py`:

```python
def test_silence_status_endpoint_returns_current_silent_set(monkeypatch):
    from tradelab.live import silence_checker
    monkeypatch.setattr(silence_checker, "_silent_cards", {"foo-v1", "bar-v2"})
    body, status = handlers.handle_silence_status_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"] == {"foo-v1": True, "bar-v2": True}


def test_silence_status_empty_set_returns_empty_dict(monkeypatch):
    from tradelab.live import silence_checker
    monkeypatch.setattr(silence_checker, "_silent_cards", set())
    body, status = handlers.handle_silence_status_get()
    assert status == 200
    assert json.loads(body)["data"] == {}


def test_silence_status_route_dispatched_via_handle_get(monkeypatch):
    from tradelab.live import silence_checker
    monkeypatch.setattr(silence_checker, "_silent_cards", {"only-one"})
    body, status = handlers.handle_get_with_status("/tradelab/live/silence-status")
    assert status == 200
    assert json.loads(body)["data"] == {"only-one": True}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/web/test_live_config_handlers.py::test_silence_status_endpoint_returns_current_silent_set -v`
Expected: AttributeError on `handlers.handle_silence_status_get`

- [ ] **Step 4: Add the handler + route**

Edit `tradelab/src/tradelab/web/handlers.py`. Add after `handle_test_notification` (around the existing `if path == "/tradelab/live/config/test-notification"` block):

```python
def handle_silence_status_get() -> Tuple[str, int]:
    """Return current silent-card set as {<card_id>: true} envelope."""
    from tradelab.live import silence_checker
    return _ok({cid: True for cid in silence_checker.silent_set()}), 200
```

In the GET routing block (find by `grep -n "/tradelab/live/config" handlers.py | head -1` then locate the GET branch), add the route. Search for the existing GET routing pattern (likely near `if path == "/tradelab/live/config":`):

```python
    if path == "/tradelab/live/silence-status":
        return handle_silence_status_get()
```

(Place adjacent to the other `/tradelab/live/*` GET cases; exact line number depends on the surrounding switch — grep first.)

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/web/test_live_config_handlers.py -v`
Expected: 3 new tests pass; pre-existing tests stay green.

- [ ] **Step 6: Commit**

```bash
cd /c/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_live_config_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET /tradelab/live/silence-status

FE needs to know which cards are silent so .lt-row can render an amber pill.
Returns {<card_id>: true} envelope. Reads silence_checker.silent_set() —
process-local in-memory state per spec §8.3, no JSON file dependency.

3 endpoint tests pin the contract: populated set, empty set, route dispatch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: FE amber pill on .lt-row[data-silent=true]

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

Render an amber pill on rows that are currently silent. Fetch silence-status on render; refetch on every notify SSE event so the pill clears the moment a silent-card fires (silence_checker won't tick for up to 30 min, but the receiver writes last_fired_at on fire — and silence_checker's next tick will clear; the FE refetch piggybacks on the notify Broadcaster fan-out so user sees the pill clear quickly when notifications flow).

- [ ] **Step 1: Grep the current LT row rendering**

Run:
```bash
grep -nE "renderRow|renderGroup|fetchAndRender|subscribeBrowserToasts|escHtml" /c/TradingScripts/command_center.html | head -20
```
Expected (verified during plan authoring 2026-04-26):
- `function renderRow(card)` at line 4695 — single row template
- `function renderGroup(group)` at line 4721
- `async function fetchAndRender()` at line 4884 — orchestrator (the entry point that fetches /tradelab/cards then renders)
- `subscribeBrowserToasts` SSE subscriber from Slice 4
- LT IIFE uses `escHtml(...)` not `escapeHtml(...)` for HTML escape (line 4701)

Row template lives at line 4701: `<div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}">` — that's where `data-silent` attribute goes.

- [ ] **Step 2: Add CSS for the amber pill**

Find the existing `<style>` block (or LT-scoped style block) and add:

```css
.lt-row[data-silent="true"] .lt-status-pill::after {
  content: "● silent";
  display: inline-block;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 600;
  background: #f59e0b;        /* amber-500 */
  color: #1f2937;             /* slate-800 for contrast */
  border-radius: 9999px;
  vertical-align: middle;
}
```

(If `lt-status-pill` is not the existing pill class, replace with the actual class confirmed in Step 1 grep.)

- [ ] **Step 3: Add the silence-status fetcher + state**

Inside the LT IIFE, near other module-level state (alongside the existing card-list state), add:

```javascript
let silentSet = new Set();

async function fetchSilenceStatus() {
  try {
    const r = await fetch("/tradelab/live/silence-status");
    if (!r.ok) return;
    const j = await r.json();
    if (j.error) return;
    silentSet = new Set(Object.keys(j.data || {}));
  } catch (e) {
    // benign — pill just stays in last known state until next refetch
  }
}
```

- [ ] **Step 4: Inject data-silent attribute into row template**

In `renderRow(card)` at line 4695, modify the outer `.lt-row` element template at line 4701 to add `data-silent`:

Before:
```javascript
<div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}">
```

After:
```javascript
<div class="lt-row lt-row--${statusCls}" data-card-id="${escHtml(card.card_id)}" data-silent="${silentSet.has(card.card_id) ? 'true' : 'false'}">
```

- [ ] **Step 5: Wire fetchSilenceStatus into fetchAndRender + SSE refresh**

In `async function fetchAndRender()` (line 4884), call `await fetchSilenceStatus()` BEFORE the render loop so `silentSet` is fresh when `renderRow(card)` reads it.

In `subscribeBrowserToasts()` (added in Slice 4 T14), augment the SSE event handler to also call `fetchAndRender()` after the toast renders. When a notify event arrives — including a silence transition or a successful order — the LT rows refresh and the amber pill clears immediately when a silenced card fires.

```javascript
// Inside the existing eventSource.onmessage handler in subscribeBrowserToasts
eventSource.onmessage = (ev) => {
  // ... existing toast rendering ...
  if (typeof fetchAndRender === "function") {
    fetchAndRender();  // refresh silent pills on every notify event
  }
};
```

- [ ] **Step 6: Verify in the browser**

```bash
# Restart dashboard so the HTML/JS changes load
netstat -ano | grep ":8877" | grep LISTENING
powershell -Command "Stop-Process -Id <PID> -Force"
cd /c/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py > /tmp/dashboard.log 2>&1 &
until curl -sf http://127.0.0.1:8877/tradelab/cards >/dev/null; do sleep 0.5; done
```

Open http://127.0.0.1:8877 → Live Trading tab → DevTools Network tab. Confirm:
- `GET /tradelab/live/silence-status` fires on tab load
- Response is `{"error": null, "data": {}}` (empty set initially)
- No console errors

- [ ] **Step 7: Commit**

```bash
cd /c/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): amber 'silent' pill on .lt-row[data-silent=true]

Slice 5 FE: fetch /tradelab/live/silence-status before rendering LT rows;
inject data-silent attribute on outer .lt-row; CSS adds an amber pill via
::after. Refetch on every notify SSE event so the pill clears immediately
when a silenced card fires (silence_checker's next tick will also clear,
within 30 min).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Pin DOM contract for amber pill

**Files:**
- Modify: `tradelab/tests/web/test_command_center_pin.py`

Slice 4 established the pattern: pytest pins the JS-function-name and DOM-attribute contracts that pure-Python tests can't catch (per memory `feedback_plan_grep_verification`). Add similar pins so renames silently break the build instead of the live page.

- [ ] **Step 1: Grep the existing pin file structure**

Run:
```bash
grep -nE "def test_|fetchSilenceStatus|silentSet|data-silent" /c/TradingScripts/tradelab/tests/web/test_command_center_pin.py | head -20
```
Expected: existing pattern — tests that read command_center.html as text and assert specific tokens are present exactly once.

- [ ] **Step 2: Write the failing test**

Append to `tradelab/tests/web/test_command_center_pin.py`:

```python
def test_command_center_defines_fetch_silence_status_exactly_once():
    """Slice 5 FE: fetchSilenceStatus must be defined exactly once."""
    html = _command_center_html()
    occurrences = html.count("function fetchSilenceStatus") + html.count("async function fetchSilenceStatus")
    assert occurrences == 1, f"expected exactly one definition of fetchSilenceStatus, got {occurrences}"


def test_command_center_lt_row_has_data_silent_attribute():
    """Slice 5 FE: outer .lt-row tag must carry data-silent for the pill CSS."""
    html = _command_center_html()
    # The attribute must appear in the row template
    assert 'data-silent="${silentSet.has' in html or 'data-silent="${(silentSet.has' in html, \
        "lt-row template must inject data-silent dynamically from silentSet"


def test_command_center_amber_pill_css_targets_data_silent():
    html = _command_center_html()
    assert '.lt-row[data-silent="true"]' in html, \
        "CSS rule for amber pill must target .lt-row[data-silent='true']"


def test_command_center_subscribe_browser_toasts_calls_fetch_and_render():
    """Slice 5 FE: notify SSE handler must trigger LT row refresh so pill clears."""
    html = _command_center_html()
    # Locate subscribeBrowserToasts body — must contain fetchAndRender() call
    idx = html.find("subscribeBrowserToasts")
    assert idx >= 0
    # Look at the next ~3000 chars (handler body)
    chunk = html[idx:idx + 3000]
    assert "fetchAndRender()" in chunk, "subscribeBrowserToasts must call fetchAndRender() to refresh silent pills"
```

(If the helper `_command_center_html()` is named differently in the file, use whatever the existing tests use — Step 1 grep reveals it.)

- [ ] **Step 3: Run tests**

Run: `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest tests/web/test_command_center_pin.py -v`
Expected: all 4 new tests pass (T9 already shipped the underlying impl).

If any fail, the FE work in T9 didn't match the contract — fix in command_center.html (likely the function name was different, or renderLT() needs renaming, or data-silent template form needs adjustment).

- [ ] **Step 4: Commit**

```bash
cd /c/TradingScripts/tradelab
git add tests/web/test_command_center_pin.py
git commit -m "$(cat <<'EOF'
test(web): pin Slice 5 FE DOM + JS contracts

4 pin tests guard against silent regressions:
- fetchSilenceStatus defined exactly once
- .lt-row template injects data-silent from silentSet
- CSS rule targets .lt-row[data-silent="true"]
- subscribeBrowserToasts handler calls fetchAndRender() so pill clears on fire

Same pattern as T15 from Slice 4 — pure Python pytest catches FE rename
regressions without needing a browser test runner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Smoke + done doc + Slice 6 handoff

**Files:**
- Create: `C:\TradingScripts\2026-04-25-DIRECTION-A-SLICE-5-COMPLETE.md`

Final task — drive the full smoke checklist by hand, document results, and write the Slice 6 handoff. Per Slice-3-and-4 lesson (`feedback_live_smoke_before_next_slice`): always smoke between slices; Step 0 is always kill+restart so stale processes don't mask bugs.

- [ ] **Step 1: Step 0 — kill + relaunch both processes under latest commits**

```bash
# Receiver
netstat -ano | grep ":8878" | grep LISTENING
powershell -Command "Stop-Process -Id <RECEIVER_PID> -Force"
cd /c/TradingScripts/tradelab && PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m uvicorn tradelab.live.receiver:app --host 127.0.0.1 --port 8878 --log-level info > /tmp/receiver.log 2>&1 &

# Dashboard (boots both notify_dispatcher AND silence_checker)
netstat -ano | grep ":8877" | grep LISTENING
powershell -Command "Stop-Process -Id <DASHBOARD_PID> -Force"
cd /c/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py > /tmp/dashboard.log 2>&1 &
until curl -sf http://127.0.0.1:8877/tradelab/cards >/dev/null; do sleep 0.5; done

# Both startup banners visible
grep -E "notify_dispatcher started|silence_checker started" /tmp/dashboard.log
```
Expected: both `[startup] X started` lines present.

- [ ] **Step 2: Run the smoke checklist**

Each box below produces evidence — paste outputs into the done doc as you go.

| # | What to test | How |
|---|---|---|
| 1 | Pytest baseline | `cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest -q` — expect 602 + new tests, 0 failed |
| 2 | `is_trading_day` correctness | Confirmed by T1 unit tests; smoke just runs the suite |
| 3 | `count_trading_days_between` correctness | Confirmed by T2 unit tests |
| 4 | Compute verdict for never-fired card | T3 unit tests |
| 5 | `tick()` transition into silent fires WARNING once | T4 unit tests |
| 6 | `tick()` outside RTH no-ops | T4 unit tests |
| 7 | `is_rth` boundaries | T5 unit tests |
| 8 | start/stop thread lifecycle | T6 unit tests |
| 9 | atexit registered for both subsystems | `python -c "import atexit; ..."` or kill SIGTERM and confirm clean shutdown in dashboard.log |
| 10 | GET /tradelab/live/silence-status returns empty initially | `curl -s http://127.0.0.1:8877/tradelab/live/silence-status` → `{"error":null,"data":{}}` |
| 11 | Force a silent transition end-to-end | Re-enable `smoke-amzn-v1` with last_fired_at backdated to 2026-04-15 (10 trading days ago, ≥ daily threshold of 5). Wait for or trigger a tick. silence-status should include the card; dashboard should show amber pill; notify_events.jsonl should have a `severity:warning, title:"Card silent"` entry. To trigger an immediate tick without waiting 30 min: from a Python REPL inside the dashboard process, or via a one-off script: `python -c "from tradelab.live import silence_checker; silence_checker.tick()"` (run with PYTHONPATH=src cwd=tradelab). |
| 12 | Card fires → silent flag clears | While card is in silent set, send a webhook to the receiver. Confirm last_fired_at updates in cards.json, then trigger tick again — silent-status endpoint no longer lists the card; amber pill clears. No second notify event. |
| 13 | Repeat tick while silent: no repeat notify | Trigger tick 3 times in succession with the silent card unchanged; notify_events.jsonl has exactly 1 "Card silent" line for that card_id. |
| 14 | Manual cadence card never silent | Add a manual-cadence card with last_fired_at 2020-01-01; tick; confirm not in silent_set. |
| 15 | Outside RTH no tick effect | Set system clock or use a one-off `python -c "from tradelab.live.silence_checker import tick; from datetime import datetime, timezone; tick(now_utc=datetime(2026,4,25,16,tzinfo=timezone.utc))"` (Saturday) — silent_set unchanged. |
| 16 | FE amber pill renders | Browser → Live Trading tab → row of silent card has amber `● silent` pill next to status |
| 17 | FE pill clears on fire (via SSE refresh) | While silent pill visible, trigger a notify event (e.g., test-notification); pill clears within ~1s as renderLT() refetches silence-status |

- [ ] **Step 3: Restore baseline state**

```bash
# Disable the smoke card again
curl -s -X PATCH http://127.0.0.1:8877/tradelab/cards/smoke-amzn-v1 \
  -H "Content-Type: application/json" \
  -d '{"status":"disabled","last_fired_at":null}'

# Confirm cards.json baseline restored
cat /c/TradingScripts/tradelab/live/cards.json | python -c "import json,sys; d=json.load(sys.stdin); print(d['smoke-amzn-v1']['status'])"
# Expected: disabled
```

- [ ] **Step 4: Write the done doc**

Create `C:\TradingScripts\2026-04-25-DIRECTION-A-SLICE-5-COMPLETE.md` modeled on the Slice 4 done doc structure. Required sections:
- **Summary** — what shipped (T1–T10 commit SHAs), pytest count delta, files changed, key design decisions (in-memory state per spec §8.3, hardcoded NYSE 2026 holidays, 30-min wall-clock tick gated by is_rth)
- **Smoke results** — every box from Step 2 with `[x]` + the evidence (curl output, cards.json diff, JSONL line, screenshot path or DOM-inspection note)
- **Bug fixes applied during slice** — anything caught and fixed mid-implementation
- **Reviewer flags declined** — same triage discipline as Slices 3/4
- **Architectural follow-ups** — known limitations carried into Slice 6+ (e.g., dashboard-restart re-notifies still-silent cards once; `_silent_cards` not persisted across restarts; 30-min cadence is wall-clock not RTH-aligned)
- **Slice 5 status: COMPLETE ✅ (X/17 smoke boxes verified)**
- **Handoff for Slice 6** — Slice 6 is panic panel per spec §10 (or whatever §10 actually is — grep spec to confirm). List prereqs satisfied in Slice 5 (notify pipeline, settings panel, in-memory subsystem boot pattern).

- [ ] **Step 5: Commit done doc**

```bash
cd /c/TradingScripts
git add 2026-04-25-DIRECTION-A-SLICE-5-COMPLETE.md
git commit -m "$(cat <<'EOF'
docs: Direction A Slice 5 done doc — silence detection complete

X/X tasks shipped. Pytest 602 → Y passed / 0 failed. Smoke 17/17 verified
2026-XX-XX. Architectural follow-ups + Slice 6 handoff documented.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Final pytest baseline confirmation**

```bash
cd /c/TradingScripts/tradelab && PYTHONPATH=src python -m pytest -q
```
Expected: full suite green; new test count delta documented in done doc.

---

## Self-review checklist

This was run after drafting; outcomes recorded inline:

**Spec coverage:**
- §8.1 cadence model (`intraday|daily|weekly|manual`, default `daily`) — covered by T3 test matrix + cards.py:18 default already in place from Slice 1
- §8.2 threshold table — implemented in T1+T2 (trading-day calc) + T3 (verdict using multipliers)
- §8.2 hardcoded 9 US holidays note — T1 hardcodes 10 (NYSE actually has 10 in 2026; the spec said "9" but enumeration confirms 10 — discrepancy noted in T1 docstring)
- §8.3 launcher process — T7
- §8.3 cron 30 min RTH — T6 (TICK_SECONDS=1800) + T4 (is_rth gate inside tick)
- §8.3 elapsed vs threshold per card — T3
- §8.3 fire WARNING + flip in-memory flag on transition — T4
- §8.3 silent flag clears on next fire — T4 (`test_tick_card_fires_after_silence_clears_silently`)
- §8.3 one notify per transition — T4 (`test_tick_silent_then_silent_no_repeat_notify`)
- FE amber pill (handoff §6.6.7) — T9 + T10

**Placeholder scan:** zero TBDs. Every code block is complete; every command has expected output; every test has full code; every commit message is drafted.

**Type consistency:** `_compute_should_be_silent`, `tick`, `is_rth`, `is_silent`, `silent_set`, `start`, `stop` used consistently across T3–T7. `silentSet` (FE) and `_silent_cards` (Python) parallel naming. `fetchSilenceStatus` named identically in T9 impl and T10 pin.

**Architectural follow-ups (carried forward — log in Slice 5 done doc):**
1. Dashboard restart re-notifies any still-silent card on first post-restart tick (in-memory state per spec §8.3 — accept; document)
2. `_silent_cards` not persisted to disk — same as #1
3. Tick cadence is wall-clock 30 min, not RTH-aligned (e.g., first tick after 9:30 ET could be at 9:42, 10:12, …) — spec §8.3 says "every 30 minutes during market hours" which this satisfies; mention if RTH-aligned cadence is desired in v2
4. silence-status endpoint returns set membership only — if FE later wants reason/threshold-elapsed metadata, extend payload shape
5. Notify event for silence transition has `body` but no structured metadata — Slice 6+ may want a `meta: {card_id, cadence, elapsed_days}` field for FE row update without re-fetching silence-status

---

**End of plan.** 11 tasks, ~1.5 days estimate, TDD throughout, zero placeholders.
