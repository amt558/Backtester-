# Direction A — Slice 7a — Daily Email Summary (code only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the daily 16:00 ET HTML email digest (anomaly debrief + health snapshot), the dashboard preview surface, and bundled cleanup of two carry-over architectural follow-ups (F1 receiver Alpaca exception wrapping, F2 jsonl rotation utility). Closes the code path for Direction A v1; the manual rewrite ships separately as Slice 7b.

**Architecture:** New `daily_summary.py` runs as a daemon thread in the launcher process (mirrors `silence_checker.py` shape) — pure `render(now)` produces (subject, html_body), `tick(now)` is RTH+send_time-gated and idempotent via `digest_state.json`. Send is direct via `notify_channels.email.send()` (NOT through `notify()` — avoids recursive logging). New `jsonl_rotation.py` is called once-per-day from the same tick after a successful send. Two new GET endpoints expose preview HTML and last-sent state. F1 wraps `build_alpaca_state()` in `receiver.py` with a fail-closed `try/except APIError`.

**Tech Stack:** Python 3.11, alpaca-py SDK, smtplib (already wired in Slice 4 `notify_channels/email.py`), pytest, vanilla HTML/CSS/JS (settings panel additions in `command_center.html`).

**Spec:** `docs/superpowers/specs/2026-04-26-direction-a-slice-7-daily-summary-design.md` (commits `cc37306` + `eca54fb`).

**Out of scope for 7a:** `TRADELAB_MANUAL.html` rewrite (Slice 7b).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/tradelab/live/jsonl_rotation.py` | NEW | `rotate_if_needed(path, max_size_mb, keep_archives)` + `rotate_all()`; gzip archives; best-effort (catches OSError, never raises) |
| `src/tradelab/live/daily_summary.py` | NEW | `render(now) -> (subject, html_body)`; `tick(now)`; `start()/stop()` daemon-thread lifecycle; state persistence; retry policy |
| `src/tradelab/live/_jsonl_helpers.py` | NEW | Tiny shared helper: `read_today_lines(path, today_et)` (read-all, filter by ET date, skip corrupt) — used by `daily_summary.render()` for the three jsonl data sources |
| `src/tradelab/live/receiver.py` | Modify | F1 — wrap `build_alpaca_state()` (or its inline equivalent) with `try/except APIError` → `_reject(card_id, "alpaca_unreachable", ...)` + CRITICAL notify |
| `src/tradelab/web/handlers.py` | Modify | Add 2 GET handlers: `handle_digest_preview_get()`, `handle_digest_state_get()`; register both routes in `handle_get()` dispatcher |
| `live/digest_state.json` | NEW (runtime) | Single-line JSON, gitignored; `{last_sent_date, last_sent_failed, last_attempted_at, attempts_today}` |
| `.gitignore` | Modify | Add `live/digest_state.json` to ignore list |
| `command_center.html` (parent repo) | Modify | Settings-panel Email Digest section: wire-up enabled toggle + send_time input → PATCH config; add [🔄 Refresh preview] button + iframe + "Last sent" status line; new JS functions `loadDigestPreview()` + `loadDigestState()` + state PATCHers |
| `launch_dashboard.py` (parent repo) | Modify | Boot `daily_summary.start()` after `silence_checker.start()`; register `atexit.register(daily_summary.stop)` |
| `tests/live/test_jsonl_rotation.py` | NEW | Rotation: under-threshold no-op, over-threshold rotates with .gz, archive cap (oldest deleted), OSError swallowed, missing-file no-op, three-file `rotate_all` integration, naming collision (multiple rotations same day) |
| `tests/live/test_daily_summary_render.py` | NEW | `render()` pure-function: subject formatting, all 6 anomaly types, snapshot section, error-section degradation, ET timezone correctness, malformed-jsonl handling, all-clear case |
| `tests/live/test_daily_summary_tick.py` | NEW | `tick()` gating: not-trading-day, before-send-time, disabled-config, idempotency (already-sent today), retry-after-failure, retry-cap (5 attempts/day) |
| `tests/live/test_daily_summary_state.py` | NEW | State file: atomic write, read-on-startup, corrupt-file recovery, restart idempotency, attempts_today reset on new day |
| `tests/live/test_jsonl_helpers.py` | NEW | `read_today_lines`: empty file, missing file, mixed-date entries, ET timezone boundary, skip-corrupt-line behavior |
| `tests/live/test_receiver_alpaca_wrap.py` | NEW | F1: APIError on `build_alpaca_state` → `alpaca_unreachable` reject + CRITICAL notify; happy path unchanged |
| `tests/web/test_digest_handlers.py` | NEW | GET `/preview` returns HTML 200 with expected markers; GET `/state` returns JSON envelope; render-error → 500; missing state file → `data: null` |
| `tests/web/test_digest_fe_contract.py` | NEW | FE contract: `loadDigestPreview` JS function present in served HTML, settings-panel iframe markup present, [Refresh preview] button present, "Last sent" status line container present |

**Total: 16 task blocks. ~45-50 net-new tests. Estimated 13-17 hours.**

---

## Dependency graph & parallelization

```
T1 (jsonl_rotation)          ─────────────┐
T2 (jsonl_helpers)           ─────────────┤
T13 (F1 receiver wrap)       ─────────────┤  Independent — run in parallel
                                          ↓
T3 (render anomaly)  → T4 (render snapshot) → T5 (render assembly + plaintext)
                                                ↓
                                              T6 (tick + state) → T7 (retry policy) → T8 (start/stop)
                                                                                       ↓
                              ┌────────── T9 (preview endpoint) ──┐
                              ├────────── T10 (state endpoint) ───┤  Endpoints can run parallel
                                                                  ↓
                              T11 (FE config wire-ups) → T12 (FE preview UI)
                                                          ↓
                                                        T14 (launcher wiring)
                                                          ↓
                                                        T15 (gitignore)
                                                          ↓
                                                        T16 (full pytest run)
```

Subagent-driven dispatch can run T1+T2+T13 in parallel as the first wave; T9+T10 in parallel after T8; otherwise sequential.

---

## Task 1: `jsonl_rotation.py` — generic gzip-based log rotation utility

**Files:**
- Create: `src/tradelab/live/jsonl_rotation.py`
- Test: `tests/live/test_jsonl_rotation.py` (NEW)

**Why first:** No dependencies on other Slice 7 work. Independent of T2 and T13 — can run in parallel with both.

- [ ] **Step 1: Write failing tests for `rotate_if_needed` (no-op cases)**

Create `tests/live/test_jsonl_rotation.py`:

```python
"""Tests for jsonl_rotation utility added in Slice 7a."""
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.live import jsonl_rotation


def test_rotate_if_needed_missing_file_returns_none(tmp_path):
    p = tmp_path / "absent.jsonl"
    assert jsonl_rotation.rotate_if_needed(p) is None


def test_rotate_if_needed_under_threshold_returns_none(tmp_path):
    p = tmp_path / "small.jsonl"
    p.write_text('{"x":1}\n', encoding="utf-8")
    assert jsonl_rotation.rotate_if_needed(p, max_size_mb=1) is None
    # Original file untouched
    assert p.read_text(encoding="utf-8") == '{"x":1}\n'


def test_rotate_if_needed_oserror_returns_none_does_not_raise(tmp_path):
    p = tmp_path / "broken.jsonl"
    p.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    with patch("tradelab.live.jsonl_rotation.os.replace", side_effect=OSError("simulated")):
        # Should not raise; should return None
        result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert result is None
```

- [ ] **Step 2: Write failing tests for `rotate_if_needed` (rotation cases)**

Append to `tests/live/test_jsonl_rotation.py`:

```python
def test_rotate_if_needed_over_threshold_creates_gz(tmp_path):
    p = tmp_path / "big.jsonl"
    payload = '{"a":1}\n' * 200_000  # ~1.6 MB
    p.write_text(payload, encoding="utf-8")

    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert archive is not None
    assert archive.exists()
    assert archive.suffix == ".gz"
    # Original file should now be empty (started fresh)
    assert p.read_text(encoding="utf-8") == ""
    # Archive should round-trip via gzip
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        assert f.read() == payload


def test_rotate_if_needed_naming_collision_increments_n(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text("a" * (2 * 1024 * 1024), encoding="utf-8")  # >1 MB

    # Pre-create today's N=0 archive so the rotator must pick N=1
    from datetime import datetime
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    pre_existing = tmp_path / f"log.{today}.0.jsonl.gz"
    pre_existing.write_bytes(b"prior")

    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert archive is not None
    assert archive.name == f"log.{today}.1.jsonl.gz"
    # Pre-existing archive untouched
    assert pre_existing.read_bytes() == b"prior"


def test_rotate_if_needed_archive_cap_drops_oldest(tmp_path):
    p = tmp_path / "log.jsonl"

    # Create 4 fake old archives (pretend they exist from prior days)
    for i, day in enumerate(["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"]):
        (tmp_path / f"log.{day}.0.jsonl.gz").write_bytes(b"old" + str(i).encode())

    # Now trigger a rotation that would create a 5th archive — keep_archives=3
    p.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1, keep_archives=3)

    assert archive is not None
    archives = sorted(tmp_path.glob("log.*.jsonl.gz"))
    # Should now have exactly 3 archives total (the cap)
    assert len(archives) == 3
    # The oldest two (2026-04-20, 2026-04-21) should be gone
    surviving_names = {a.name for a in archives}
    assert not any("2026-04-20" in n or "2026-04-21" in n for n in surviving_names)
```

- [ ] **Step 3: Write failing test for `rotate_all` integration**

Append to `tests/live/test_jsonl_rotation.py`:

```python
def test_rotate_all_handles_three_files(tmp_path, monkeypatch):
    """rotate_all should call rotate_if_needed on alerts, notify_events, panic_events."""
    alerts = tmp_path / "alerts.jsonl"
    notify = tmp_path / "notify_events.jsonl"
    panic = tmp_path / "panic_events.jsonl"
    alerts.write_text("a\n", encoding="utf-8")
    notify.write_text("b\n", encoding="utf-8")
    # panic deliberately missing (no rotation needed)

    monkeypatch.setattr(jsonl_rotation, "ALERTS_PATH", alerts)
    monkeypatch.setattr(jsonl_rotation, "NOTIFY_PATH", notify)
    monkeypatch.setattr(jsonl_rotation, "PANIC_PATH", panic)

    result = jsonl_rotation.rotate_all()

    # All three keys present; values are None (under threshold or missing)
    assert set(result.keys()) == {"alerts", "notify_events", "panic_events"}
    assert all(v is None for v in result.values())
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_jsonl_rotation.py -v`
Expected: ImportError or ModuleNotFoundError (`tradelab.live.jsonl_rotation` does not exist yet).

- [ ] **Step 5: Implement `jsonl_rotation.py`**

Create `src/tradelab/live/jsonl_rotation.py`:

```python
"""JSONL log rotation utility — gzip-based, size-triggered, archive-capped.

Used by daily_summary.tick() to rotate the three append-only logs once per
trading day after a successful digest send. Best-effort: catches OSError,
logs to stderr, never raises.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Default paths — pointed to the live data dir. Tests monkeypatch these.
_LIVE_DIR = Path(__file__).resolve().parents[3] / "live"
ALERTS_PATH = _LIVE_DIR / "alerts.jsonl"
NOTIFY_PATH = _LIVE_DIR / "notify_events.jsonl"
PANIC_PATH = _LIVE_DIR / "panic_events.jsonl"


def _today_et_str() -> str:
    """Today's date as YYYY-MM-DD in local server time. Plan picks local; ET conversion
    not strictly required here because rotation timing is "after digest send" which is
    already ET-gated. Keeps this helper dependency-free of pytz/zoneinfo."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _next_archive_path(path: Path, today: str) -> Path:
    """Compute next available `<base>.YYYY-MM-DD.N.jsonl.gz` for today.

    Looks at existing archives in the same dir; picks N = max(existing_N) + 1
    for today's date, or 0 if no archive exists for today.
    """
    base = path.stem  # e.g. "alerts" from "alerts.jsonl"
    parent = path.parent
    pattern = f"{base}.{today}.*.jsonl.gz"
    existing = list(parent.glob(pattern))
    used_n = []
    for p in existing:
        # p.name like "alerts.2026-04-27.3.jsonl.gz" → extract the "3"
        try:
            n_str = p.name.removeprefix(f"{base}.{today}.").removesuffix(".jsonl.gz")
            used_n.append(int(n_str))
        except (ValueError, AttributeError):
            continue
    next_n = (max(used_n) + 1) if used_n else 0
    return parent / f"{base}.{today}.{next_n}.jsonl.gz"


def _enforce_archive_cap(path: Path, keep_archives: int) -> None:
    """Delete oldest <base>.*.jsonl.gz files until count <= keep_archives.

    Best-effort. Sorts by mtime ascending; oldest deleted first.
    """
    base = path.stem
    parent = path.parent
    archives = sorted(parent.glob(f"{base}.*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    while len(archives) > keep_archives:
        victim = archives.pop(0)
        try:
            victim.unlink()
        except OSError as e:
            print(f"[jsonl_rotation] failed to delete archive {victim}: {e}", file=sys.stderr)
            break  # don't loop on persistent failure


def rotate_if_needed(
    path: Path,
    max_size_mb: int = 50,
    keep_archives: int = 5,
) -> Optional[Path]:
    """If path exceeds max_size_mb, rename to `<base>.YYYY-MM-DD.N.jsonl.gz` and start fresh.

    Returns the rotated archive Path on success, or None if no rotation occurred
    (file missing, under threshold, or OSError caught).
    """
    try:
        if not path.exists():
            return None
        size_bytes = path.stat().st_size
        if size_bytes < max_size_mb * 1024 * 1024:
            return None

        today = _today_et_str()
        archive = _next_archive_path(path, today)

        # Stream-compress: read source, write gz; then truncate source.
        with open(path, "rb") as src, gzip.open(archive, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Atomic-ish truncate: replace with empty file
        empty_tmp = path.with_suffix(path.suffix + ".tmp")
        empty_tmp.write_bytes(b"")
        os.replace(empty_tmp, path)

        _enforce_archive_cap(path, keep_archives)
        return archive
    except OSError as e:
        print(f"[jsonl_rotation] rotate failed for {path}: {e}", file=sys.stderr)
        return None


def rotate_all() -> dict[str, Optional[Path]]:
    """Rotate alerts.jsonl, notify_events.jsonl, panic_events.jsonl with default thresholds.

    Returns map of name → rotation result for caller logging.
    """
    return {
        "alerts": rotate_if_needed(ALERTS_PATH),
        "notify_events": rotate_if_needed(NOTIFY_PATH),
        "panic_events": rotate_if_needed(PANIC_PATH),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_jsonl_rotation.py -v`
Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/jsonl_rotation.py tests/live/test_jsonl_rotation.py
git commit -m "feat(live): jsonl_rotation utility with gzip archives + cap

rotate_if_needed: size-triggered rotation to <base>.YYYY-MM-DD.N.jsonl.gz
with archive count cap; best-effort OSError handling.
rotate_all: convenience wrapper for alerts/notify_events/panic_events.

Slice 7a — T1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `_jsonl_helpers.py` — `read_today_lines` shared helper

**Files:**
- Create: `src/tradelab/live/_jsonl_helpers.py`
- Test: `tests/live/test_jsonl_helpers.py` (NEW)

**Why second:** Used by `daily_summary.render()` for the three jsonl data sources. Independent of T1 and T13 — can run in parallel with both.

- [ ] **Step 1: Write failing tests**

Create `tests/live/test_jsonl_helpers.py`:

```python
"""Tests for _jsonl_helpers shared by daily_summary.render()."""
from datetime import date

import pytest

from tradelab.live import _jsonl_helpers


def test_read_today_lines_missing_file_returns_empty(tmp_path):
    p = tmp_path / "absent.jsonl"
    assert _jsonl_helpers.read_today_lines(p, date(2026, 4, 27)) == []


def test_read_today_lines_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert _jsonl_helpers.read_today_lines(p, date(2026, 4, 27)) == []


def test_read_today_lines_filters_by_today_in_et(tmp_path):
    p = tmp_path / "log.jsonl"
    # Two entries today (in ET), one yesterday
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'      # 09:30 ET on 04-27
        '{"ts":"2026-04-27T20:00:00+00:00","x":2}\n'      # 16:00 ET on 04-27
        '{"ts":"2026-04-26T20:00:00+00:00","x":3}\n',     # 16:00 ET on 04-26 — yesterday
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 2
    assert [e["x"] for e in out] == [1, 2]


def test_read_today_lines_skips_corrupt_lines(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'
        '{garbage not json}\n'
        '{"ts":"2026-04-27T14:00:00+00:00","x":2}\n',
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 2
    assert [e["x"] for e in out] == [1, 2]


def test_read_today_lines_skips_entries_missing_ts(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'
        '{"no_ts_field":true}\n'
        '{"ts":"not a timestamp","x":2}\n',
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 1
    assert out[0]["x"] == 1


def test_read_today_lines_handles_pre_market_et_boundary(tmp_path):
    """An entry at 23:00 ET on 04-27 is at 03:00 UTC on 04-28.
    Filter for `today=date(2026, 4, 27)` should still include it."""
    p = tmp_path / "log.jsonl"
    p.write_text('{"ts":"2026-04-28T03:00:00+00:00","x":1}\n', encoding="utf-8")
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_jsonl_helpers.py -v`
Expected: ImportError (`tradelab.live._jsonl_helpers` does not exist yet).

- [ ] **Step 3: Implement `_jsonl_helpers.py`**

Create `src/tradelab/live/_jsonl_helpers.py`:

```python
"""Shared JSONL helpers for daily_summary.render() data sources.

read_today_lines: read a jsonl file, filter to entries whose `ts` (ISO 8601
UTC) corresponds to the given date in America/New_York. Skips corrupt lines
silently. Returns list of dicts in original file order.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — Windows may need tzdata
    import pytz
    _ET = pytz.timezone("America/New_York")


def _parse_ts_to_et_date(ts_value: Any) -> date | None:
    """Parse an ISO 8601 timestamp (with or without offset) and return its date in ET.
    Returns None on any parse failure or unsupported type."""
    if not isinstance(ts_value, str):
        return None
    try:
        # fromisoformat handles "2026-04-27T13:30:00+00:00" natively in Py3.11
        # Fallback for trailing "Z" form
        ts = ts_value.replace("Z", "+00:00") if ts_value.endswith("Z") else ts_value
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(_ET).date()


def read_today_lines(path: Path, today_et: date) -> list[dict]:
    """Read jsonl at `path`, return entries whose `ts` field falls on `today_et` in ET.

    Returns [] if file is missing, empty, or unreadable. Skips lines that
    don't parse as JSON, lack a `ts` field, or have an unparseable timestamp.
    Preserves original file order.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[_jsonl_helpers] read failed for {path}: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entry_date = _parse_ts_to_et_date(entry.get("ts"))
        if entry_date != today_et:
            continue
        out.append(entry)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_jsonl_helpers.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/_jsonl_helpers.py tests/live/test_jsonl_helpers.py
git commit -m "feat(live): _jsonl_helpers.read_today_lines for digest data sources

Read a jsonl file, filter entries whose ts field corresponds to the
given date in America/New_York. Skips corrupt lines and entries with
missing/unparseable ts.

Slice 7a — T2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `daily_summary.render()` — anomaly section

**Files:**
- Create: `src/tradelab/live/daily_summary.py` (skeleton + render anomaly section only)
- Test: `tests/live/test_daily_summary_render.py` (NEW)

**Why now:** Depends on T2 (_jsonl_helpers). Building render() incrementally — anomaly section first because it has the most variation.

- [ ] **Step 1: Write failing tests for `_render_anomaly_section`**

Create `tests/live/test_daily_summary_render.py`:

```python
"""Tests for daily_summary.render() pure-function and its sub-renderers."""
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.live import daily_summary


def _make_panic_entry(ts: str, level: str, **extra) -> dict:
    return {"ts": ts, "level": level, **extra}


def _make_notify_entry(ts: str, severity: str, title: str, **extra) -> dict:
    return {"ts": ts, "severity": severity, "title": title, **extra}


def _make_alert_entry(ts: str, status: str, card_id: str, **extra) -> dict:
    return {"ts": ts, "status": status, "card_id": card_id, **extra}


def test_render_anomaly_section_all_clear(monkeypatch):
    """No anomalies today → returns the ✓ all-clear header and counts (0,0,0,0)."""
    monkeypatch.setattr(daily_summary, "_today_panics", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_order_failures", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_receiver_downtimes", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_ngrok_changes", lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "✓ No anomalies today" in section
    assert counts == {"panic": 0, "block": 0, "fail": 0, "silent": 0, "downtime": 0, "ngrok": 0}


def test_render_anomaly_section_with_panic(monkeypatch):
    """One panic event → renders PANIC L1 badge with timestamp."""
    monkeypatch.setattr(daily_summary, "_today_panics", lambda d: [
        _make_panic_entry("2026-04-27T18:22:00+00:00", "L1", cards_disabled=8),
    ])
    for fn in ("_today_silent_transitions", "_today_guardrail_blocks", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "PANIC L1" in section
    assert "14:22 ET" in section  # 18:22 UTC = 14:22 ET on 04-27
    assert "8 cards disabled" in section
    assert counts["panic"] == 1


def test_render_anomaly_section_with_blocks(monkeypatch):
    """Three guardrail blocks across two cards → renders count + per-card breakdown."""
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [
        _make_alert_entry("2026-04-27T13:30:00+00:00", "guardrail_blocked", "card-a", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T13:35:00+00:00", "guardrail_blocked", "card-a", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T14:00:00+00:00", "guardrail_blocked", "card-b", reason="symbol_collision"),
    ])
    for fn in ("_today_panics", "_today_silent_transitions", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "3 guardrail blocks" in section
    assert "card-a" in section
    assert "card-b" in section
    assert "cooldown_active" in section
    assert counts["block"] == 3


def test_render_anomaly_section_with_silent_transition(monkeypatch):
    """One silent-card transition → renders SILENT badge + card_id."""
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [
        _make_notify_entry("2026-04-27T15:00:00+00:00", "WARNING", "Card silent", card_id="card-c"),
    ])
    for fn in ("_today_panics", "_today_guardrail_blocks", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "SILENT" in section
    assert "card-c" in section
    assert counts["silent"] == 1


def test_render_anomaly_section_section_error_degrades(monkeypatch):
    """If one section's data source raises, that section gets [error: <type>] but rest continues."""
    monkeypatch.setattr(daily_summary, "_today_panics",
                         lambda d: (_ for _ in ()).throw(RuntimeError("simulated")))
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_order_failures", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_receiver_downtimes", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_ngrok_changes", lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "[error: RuntimeError]" in section
    # Other sections still rendered (no anomalies in them)
    assert counts["block"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py -v`
Expected: ImportError (`tradelab.live.daily_summary` does not exist yet).

- [ ] **Step 3: Implement skeleton + `_render_anomaly_section`**

Create `src/tradelab/live/daily_summary.py`:

```python
"""Daily email digest — render + tick + start/stop daemon thread.

Runs in the dashboard launcher process. Mirrors silence_checker shape.
Renders an end-of-day HTML email summarizing today's anomalies and
current system snapshot, sends via notify_channels.email.send() (NOT
through notify() — see spec §3.3 for why), with idempotent state in
digest_state.json to prevent same-day re-fires.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    import pytz
    _ET = pytz.timezone("America/New_York")

from tradelab.live import _jsonl_helpers


_LIVE_DIR = Path(__file__).resolve().parents[3] / "live"
ALERTS_PATH = _LIVE_DIR / "alerts.jsonl"
NOTIFY_PATH = _LIVE_DIR / "notify_events.jsonl"
PANIC_PATH = _LIVE_DIR / "panic_events.jsonl"
STATE_PATH = _LIVE_DIR / "digest_state.json"


# ────────────────────────────────────────────────────────────────────────────
# Data source readers — small wrappers around _jsonl_helpers + filtering
# ────────────────────────────────────────────────────────────────────────────

def _today_panics(today_et: date) -> list[dict]:
    """All entries in panic_events.jsonl with ts on today_et."""
    return _jsonl_helpers.read_today_lines(PANIC_PATH, today_et)


def _today_silent_transitions(today_et: date) -> list[dict]:
    """notify_events entries today with severity=WARNING and title containing 'silent'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "WARNING"
        and "silent" in str(e.get("title", "")).lower()
    ]


def _today_guardrail_blocks(today_et: date) -> list[dict]:
    """alerts.jsonl entries today with status='guardrail_blocked'."""
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return [e for e in entries if e.get("status") == "guardrail_blocked"]


def _today_order_failures(today_et: date) -> list[dict]:
    """alerts.jsonl entries today with status='order_failed'."""
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return [e for e in entries if e.get("status") == "order_failed"]


def _today_receiver_downtimes(today_et: date) -> list[dict]:
    """notify_events entries today with severity=CRITICAL and title containing 'receiver down'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "CRITICAL"
        and "receiver down" in str(e.get("title", "")).lower()
    ]


def _today_ngrok_changes(today_et: date) -> list[dict]:
    """notify_events entries today with severity=CRITICAL and title containing 'ngrok'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "CRITICAL"
        and "ngrok" in str(e.get("title", "")).lower()
    ]


# ────────────────────────────────────────────────────────────────────────────
# Render — anomaly section
# ────────────────────────────────────────────────────────────────────────────

def _ts_to_et_hhmm(ts: str) -> str:
    """Format an ISO 8601 UTC ts as HH:MM ET."""
    try:
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        return dt.astimezone(_ET).strftime("%H:%M") + " ET"
    except Exception:
        return ts


def _safe_call(fn, *args, default):
    """Call fn(*args); on any exception return (default, exc_type_name)."""
    try:
        return fn(*args), None
    except Exception as e:
        return default, type(e).__name__


_BADGE_CRIT = 'style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;color:#fff;background:#d32f2f;margin-right:6px"'
_BADGE_WARN = 'style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;color:#fff;background:#f57c00;margin-right:6px"'
_HEADER_OK = 'style="margin:16px 0 6px 0;font-size:13px;font-weight:600;color:#388e3c;border-bottom:1px solid #f0f0f0;padding-bottom:3px"'
_HEADER = 'style="margin:16px 0 6px 0;font-size:13px;font-weight:600;color:#444;border-bottom:1px solid #f0f0f0;padding-bottom:3px"'
_META = 'style="color:#888;font-size:11px"'


def _render_anomaly_section(today_et: date) -> tuple[str, dict[str, int]]:
    """Render the anomaly section HTML. Returns (html_str, counts_dict).
    Each sub-section wrapped in try; on failure shows [error: <type>] placeholder."""
    counts = {"panic": 0, "block": 0, "fail": 0, "silent": 0, "downtime": 0, "ngrok": 0}
    items: list[str] = []

    panics, err = _safe_call(_today_panics, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] panic events failed to load</li>")
    else:
        counts["panic"] = len(panics)
        for p in panics:
            level = p.get("level", "?")
            cards = p.get("cards_disabled") or p.get("cards_count") or 0
            t = _ts_to_et_hhmm(p.get("ts", ""))
            items.append(
                f'<li><span {_BADGE_CRIT}>PANIC {level}</span> {t} — {cards} cards disabled</li>'
            )

    blocks, err = _safe_call(_today_guardrail_blocks, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] guardrail blocks failed to load</li>")
    else:
        counts["block"] = len(blocks)
        if blocks:
            # Group by card_id, count, list reasons
            by_card: dict[str, list[str]] = {}
            for b in blocks:
                cid = b.get("card_id", "?")
                by_card.setdefault(cid, []).append(b.get("reason", "?"))
            breakdown_parts = []
            for cid, reasons in list(by_card.items())[:5]:
                # Show count + first reason
                breakdown_parts.append(f"<code>{cid}</code> ×{len(reasons)} ({reasons[0]})")
            breakdown = " · ".join(breakdown_parts)
            items.append(
                f'<li><span {_BADGE_CRIT}>BLOCK</span> {len(blocks)} guardrail blocks: {breakdown}</li>'
            )

    fails, err = _safe_call(_today_order_failures, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] order failures failed to load</li>")
    else:
        counts["fail"] = len(fails)
        if fails:
            items.append(
                f'<li><span {_BADGE_CRIT}>FAIL</span> {len(fails)} order failures (Alpaca rejected or network error)</li>'
            )

    silents, err = _safe_call(_today_silent_transitions, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] silent transitions failed to load</li>")
    else:
        counts["silent"] = len(silents)
        if silents:
            ids = ", ".join(f"<code>{e.get('card_id', '?')}</code>" for e in silents[:5])
            items.append(
                f'<li><span {_BADGE_WARN}>SILENT</span> {len(silents)} silent transition(s): {ids}</li>'
            )

    downs, err = _safe_call(_today_receiver_downtimes, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] receiver downtimes failed to load</li>")
    else:
        counts["downtime"] = len(downs)
        if downs:
            items.append(
                f'<li><span {_BADGE_CRIT}>DOWN</span> {len(downs)} receiver downtime event(s)</li>'
            )

    ngrok, err = _safe_call(_today_ngrok_changes, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] ngrok changes failed to load</li>")
    else:
        counts["ngrok"] = len(ngrok)
        if ngrok:
            items.append(
                f'<li><span {_BADGE_CRIT}>NGROK</span> {len(ngrok)} ngrok URL change(s)</li>'
            )

    total = sum(counts.values())
    if total == 0 and not any("[error:" in s for s in items):
        return f'<h4 {_HEADER_OK}>✓ No anomalies today</h4>', counts

    body = (
        f'<h4 {_HEADER}>⚠ Anomalies ({total})</h4>\n'
        '<ul style="margin:4px 0;padding-left:22px">\n'
        + "\n".join(items)
        + "\n</ul>"
    )
    return body, counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/daily_summary.py tests/live/test_daily_summary_render.py
git commit -m "feat(live): daily_summary render — anomaly section + data sources

Skeleton daily_summary module with _today_*() data-source readers
and _render_anomaly_section(). Each anomaly type is rendered in a
try block; on failure the section shows [error: <type>] but the
rest of the email continues.

Slice 7a — T3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `daily_summary._render_snapshot_section` — health snapshot

**Files:**
- Modify: `src/tradelab/live/daily_summary.py` (append `_render_snapshot_section` + new data-source readers)
- Modify: `tests/live/test_daily_summary_render.py` (append snapshot tests)

**Why now:** Depends on T3 daily_summary skeleton existing. Adds the bottom half of the email body.

- [ ] **Step 1: Write failing tests for snapshot section**

Append to `tests/live/test_daily_summary_render.py`:

```python
def test_render_snapshot_section_with_data(monkeypatch):
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 12, "enabled": 8, "disabled": 3, "silent": 1})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 14)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity", lambda d: {
        "CRITICAL": 4, "WARNING": 2, "INFO": 11, "DEBUG": 0,
    })
    monkeypatch.setattr(daily_summary, "_open_positions",
                         lambda: [{"symbol": "AMZN", "qty": "12", "side": "long"}])
    monkeypatch.setattr(daily_summary, "_open_orders",
                         lambda: [{"symbol": "GOOG", "qty": "10", "side": "buy", "status": "new"}])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "uptime_seconds": 30120, "ngrok_url": "abc.ngrok-free.app"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))

    assert "12 total" in section and "8 enabled" in section
    assert "14 order submissions" in section
    assert "4 CRITICAL" in section
    assert "AMZN" in section and "GOOG" in section
    assert "abc.ngrok-free.app" in section
    assert "8h" in section.lower()  # uptime humanized


def test_render_snapshot_section_empty_alpaca(monkeypatch):
    """When Alpaca returns empty lists, show empty-state lines, not tables."""
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 0, "enabled": 0, "disabled": 0, "silent": 0})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions", lambda: [])
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "uptime_seconds": 0, "ngrok_url": "—"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))
    assert "Open positions (0)" in section
    assert "Open orders (0)" in section
    # No <table> rows when empty
    assert "<table" not in section


def test_render_snapshot_section_alpaca_error_degrades(monkeypatch):
    """If Alpaca raises, the positions section shows [error: ...] but rest renders."""
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 1, "enabled": 1, "disabled": 0, "silent": 0})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions",
                         lambda: (_ for _ in ()).throw(RuntimeError("alpaca down")))
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "uptime_seconds": 100, "ngrok_url": "x"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))
    assert "[error: RuntimeError]" in section
    # The rest still rendered
    assert "1 total" in section
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py::test_render_snapshot_section_with_data -v`
Expected: AttributeError (`module has no attribute '_render_snapshot_section'`).

- [ ] **Step 3: Implement snapshot data sources + renderer**

Append to `src/tradelab/live/daily_summary.py`:

```python
# ────────────────────────────────────────────────────────────────────────────
# Data sources for snapshot section
# ────────────────────────────────────────────────────────────────────────────

def _card_counts() -> dict:
    """Return {total, enabled, disabled, silent} from cards.json + silence_checker."""
    from tradelab.live.cards import CardRegistry
    from tradelab.live import silence_checker

    cards = CardRegistry().list_all()
    total = len(cards)
    enabled = sum(1 for c in cards if c.get("status") == "enabled")
    disabled = sum(1 for c in cards if c.get("status") == "disabled")
    try:
        silent = len(silence_checker.silent_set())
    except Exception:
        silent = 0
    return {"total": total, "enabled": enabled, "disabled": disabled, "silent": silent}


def _today_order_submission_count(today_et: date) -> int:
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return sum(1 for e in entries if e.get("status") == "order_submitted")


def _today_notify_counts_by_severity(today_et: date) -> dict[str, int]:
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
    for e in _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et):
        sev = str(e.get("severity", "")).upper()
        if sev in counts:
            counts[sev] += 1
    return counts


def _open_positions() -> list[dict]:
    from tradelab.live import alpaca_client
    return alpaca_client.list_positions()


def _open_orders() -> list[dict]:
    from tradelab.live import alpaca_client
    return alpaca_client.list_open_orders()


def _receiver_status() -> dict:
    """Best-effort: probe the receiver's /health endpoint via the receiver_status helper.
    Returns {up, uptime_seconds, ngrok_url}. On failure: up=False."""
    try:
        # Reuse the existing /tradelab/receiver/status logic if present.
        # Defer import to avoid circular ref at module-load time.
        import urllib.request
        import json as _json
        with urllib.request.urlopen("http://127.0.0.1:8877/tradelab/receiver/status", timeout=2) as r:
            data = _json.loads(r.read().decode("utf-8")).get("data", {})
        return {
            "up": bool(data.get("receiver_up", False)),
            "uptime_seconds": int(data.get("receiver_uptime_seconds", 0)),
            "ngrok_url": data.get("ngrok_url", "—") or "—",
        }
    except Exception:
        return {"up": False, "uptime_seconds": 0, "ngrok_url": "—"}


def _humanize_seconds(s: int) -> str:
    """120 → '2m', 7320 → '2h 2m', 0 → '0m'."""
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# ────────────────────────────────────────────────────────────────────────────
# Render — snapshot section
# ────────────────────────────────────────────────────────────────────────────

def _render_snapshot_section(today_et: date) -> str:
    parts: list[str] = [f'<h4 {_HEADER}>📊 Health snapshot (now)</h4>']

    cc, err = _safe_call(_card_counts, default={"total": 0, "enabled": 0, "disabled": 0, "silent": 0})
    if err:
        parts.append(f'<p>[error: {err}] cards counts</p>')
    else:
        parts.append(
            f'<p><strong>Cards:</strong> {cc["total"]} total · '
            f'<span style="color:#388e3c">{cc["enabled"]} enabled</span> · '
            f'{cc["disabled"]} disabled · '
            f'<span style="color:#f57c00">{cc["silent"]} silent</span></p>'
        )

    osc, err = _safe_call(_today_order_submission_count, today_et, default=0)
    nsc, err2 = _safe_call(_today_notify_counts_by_severity, today_et, default={"CRITICAL":0,"WARNING":0,"INFO":0,"DEBUG":0})
    if err or err2:
        parts.append(f'<p>[error: {err or err2}] today counts</p>')
    else:
        parts.append(
            f'<p><strong>Today:</strong> {osc} order submissions · '
            f'{nsc["CRITICAL"]} CRITICAL / {nsc["WARNING"]} WARNING / {nsc["INFO"]} INFO notifications</p>'
        )

    rs, err = _safe_call(_receiver_status, default={"up": False, "uptime_seconds": 0, "ngrok_url": "—"})
    if err:
        parts.append(f'<p>[error: {err}] receiver status</p>')
    else:
        up_str = f'up, {_humanize_seconds(rs["uptime_seconds"])}' if rs["up"] else "down"
        parts.append(
            f'<p><strong>Receiver:</strong> {up_str} · '
            f'<strong>ngrok:</strong> <code>{rs["ngrok_url"]}</code></p>'
        )

    positions, err = _safe_call(_open_positions, default=[])
    if err:
        parts.append(f'<p>[error: {err}] open positions</p>')
    else:
        parts.append(f'<p style="margin-top:10px"><strong>Open positions ({len(positions)})</strong></p>')
        if positions:
            rows = "".join(
                f'<tr><td style="border:1px solid #e0e0e0;padding:4px 8px">{p["symbol"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{p["qty"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{p["side"]}</td></tr>'
                for p in positions
            )
            parts.append(
                '<table style="border-collapse:collapse;font-size:12px">\n'
                '<tr style="background:#f7f7f7">'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Symbol</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Qty</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Side</th></tr>'
                f'{rows}\n</table>'
            )

    orders, err = _safe_call(_open_orders, default=[])
    if err:
        parts.append(f'<p>[error: {err}] open orders</p>')
    else:
        parts.append(f'<p style="margin-top:10px"><strong>Open orders ({len(orders)})</strong></p>')
        if orders:
            rows = "".join(
                f'<tr><td style="border:1px solid #e0e0e0;padding:4px 8px">{o["symbol"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["qty"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["side"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["status"]}</td></tr>'
                for o in orders
            )
            parts.append(
                '<table style="border-collapse:collapse;font-size:12px">\n'
                '<tr style="background:#f7f7f7">'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Symbol</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Qty</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Side</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Status</th></tr>'
                f'{rows}\n</table>'
            )

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py -v`
Expected: 8 passed (5 from T3 + 3 from this task).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/daily_summary.py tests/live/test_daily_summary_render.py
git commit -m "feat(live): daily_summary snapshot section + data sources

_render_snapshot_section() renders cards counts, today's submission/notify
counts, receiver+ngrok status, open positions table, open orders table.
Each subsection wrapped in try; Alpaca failures degrade gracefully.

Slice 7a — T4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `daily_summary.render()` — assemble subject + full body + plaintext fallback

**Files:**
- Modify: `src/tradelab/live/daily_summary.py` (add `render()` + `_render_subject()` + `_render_plaintext()`)
- Modify: `tests/live/test_daily_summary_render.py` (append assembly tests)

**Why now:** Combines T3 + T4 into the public `render(now)` API used by tick() and the preview endpoint.

- [ ] **Step 1: Write failing tests for `render()`**

Append to `tests/live/test_daily_summary_render.py`:

```python
def test_render_returns_subject_and_html(monkeypatch):
    """render(now) returns (subject, html_body) with both populated."""
    # All-clear case
    for fn in ("_today_panics", "_today_silent_transitions", "_today_guardrail_blocks",
               "_today_order_failures", "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 1, "enabled": 1, "disabled": 0, "silent": 0})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions", lambda: [])
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "uptime_seconds": 100, "ngrok_url": "x"})

    now = datetime(2026, 4, 27, 16, 0, 0)
    subject, html = daily_summary.render(now)

    assert subject == "tradelab daily — 2026-04-27 — all clear"
    assert "tradelab daily — 2026-04-27 — all clear" in html
    assert "✓ No anomalies today" in html
    assert "📊 Health snapshot" in html
    assert "tradelab · end of summary" in html


def test_render_subject_with_anomalies(monkeypatch):
    """Subject shows top-2 categories ordered PANIC > BLOCK > FAIL > DOWNTIME > NGROK > SILENT."""
    monkeypatch.setattr(daily_summary, "_today_panics", lambda d: [
        _make_panic_entry("2026-04-27T13:00:00+00:00", "L1"),
    ])
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [
        _make_alert_entry("2026-04-27T14:00:00+00:00", "guardrail_blocked", "c1", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T14:01:00+00:00", "guardrail_blocked", "c1", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T14:02:00+00:00", "guardrail_blocked", "c2", reason="symbol_collision"),
    ])
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [
        _make_notify_entry("2026-04-27T15:00:00+00:00", "WARNING", "Card silent", card_id="c3"),
    ])
    for fn in ("_today_order_failures", "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])
    # Fill in snapshot stubs
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 1, "enabled": 1, "disabled": 0, "silent": 1})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 1, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions", lambda: [])
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "uptime_seconds": 100, "ngrok_url": "x"})

    subject, _ = daily_summary.render(datetime(2026, 4, 27, 16, 0, 0))
    # PANIC (1) > BLOCK (3) by precedence even though count is lower; spec §15 q6 ordering
    assert subject == "tradelab daily — 2026-04-27 — 1 panic, 3 blocks"


def test_render_plaintext_fallback_present():
    """render_plaintext(html) returns a stripped-tag version with section headers preserved."""
    html = '<h4>⚠ Anomalies (1)</h4><p>Stuff</p><table><tr><td>X</td></tr></table>'
    plain = daily_summary._render_plaintext(html)
    assert "Anomalies" in plain
    assert "Stuff" in plain
    assert "X" in plain
    # No HTML tags in output
    assert "<" not in plain and ">" not in plain
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py -v`
Expected: 3 new tests fail with AttributeError.

- [ ] **Step 3: Implement `render()` + `_render_subject` + `_render_plaintext`**

Append to `src/tradelab/live/daily_summary.py`:

```python
import re

_SUBJECT_PRECEDENCE = ["panic", "block", "fail", "downtime", "ngrok", "silent"]
_SUBJECT_LABELS = {
    "panic": "panic",
    "block": "blocks",
    "fail": "failures",
    "downtime": "downtimes",
    "ngrok": "ngrok changes",
    "silent": "silent",
}


def _render_subject(today_str: str, counts: dict[str, int]) -> str:
    """tradelab daily — YYYY-MM-DD — <tail>.
    Tail = 'all clear' if total=0, else top-2 categories by precedence (PANIC>BLOCK>FAIL>DOWNTIME>NGROK>SILENT)."""
    if sum(counts.values()) == 0:
        return f"tradelab daily — {today_str} — all clear"
    nonzero = [(k, counts[k]) for k in _SUBJECT_PRECEDENCE if counts.get(k, 0) > 0]
    top = nonzero[:2]
    parts = []
    for k, n in top:
        # Singular handling for panic only ("1 panic" not "1 panics")
        label = "panic" if (k == "panic" and n == 1) else _SUBJECT_LABELS[k]
        parts.append(f"{n} {label}")
    return f"tradelab daily — {today_str} — {', '.join(parts)}"


def _render_plaintext(html: str) -> str:
    """Strip HTML tags and decode entities for the plaintext alternative MIME part.
    Preserves section text and table cell contents; collapses whitespace."""
    # Replace block-level closers with newlines for readability
    s = re.sub(r"</(h[1-6]|p|li|tr|div)>", "\n", html, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</td>", "  ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)  # strip remaining tags
    # Decode common entities
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Collapse runs of blank lines and trailing spaces
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def render(now: datetime) -> tuple[str, str]:
    """Render today's digest. Returns (subject, html_body). Pure — no I/O writes."""
    today_et = now.astimezone(_ET).date()
    today_str = today_et.strftime("%Y-%m-%d")

    anomaly_html, counts = _render_anomaly_section(today_et)
    snapshot_html = _render_snapshot_section(today_et)
    subject = _render_subject(today_str, counts)

    body = (
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:13px;color:#1a1a1a;line-height:1.5">\n'
        f'<div style="font-weight:600;border-bottom:1px solid #eee;padding-bottom:8px;margin-bottom:12px;font-size:14px">{subject}</div>\n'
        f'{anomaly_html}\n'
        f'{snapshot_html}\n'
        f'<p {_META} style="margin-top:14px">tradelab · end of summary</p>\n'
        f'</div>'
    )
    return subject, body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_render.py -v`
Expected: 11 passed (5 from T3 + 3 from T4 + 3 from T5).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/daily_summary.py tests/live/test_daily_summary_render.py
git commit -m "feat(live): daily_summary.render() + subject + plaintext fallback

Public render(now) returns (subject, html_body). Subject precedence:
PANIC > BLOCK > FAIL > DOWNTIME > NGROK > SILENT. _render_plaintext()
produces the alternative MIME part by tag-stripping the HTML.

Slice 7a — T5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `daily_summary.tick()` + state read/write + idempotency

**Files:**
- Modify: `src/tradelab/live/daily_summary.py` (add `tick`, `_read_state`, `_write_state`, `_should_send`)
- Test: `tests/live/test_daily_summary_tick.py` (NEW)
- Test: `tests/live/test_daily_summary_state.py` (NEW)

**Why now:** Depends on T5 (render is the work tick performs). State helpers are bundled here to avoid splitting tick into multiple tasks.

- [ ] **Step 1: Write failing tests for state helpers**

Create `tests/live/test_daily_summary_state.py`:

```python
"""Tests for daily_summary state file (digest_state.json)."""
import json
from pathlib import Path

import pytest

from tradelab.live import daily_summary


def test_read_state_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_summary, "STATE_PATH", tmp_path / "digest_state.json")
    state = daily_summary._read_state()
    assert state == {}


def test_read_state_corrupt_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    p.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    assert daily_summary._read_state() == {}


def test_write_state_atomic(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    daily_summary._write_state({"last_sent_date": "2026-04-27", "attempts_today": 0})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["last_sent_date"] == "2026-04-27"
    assert data["attempts_today"] == 0


def test_write_state_then_read_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    payload = {
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T20:00:14+00:00",
        "attempts_today": 0,
    }
    daily_summary._write_state(payload)
    assert daily_summary._read_state() == payload
```

- [ ] **Step 2: Write failing tests for tick gating**

Create `tests/live/test_daily_summary_tick.py`:

```python
"""Tests for daily_summary.tick() gating + idempotency + retry policy."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tradelab.live import daily_summary


@pytest.fixture
def tick_env(tmp_path, monkeypatch):
    """Setup: empty state file, send succeeds by default, config enabled, today is trading."""
    state_path = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_path)

    # Stub config: enabled, send_time 16:00
    monkeypatch.setattr(daily_summary, "_config_enabled", lambda: True)
    monkeypatch.setattr(daily_summary, "_config_send_time", lambda: "16:00")

    # Stub trading day check
    monkeypatch.setattr(daily_summary, "_is_trading_day", lambda d: True)

    # Stub render to a known value
    monkeypatch.setattr(daily_summary, "render",
                         lambda now: ("test subject", "<html>test</html>"))

    # Stub email send
    send_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_send_email", send_mock)

    # Stub audit appender
    audit_mock = MagicMock()
    monkeypatch.setattr(daily_summary, "_append_audit_line", audit_mock)

    return {"state_path": state_path, "send": send_mock, "audit": audit_mock}


def test_tick_skips_when_not_trading_day(tick_env, monkeypatch):
    monkeypatch.setattr(daily_summary, "_is_trading_day", lambda d: False)
    daily_summary.tick(datetime(2026, 4, 25, 16, 0, 0))  # Sat
    tick_env["send"].assert_not_called()


def test_tick_skips_when_before_send_time(tick_env):
    daily_summary.tick(datetime(2026, 4, 27, 15, 59, 0))  # 1 min before 16:00
    tick_env["send"].assert_not_called()


def test_tick_skips_when_disabled(tick_env, monkeypatch):
    monkeypatch.setattr(daily_summary, "_config_enabled", lambda: False)
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_not_called()


def test_tick_fires_when_all_gates_pass(tick_env):
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_called_once()
    args = tick_env["send"].call_args
    assert args[0][0] == "test subject"
    assert "<html>test</html>" in args[0][1]
    # State file written with today's date
    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["last_sent_date"] == "2026-04-27"
    assert state["last_sent_failed"] is False
    # Audit line appended
    tick_env["audit"].assert_called_once()


def test_tick_idempotent_same_day(tick_env):
    """Two ticks within the same day after success → only one send."""
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    daily_summary.tick(datetime(2026, 4, 27, 16, 5, 0))
    tick_env["send"].assert_called_once()


def test_tick_resets_attempts_today_on_new_day(tick_env):
    """If state has yesterday's date with attempts_today=3, today's tick ignores attempts."""
    import json as _json
    tick_env["state_path"].write_text(_json.dumps({
        "last_sent_date": "2026-04-26",
        "last_sent_failed": True,
        "attempts_today": 3,
    }), encoding="utf-8")

    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    tick_env["send"].assert_called_once()
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["last_sent_date"] == "2026-04-27"
    assert state["attempts_today"] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_state.py tests/live/test_daily_summary_tick.py -v`
Expected: AttributeError on first state test (`_read_state` not defined yet).

- [ ] **Step 4: Implement state helpers + tick() + supporting helpers**

Append to `src/tradelab/live/daily_summary.py`:

```python
import os
import tempfile

# ────────────────────────────────────────────────────────────────────────────
# Config + calendar helpers (small wrappers — easy to monkeypatch in tests)
# ────────────────────────────────────────────────────────────────────────────

def _config_enabled() -> bool:
    from tradelab.live import live_config
    return bool(live_config.get("email_digest.enabled", False))


def _config_send_time() -> str:
    from tradelab.live import live_config
    return str(live_config.get("email_digest.send_time", "16:00"))


def _is_trading_day(d: date) -> bool:
    from tradelab.live import trading_calendar
    return trading_calendar.is_trading_day(d)


def _config_recipient() -> str:
    from tradelab.live import live_config
    return str(live_config.get("notifications.smtp.to_address", ""))


# ────────────────────────────────────────────────────────────────────────────
# State helpers
# ────────────────────────────────────────────────────────────────────────────

def _read_state() -> dict:
    """Read digest_state.json. Returns {} on missing or corrupt file."""
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[daily_summary] state read failed: {e}", file=sys.stderr)
        return {}


def _write_state(state: dict) -> None:
    """Atomic write via tmpfile + os.replace."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".digest_state.", dir=str(STATE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, STATE_PATH)
    except OSError as e:
        print(f"[daily_summary] state write failed: {e}", file=sys.stderr)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ────────────────────────────────────────────────────────────────────────────
# Send + audit
# ────────────────────────────────────────────────────────────────────────────

def _send_email(subject: str, html_body: str, to_address: str) -> None:
    """Direct send via the Slice 4 email channel module. Raises on failure."""
    from tradelab.live.notify_channels import email as email_channel
    plaintext = _render_plaintext(html_body)
    email_channel.send(subject=subject, html_body=html_body, plaintext_body=plaintext, to_address=to_address)


def _append_audit_line(today_str: str) -> None:
    """Append a single INFO line to notify_events.jsonl marking that today's digest was sent.
    Does NOT route through notify() — direct file append to avoid dispatcher loop."""
    line = json.dumps({
        "ts": datetime.now(_ET).isoformat(),
        "severity": "INFO",
        "title": "daily_digest_sent",
        "body": f"Daily digest for {today_str} sent successfully.",
        "event_type": "daily_digest_sent",
    }) + "\n"
    try:
        NOTIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFY_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"[daily_summary] audit append failed: {e}", file=sys.stderr)


# ────────────────────────────────────────────────────────────────────────────
# Tick — gate, render, send, persist state
# ────────────────────────────────────────────────────────────────────────────

MAX_ATTEMPTS_PER_DAY = 5


def tick(now: datetime) -> None:
    """One tick of the digest scheduler. Idempotent + RTH+send_time-gated."""
    # 1. Trading-day gate
    today_et = now.astimezone(_ET).date()
    if not _is_trading_day(today_et):
        return

    # 2. Send-time gate (current ET time >= configured send_time HH:MM)
    send_time_str = _config_send_time()
    try:
        hh, mm = (int(x) for x in send_time_str.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 16, 0
    now_et = now.astimezone(_ET)
    if (now_et.hour, now_et.minute) < (hh, mm):
        return

    # 3. Config-enabled gate
    if not _config_enabled():
        return

    today_str = today_et.strftime("%Y-%m-%d")
    state = _read_state()

    # 4. Idempotency gate — already sent (or capped) today?
    if state.get("last_sent_date") == today_str:
        return

    # New day — reset attempts_today if state is stale
    attempts = state.get("attempts_today", 0)
    if state.get("last_sent_date") != today_str and state.get("last_sent_date") is not None:
        attempts = 0

    # 5. Render + send
    subject, html_body = render(now)
    to_address = _config_recipient()
    if not to_address:
        # Can't send without a recipient — treat as fatal-for-the-day to avoid spinning
        _write_state({
            "last_sent_date": today_str,
            "last_sent_failed": True,
            "last_attempted_at": now.astimezone(_ET).isoformat(),
            "attempts_today": attempts,
        })
        return

    try:
        _send_email(subject, html_body, to_address)
    except Exception as e:
        attempts += 1
        capped = attempts >= MAX_ATTEMPTS_PER_DAY
        _write_state({
            "last_sent_date": today_str if capped else state.get("last_sent_date"),
            "last_sent_failed": True,
            "last_attempted_at": now.astimezone(_ET).isoformat(),
            "attempts_today": attempts,
        })
        # Notify only on failure (one line per attempt)
        try:
            from tradelab.live.notify import notify, Severity
            suffix = " — no further retries today" if capped else ""
            notify(Severity.WARNING, "daily digest send failed",
                   f"attempt={attempts}: {type(e).__name__}: {e}{suffix}")
        except Exception:
            pass  # never let notify-failure crash tick
        return

    # Success path
    _write_state({
        "last_sent_date": today_str,
        "last_sent_failed": False,
        "last_attempted_at": now.astimezone(_ET).isoformat(),
        "attempts_today": 0,
    })
    _append_audit_line(today_str)

    # F2 — rotate logs once per day after a successful send
    try:
        from tradelab.live import jsonl_rotation
        jsonl_rotation.rotate_all()
    except Exception as e:
        print(f"[daily_summary] jsonl_rotation failed: {e}", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_state.py tests/live/test_daily_summary_tick.py -v`
Expected: 4 state tests + 6 tick tests = 10 passed.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/daily_summary.py tests/live/test_daily_summary_state.py tests/live/test_daily_summary_tick.py
git commit -m "feat(live): daily_summary.tick + state file + idempotency

Tick gates: trading-day, send-time, config-enabled, idempotent (state
file). On success: send via notify_channels.email, write state, append
audit line, call jsonl_rotation.rotate_all(). On failure: increment
attempts_today, fire WARNING notify, retry next minute.

Slice 7a — T6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Retry-cap behavior — explicit test

**Files:**
- Modify: `tests/live/test_daily_summary_tick.py` (add retry-cap tests)

**Why separated:** T6 implementation already includes retry-cap logic; this task verifies it via explicit tests rather than bundling more cases into T6's already-large test file.

- [ ] **Step 1: Add failing tests for retry policy**

Append to `tests/live/test_daily_summary_tick.py`:

```python
def test_tick_increments_attempts_on_send_failure(tick_env, monkeypatch):
    """First failed send → attempts_today=1, last_sent_failed=True, no last_sent_date update."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 1
    assert state["last_sent_failed"] is True
    # last_sent_date NOT set to today (so next tick will retry)
    assert state.get("last_sent_date") in (None,)


def test_tick_retries_after_failure(tick_env, monkeypatch):
    """Second tick after failure → another send attempt, attempts_today=2."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    daily_summary.tick(datetime(2026, 4, 27, 16, 0, 0))
    daily_summary.tick(datetime(2026, 4, 27, 16, 1, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 2
    assert tick_env["send"].call_count == 2


def test_tick_retry_cap_at_5_attempts(tick_env, monkeypatch):
    """5th failed attempt → state.last_sent_date set to today; 6th tick is skipped."""
    tick_env["send"].side_effect = RuntimeError("smtp down")
    for i in range(5):
        daily_summary.tick(datetime(2026, 4, 27, 16, i, 0))

    import json as _json
    state = _json.loads(tick_env["state_path"].read_text(encoding="utf-8"))
    assert state["attempts_today"] == 5
    assert state["last_sent_date"] == "2026-04-27"
    assert state["last_sent_failed"] is True

    # 6th tick should skip (gate matches)
    daily_summary.tick(datetime(2026, 4, 27, 16, 5, 0))
    assert tick_env["send"].call_count == 5  # no new attempt
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_tick.py -v`
Expected: 9 passed (6 from T6 + 3 from this task).

- [ ] **Step 3: Commit**

```bash
cd C:/TradingScripts/tradelab && git add tests/live/test_daily_summary_tick.py
git commit -m "test(live): explicit retry-cap coverage for daily_summary.tick

Three additional tests verifying: attempt-counter increments on send
failure, retries continue across ticks, hard cap at 5 attempts/day
sets last_sent_date so subsequent ticks skip.

Slice 7a — T7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `daily_summary.start()` / `stop()` — daemon thread lifecycle

**Files:**
- Modify: `src/tradelab/live/daily_summary.py` (append start/stop)
- Modify: `tests/live/test_daily_summary_state.py` (rename to `test_daily_summary_lifecycle.py` if preferred, or append) — for this plan, append to state file to keep file count bounded.

**Why now:** All `tick()` work is done; just wire up the daemon thread that calls it. Mirrors `silence_checker.start()/stop()` exactly.

- [ ] **Step 1: Add failing lifecycle tests**

Append to `tests/live/test_daily_summary_state.py`:

```python
import threading
import time

from unittest.mock import patch


def test_start_creates_daemon_thread():
    daily_summary.stop()  # ensure clean slate
    daily_summary.start()
    assert daily_summary._thread is not None
    assert daily_summary._thread.is_alive()
    assert daily_summary._thread.daemon is True
    daily_summary.stop()


def test_start_is_idempotent():
    daily_summary.stop()
    daily_summary.start()
    t1 = daily_summary._thread
    daily_summary.start()  # second call
    t2 = daily_summary._thread
    assert t1 is t2  # same thread, no second one spawned
    daily_summary.stop()


def test_stop_joins_thread():
    daily_summary.start()
    daily_summary.stop()
    assert daily_summary._thread is None


def test_stop_when_not_running_is_safe():
    # Should be no-op, no exception
    daily_summary.stop()
    daily_summary.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_state.py -v`
Expected: AttributeError or NameError on `_thread`.

- [ ] **Step 3: Implement start/stop lifecycle**

Append to `src/tradelab/live/daily_summary.py`:

```python
import threading

# ────────────────────────────────────────────────────────────────────────────
# Daemon thread lifecycle — mirrors silence_checker
# ────────────────────────────────────────────────────────────────────────────

TICK_SECONDS = 60

_thread: Optional[threading.Thread] = None
_stop_evt = threading.Event()
_start_lock = threading.Lock()


def _run_loop() -> None:
    """Thread body: tick, sleep TICK_SECONDS (interruptible), repeat."""
    while not _stop_evt.is_set():
        try:
            tick(datetime.now(_ET))
        except Exception as e:
            print(f"[daily_summary] tick raised: {type(e).__name__}: {e}", file=sys.stderr)
        if _stop_evt.wait(TICK_SECONDS):
            break


def start() -> None:
    """Boot the periodic thread. Idempotent — repeated calls are no-ops."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_evt.clear()
        _thread = threading.Thread(target=_run_loop, daemon=True, name="daily_summary")
        _thread.start()


def stop() -> None:
    """Signal stop and join the thread. Safe when not running.
    Acquires _start_lock to mirror start() and prevent torn reads of _thread."""
    global _thread
    _stop_evt.set()
    with _start_lock:
        if _thread is not None:
            _thread.join(timeout=2.0)
            _thread = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_daily_summary_state.py -v`
Expected: 8 passed (4 state + 4 lifecycle).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/daily_summary.py tests/live/test_daily_summary_state.py
git commit -m "feat(live): daily_summary.start/stop daemon thread lifecycle

Mirrors silence_checker shape: idempotent start, lock-guarded stop,
interruptible sleep, daemon thread. TICK_SECONDS=60. Body runs tick()
in a try/except so a bad tick doesn't crash the loop.

Slice 7a — T8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `GET /tradelab/live/digest/preview` endpoint

**Files:**
- Modify: `src/tradelab/web/handlers.py` (add `handle_digest_preview_get` + register route)
- Test: `tests/web/test_digest_handlers.py` (NEW)

**Why now:** Depends on T5 (render is what /preview calls). Independent of T10 — can run parallel with T10.

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_digest_handlers.py`:

```python
"""Tests for the two new GET endpoints registered by Slice 7a."""
import json
from unittest.mock import patch

import pytest

from tradelab.web import handlers


def test_digest_preview_returns_html_200():
    with patch("tradelab.live.daily_summary.render",
               return_value=("test subject", "<div>preview body</div>")):
        body, status = handlers.handle_digest_preview_get()
    assert status == 200
    assert "<div>preview body</div>" in body


def test_digest_preview_render_error_returns_500():
    with patch("tradelab.live.daily_summary.render",
               side_effect=RuntimeError("simulated render failure")):
        body, status = handlers.handle_digest_preview_get()
    assert status == 500
    payload = json.loads(body)
    assert payload["error"] is not None
    assert "RuntimeError" in payload["error"]


def test_get_dispatcher_routes_preview():
    with patch("tradelab.live.daily_summary.render",
               return_value=("s", "<x>html</x>")):
        body, status = handlers.handle_get("/tradelab/live/digest/preview", {})
    assert status == 200
    assert "<x>html</x>" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_handlers.py::test_digest_preview_returns_html_200 -v`
Expected: AttributeError (`module 'handlers' has no attribute 'handle_digest_preview_get'`).

- [ ] **Step 3: Implement handler + register route**

Append to `src/tradelab/web/handlers.py` (after the existing `handle_panic_last_event_get`):

```python
def handle_digest_preview_get() -> Tuple[str, int]:
    """GET /tradelab/live/digest/preview — render today's digest as HTML.

    Pure render. Does not send, does not write state, does not log.
    Returns 200 with text/html on success, 500 with JSON error envelope on failure.
    """
    from tradelab.live import daily_summary
    from datetime import datetime
    try:
        _, html_body = daily_summary.render(datetime.now(daily_summary._ET))
        return html_body, 200
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}"), 500
```

Modify `handle_get()` dispatcher to add the route — insert before the `return _err("not found"), 404` line:

```python
    if path == "/tradelab/live/digest/preview":
        return handle_digest_preview_get()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_handlers.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_digest_handlers.py
git commit -m "feat(web): GET /tradelab/live/digest/preview endpoint

Renders today's digest HTML body via daily_summary.render(). Pure —
no state writes, no email send. 200 text/html on success, 500 with
error envelope on render failure.

Slice 7a — T9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `GET /tradelab/live/digest/state` endpoint

**Files:**
- Modify: `src/tradelab/web/handlers.py` (add `handle_digest_state_get` + register route)
- Modify: `tests/web/test_digest_handlers.py` (append state-endpoint tests)

**Why now:** Independent of T9, can be parallelized.

- [ ] **Step 1: Write failing tests**

Append to `tests/web/test_digest_handlers.py`:

```python
def test_digest_state_returns_envelope_with_state(tmp_path, monkeypatch):
    state_path = tmp_path / "digest_state.json"
    state_path.write_text(json.dumps({
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T20:00:14+00:00",
        "attempts_today": 0,
    }), encoding="utf-8")
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_path)

    body, status = handlers.handle_digest_state_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"]["last_sent_date"] == "2026-04-27"


def test_digest_state_missing_file_returns_null_data(tmp_path, monkeypatch):
    state_path = tmp_path / "absent.json"
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_path)

    body, status = handlers.handle_digest_state_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"] is None


def test_get_dispatcher_routes_state(tmp_path, monkeypatch):
    state_path = tmp_path / "digest_state.json"
    state_path.write_text('{"last_sent_date":"2026-04-27"}', encoding="utf-8")
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_path)

    body, status = handlers.handle_get("/tradelab/live/digest/state", {})
    assert status == 200
    payload = json.loads(body)
    assert payload["data"]["last_sent_date"] == "2026-04-27"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_handlers.py -v`
Expected: 3 new tests fail with AttributeError.

- [ ] **Step 3: Implement handler + register route**

Append to `src/tradelab/web/handlers.py`:

```python
def handle_digest_state_get() -> Tuple[str, int]:
    """GET /tradelab/live/digest/state — return digest_state.json contents.

    Returns {"error": null, "data": null} if state file is missing.
    """
    from tradelab.live import daily_summary
    state = daily_summary._read_state()
    if not state:
        return _ok(None), 200
    return _ok(state), 200
```

Modify `handle_get()` dispatcher to add the route — insert before `return _err("not found"), 404`:

```python
    if path == "/tradelab/live/digest/state":
        return handle_digest_state_get()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_handlers.py -v`
Expected: 6 passed (3 from T9 + 3 from T10).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_digest_handlers.py
git commit -m "feat(web): GET /tradelab/live/digest/state endpoint

Returns digest_state.json contents in the standard envelope. Missing
file → {error:null, data:null} (not an error condition).

Slice 7a — T10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: FE — wire up Email Digest enabled toggle + send_time input

**Files:**
- Modify: `command_center.html` (parent repo at `C:\TradingScripts\command_center.html`)
- Test: `tests/web/test_digest_fe_contract.py` (NEW)

**Why now:** Depends on the live_config.json `email_digest` block existing (already there from Slice 4) and the PATCH endpoint working (Slice 4). T10 must be done so we know the state endpoint works for the next task.

**Note:** The settings panel's Email Digest section already has `enabled` and `send_time` fields scaffolded by Slice 4 (likely as static markup or unbound input). This task wires them to PATCH the config.

- [ ] **Step 1: Inspect current Email Digest section markup**

Run: `cd C:/TradingScripts && grep -n "email_digest\|Email Digest\|email-digest\|emailDigest" command_center.html | head -20`
Expected: existing markup references from Slice 4. Note line numbers for the next step.

If no existing markup is found, create the section from scratch (see Step 3).

- [ ] **Step 2: Write failing FE contract tests**

Create `tests/web/test_digest_fe_contract.py`:

```python
"""FE contract tests for Slice 7a Email Digest section in command_center.html.

The dashboard launcher serves command_center.html from the parent dir,
not from the tradelab repo. We verify the served HTML contains the
expected JS function names and DOM markers.
"""
from pathlib import Path

import pytest

# command_center.html lives in the parent repo (C:\TradingScripts\command_center.html).
# Adjust path if running from a worktree.
HTML_PATH = Path(__file__).resolve().parents[2].parent / "command_center.html"


@pytest.fixture
def html_text() -> str:
    if not HTML_PATH.exists():
        pytest.skip(f"command_center.html not found at {HTML_PATH}")
    return HTML_PATH.read_text(encoding="utf-8")


def test_html_contains_email_digest_enabled_toggle(html_text):
    """An input with id email-digest-enabled (checkbox) is present."""
    assert 'id="email-digest-enabled"' in html_text
    assert 'type="checkbox"' in html_text  # somewhere in vicinity — broad pin


def test_html_contains_email_digest_send_time_input(html_text):
    assert 'id="email-digest-send-time"' in html_text


def test_html_contains_patchEmailDigestEnabled_js(html_text):
    """JS function patchEmailDigestEnabled() is defined."""
    assert "patchEmailDigestEnabled" in html_text


def test_html_contains_patchEmailDigestSendTime_js(html_text):
    """JS function patchEmailDigestSendTime() is defined."""
    assert "patchEmailDigestSendTime" in html_text


def test_html_email_digest_section_has_recipient_display(html_text):
    """The 'Recipient: ...' line is present (read-only display)."""
    assert "Recipient:" in html_text or "recipient" in html_text.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_fe_contract.py -v`
Expected: 5 tests fail (markup/JS not yet present).

- [ ] **Step 4: Add or update Email Digest section in `command_center.html`**

Locate the settings panel's Notifications/Email Digest area in `C:\TradingScripts\command_center.html`. The existing scaffolded section (from Slice 4) likely looks similar to:

```html
<!-- BEFORE (Slice 4 scaffold, may or may not exist verbatim) -->
<div class="settings-row">
  <h4>Email Digest</h4>
  <p class="hint">Daily summary email at end-of-day.</p>
</div>
```

Replace (or insert if absent) with:

```html
<div class="settings-row" id="email-digest-section">
  <h4>📧 Email Digest</h4>
  <p class="hint">Daily summary email at end of trading day. Sent via the SMTP channel above.</p>

  <label>
    <input type="checkbox" id="email-digest-enabled" onchange="patchEmailDigestEnabled(this.checked)">
    Enabled
  </label>

  <label style="margin-top:8px;display:block">
    Send time:
    <input type="text" id="email-digest-send-time" placeholder="16:00"
           pattern="^\d{2}:\d{2}$" style="width:60px"
           onblur="patchEmailDigestSendTime(this.value)">
    ET
  </label>

  <p style="margin-top:8px">
    Recipient: <code id="email-digest-recipient">—</code>
    <span class="hint">(read-only — change in SMTP section above)</span>
  </p>

  <div style="margin-top:12px">
    <button type="button" onclick="loadDigestPreview()">🔄 Refresh preview</button>
    <iframe id="email-digest-preview" srcdoc="<p style='font-family:sans-serif;color:#888;padding:12px'>Click [Refresh preview] to load.</p>"
            style="width:100%;height:480px;border:1px solid #ddd;margin-top:8px;background:#fff"></iframe>
  </div>

  <p id="email-digest-last-sent" class="hint" style="margin-top:8px">Last sent: —</p>
</div>
```

Then in the existing settings-panel JS IIFE (or near the existing `loadLiveConfig` function), add the wire-up functions:

```javascript
async function patchEmailDigestEnabled(enabled) {
  try {
    const res = await fetch('/tradelab/live/config', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email_digest: {enabled: !!enabled}}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (e) {
    console.error('patchEmailDigestEnabled failed', e);
    alert('Failed to update digest enabled — see console.');
  }
}

async function patchEmailDigestSendTime(value) {
  if (!/^\d{2}:\d{2}$/.test(value)) {
    alert('Send time must be HH:MM (e.g. 16:00)');
    return;
  }
  try {
    const res = await fetch('/tradelab/live/config', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email_digest: {send_time: value}}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (e) {
    console.error('patchEmailDigestSendTime failed', e);
    alert('Failed to update send time — see console.');
  }
}
```

Also extend the existing `loadLiveConfig()` (or whichever function populates settings from `GET /tradelab/live/config`) so that on load it sets:
- `document.getElementById('email-digest-enabled').checked = config.email_digest?.enabled ?? false;`
- `document.getElementById('email-digest-send-time').value = config.email_digest?.send_time ?? '16:00';`
- `document.getElementById('email-digest-recipient').textContent = config.notifications?.smtp?.to_address ?? '—';`

Find the existing `loadLiveConfig` (or equivalent) in `command_center.html` and add those three lines inside its success path.

- [ ] **Step 5: Run FE contract tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_fe_contract.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit (parent repo)**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): wire up Email Digest enabled + send_time

Add onchange/onblur handlers that PATCH /tradelab/live/config with the
email_digest sub-block. Recipient line displays the SMTP to_address.
Includes preview iframe + Refresh button shell (loadDigestPreview JS
arrives in next commit).

Slice 7a — T11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

```bash
cd C:/TradingScripts/tradelab && git add tests/web/test_digest_fe_contract.py
git commit -m "test(web): FE contract pins for Email Digest section markup

Slice 7a — T11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: FE — `loadDigestPreview()` + `loadDigestState()` JS functions

**Files:**
- Modify: `command_center.html` (parent repo) — add the two JS functions
- Modify: `tests/web/test_digest_fe_contract.py` (append new contract tests)

**Why now:** Depends on T9 and T10 endpoints working, and on T11 having created the iframe + last-sent line markup.

- [ ] **Step 1: Add failing FE contract tests**

Append to `tests/web/test_digest_fe_contract.py`:

```python
def test_html_contains_loadDigestPreview_js(html_text):
    assert "loadDigestPreview" in html_text


def test_html_contains_loadDigestState_js(html_text):
    assert "loadDigestState" in html_text


def test_html_iframe_id_present(html_text):
    assert 'id="email-digest-preview"' in html_text


def test_html_last_sent_line_present(html_text):
    assert 'id="email-digest-last-sent"' in html_text


def test_html_refresh_button_calls_loadDigestPreview(html_text):
    """The Refresh preview button has onclick=loadDigestPreview()."""
    assert "loadDigestPreview()" in html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_fe_contract.py -v`
Expected: 5 new tests fail (`loadDigestPreview`, `loadDigestState` not yet defined).

- [ ] **Step 3: Add JS functions to `command_center.html`**

In the existing settings-panel JS IIFE (or alongside the patch handlers from T11), add:

```javascript
async function loadDigestPreview() {
  const iframe = document.getElementById('email-digest-preview');
  if (!iframe) return;
  iframe.srcdoc = '<p style="font-family:sans-serif;color:#888;padding:12px">Loading…</p>';
  try {
    const res = await fetch('/tradelab/live/digest/preview');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    iframe.srcdoc = html;
  } catch (e) {
    console.error('loadDigestPreview failed', e);
    iframe.srcdoc = `<p style="font-family:sans-serif;color:#d32f2f;padding:12px">Preview failed: ${e.message}</p>`;
  }
}

async function loadDigestState() {
  const el = document.getElementById('email-digest-last-sent');
  if (!el) return;
  try {
    const res = await fetch('/tradelab/live/digest/state');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    if (payload.error) throw new Error(payload.error);
    if (!payload.data) {
      el.textContent = 'Last sent: never';
      return;
    }
    const d = payload.data;
    const stat = d.last_sent_failed ? '⚠ failed' : 'OK';
    el.textContent = `Last sent: ${d.last_sent_date || '—'} (${stat}, ${d.attempts_today ?? 0} attempts today)`;
  } catch (e) {
    console.error('loadDigestState failed', e);
    el.textContent = 'Last sent: error loading';
  }
}
```

Also: in the existing settings-panel "open" handler (whichever function is bound to opening the settings panel), add a single line at the end:
```javascript
loadDigestState();  // Refresh "Last sent" status when panel opens
```
Find it in `command_center.html` near the existing settings-panel toggle code (search for `settings-panel` open/show logic).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/web/test_digest_fe_contract.py -v`
Expected: 10 passed (5 from T11 + 5 from T12).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): loadDigestPreview + loadDigestState JS

loadDigestPreview fetches /tradelab/live/digest/preview and sets the
iframe srcdoc. loadDigestState fetches /digest/state and updates the
'Last sent' status line. State load runs on settings-panel open.

Slice 7a — T12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

```bash
cd C:/TradingScripts/tradelab && git add tests/web/test_digest_fe_contract.py
git commit -m "test(web): FE contract pins for digest preview + state JS

Slice 7a — T12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: F1 — wrap `build_alpaca_state` in `receiver.py` with try/except APIError

**Files:**
- Modify: `src/tradelab/live/receiver.py`
- Test: `tests/live/test_receiver_alpaca_wrap.py` (NEW)

**Why parallelizable:** Independent of all daily_summary work. Can run in the first wave alongside T1 + T2.

- [ ] **Step 1: Locate the Alpaca state-fetch call in receiver.py**

Run: `cd C:/TradingScripts/tradelab && grep -n "build_alpaca_state\|alpaca_state\|list_positions\|list_open_orders\|get_account" src/tradelab/live/receiver.py`
Expected: shows the line(s) where alpaca state is constructed for guardrail evaluation. Note the function name and surrounding context.

If the call is inlined (no `build_alpaca_state` helper exists yet), the implementation in Step 3 introduces the helper. If a helper exists, modify it in-place.

- [ ] **Step 2: Write failing tests**

Create `tests/live/test_receiver_alpaca_wrap.py`:

```python
"""F1 — verify receiver wraps Alpaca state fetch with try/except APIError.

Slice 5 follow-up #3 (originally Slice 4 follow-up #8). Slice 6 wrapped only
panic.py; this slice wraps the receiver guardrail path.
"""
from unittest.mock import MagicMock, patch

import pytest

from tradelab.live import receiver


def test_alpaca_unreachable_rejection_envelope_shape():
    """When build_alpaca_state raises APIError, receiver should reject with
    reason='alpaca_unreachable' and fire CRITICAL notify."""
    # Simulate Alpaca raising
    with patch.object(receiver, "build_alpaca_state",
                      side_effect=Exception("alpaca down")):
        with patch.object(receiver, "notify") as notify_mock:
            # Build a minimal valid webhook payload that would otherwise pass secret check
            # ... this test will be expanded based on actual receiver entry-point signature
            response, status = receiver._evaluate_guardrails_with_safety(
                card_id="card-a", action="buy", symbol="AAPL", qty=10
            )
    assert response.get("status") == "guardrail_blocked"
    assert response.get("reason") == "alpaca_unreachable"
    notify_mock.assert_called_once()
    args, _ = notify_mock.call_args
    # First arg is severity — should be CRITICAL
    assert "CRITICAL" in str(args[0]).upper()


def test_happy_path_unchanged_when_alpaca_succeeds():
    """When build_alpaca_state succeeds, normal guardrail path runs."""
    fake_state = MagicMock()
    fake_state.positions = []
    fake_state.open_orders = []
    fake_state.account = MagicMock(buying_power=100000.0, equity=100000.0)
    with patch.object(receiver, "build_alpaca_state", return_value=fake_state):
        with patch.object(receiver, "check_guardrails", return_value=None):
            response, status = receiver._evaluate_guardrails_with_safety(
                card_id="card-a", action="buy", symbol="AAPL", qty=10
            )
    # No early-rejection envelope; pass-through case (None or not-blocked)
    assert response.get("status") != "guardrail_blocked" or response.get("reason") != "alpaca_unreachable"
```

**Note for the implementing engineer:** the exact entry-point name (`_evaluate_guardrails_with_safety` above) is a placeholder. Inspect `receiver.py` to find the actual function being called between secret-check and Alpaca submit. Adjust test imports + the wrapper function name in Step 3 to match.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_receiver_alpaca_wrap.py -v`
Expected: AttributeError or test failure (the wrapped function does not exist or doesn't catch APIError yet).

- [ ] **Step 4: Implement F1 wrapping**

Edit `src/tradelab/live/receiver.py`. Locate where `alpaca_state` is constructed for `check_guardrails(...)` (likely a few lines before the `check_guardrails` call inside the webhook handler). Wrap the construction:

```python
# BEFORE (un-wrapped — current state):
# alpaca_state = build_alpaca_state()
# block_reason = check_guardrails(card, alert, alpaca_state)

# AFTER:
def _evaluate_guardrails_with_safety(card_id: str, action: str, symbol: str, qty: int):
    """Build alpaca_state + check guardrails, with fail-closed handling
    of Alpaca API errors.

    On APIError or other exception during build_alpaca_state(): reject the
    order with reason='alpaca_unreachable' and fire a CRITICAL notify.
    Returns (response_dict, http_status).
    """
    from alpaca.common.exceptions import APIError
    try:
        alpaca_state = build_alpaca_state()
    except APIError as e:
        notify(Severity.CRITICAL, "alpaca state fetch failed",
               f"card={card_id} action={action} symbol={symbol} qty={qty}: {e}",
               card_id=card_id)
        return _reject(card_id, "alpaca_unreachable", str(e))
    except Exception as e:
        # Broader catch to keep the trader's webhook path resilient
        notify(Severity.CRITICAL, "alpaca state fetch raised unexpected error",
               f"card={card_id} action={action}: {type(e).__name__}: {e}",
               card_id=card_id)
        return _reject(card_id, "alpaca_unreachable", f"{type(e).__name__}: {e}")

    # Normal path — happy case unchanged
    block_reason = check_guardrails(card, alert, alpaca_state)
    if block_reason:
        return _reject(card_id, block_reason.reason, block_reason.detail)
    return None, 200  # caller proceeds to submit
```

Then update the existing webhook handler to call this wrapper instead of the inline pattern. Search for the existing `build_alpaca_state` / `check_guardrails` call site and replace.

If `_reject` does not yet exist as a helper, define it inline:
```python
def _reject(card_id: str, reason: str, detail: str):
    """Build the standard rejection response + append to alerts.jsonl."""
    response = {"status": "guardrail_blocked", "reason": reason, "card_id": card_id, "detail": detail}
    # Append to alerts.jsonl using existing alert-write helper
    _append_alert(card_id=card_id, status="guardrail_blocked", reason=reason, detail=detail)
    return response, 200
```

(If `_append_alert` already exists in receiver.py, use it. If not, leverage whatever existing alert-writing pattern is in the file.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/test_receiver_alpaca_wrap.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run all receiver tests to verify no regressions**

Run: `cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest tests/live/ -v -k receiver`
Expected: all existing receiver tests still pass.

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/live/receiver.py tests/live/test_receiver_alpaca_wrap.py
git commit -m "feat(live): F1 — wrap receiver Alpaca state fetch with fail-closed guard

Slice 5 follow-up #3 (originally Slice 4 #8). On APIError or other
exception from build_alpaca_state(), reject the order with reason=
'alpaca_unreachable' and fire CRITICAL notify. The trading path's
safety stance is fail-closed: if we can't read state, we don't trade.

Slice 7a — T13.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Launcher wiring — boot `daily_summary.start()` + atexit

**Files:**
- Modify: `launch_dashboard.py` (parent repo at `C:\TradingScripts\launch_dashboard.py`)

**Why now:** Final integration. All daily_summary code is in place; just need the launcher to boot it.

- [ ] **Step 1: Inspect existing daemon-thread boot pattern**

Run: `cd C:/TradingScripts && grep -n "silence_checker\|notify_dispatcher\|atexit" launch_dashboard.py`
Expected: shows existing `notify_dispatcher.start()` and `silence_checker.start()` calls + `atexit.register(...)` lines from Slice 4 + Slice 5. Note their location.

- [ ] **Step 2: Add daily_summary boot + atexit (mirror existing pattern)**

Edit `launch_dashboard.py`. Locate the block where `notify_dispatcher.start()` and `silence_checker.start()` are called. Add a third line:

```python
# Existing
from tradelab.live import notify_dispatcher, silence_checker
notify_dispatcher.start()
silence_checker.start()

# NEW
from tradelab.live import daily_summary
daily_summary.start()
```

And in the atexit registration block (search for `atexit.register(notify_dispatcher.stop)`):

```python
# Existing
atexit.register(notify_dispatcher.stop)
atexit.register(silence_checker.stop)

# NEW
atexit.register(daily_summary.stop)
```

- [ ] **Step 3: Smoke-test the boot sequence**

The launcher boot is traditionally tested via a manual smoke. If there's an existing `tests/launcher/` test file that pins the daemon names, add an assertion. Otherwise, this is a smoke-only step.

Manually verify (or hand off to Monday smoke):

```powershell
# Stop any running launcher first, then re-launch
$env:PYTHONPATH = "src"
python "C:/TradingScripts/launch_dashboard.py"
# In the boot log, verify three lines (or equivalent):
#   [startup] notify_dispatcher started
#   [startup] silence_checker started
#   [startup] daily_summary started
```

If `daily_summary.start()` doesn't print a startup line by default, the boot can be verified post-hoc by listing thread names from another process, or by setting up the digest with `send_time = <now+2min>` and watching for the email at the appropriate time.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add launch_dashboard.py
git commit -m "feat(launcher): boot daily_summary daemon thread + atexit cleanup

Slice 7a — T14. Mirrors notify_dispatcher + silence_checker boot pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: gitignore — add `live/digest_state.json`

**Files:**
- Modify: `tradelab/.gitignore` (or whichever ignore file already covers `live/live_config.json`)

**Why now:** Trivial cleanup. Done after the state file's first write happens (which won't happen until digest is enabled), but adding to ignore now prevents accidental commit later.

- [ ] **Step 1: Inspect existing live/* ignore rules**

Run: `cd C:/TradingScripts/tradelab && grep -n "live/" .gitignore`
Expected: shows existing patterns like `live/live_config.json`, `live/*.jsonl`, etc. Note exactly how the existing entries are formatted.

- [ ] **Step 2: Add the new ignore line**

Edit `.gitignore`. Add this line near the other `live/` ignores:

```
live/digest_state.json
```

If the existing `live/` ignores use a glob pattern like `live/*.json` that already covers it, this step is a no-op (verify via `git check-ignore -v live/digest_state.json` once a file exists).

- [ ] **Step 3: Verify**

Run: `cd C:/TradingScripts/tradelab && touch live/digest_state.json && git status --short live/digest_state.json`
Expected: empty output (file is ignored).

Cleanup:
```
cd C:/TradingScripts/tradelab && rm live/digest_state.json
```

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab && git add .gitignore
git commit -m "chore(gitignore): ignore live/digest_state.json

Slice 7a — T15.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Full pytest run — verify Slice 7a pytest baseline

**Files:** none modified — verification only.

**Why now:** Final integration check before declaring Slice 7a done.

- [ ] **Step 1: Run full test suite**

Run:
```bash
cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -m pytest -v 2>&1 | tail -40
```
Expected: ~755 passed / 0 failed (was 709 / 0 at Slice 6 close). If actual count is between 745-760, that's within tolerance.

- [ ] **Step 2: If any failures — investigate before claiming done**

Common causes:
- Import-time circular ref between `daily_summary` and `silence_checker` — refactor imports to be inside function bodies
- Test pollution from `silence_checker._silent_set()` shared state — the test fixture should monkeypatch instead of mutating
- `command_center.html` markup not in expected location — adjust HTML_PATH in `test_digest_fe_contract.py`

Fix any failures, re-run, and only proceed when all green.

- [ ] **Step 3: Smoke-check daily_summary import + render in REPL**

Run:
```bash
cd C:/TradingScripts/tradelab && set PYTHONPATH=src && python -c "from datetime import datetime; from tradelab.live import daily_summary; subj, html = daily_summary.render(datetime.now()); print('SUBJECT:', subj); print('HTML LEN:', len(html)); print('CONTAINS PANIC:', 'PANIC' in html); print('OK')"
```
Expected: `OK` printed, subject is reasonable, HTML length > 200.

- [ ] **Step 4: Commit (the count change as a marker if anything in repo changed during verification)**

Only if changes were made during Step 2:

```bash
cd C:/TradingScripts/tradelab && git add -p
git commit -m "fix(live): integration fixes from Slice 7a final smoke

Slice 7a — T16.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If no changes — skip. Final pytest count is the deliverable.

---

## Done criteria for Slice 7a

- [ ] All 16 tasks above committed
- [ ] `pytest -v` reports ~755 / 0 (or within ±10 of that)
- [ ] `from tradelab.live import daily_summary` works from a fresh REPL
- [ ] `GET /tradelab/live/digest/preview` returns 200 with HTML when launcher is running
- [ ] `GET /tradelab/live/digest/state` returns 200 with state JSON or `{data: null}`
- [ ] Settings panel shows the Email Digest section with toggle, send-time, recipient, [Refresh preview], iframe, and "Last sent" line
- [ ] `launch_dashboard.py` boots `daily_summary` daemon thread on startup

**NOT done:** Live email send via SMTP — deferred to live smoke on next trading day after a Slice 7a build is deployed (per spec §11.3).

**NOT done:** `TRADELAB_MANUAL.html` rewrite — that's Slice 7b, separate plan.

---

## Self-review notes

**Spec coverage check** (against `2026-04-26-direction-a-slice-7-daily-summary-design.md`):

| Spec section | Task |
|---|---|
| §3.1 Process placement (launcher) | T14 |
| §3.2 Daemon thread lifecycle | T8 |
| §3.3 Send path (direct, NOT via notify) | T6 (`_send_email`, `_append_audit_line`) |
| §3.4 Idempotency state schema | T6 (`_read_state`, `_write_state`) |
| §3.5 Send-failure retry policy (cap 5/day) | T6 + T7 |
| §4 Data sources | T3, T4 (`_today_*`, `_card_counts`, `_open_*`, etc.) |
| §5.1 Subject line format | T5 (`_render_subject`) |
| §5.2 HTML body structure (inline-styled) | T3 + T4 + T5 (`render`) |
| §5.3 Plaintext fallback | T5 (`_render_plaintext`) |
| §5.4 All-clear rendering | T3 (✓ header path) + tested in T3 |
| §5.5 Section-level error handling | T3, T4 (each section in `_safe_call`) |
| §6 New endpoints | T9, T10 |
| §7 Frontend (preview iframe + state line + JS) | T11, T12 |
| §8 Backwards compatibility | implicit; T15 covers gitignore; live_config block already exists |
| §9.1 F1 receiver Alpaca wrap | T13 |
| §9.2 F2 jsonl rotation utility | T1 + integrated into T6 |
| §10 Manual update | NOT IN SLICE 7a — deferred to 7b |
| §11.1 Test files (new) | T1 (`test_jsonl_rotation`), T2 (`test_jsonl_helpers`), T3-T5 (`test_daily_summary_render`), T6-T7 (`test_daily_summary_tick`, `test_daily_summary_state`), T9-T10 (`test_digest_handlers`), T11-T12 (`test_digest_fe_contract`), T13 (`test_receiver_alpaca_wrap`) |
| §11.2 Pytest baseline (~755) | T16 |
| §11.3 Live smoke | DEFERRED to live smoke after deploy (per spec) |
| §14.1 Launcher wiring | T14 |

**Gaps:** Manual update (§10) is intentionally out of scope for 7a. Everything else is covered.

**Type consistency check:** `STATE_PATH`, `_today_*` function names, `MAX_ATTEMPTS_PER_DAY`, `_render_anomaly_section`, `_render_snapshot_section` are all consistent across tasks 3-8.

**Placeholder scan:** the F1 entry-point name `_evaluate_guardrails_with_safety` in T13 is acknowledged as a placeholder pending receiver.py inspection — Step 1 of T13 instructs the engineer to find the real function name. All other code blocks contain complete implementations.

---

**End of Slice 7a plan.**
