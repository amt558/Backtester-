# Direction A — Slice 4 (Notification System + Settings Panel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface receiver-side events (`guardrail_blocked`, `order_failed`) to the user across five best-effort channels (browser toast, Windows toast, audible, ntfy.sh, email) with per-severity routing. Add a collapsed settings panel at the bottom of the Live Trading tab so the user can toggle channels, fill credentials, and test each channel.

**Architecture:** A single `notify(severity, title, body, channels=None)` function appends one JSON line to `tradelab/live/notify_events.jsonl`. A dispatcher running in the dashboard launcher process watches that file, resolves each event's channels via the routing matrix in `live_config.json`, and fans out to channel modules in isolation (one channel failure does not stop others). The browser channel pushes to a new `Broadcaster` instance whose SSE endpoint feeds an in-page toast UI on the dashboard. Cross-process delivery (receiver → dashboard) is solved by the JSONL file — both processes append/tail it the same way they already do for `alerts.jsonl`. Frontend extends the existing `LT` IIFE in `command_center.html` with a `<details id="lt-settings">` collapsed-by-default block.

**Tech Stack:** Python stdlib (`smtplib`, `winsound`, `urllib.request`, `dataclasses`, `threading.Lock`, `json`), `watchdog` (already a tradelab dep — Slice 1), `plyer` (NEW dep for Windows toast), existing `tradelab.web.sse.Broadcaster` (Slice 1 primitive — no new SSE plumbing), vanilla JS.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `tradelab/pyproject.toml` | Add `plyer>=2.1.0` to `dependencies` |
| Create | `tradelab/src/tradelab/live/live_config.py` | `LiveConfig` dataclass; load/save with atomic write; `mask_passwords()`; module-level singleton + `reload()` hook |
| Create | `tradelab/src/tradelab/live/notify.py` | `Severity` enum (`CRITICAL`/`WARNING`/`INFO`); `notify(severity, title, body, channels=None)` — single-line append to `notify_events.jsonl` |
| Create | `tradelab/src/tradelab/live/notify_dispatcher.py` | Watchdog observer on `notify_events.jsonl`; reads new lines after start; resolves routing; fans out to channel modules with per-channel try/except |
| Create | `tradelab/src/tradelab/live/notify_channels/__init__.py` | Channel registry: `CHANNELS = {"audible": ..., "windows_toast": ..., "ntfy": ..., "email": ..., "browser": ...}` |
| Create | `tradelab/src/tradelab/live/notify_channels/audible.py` | `send(severity, title, body, config) -> bool` via `winsound` |
| Create | `tradelab/src/tradelab/live/notify_channels/windows_toast.py` | `send(...)` via `plyer.notification.notify`; gracefully no-op if plyer import fails |
| Create | `tradelab/src/tradelab/live/notify_channels/ntfy.py` | `send(...)` via `urllib.request` POST to `<server>/<topic>`; 3s timeout |
| Create | `tradelab/src/tradelab/live/notify_channels/email.py` | `send(...)` via `smtplib.SMTP` STARTTLS; 10s timeout |
| Create | `tradelab/src/tradelab/live/notify_channels/browser.py` | `send(...)` calls `tradelab.web.get_notify_broadcaster().broadcast(...)` |
| Modify | `tradelab/src/tradelab/web/__init__.py` | Add `_notify_broadcaster = Broadcaster()` + `get_notify_broadcaster()` accessor (mirror existing `_broadcaster` / `get_broadcaster()` at lines 16/28) |
| Modify | `tradelab/src/tradelab/web/handlers.py` | Add `handle_notify_sse(wfile)` (mirror `handle_sse` at line 724); add 3 endpoints (`GET`/`PATCH /tradelab/live/config`, `POST /tradelab/live/config/test-notification`); add `_ALLOWED_LIVE_CONFIG_FIELDS` validator (mirror `_ALLOWED_PATCH_FIELDS` at line 818) |
| Modify | `tradelab/src/tradelab/live/receiver.py` | Call `notify(Severity.CRITICAL, ...)` after each `guardrail_blocked` and `order_failed` log entry |
| Modify | `launch_dashboard.py` (parent repo) | Boot `NotifyDispatcher` in startup; add 3 new HTTP routes to `do_GET`/`do_POST`/`do_PATCH` plus `/tradelab/live/notify-stream` SSE route |
| Modify | `command_center.html` (parent repo) | Settings panel `<details>` block + CSS + JS extensions to `LT` IIFE (loadSettings/saveSettings/testChannel/subscribeBrowserToasts) |
| Create | `tradelab/tests/live/test_live_config.py` | Default load; round-trip; atomic save; mask; reload |
| Create | `tradelab/tests/live/test_notify.py` | Severity values; notify() appends JSONL; channels override; ts is ISO-UTC |
| Create | `tradelab/tests/live/test_notify_dispatcher.py` | Watcher reads new lines; channel exception isolated; routing pulled from config |
| Create | `tradelab/tests/live/test_notify_channels.py` | One success + one failure-isolation test per channel (table-style) |
| Create | `tradelab/tests/live/test_receiver_notify_integration.py` | Webhook → blocked → notify_events.jsonl AND alerts.jsonl both written |
| Create | `tradelab/tests/web/test_live_config_handlers.py` | GET masks passwords; PATCH validates + persists; POST test-notification fires `notify()` |
| Modify | `tradelab/tests/web/test_command_center_html.py` | Pin `LT.loadSettings` / `LT.saveSettings` / `LT.testChannel` / `LT.subscribeBrowserToasts` + DOM contract for `#lt-settings` block |
| Create | parent repo: `2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md` | Done doc + smoke checklist + Slice 5 handoff |

Baseline: 544 tests passing at end of Slice 3. Target end-of-Slice-4: ~590+ (≈45–55 net-new across config + notify + dispatcher + 5 channels + 3 endpoints + receiver integration + FE pins).

---

## Conventions (load-bearing — Slices 1+2+3 validated these)

- **TDD strict:** failing test → verify it fails for the right reason → minimal impl → green → commit.
- **Test layout:** `from __future__ import annotations` at top; pytest `tmp_path` fixture; mock the boundary (smtplib.SMTP, urllib.request.urlopen, winsound, plyer), never the network. Use `monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", path)` and `monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", path)` to override module-level singletons.
- **Response envelope:** all dashboard endpoints return `_ok(data)` / `_err(msg)` per `handlers.py:782-787`. Receiver-side endpoints (none added in Slice 4) use the receiver's bare-string envelope.
- **Validation lives in the handler (system boundary).** `LiveConfig.update()` is internal — it trusts callers. Channel modules trust their inputs (config has already passed `_validate_live_config_payload`).
- **Atomic write:** `live_config.py` uses the same `tmp.write_text → os.replace` pattern as `cards.py:_persist`. The notify_events.jsonl uses plain `open(... "a")` append (atomic for short writes on Windows ≤ PIPE_BUF size).
- **Best-effort channels:** every channel `send()` returns `bool` (True on success, False on any handled error). Channel module catches `Exception`, logs to stderr, returns False. The dispatcher catches `Exception` around the `send()` call too as belt-and-suspenders.
- **Cross-process notify:** the receiver process writes to `notify_events.jsonl` exactly the same way the dashboard does. The dispatcher only runs in the dashboard launcher (single consumer).
- **Commits:** Direct to `master` in tradelab repo (no branches). Conventional `feat(layer): …`, `fix(layer): …`, `test(live): …`, `ui(command-center): …`. Footer required:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **HTML selectors (verified against current `command_center.html` 2026-04-25):**
  - Live Trading tab content is `<div id="live-trading" class="tab-content">`.
  - LT IIFE is at `command_center.html:4298` — extend the existing module, do NOT create a new IIFE for settings.
  - Settings panel inserts as a sibling `<details id="lt-settings">` after the LT card list (`#lt-cards`) and before the closing `</div>` of `#live-trading`.
  - Existing CSS namespace prefix is `.lt-` — use `.lt-settings-*` for new classes.
- **DO NOT** add notification logic to receiver beyond a single `notify(...)` call after each existing `_log_alert` call. Routing happens in dispatcher; receiver stays dumb.
- **DO NOT** introduce a separate FastAPI app for notify endpoints. They live in the dashboard `BaseHTTPRequestHandler` like every other `/tradelab/*` route.
- **DO NOT** add channel-specific config to the per-card `cards.json`. All channel config lives in `live_config.json`. Per-card overrides remain Slice 3's 4 fields only.
- **DO NOT** delete `notify_events.jsonl` on dispatcher restart. The dispatcher reads from EOF on start (event log is best-effort + ephemeral; missed events during dispatcher downtime stay in the file as audit only). Defer rotation to Slice 5+ alongside `alerts.jsonl` rotation.

---

## Single source of truth: routing matrix + event taxonomy

Per spec §7.1 and §7.2.

```python
# tradelab/src/tradelab/live/notify.py
class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


# tradelab/src/tradelab/live/live_config.py — DEFAULTS
DEFAULT_SEVERITY_ROUTING = {
    "critical": ["browser", "windows_toast", "audible", "ntfy", "email"],
    "warning":  ["browser", "windows_toast", "audible"],
    "info":     ["browser"],
}
```

| Event (Slice 4 wires these) | Severity | Default channels |
|---|---|---|
| `guardrail_blocked` (any reason) | CRITICAL | all 5 |
| `order_failed` (Alpaca submit raised) | CRITICAL | all 5 |

Other spec §7.2 events (`receiver process down`, `ngrok down`, `panic activated`, `card silent`, `order submitted`, `daily summary`) are produced by future slices and out of scope here. Slice 4 only ships the wiring for the two receiver-side events that already log to `alerts.jsonl`.

When the caller passes an explicit `channels=` set, routing is overridden. The settings-panel "Test [channel]" buttons use this to send to exactly one channel.

---

## Single source of truth: live_config.json schema

Default contents written by `live_config.load()` if the file does not exist. Existing files are merged with defaults on load (any new key in defaults is added; any unknown key in the file is preserved but ignored).

```json
{
  "schema_version": 1,
  "notifications": {
    "enabled_channels": ["browser"],
    "severity_routing": {
      "critical": ["browser", "windows_toast", "audible", "ntfy", "email"],
      "warning":  ["browser", "windows_toast", "audible"],
      "info":     ["browser"]
    },
    "ntfy": {
      "topic": "",
      "server": "https://ntfy.sh"
    },
    "smtp": {
      "host": "",
      "port": 587,
      "user": "",
      "password": "",
      "from_address": "",
      "to_address": ""
    },
    "audible": {
      "volume_pct": 70,
      "sound_file": ""
    }
  },
  "guardrails": {
    "max_exposure_pct": 0.90,
    "default_daily_limit": 5,
    "default_cooldown_seconds": 30
  },
  "silence": {
    "multipliers": {
      "intraday": 2,
      "daily": 5,
      "weekly": 21
    }
  },
  "email_digest": {
    "enabled": false,
    "send_time": "16:00"
  }
}
```

`enabled_channels` is the master kill-switch: a channel must be in this set AND in the severity's routing for an event to reach it. Defaults to `["browser"]` so a fresh install does not blast the user's email/ntfy until they opt in per channel.

`smtp.password` is the only field masked by `mask_passwords()` (returns `"******"` if non-empty, `""` if empty). PATCH ignores incoming `smtp.password == "******"` (treats as no-change), so the masked GET → unmodified PATCH round trip does not blank the password.

`schema_version` is in the schema for future migration. Slice 4 only writes `1` — no migration logic.

`guardrails.max_exposure_pct` replaces Slice 3's hardcoded `0.90` in `tradelab/src/tradelab/live/guardrails.py`. T13 includes the receiver-side rewire.

---

## Task 1: Add `plyer` dep + import-with-fallback helper

**Files:**
- Modify: `tradelab/pyproject.toml`

`plyer>=2.1.0` is the cross-platform notification dep. On Windows it uses `Windows.UI.Notifications` via `pywin32` (which plyer installs transitively). Channel module guards against import failures so the package never crashes if a CI env lacks it.

- [ ] **Step 1: Add the dep**

Edit `tradelab/pyproject.toml`:

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
    "plyer>=2.1.0",
]
```

- [ ] **Step 2: Install**

Run: `cd C:/TradingScripts/tradelab && pip install -e .`
Expected: `Successfully installed plyer-2.1.0` (and pywin32 transitively on Windows).

- [ ] **Step 3: Verify import works**

Run: `python -c "import plyer; from plyer import notification; print(notification.notify)"`
Expected: prints a bound method (e.g. `<bound method Notification.notify of <plyer.facades.notification.Notification object at 0x...>>`); does NOT raise.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab
git add pyproject.toml
git commit -m "$(cat <<'EOF'
deps(live): add plyer for Windows toast notifications (Slice 4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `live_config.py` — `LiveConfig` dataclass + atomic load/save + masking

**Files:**
- Create: `tradelab/src/tradelab/live/live_config.py`
- Create: `tradelab/tests/live/test_live_config.py`

The module owns the on-disk schema (`live_config.json`), a single in-memory cache, and an atomic `save()`. Other modules call `live_config.get()` (returns the singleton) and `live_config.reload()` (re-reads from disk after a PATCH). All other Slice 4 modules depend on this one.

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_live_config.py`:

```python
"""LiveConfig — runtime config for notification channels + guardrail thresholds."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.live import live_config


@pytest.fixture(autouse=True)
def _isolated_config_path(tmp_path, monkeypatch):
    p = tmp_path / "live_config.json"
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", p)
    live_config.reload()
    yield p


def test_load_writes_defaults_if_missing(_isolated_config_path):
    cfg = live_config.get()
    assert cfg["schema_version"] == 1
    assert cfg["notifications"]["enabled_channels"] == ["browser"]
    assert cfg["guardrails"]["max_exposure_pct"] == 0.90
    assert _isolated_config_path.exists()
    on_disk = json.loads(_isolated_config_path.read_text(encoding="utf-8"))
    assert on_disk == cfg


def test_save_roundtrip(_isolated_config_path):
    cfg = live_config.get()
    cfg["notifications"]["enabled_channels"] = ["browser", "audible"]
    live_config.save(cfg)
    live_config.reload()
    assert live_config.get()["notifications"]["enabled_channels"] == ["browser", "audible"]


def test_save_is_atomic(_isolated_config_path, tmp_path):
    cfg = live_config.get()
    cfg["notifications"]["smtp"]["host"] = "smtp.example.com"
    live_config.save(cfg)
    # No leftover .tmp file after save
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_mask_passwords_replaces_nonempty_smtp_password(_isolated_config_path):
    cfg = live_config.get()
    cfg["notifications"]["smtp"]["password"] = "supersecret"
    masked = live_config.mask_passwords(cfg)
    assert masked["notifications"]["smtp"]["password"] == "******"
    # Non-mutating: original cfg untouched
    assert cfg["notifications"]["smtp"]["password"] == "supersecret"


def test_mask_passwords_leaves_empty_password_empty(_isolated_config_path):
    cfg = live_config.get()
    masked = live_config.mask_passwords(cfg)
    assert masked["notifications"]["smtp"]["password"] == ""


def test_load_merges_new_default_keys_into_existing_file(_isolated_config_path):
    # Simulate an old file missing a key that defaults adds
    _isolated_config_path.write_text(json.dumps({"schema_version": 1, "guardrails": {"max_exposure_pct": 0.5}}), encoding="utf-8")
    live_config.reload()
    cfg = live_config.get()
    # Existing key preserved
    assert cfg["guardrails"]["max_exposure_pct"] == 0.5
    # Missing default added
    assert cfg["notifications"]["enabled_channels"] == ["browser"]


def test_load_preserves_unknown_keys(_isolated_config_path):
    _isolated_config_path.write_text(json.dumps({"schema_version": 1, "experimental": {"foo": "bar"}}), encoding="utf-8")
    live_config.reload()
    assert live_config.get()["experimental"] == {"foo": "bar"}


def test_update_in_place_then_save(_isolated_config_path):
    live_config.update({"notifications": {"ntfy": {"topic": "tradelab-test"}}})
    cfg = live_config.get()
    assert cfg["notifications"]["ntfy"]["topic"] == "tradelab-test"
    # Other ntfy fields not blown away
    assert cfg["notifications"]["ntfy"]["server"] == "https://ntfy.sh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_live_config.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'tradelab.live.live_config'`.

- [ ] **Step 3: Implement `live_config.py`**

Create `tradelab/src/tradelab/live/live_config.py`:

```python
"""Runtime configuration for notification channels + global guardrail thresholds.

On-disk: tradelab/live/live_config.json (gitignored via /live/*.json).
In-memory: a single dict cache, refreshed by reload().

Schema is intentionally a plain dict — no pydantic — to keep PATCH semantics
(deep-merge of partial payloads) simple. mask_passwords() returns a copy with
SMTP password replaced; never mutates the source.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

# Path resolved against the tradelab/ repo root (parent of src/).
_LIVE_CONFIG_PATH = Path(__file__).resolve().parents[3] / "live" / "live_config.json"

_DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "notifications": {
        "enabled_channels": ["browser"],
        "severity_routing": {
            "critical": ["browser", "windows_toast", "audible", "ntfy", "email"],
            "warning":  ["browser", "windows_toast", "audible"],
            "info":     ["browser"],
        },
        "ntfy": {
            "topic": "",
            "server": "https://ntfy.sh",
        },
        "smtp": {
            "host": "",
            "port": 587,
            "user": "",
            "password": "",
            "from_address": "",
            "to_address": "",
        },
        "audible": {
            "volume_pct": 70,
            "sound_file": "",
        },
    },
    "guardrails": {
        "max_exposure_pct": 0.90,
        "default_daily_limit": 5,
        "default_cooldown_seconds": 30,
    },
    "silence": {
        "multipliers": {"intraday": 2, "daily": 5, "weekly": 21},
    },
    "email_digest": {
        "enabled": False,
        "send_time": "16:00",
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _deep_merge_defaults(target: dict, defaults: dict) -> dict:
    """Add any missing default keys to target (recursive). Existing keys preserved."""
    for k, v in defaults.items():
        if k not in target:
            target[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(target[k], dict):
            _deep_merge_defaults(target[k], v)
    return target


def reload() -> None:
    """Re-read from disk into the cache. Writes defaults if file missing."""
    global _cache
    with _lock:
        if _LIVE_CONFIG_PATH.exists():
            raw = _LIVE_CONFIG_PATH.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        else:
            data = {}
        _deep_merge_defaults(data, _DEFAULTS)
        _cache = data
        if not _LIVE_CONFIG_PATH.exists():
            _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(_LIVE_CONFIG_PATH, _cache)


def get() -> dict[str, Any]:
    """Return the cached config (lazy-loads on first call)."""
    if not _cache:
        reload()
    return _cache


def save(new_cfg: dict[str, Any]) -> None:
    """Atomic write + cache refresh."""
    global _cache
    with _lock:
        _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_LIVE_CONFIG_PATH, new_cfg)
        _cache = copy.deepcopy(new_cfg)


def update(partial: dict[str, Any]) -> None:
    """Deep-merge partial into the cache, then save."""
    cfg = copy.deepcopy(get())
    _deep_merge_overwrite(cfg, partial)
    save(cfg)


def _deep_merge_overwrite(target: dict, src: dict) -> None:
    """Merge src into target, overwriting at the leaf level."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge_overwrite(target[k], v)
        else:
            target[k] = v


def mask_passwords(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copy with SMTP password replaced by '******' if non-empty."""
    masked = copy.deepcopy(cfg)
    pw = masked.get("notifications", {}).get("smtp", {}).get("password", "")
    if pw:
        masked["notifications"]["smtp"]["password"] = "******"
    return masked


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_live_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/live_config.py tests/live/test_live_config.py
git commit -m "$(cat <<'EOF'
feat(live): live_config.py with atomic save + password masking

Single source of truth for notification channel toggles, severity routing,
ntfy/SMTP creds, and global guardrail thresholds. Defaults written on first
read; existing files merged with defaults so adding a key in code does not
break older installs. mask_passwords() is non-mutating.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `notify.py` — `Severity` enum + `notify()` JSONL appender

**Files:**
- Create: `tradelab/src/tradelab/live/notify.py`
- Create: `tradelab/tests/live/test_notify.py`

The entry point is intentionally minimal: it appends one JSON line to `notify_events.jsonl` and returns. All routing/dispatch happens in `notify_dispatcher.py` (T4) running in the dashboard process. This decouples the producer (any process) from the consumer (one process), matching the same pattern as `alerts.jsonl`.

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_notify.py`:

```python
"""notify() — single-line JSONL append for cross-process event delivery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradelab.live import notify
from tradelab.live.notify import Severity


@pytest.fixture(autouse=True)
def _isolated_events_path(tmp_path, monkeypatch):
    p = tmp_path / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", p)
    yield p


def test_severity_enum_values():
    assert Severity.CRITICAL.value == "critical"
    assert Severity.WARNING.value == "warning"
    assert Severity.INFO.value == "info"


def test_notify_appends_one_jsonl_line(_isolated_events_path):
    notify.notify(Severity.CRITICAL, "Test title", "Test body")
    lines = _isolated_events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["severity"] == "critical"
    assert event["title"] == "Test title"
    assert event["body"] == "Test body"
    assert event["channels"] is None  # null = use routing matrix


def test_notify_with_explicit_channels(_isolated_events_path):
    notify.notify(Severity.INFO, "T", "B", channels={"browser"})
    event = json.loads(_isolated_events_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["channels"] == ["browser"]


def test_notify_ts_is_iso_utc(_isolated_events_path):
    notify.notify(Severity.WARNING, "T", "B")
    event = json.loads(_isolated_events_path.read_text(encoding="utf-8").splitlines()[0])
    parsed = datetime.fromisoformat(event["ts"])
    assert parsed.tzinfo is not None
    # Within 5s of now
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 5.0


def test_notify_appends_does_not_overwrite(_isolated_events_path):
    notify.notify(Severity.INFO, "first", "")
    notify.notify(Severity.INFO, "second", "")
    lines = _isolated_events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "first"
    assert json.loads(lines[1])["title"] == "second"


def test_notify_creates_parent_dir_if_missing(tmp_path, monkeypatch):
    deep = tmp_path / "does" / "not" / "exist" / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", deep)
    notify.notify(Severity.INFO, "x", "y")
    assert deep.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `notify.py`**

Create `tradelab/src/tradelab/live/notify.py`:

```python
"""notify() — append-one-line entry point for cross-process notification delivery.

Producers (receiver, dashboard, future panic/silence checkers) call notify(...).
The dispatcher process (one per host, lives in the dashboard launcher) tails
notify_events.jsonl and fans out to channel modules.

Decoupling via JSONL keeps producer code path identical regardless of which
process it runs in — same as alerts.jsonl.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

NOTIFY_EVENTS_PATH = Path(__file__).resolve().parents[3] / "live" / "notify_events.jsonl"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


def notify(
    severity: Severity,
    title: str,
    body: str,
    *,
    channels: Optional[set[str]] = None,
) -> None:
    """Append a single JSONL event. Best-effort; failures swallowed.

    severity: routing key (resolved by dispatcher against live_config).
    title/body: human-readable strings.
    channels: optional explicit channel set, bypasses routing matrix.
    """
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "severity": severity.value if isinstance(severity, Severity) else str(severity),
        "title": title,
        "body": body,
        "channels": sorted(channels) if channels is not None else None,
    }
    try:
        NOTIFY_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFY_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        # Notification machinery must never crash the producer.
        import sys
        print(f"[notify] failed to append event: {type(e).__name__}: {e}", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify.py tests/live/test_notify.py
git commit -m "$(cat <<'EOF'
feat(live): notify.py with Severity enum + JSONL appender

Producer-side entry point. Append-only to tradelab/live/notify_events.jsonl
so any process (receiver, dashboard, future silence checker) can produce
events the same way. Routing/dispatch lives in notify_dispatcher.py (T4).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `notify_dispatcher.py` — watchdog tail + routing + channel isolation

**Files:**
- Create: `tradelab/src/tradelab/live/notify_dispatcher.py`
- Create: `tradelab/tests/live/test_notify_dispatcher.py`

Dispatcher runs in the dashboard launcher only (single consumer). Uses watchdog's `PollingObserver` (matches Slice 1's choice for Windows reliability) to watch `notify_events.jsonl`. Tracks a byte offset so each restart skips past previously-dispatched events (read-from-EOF on start). For each new line: parse JSON, resolve channels (event.channels overrides; else `live_config.severity_routing[severity]` ∩ `enabled_channels`), call each channel's `send()` inside try/except so one failure does not stop others.

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_notify_dispatcher.py`:

```python
"""NotifyDispatcher — watchdog tail of notify_events.jsonl + channel fan-out."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tradelab.live import live_config, notify
from tradelab.live.notify import Severity
from tradelab.live.notify_dispatcher import NotifyDispatcher


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    events = tmp_path / "notify_events.jsonl"
    cfg_path = tmp_path / "live_config.json"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", events)
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", cfg_path)
    live_config.reload()
    # Default to all 5 channels enabled for routing tests
    live_config.update({"notifications": {"enabled_channels": ["browser", "audible", "windows_toast", "ntfy", "email"]}})
    yield events


def _start_dispatcher(events_path) -> NotifyDispatcher:
    d = NotifyDispatcher(events_path=events_path)
    d.start()
    # Allow watcher thread to register
    time.sleep(0.1)
    return d


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_dispatcher_calls_browser_channel_for_info_severity(_isolated_paths, monkeypatch):
    calls = []
    def fake_browser_send(severity, title, body, config):
        calls.append((severity, title, body))
        return True

    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", fake_browser_send)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "info-title", "info-body")
        assert _wait_for(lambda: len(calls) == 1)
        assert calls[0] == ("info", "info-title", "info-body")
    finally:
        d.stop()


def test_dispatcher_resolves_critical_to_all_default_channels(_isolated_paths, monkeypatch):
    fired = set()
    def make(name):
        def _send(s, t, b, c):
            fired.add(name)
            return True
        return _send

    from tradelab.live.notify_channels import CHANNELS
    for name in ("browser", "audible", "windows_toast", "ntfy", "email"):
        monkeypatch.setitem(CHANNELS, name, make(name))

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.CRITICAL, "boom", "everything")
        assert _wait_for(lambda: fired == {"browser", "audible", "windows_toast", "ntfy", "email"})
    finally:
        d.stop()


def test_dispatcher_isolates_channel_failure(_isolated_paths, monkeypatch):
    successes = []
    def good_send(s, t, b, c):
        successes.append("good")
        return True
    def bad_send(s, t, b, c):
        raise RuntimeError("transport down")

    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", bad_send)
    monkeypatch.setitem(CHANNELS, "audible", good_send)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.WARNING, "T", "B")  # WARNING routes to browser+audible+windows_toast
        assert _wait_for(lambda: "good" in successes)
    finally:
        d.stop()


def test_dispatcher_explicit_channels_override_routing(_isolated_paths, monkeypatch):
    calls = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "ntfy", lambda s, t, b, c: calls.append("ntfy") or True)
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: calls.append("browser") or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "T", "B", channels={"ntfy"})  # INFO normally → browser only
        assert _wait_for(lambda: calls == ["ntfy"])
    finally:
        d.stop()


def test_dispatcher_skips_disabled_channel(_isolated_paths, monkeypatch):
    live_config.update({"notifications": {"enabled_channels": ["browser"]}})  # only browser enabled
    fired = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "ntfy", lambda s, t, b, c: fired.append("ntfy") or True)
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: fired.append("browser") or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.CRITICAL, "T", "B")  # would route to all 5; only browser enabled
        assert _wait_for(lambda: fired == ["browser"], timeout=1.0)
        assert "ntfy" not in fired
    finally:
        d.stop()


def test_dispatcher_starts_at_eof_skips_existing_events(_isolated_paths, monkeypatch):
    # Pre-write an event that was "missed"
    notify.notify(Severity.CRITICAL, "old", "should be skipped")
    fired = []
    from tradelab.live.notify_channels import CHANNELS
    monkeypatch.setitem(CHANNELS, "browser", lambda s, t, b, c: fired.append((t, b)) or True)

    d = _start_dispatcher(_isolated_paths)
    try:
        notify.notify(Severity.INFO, "new", "should fire")
        assert _wait_for(lambda: ("new", "should fire") in fired)
        assert ("old", "should be skipped") not in fired
    finally:
        d.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_dispatcher.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'tradelab.live.notify_dispatcher'` or `'tradelab.live.notify_channels'`.

- [ ] **Step 3: Implement `notify_channels/__init__.py` (registry stub) + `notify_dispatcher.py`**

Create `tradelab/src/tradelab/live/notify_channels/__init__.py`:

```python
"""Notification channel registry. Each channel module exposes `send(severity, title, body, config) -> bool`.

Slots are populated by importing each channel module. Tests monkeypatch CHANNELS
directly to install fakes — this avoids cascading imports during unit tests.
"""
from __future__ import annotations

from typing import Callable, Dict

# Channel signature: (severity_str, title, body, live_config_dict) -> bool
ChannelSend = Callable[[str, str, str, dict], bool]

CHANNELS: Dict[str, ChannelSend] = {}


def register(name: str, send_fn: ChannelSend) -> None:
    CHANNELS[name] = send_fn


# Best-effort imports — a missing channel module should not crash the dispatcher.
# Each channel module calls register() at import time.
for _mod in ("audible", "windows_toast", "ntfy", "email", "browser"):
    try:
        __import__(f"tradelab.live.notify_channels.{_mod}", fromlist=["_"])
    except Exception as e:
        import sys
        print(f"[notify_channels] failed to register {_mod}: {type(e).__name__}: {e}", file=sys.stderr)
```

Create `tradelab/src/tradelab/live/notify_dispatcher.py`:

```python
"""NotifyDispatcher — watchdog tail of notify_events.jsonl + channel fan-out.

Runs in the dashboard launcher process (single consumer per host). Tracks a
byte offset; reads from EOF on start so previously-dispatched events do not
re-fire on dispatcher restart.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from tradelab.live import live_config, notify
from tradelab.live.notify_channels import CHANNELS


class _EventHandler(FileSystemEventHandler):
    def __init__(self, dispatcher: "NotifyDispatcher"):
        self._d = dispatcher

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).resolve() == self._d.events_path.resolve():
            self._d._drain()


class NotifyDispatcher:
    def __init__(self, events_path: Optional[Path] = None):
        self.events_path = events_path or notify.NOTIFY_EVENTS_PATH
        self._offset = 0
        self._lock = threading.Lock()
        self._observer: Optional[PollingObserver] = None

    def start(self) -> None:
        # Make sure file exists before observer attaches (avoids first-modify-after-create races)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        # Read-from-EOF: skip past any pre-existing events
        with self._lock:
            self._offset = self.events_path.stat().st_size

        self._observer = PollingObserver(timeout=0.2)
        self._observer.schedule(_EventHandler(self), str(self.events_path.parent), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

    def _drain(self) -> None:
        """Read all bytes appended since last drain, dispatch one event per line."""
        with self._lock:
            try:
                with open(self.events_path, "rb") as f:
                    f.seek(self._offset)
                    new_bytes = f.read()
                    self._offset = f.tell()
            except OSError as e:
                print(f"[notify_dispatcher] read failed: {type(e).__name__}: {e}", file=sys.stderr)
                return

        if not new_bytes:
            return
        for raw_line in new_bytes.decode("utf-8", errors="replace").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as e:
                print(f"[notify_dispatcher] bad JSON: {e}: {raw_line!r}", file=sys.stderr)
                continue
            self._dispatch(event)

    def _dispatch(self, event: dict) -> None:
        cfg = live_config.get()
        severity = event.get("severity", "info")
        title = event.get("title", "")
        body = event.get("body", "")
        explicit = event.get("channels")

        enabled = set(cfg["notifications"]["enabled_channels"])
        if explicit is not None:
            requested = set(explicit)
        else:
            requested = set(cfg["notifications"]["severity_routing"].get(severity, []))

        for ch_name in sorted(requested & enabled):
            send_fn = CHANNELS.get(ch_name)
            if send_fn is None:
                print(f"[notify_dispatcher] no such channel: {ch_name}", file=sys.stderr)
                continue
            try:
                send_fn(severity, title, body, cfg)
            except Exception as e:
                print(f"[notify_dispatcher] {ch_name} raised: {type(e).__name__}: {e}", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_dispatcher.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_dispatcher.py src/tradelab/live/notify_channels/__init__.py tests/live/test_notify_dispatcher.py
git commit -m "$(cat <<'EOF'
feat(live): notify_dispatcher.py with watchdog tail + channel isolation

PollingObserver-based tail of notify_events.jsonl. Read-from-EOF on start
so dispatcher restart does not re-fire historical events. Per-event channel
resolution: explicit override > routing-matrix-by-severity, intersected
with enabled_channels. Each channel send() runs inside try/except so one
failure cannot stop others.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `notify_channels/audible.py` — winsound

**Files:**
- Create: `tradelab/src/tradelab/live/notify_channels/audible.py`
- Modify: `tradelab/tests/live/test_notify_channels.py` (create on first channel; subsequent tasks append)

Plays a system sound. Uses `winsound.PlaySound` if `audible.sound_file` is set + readable; falls back to `winsound.MessageBeep(MB_ICONHAND)` for the CRITICAL severity, `MB_ICONEXCLAMATION` for WARNING, `MB_OK` for INFO. Best-effort: returns False on any failure (does NOT raise).

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/live/test_notify_channels.py`:

```python
"""Per-channel send() tests. One success + one failure-isolation case per channel."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─── audible ─────────────────────────────────────────────────────────


def test_audible_send_falls_back_to_messagebeep_when_no_soundfile(monkeypatch):
    fake_winsound = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    cfg = {"notifications": {"audible": {"sound_file": ""}}}
    ok = send("critical", "T", "B", cfg)
    assert ok is True
    fake_winsound.MessageBeep.assert_called_once()


def test_audible_send_uses_playsound_when_soundfile_set(tmp_path, monkeypatch):
    wav = tmp_path / "panic.wav"
    wav.write_bytes(b"RIFF")
    fake_winsound = MagicMock()
    fake_winsound.SND_FILENAME = 0x20000
    fake_winsound.SND_ASYNC = 0x0001
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    cfg = {"notifications": {"audible": {"sound_file": str(wav)}}}
    ok = send("critical", "T", "B", cfg)
    assert ok is True
    fake_winsound.PlaySound.assert_called_once()


def test_audible_send_returns_false_on_winsound_error(monkeypatch):
    fake_winsound = MagicMock()
    fake_winsound.MessageBeep.side_effect = RuntimeError("audio device unavailable")
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    ok = send("critical", "T", "B", {"notifications": {"audible": {"sound_file": ""}}})
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 3 FAIL with `ModuleNotFoundError: No module named 'tradelab.live.notify_channels.audible'`.

- [ ] **Step 3: Implement `audible.py`**

Create `tradelab/src/tradelab/live/notify_channels/audible.py`:

```python
"""Audible notification channel. Plays a WAV if configured, else MessageBeep."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import winsound  # type: ignore[import-not-found]  # Windows-only stdlib
except ImportError:
    winsound = None  # type: ignore[assignment]

from tradelab.live.notify_channels import register


_BEEP_BY_SEVERITY = {
    "critical": "MB_ICONHAND",
    "warning": "MB_ICONEXCLAMATION",
    "info": "MB_OK",
}


def send(severity: str, title: str, body: str, config: dict) -> bool:
    if winsound is None:
        return False
    try:
        path = config.get("notifications", {}).get("audible", {}).get("sound_file", "")
        if path and Path(path).is_file():
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            const_name = _BEEP_BY_SEVERITY.get(severity, "MB_OK")
            winsound.MessageBeep(getattr(winsound, const_name, winsound.MB_OK))
        return True
    except Exception as e:
        print(f"[notify.audible] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("audible", send)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_channels/audible.py tests/live/test_notify_channels.py
git commit -m "$(cat <<'EOF'
feat(live): audible notify channel via winsound

Plays configured WAV via PlaySound(SND_ASYNC), or falls back to
MessageBeep with severity-mapped icon. Returns False (not raises) on any
winsound error so dispatcher isolation is preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `notify_channels/windows_toast.py` — plyer

**Files:**
- Create: `tradelab/src/tradelab/live/notify_channels/windows_toast.py`
- Modify: `tradelab/tests/live/test_notify_channels.py` (append)

Uses `plyer.notification.notify` for cross-platform toast. Slice 4 only ships Windows but the dep is platform-agnostic. Title format: `[CRITICAL] guardrail_blocked` style; body is the event body. Best-effort.

- [ ] **Step 1: Append the failing tests**

Append to `tradelab/tests/live/test_notify_channels.py`:

```python
# ─── windows_toast ───────────────────────────────────────────────────


def test_windows_toast_send_calls_plyer_notify(monkeypatch):
    fake_plyer_notification = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", fake_plyer_notification)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("critical", "Guardrail blocked", "AAPL cooldown_active", {})
    assert ok is True
    fake_plyer_notification.notify.assert_called_once()
    kwargs = fake_plyer_notification.notify.call_args.kwargs
    assert "[CRITICAL]" in kwargs["title"]
    assert "Guardrail blocked" in kwargs["title"]
    assert kwargs["message"] == "AAPL cooldown_active"
    assert kwargs["app_name"] == "tradelab"


def test_windows_toast_send_returns_false_on_plyer_error(monkeypatch):
    fake = MagicMock()
    fake.notify.side_effect = RuntimeError("notification system unavailable")
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", fake)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("warning", "T", "B", {})
    assert ok is False


def test_windows_toast_no_op_when_plyer_unimportable(monkeypatch):
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", None)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("info", "T", "B", {})
    assert ok is False
```

- [ ] **Step 2: Run new tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v -k windows_toast`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `windows_toast.py`**

Create `tradelab/src/tradelab/live/notify_channels/windows_toast.py`:

```python
"""Windows toast notification channel via plyer."""
from __future__ import annotations

import sys

try:
    from plyer import notification  # type: ignore[import-not-found]
except Exception:
    notification = None  # type: ignore[assignment]

from tradelab.live.notify_channels import register


def send(severity: str, title: str, body: str, config: dict) -> bool:
    if notification is None:
        return False
    try:
        notification.notify(
            title=f"[{severity.upper()}] {title}",
            message=body,
            app_name="tradelab",
            timeout=10,
        )
        return True
    except Exception as e:
        print(f"[notify.windows_toast] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("windows_toast", send)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 6 passed (3 audible + 3 windows_toast).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_channels/windows_toast.py tests/live/test_notify_channels.py
git commit -m "$(cat <<'EOF'
feat(live): windows_toast notify channel via plyer

Best-effort wrapper around plyer.notification.notify. Title formatted
'[SEVERITY] title'. Returns False on plyer import failure or any toast
exception so dispatcher isolation holds.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `notify_channels/ntfy.py` — urllib.request POST

**Files:**
- Create: `tradelab/src/tradelab/live/notify_channels/ntfy.py`
- Modify: `tradelab/tests/live/test_notify_channels.py` (append)

POSTs to `<ntfy.server>/<ntfy.topic>` with body as the message and `Title` + `Priority` headers. Priority: critical → 5 (max), warning → 4, info → 3. 3-second timeout. No-op when topic is empty.

- [ ] **Step 1: Append the failing tests**

```python
# ─── ntfy ────────────────────────────────────────────────────────────


def test_ntfy_send_posts_to_topic_url(monkeypatch):
    fake_urlopen = MagicMock()
    fake_urlopen.return_value.__enter__.return_value.status = 200
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    cfg = {"notifications": {"ntfy": {"topic": "tradelab-test", "server": "https://ntfy.sh"}}}
    ok = send("critical", "Boom", "AAPL guardrail blocked", cfg)
    assert ok is True
    req = fake_urlopen.call_args[0][0]
    assert req.full_url == "https://ntfy.sh/tradelab-test"
    assert req.data == b"AAPL guardrail blocked"
    assert req.headers["Title"] == "Boom"
    assert req.headers["Priority"] == "5"


def test_ntfy_send_no_op_when_topic_empty(monkeypatch):
    fake_urlopen = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    ok = send("critical", "T", "B", {"notifications": {"ntfy": {"topic": "", "server": "https://ntfy.sh"}}})
    assert ok is False
    fake_urlopen.assert_not_called()


def test_ntfy_send_returns_false_on_http_error(monkeypatch):
    from urllib.error import URLError
    fake_urlopen = MagicMock(side_effect=URLError("connection refused"))
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    cfg = {"notifications": {"ntfy": {"topic": "x", "server": "https://ntfy.sh"}}}
    ok = send("info", "T", "B", cfg)
    assert ok is False
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v -k ntfy`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ntfy.py`**

```python
"""ntfy.sh notification channel via stdlib urllib.request."""
from __future__ import annotations

import sys
from urllib.request import Request, urlopen

from tradelab.live.notify_channels import register


_PRIORITY_BY_SEVERITY = {"critical": "5", "warning": "4", "info": "3"}


def send(severity: str, title: str, body: str, config: dict) -> bool:
    ntfy_cfg = config.get("notifications", {}).get("ntfy", {})
    topic = ntfy_cfg.get("topic", "").strip()
    if not topic:
        return False
    server = ntfy_cfg.get("server", "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    req = Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": _PRIORITY_BY_SEVERITY.get(severity, "3"),
        },
    )
    try:
        with urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"[notify.ntfy] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("ntfy", send)
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_channels/ntfy.py tests/live/test_notify_channels.py
git commit -m "$(cat <<'EOF'
feat(live): ntfy.sh notify channel via urllib.request

Single POST with Title + Priority headers. 3s timeout. No-op when topic
is empty. Severity → priority: critical=5, warning=4, info=3. Returns
False on URLError or non-2xx response.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `notify_channels/email.py` — smtplib

**Files:**
- Create: `tradelab/src/tradelab/live/notify_channels/email.py`
- Modify: `tradelab/tests/live/test_notify_channels.py` (append)

SMTP STARTTLS to `smtp.host:smtp.port`, login with `smtp.user/password`, send a single plaintext message from `from_address` to `to_address`. 10-second connect timeout. No-op when host or to_address is empty.

- [ ] **Step 1: Append the failing tests**

```python
# ─── email ───────────────────────────────────────────────────────────


def test_email_send_uses_starttls_login_and_sendmail(monkeypatch):
    smtp_instance = MagicMock()
    smtp_class = MagicMock(return_value=smtp_instance)
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", smtp_class)
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587,
        "user": "u@e.com", "password": "pw",
        "from_address": "u@e.com", "to_address": "amit@e.com",
    }}}
    ok = send("critical", "Boom", "Body line", cfg)
    assert ok is True
    smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("u@e.com", "pw")
    smtp_instance.sendmail.assert_called_once()
    args = smtp_instance.sendmail.call_args[0]
    assert args[0] == "u@e.com"
    assert args[1] == ["amit@e.com"]
    assert "Boom" in args[2]
    assert "Body line" in args[2]


def test_email_send_no_op_when_host_empty(monkeypatch):
    smtp_class = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", smtp_class)
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {"host": "", "to_address": "x@e.com"}}}
    ok = send("info", "T", "B", cfg)
    assert ok is False
    smtp_class.assert_not_called()


def test_email_send_returns_false_on_smtp_exception(monkeypatch):
    import smtplib as real_smtplib
    smtp_instance = MagicMock()
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    smtp_instance.login.side_effect = real_smtplib.SMTPAuthenticationError(535, b"nope")
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", MagicMock(return_value=smtp_instance))
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587, "user": "u", "password": "x",
        "from_address": "u@e.com", "to_address": "amit@e.com",
    }}}
    ok = send("warning", "T", "B", cfg)
    assert ok is False
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v -k email`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `email.py`**

```python
"""Email notification channel via stdlib smtplib (STARTTLS)."""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

from tradelab.live.notify_channels import register


def send(severity: str, title: str, body: str, config: dict) -> bool:
    smtp_cfg = config.get("notifications", {}).get("smtp", {})
    host = smtp_cfg.get("host", "").strip()
    to_addr = smtp_cfg.get("to_address", "").strip()
    if not host or not to_addr:
        return False
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg.get("user", "")
    password = smtp_cfg.get("password", "")
    from_addr = smtp_cfg.get("from_address", user)

    msg = EmailMessage()
    msg["Subject"] = f"[tradelab {severity.upper()}] {title}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as conn:
            conn.starttls()
            if user:
                conn.login(user, password)
            conn.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[notify.email] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("email", send)
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_channels/email.py tests/live/test_notify_channels.py
git commit -m "$(cat <<'EOF'
feat(live): email notify channel via smtplib STARTTLS

10s connect timeout; no-op when host or to_address is empty. Subject
formatted '[tradelab SEVERITY] title'. Returns False on any SMTP
exception (auth failure, connection refused, etc).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `notify_channels/browser.py` + `get_notify_broadcaster()` accessor

**Files:**
- Create: `tradelab/src/tradelab/live/notify_channels/browser.py`
- Modify: `tradelab/src/tradelab/web/__init__.py` — add `_notify_broadcaster` + `get_notify_broadcaster()`
- Modify: `tradelab/tests/live/test_notify_channels.py` (append)

A second `Broadcaster` instance dedicated to notification SSE. The browser channel calls `get_notify_broadcaster().broadcast({...})`. Connected dashboard tabs receive the event over `/tradelab/live/notify-stream` (handler added in T10).

- [ ] **Step 1: Append the failing tests**

```python
# ─── browser ─────────────────────────────────────────────────────────


def test_browser_send_calls_notify_broadcaster_broadcast(monkeypatch):
    fake_bc = MagicMock()
    fake_bc.broadcast = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.browser.get_notify_broadcaster", lambda: fake_bc)
    from tradelab.live.notify_channels.browser import send
    ok = send("warning", "Title", "Body", {})
    assert ok is True
    fake_bc.broadcast.assert_called_once()
    payload = fake_bc.broadcast.call_args[0][0]
    assert payload["severity"] == "warning"
    assert payload["title"] == "Title"
    assert payload["body"] == "Body"
    assert "ts" in payload


def test_browser_send_returns_false_on_broadcaster_error(monkeypatch):
    fake_bc = MagicMock()
    fake_bc.broadcast.side_effect = RuntimeError("no subscribers? actually any raise")
    monkeypatch.setattr("tradelab.live.notify_channels.browser.get_notify_broadcaster", lambda: fake_bc)
    from tradelab.live.notify_channels.browser import send
    ok = send("info", "T", "B", {})
    assert ok is False


def test_get_notify_broadcaster_is_a_singleton():
    from tradelab.web import get_notify_broadcaster
    assert get_notify_broadcaster() is get_notify_broadcaster()
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v -k "browser or notify_broadcaster"`
Expected: FAIL with `ModuleNotFoundError` and `ImportError: cannot import name 'get_notify_broadcaster'`.

- [ ] **Step 3a: Add accessor to `tradelab/web/__init__.py`**

Read `tradelab/src/tradelab/web/__init__.py` first to find the existing pattern. Then add directly under the existing `_broadcaster` / `get_broadcaster()` (around lines 16-29):

```python
_notify_broadcaster = Broadcaster()


def get_notify_broadcaster() -> Broadcaster:
    return _notify_broadcaster
```

- [ ] **Step 3b: Implement `browser.py`**

Create `tradelab/src/tradelab/live/notify_channels/browser.py`:

```python
"""Browser notification channel — pushes event onto the notify SSE Broadcaster."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from tradelab.live.notify_channels import register
from tradelab.web import get_notify_broadcaster


def send(severity: str, title: str, body: str, config: dict) -> bool:
    try:
        get_notify_broadcaster().broadcast({
            "ts": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "title": title,
            "body": body,
        })
        return True
    except Exception as e:
        print(f"[notify.browser] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("browser", send)
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_notify_channels.py -v`
Expected: 15 passed (3 per channel × 5 channels).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/notify_channels/browser.py src/tradelab/web/__init__.py tests/live/test_notify_channels.py
git commit -m "$(cat <<'EOF'
feat(live,web): browser notify channel + dedicated Broadcaster

Adds a second Broadcaster instance to tradelab.web (mirrors existing
job-tracker broadcaster), accessible via get_notify_broadcaster(). The
browser channel pushes {ts, severity, title, body} onto it. SSE endpoint
that streams these events to the dashboard lands in T10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `handle_notify_sse()` + launcher route registration + dispatcher boot

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` — add `handle_notify_sse(wfile)` (mirror `handle_sse` at line 724)
- Modify: `launch_dashboard.py` (parent repo) — add `/tradelab/live/notify-stream` route to `do_GET`; instantiate + start `NotifyDispatcher` after handlers import succeeds

This is the cross-process bridge: dashboard process tails `notify_events.jsonl` (started here) AND owns the SSE Broadcaster that browser tabs connect to.

- [ ] **Step 1: Add `handle_notify_sse` to `handlers.py`**

Read `tradelab/src/tradelab/web/handlers.py:724-764` (`handle_sse` for the pattern). Insert directly below it:

```python
def handle_notify_sse(wfile) -> None:
    """SSE endpoint for /tradelab/live/notify-stream.

    Subscribes to the notify broadcaster (separate from the job-tracker
    broadcaster). No initial-state replay — notifications are ephemeral;
    a new browser tab only sees events emitted after subscription.
    """
    from tradelab.web import get_notify_broadcaster

    bc = get_notify_broadcaster()
    # Pass an empty list (not None) so the spec §6.3 retry hint is sent
    token = bc.subscribe(wfile, initial_state=[])
    try:
        import time
        while bc.is_subscribed(token):
            time.sleep(1.0)
    finally:
        bc.unsubscribe(token)
```

- [ ] **Step 2: Add the route + dispatcher boot to `launch_dashboard.py`**

Read `launch_dashboard.py` to find: (a) the `do_GET` dispatcher block that handles `/tradelab/jobs/stream`, (b) the existing `_handlers` import block (around lines 54-68 per earlier inspection).

Insert into `do_GET`, near the existing `/tradelab/jobs/stream` branch:

```python
            if self.path == "/tradelab/live/notify-stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                _handlers.handle_notify_sse(self.wfile)
                return
```

Insert after the successful `_handlers` import (around line 68) — the dispatcher boots once per process, before the HTTP server starts:

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

- [ ] **Step 3: Smoke the SSE endpoint manually**

Restart dashboard:
```bash
netstat -ano | grep ":8877" | grep LISTENING | head -1
powershell -Command "Stop-Process -Id <PID> -Force"
cd C:/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py
```

In a second terminal:
```bash
curl -N http://127.0.0.1:8877/tradelab/live/notify-stream &
sleep 1
PYTHONPATH=C:/TradingScripts/tradelab/src python -c "from tradelab.live import notify; from tradelab.live.notify import Severity; notify.notify(Severity.INFO, 'Smoke', 'launcher SSE works')"
sleep 2
```

Expected curl output:
```
retry: 3000

data: {"ts": "2026-04-25T...", "severity": "info", "title": "Smoke", "body": "launcher SSE works"}
```

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py
git commit -m "$(cat <<'EOF'
feat(web): handle_notify_sse() — Slice 4 SSE endpoint handler

Mirrors handle_sse for the notify broadcaster. No initial-state replay
since notifications are ephemeral — new tabs only see events emitted
after they subscribe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
cd C:/TradingScripts
git add launch_dashboard.py
git commit -m "$(cat <<'EOF'
feat(launcher): wire /tradelab/live/notify-stream + boot notify_dispatcher

Adds the SSE route to do_GET, and starts NotifyDispatcher once at boot
so the dashboard process is the single consumer of notify_events.jsonl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: GET + PATCH `/tradelab/live/config` endpoints (with shared validation)

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` — add `_handle_live_config_get`, `_handle_live_config_patch`, `_ALLOWED_LIVE_CONFIG_PATHS`, `_validate_live_config_payload`
- Modify: `launch_dashboard.py` — add route dispatch
- Create: `tradelab/tests/web/test_live_config_handlers.py`

GET returns the masked config. PATCH accepts a partial deep-merge payload, validates allowed paths + types, persists, and reloads the in-memory cache so the dispatcher sees the change immediately.

- [ ] **Step 1: Write the failing tests**

Create `tradelab/tests/web/test_live_config_handlers.py`:

```python
"""Handlers for GET/PATCH /tradelab/live/config."""
from __future__ import annotations

import json

import pytest

from tradelab.live import live_config
from tradelab.web import handlers


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    p = tmp_path / "live_config.json"
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", p)
    live_config.reload()
    yield p


def test_get_live_config_masks_smtp_password():
    live_config.update({"notifications": {"smtp": {"password": "supersecret"}}})
    body, status = handlers.handle_live_config_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"]["notifications"]["smtp"]["password"] == "******"


def test_get_live_config_returns_defaults_on_first_call():
    body, status = handlers.handle_live_config_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["data"]["notifications"]["enabled_channels"] == ["browser"]


def test_patch_live_config_persists_partial_payload():
    body, status = handlers.handle_live_config_patch({
        "notifications": {"ntfy": {"topic": "tradelab-amit-7g3k2x"}}
    })
    assert status == 200
    cfg = live_config.get()
    assert cfg["notifications"]["ntfy"]["topic"] == "tradelab-amit-7g3k2x"
    assert cfg["notifications"]["ntfy"]["server"] == "https://ntfy.sh"  # untouched


def test_patch_live_config_ignores_masked_password():
    live_config.update({"notifications": {"smtp": {"password": "real-pw"}}})
    body, status = handlers.handle_live_config_patch({
        "notifications": {"smtp": {"password": "******", "host": "smtp.foo.com"}}
    })
    assert status == 200
    cfg = live_config.get()
    assert cfg["notifications"]["smtp"]["password"] == "real-pw"  # preserved
    assert cfg["notifications"]["smtp"]["host"] == "smtp.foo.com"  # updated


def test_patch_live_config_rejects_unknown_top_level_key():
    body, status = handlers.handle_live_config_patch({"experimental_thing": True})
    assert status == 400
    assert "unknown" in json.loads(body)["error"].lower()


def test_patch_live_config_rejects_non_dict_payload():
    body, status = handlers.handle_live_config_patch("not a dict")
    assert status == 400


def test_patch_live_config_validates_max_exposure_pct_range():
    body, status = handlers.handle_live_config_patch({"guardrails": {"max_exposure_pct": 1.5}})
    assert status == 400
    assert "max_exposure_pct" in json.loads(body)["error"]


def test_patch_live_config_validates_severity_routing_keys():
    body, status = handlers.handle_live_config_patch({"notifications": {"severity_routing": {"unknown_severity": ["browser"]}}})
    assert status == 400


def test_test_notification_endpoint_writes_to_notify_events(tmp_path, monkeypatch):
    from tradelab.live import notify
    events_path = tmp_path / "notify_events.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", events_path)
    body, status = handlers.handle_test_notification({"channel": "browser", "severity": "info"})
    assert status == 200
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["channels"] == ["browser"]
    assert event["severity"] == "info"


def test_test_notification_rejects_unknown_channel():
    body, status = handlers.handle_test_notification({"channel": "carrier_pigeon", "severity": "critical"})
    assert status == 400
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/web/test_live_config_handlers.py -v`
Expected: All FAIL with `AttributeError: module 'tradelab.web.handlers' has no attribute 'handle_live_config_get'` etc.

- [ ] **Step 3: Implement the handlers + validators in `handlers.py`**

Add near the bottom of `tradelab/src/tradelab/web/handlers.py`, after the existing `_validate_patch_card_payload`:

```python
# ─── Validation for PATCH /tradelab/live/config ──────────────────────

_ALLOWED_LIVE_CONFIG_TOP_LEVEL = {
    "schema_version", "notifications", "guardrails", "silence", "email_digest",
}
_ALLOWED_NOTIFICATIONS_KEYS = {
    "enabled_channels", "severity_routing", "ntfy", "smtp", "audible",
}
_ALLOWED_CHANNELS = {"browser", "windows_toast", "audible", "ntfy", "email"}
_ALLOWED_SEVERITIES = {"critical", "warning", "info"}


def _validate_live_config_payload(payload) -> Optional[str]:
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    unknown = set(payload.keys()) - _ALLOWED_LIVE_CONFIG_TOP_LEVEL
    if unknown:
        return f"unknown top-level field: {sorted(unknown)[0]}"
    notif = payload.get("notifications", {})
    if not isinstance(notif, dict):
        return "notifications must be an object"
    unknown = set(notif.keys()) - _ALLOWED_NOTIFICATIONS_KEYS
    if unknown:
        return f"unknown notifications field: {sorted(unknown)[0]}"
    if "enabled_channels" in notif:
        ec = notif["enabled_channels"]
        if not isinstance(ec, list) or any(c not in _ALLOWED_CHANNELS for c in ec):
            return f"enabled_channels must be a subset of {sorted(_ALLOWED_CHANNELS)}"
    if "severity_routing" in notif:
        sr = notif["severity_routing"]
        if not isinstance(sr, dict):
            return "severity_routing must be an object"
        for sev, chans in sr.items():
            if sev not in _ALLOWED_SEVERITIES:
                return f"unknown severity: {sev}"
            if not isinstance(chans, list) or any(c not in _ALLOWED_CHANNELS for c in chans):
                return f"severity_routing[{sev}] must be a list of channel names"
    if "guardrails" in payload:
        g = payload["guardrails"]
        if not isinstance(g, dict):
            return "guardrails must be an object"
        if "max_exposure_pct" in g:
            v = g["max_exposure_pct"]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0.0 < v <= 1.0):
                return "max_exposure_pct must be a number in (0, 1]"
    return None


def handle_live_config_get() -> Tuple[str, int]:
    from tradelab.live import live_config
    return _ok(live_config.mask_passwords(live_config.get())), 200


def handle_live_config_patch(payload) -> Tuple[str, int]:
    err = _validate_live_config_payload(payload)
    if err is not None:
        return _err(err), 400
    # Strip masked passwords (treat "******" as no-change)
    if isinstance(payload, dict):
        smtp = payload.get("notifications", {}).get("smtp", {})
        if isinstance(smtp, dict) and smtp.get("password") == "******":
            smtp.pop("password")
    from tradelab.live import live_config
    live_config.update(payload)
    return _ok(live_config.mask_passwords(live_config.get())), 200


def handle_test_notification(payload) -> Tuple[str, int]:
    if not isinstance(payload, dict):
        return _err("payload must be a JSON object"), 400
    channel = payload.get("channel")
    severity_str = payload.get("severity", "info")
    if channel not in _ALLOWED_CHANNELS:
        return _err(f"channel must be one of {sorted(_ALLOWED_CHANNELS)}"), 400
    if severity_str not in _ALLOWED_SEVERITIES:
        return _err(f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}"), 400
    from tradelab.live import notify
    from tradelab.live.notify import Severity
    notify.notify(
        Severity(severity_str),
        f"Test notification ({channel})",
        f"Synthetic {severity_str} event from settings panel",
        channels={channel},
    )
    return _ok({"channel": channel, "severity": severity_str}), 200
```

- [ ] **Step 4: Wire routes in `launch_dashboard.py`**

Add to `do_GET`:

```python
            if self.path == "/tradelab/live/config":
                body, status = _handlers.handle_live_config_get()
                self._send_json(status, body)
                return
```

Add to `do_PATCH` (or extend `do_POST` if PATCH not yet wired — Slice 2 added PATCH for `/tradelab/cards/<id>` so the method handler exists):

```python
            if self.path == "/tradelab/live/config":
                payload = self._read_json_body()
                body, status = _handlers.handle_live_config_patch(payload)
                self._send_json(status, body)
                return
```

Add to `do_POST`:

```python
            if self.path == "/tradelab/live/config/test-notification":
                payload = self._read_json_body()
                body, status = _handlers.handle_test_notification(payload)
                self._send_json(status, body)
                return
```

- [ ] **Step 5: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/web/test_live_config_handlers.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_live_config_handlers.py
git commit -m "$(cat <<'EOF'
feat(web): GET/PATCH /tradelab/live/config + test-notification endpoints

GET returns masked config; PATCH validates partial payloads (allowed
fields, channel names, severity keys, max_exposure_pct range) and
persists via live_config.update(). Masked password '******' in incoming
PATCH is treated as no-change. test-notification endpoint writes a single
event with explicit channels override.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
cd C:/TradingScripts
git add launch_dashboard.py
git commit -m "$(cat <<'EOF'
feat(launcher): wire /tradelab/live/config GET/PATCH + test-notification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Wire `guardrail_blocked` + `order_failed` → `notify(CRITICAL, ...)` in receiver

**Files:**
- Modify: `tradelab/src/tradelab/live/receiver.py` — call `notify(...)` after each existing `_log_alert` for `guardrail_blocked` / `order_failed`
- Create: `tradelab/tests/live/test_receiver_notify_integration.py`
- Modify: `tradelab/src/tradelab/live/guardrails.py` — replace hardcoded `0.90` in `check_buying_power` with `live_config.get()["guardrails"]["max_exposure_pct"]`

The receiver does not need to know about routing or channels — it only emits `notify(Severity.CRITICAL, title, body)`. The dispatcher (running in dashboard) does the rest. Same for the buying-power max-exposure threshold: receiver reads from `live_config` so the settings-panel slider becomes load-bearing.

- [ ] **Step 1: Write the failing integration tests**

Create `tradelab/tests/live/test_receiver_notify_integration.py`:

```python
"""Receiver-side notify() integration: guardrail_blocked + order_failed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradelab.live import notify, live_config
from tradelab.live.receiver import app


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    notify_events = tmp_path / "notify_events.jsonl"
    cfg_path = tmp_path / "live_config.json"
    cards_path = tmp_path / "cards.json"
    alerts_path = tmp_path / "alerts.jsonl"
    monkeypatch.setattr(notify, "NOTIFY_EVENTS_PATH", notify_events)
    monkeypatch.setattr(live_config, "_LIVE_CONFIG_PATH", cfg_path)
    live_config.reload()

    from tradelab.live import receiver
    from tradelab.live.cards import CardRegistry
    cards_path.write_text(json.dumps({
        "test-aapl": {"card_id": "test-aapl", "status": "enabled", "symbol": "AAPL", "quantity": 1, "secret": "s", "cadence": "intraday", "daily_limit": 1, "cooldown_seconds": 5}
    }), encoding="utf-8")
    monkeypatch.setattr(receiver, "cards", CardRegistry(cards_path))
    monkeypatch.setattr(receiver, "ALERT_LOG", alerts_path)
    yield notify_events


def test_guardrail_blocked_writes_notify_event(_isolated, monkeypatch):
    """Webhook blocked by daily_limit=1 (already fired today) should write a notify event."""
    from tradelab.live import receiver
    # Pre-load runtime state so daily_limit blocks
    from datetime import datetime, timezone
    receiver._card_state["test-aapl"] = receiver.CardRuntimeState(fires_today=1, fire_window_start=datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0))

    client = TestClient(app)
    resp = client.post("/webhook/test-aapl?secret=s", json={"action": "buy", "symbol": "AAPL"})
    assert resp.status_code == 403
    lines = _isolated.read_text(encoding="utf-8").splitlines()
    notify_events = [json.loads(line) for line in lines]
    assert len(notify_events) == 1
    assert notify_events[0]["severity"] == "critical"
    assert "Guardrail blocked" in notify_events[0]["title"]
    assert "test-aapl" in notify_events[0]["body"]
    assert "daily_limit_exceeded" in notify_events[0]["body"]


def test_order_failed_writes_notify_event(_isolated, monkeypatch):
    """Alpaca submit raising should write a CRITICAL notify event."""
    from tradelab.live import receiver
    from unittest.mock import MagicMock
    fake_alpaca = MagicMock()
    fake_alpaca.submit_market_order.side_effect = RuntimeError("alpaca went down")
    monkeypatch.setattr(receiver, "_alpaca_client", lambda: fake_alpaca)
    # Skip guardrails so we reach the submit path
    monkeypatch.setattr(receiver, "evaluate_guardrails", lambda *a, **k: None)
    # Need a price for buying power; monkeypatch _get_last_price
    monkeypatch.setattr(receiver, "_get_last_price", lambda symbol: 100.0)

    client = TestClient(app)
    resp = client.post("/webhook/test-aapl?secret=s", json={"action": "buy", "symbol": "AAPL"})
    assert resp.status_code == 502
    lines = _isolated.read_text(encoding="utf-8").splitlines()
    notify_events = [json.loads(line) for line in lines]
    assert any(ev["severity"] == "critical" and "order failed" in ev["title"].lower() for ev in notify_events)


def test_buying_power_check_reads_max_exposure_from_live_config(_isolated):
    """check_buying_power should consult live_config, not a hardcoded constant."""
    live_config.update({"guardrails": {"max_exposure_pct": 0.5}})
    from tradelab.live.guardrails import check_buying_power
    from unittest.mock import MagicMock
    card = {"card_id": "x", "symbol": "AAPL", "quantity": 100}
    alpaca = MagicMock()
    alpaca.account = MagicMock(buying_power="10000")
    alpaca.open_orders = []
    # Order notional = 100 * 100 = 10000; max_exposure_pct=0.5 → cap=5000 → blocked
    reason = check_buying_power(card, last_price=100.0, alpaca_state=alpaca)
    assert reason is not None
    assert reason.code == "insufficient_buying_power"

    live_config.update({"guardrails": {"max_exposure_pct": 1.0}})
    reason = check_buying_power(card, last_price=100.0, alpaca_state=alpaca)
    assert reason is None  # cap=10000, fits exactly
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_receiver_notify_integration.py -v`
Expected: All FAIL — receiver does not yet call `notify()` and `check_buying_power` still uses a hardcoded threshold.

- [ ] **Step 3: Modify `receiver.py` to emit notify events**

Read current `receiver.py` to find the existing `_log_alert(... "guardrail_blocked" ...)` and `_log_alert(... "order_failed" ...)` call sites. After each call, add a `notify(...)` invocation.

At the top of `receiver.py`, add:
```python
from tradelab.live import notify as _notify
from tradelab.live.notify import Severity
```

After the `guardrail_blocked` log (find the existing call site, post-Slice-3 it returns the 403):
```python
_notify.notify(
    Severity.CRITICAL,
    "Guardrail blocked",
    f"{card_id} {alert_action} {symbol}: {reason.code} — {reason.message}",
)
```

After the `order_failed` log:
```python
_notify.notify(
    Severity.CRITICAL,
    "Alpaca order failed",
    f"{card_id} {alert_action} {symbol} qty={card['quantity']}: {type(exc).__name__}: {exc}",
)
```

(Variable names follow the existing receiver call site — adjust to match locals available there.)

- [ ] **Step 4: Modify `guardrails.py` to read max_exposure from `live_config`**

Read current `tradelab/src/tradelab/live/guardrails.py` to find `check_buying_power`. Replace the hardcoded `0.90` with:

```python
from tradelab.live import live_config
# ...
def check_buying_power(card, last_price, alpaca_state):
    max_exposure_pct = live_config.get()["guardrails"]["max_exposure_pct"]
    # ... rest unchanged, replacing the previous hardcoded 0.90 with max_exposure_pct
```

- [ ] **Step 5: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/test_receiver_notify_integration.py tests/live/test_guardrails.py -v`
Expected: 3 new + all existing guardrail tests still pass (configure live_config to default 0.90 in any guardrail-tests fixture that needs the old behavior).

- [ ] **Step 6: Run the full live suite to catch regressions**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/live/ -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/live/receiver.py src/tradelab/live/guardrails.py tests/live/test_receiver_notify_integration.py
git commit -m "$(cat <<'EOF'
feat(live): wire guardrail_blocked + order_failed into notify(CRITICAL)

Receiver now emits a CRITICAL notify event after each existing
guardrail_blocked / order_failed alerts.jsonl entry. Routing is owned
by the dispatcher; receiver stays dumb. check_buying_power now reads
max_exposure_pct from live_config (was hardcoded 0.90), so the
settings-panel slider becomes load-bearing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Settings panel — HTML markup + CSS

**Files:**
- Modify: `command_center.html` (parent repo) — append `<details id="lt-settings">` after the LT card list, before `#live-trading` close; add CSS for new classes

Sections per spec §7.4: Notifications (channel toggles, severity matrix, ntfy fields, SMTP fields, audible options, test buttons), Silence Detection (multiplier sliders), Position Guardrails (max_exposure_pct slider, default daily_limit, default cooldown_seconds), Email Digest (enabled toggle, send_time).

- [ ] **Step 1: Find the insertion point**

Read `command_center.html` and find the `#live-trading` `<div>` block. Locate the end of the card list area (look for `<div id="lt-cards">` closing, or the bottom of the LT panel before `</div><!-- #live-trading -->`).

- [ ] **Step 2: Add the markup**

Insert after `#lt-cards` and before `#live-trading` close:

```html
<details id="lt-settings" class="lt-settings">
  <summary>⚙ Notification &amp; Safety Settings</summary>

  <section class="lt-settings-section" data-section="notifications">
    <h3>Notifications</h3>

    <div class="lt-settings-group">
      <label>Enabled channels</label>
      <div class="lt-channel-row">
        <label><input type="checkbox" data-config="notifications.enabled_channels" value="browser"> Browser toast</label>
        <button type="button" class="lt-btn-test" data-channel="browser">Test</button>
      </div>
      <div class="lt-channel-row">
        <label><input type="checkbox" data-config="notifications.enabled_channels" value="windows_toast"> Windows toast</label>
        <button type="button" class="lt-btn-test" data-channel="windows_toast">Test</button>
      </div>
      <div class="lt-channel-row">
        <label><input type="checkbox" data-config="notifications.enabled_channels" value="audible"> Audible</label>
        <button type="button" class="lt-btn-test" data-channel="audible">Test</button>
      </div>
      <div class="lt-channel-row">
        <label><input type="checkbox" data-config="notifications.enabled_channels" value="ntfy"> ntfy.sh push</label>
        <button type="button" class="lt-btn-test" data-channel="ntfy">Test</button>
      </div>
      <div class="lt-channel-row">
        <label><input type="checkbox" data-config="notifications.enabled_channels" value="email"> Email</label>
        <button type="button" class="lt-btn-test" data-channel="email">Test</button>
      </div>
    </div>

    <div class="lt-settings-group">
      <label>Severity routing</label>
      <table class="lt-severity-matrix">
        <thead><tr><th></th><th>Browser</th><th>Win toast</th><th>Audible</th><th>ntfy</th><th>Email</th></tr></thead>
        <tbody>
          <tr><th>CRITICAL</th>
            <td><input type="checkbox" data-config="notifications.severity_routing.critical" value="browser"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.critical" value="windows_toast"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.critical" value="audible"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.critical" value="ntfy"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.critical" value="email"></td>
          </tr>
          <tr><th>WARNING</th>
            <td><input type="checkbox" data-config="notifications.severity_routing.warning" value="browser"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.warning" value="windows_toast"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.warning" value="audible"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.warning" value="ntfy"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.warning" value="email"></td>
          </tr>
          <tr><th>INFO</th>
            <td><input type="checkbox" data-config="notifications.severity_routing.info" value="browser"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.info" value="windows_toast"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.info" value="audible"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.info" value="ntfy"></td>
            <td><input type="checkbox" data-config="notifications.severity_routing.info" value="email"></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="lt-settings-group">
      <label>ntfy.sh</label>
      <input type="text" data-config="notifications.ntfy.topic" placeholder="topic (e.g. tradelab-amit-7g3k2x)">
      <input type="text" data-config="notifications.ntfy.server" placeholder="server URL (default https://ntfy.sh)">
    </div>

    <div class="lt-settings-group">
      <label>Email (SMTP)</label>
      <input type="text" data-config="notifications.smtp.host" placeholder="host (e.g. smtp.gmail.com)">
      <input type="number" data-config="notifications.smtp.port" placeholder="port (587)">
      <input type="text" data-config="notifications.smtp.user" placeholder="user">
      <input type="password" data-config="notifications.smtp.password" placeholder="password (masked on read)">
      <input type="text" data-config="notifications.smtp.from_address" placeholder="from address">
      <input type="text" data-config="notifications.smtp.to_address" placeholder="to address">
    </div>

    <div class="lt-settings-group">
      <label>Audible</label>
      <input type="number" data-config="notifications.audible.volume_pct" min="0" max="100" placeholder="volume %">
      <input type="text" data-config="notifications.audible.sound_file" placeholder="WAV file path (blank = system beep)">
    </div>
  </section>

  <section class="lt-settings-section" data-section="silence">
    <h3>Silence detection</h3>
    <div class="lt-settings-group">
      <label>Intraday multiplier (× trading days)</label>
      <input type="range" min="1" max="10" data-config="silence.multipliers.intraday">
      <span class="lt-slider-value"></span>
    </div>
    <div class="lt-settings-group">
      <label>Daily multiplier (× trading days)</label>
      <input type="range" min="1" max="20" data-config="silence.multipliers.daily">
      <span class="lt-slider-value"></span>
    </div>
    <div class="lt-settings-group">
      <label>Weekly multiplier (× calendar days)</label>
      <input type="range" min="7" max="60" data-config="silence.multipliers.weekly">
      <span class="lt-slider-value"></span>
    </div>
  </section>

  <section class="lt-settings-section" data-section="guardrails">
    <h3>Position guardrails</h3>
    <div class="lt-settings-group">
      <label>Max in-flight exposure (% of buying power)</label>
      <input type="range" min="0.1" max="1.0" step="0.05" data-config="guardrails.max_exposure_pct">
      <span class="lt-slider-value"></span>
    </div>
    <div class="lt-settings-group">
      <label>Default daily order limit</label>
      <input type="number" min="0" max="100" data-config="guardrails.default_daily_limit">
    </div>
    <div class="lt-settings-group">
      <label>Default cooldown seconds</label>
      <input type="number" min="0" max="3600" data-config="guardrails.default_cooldown_seconds">
    </div>
  </section>

  <section class="lt-settings-section" data-section="email_digest">
    <h3>Daily email digest</h3>
    <div class="lt-settings-group">
      <label><input type="checkbox" data-config="email_digest.enabled"> Send daily summary email</label>
    </div>
    <div class="lt-settings-group">
      <label>Send time (HH:MM ET)</label>
      <input type="text" data-config="email_digest.send_time" placeholder="16:00">
    </div>
  </section>

  <div class="lt-settings-actions">
    <button type="button" id="lt-settings-save" class="lt-btn-primary">Save settings</button>
    <span id="lt-settings-status" class="lt-settings-status"></span>
  </div>
</details>
```

- [ ] **Step 3: Add CSS**

In the existing `<style>` block, append:

```css
.lt-settings { margin-top: 24px; padding: 16px; background: #1a1a1a; border-radius: 6px; }
.lt-settings > summary { cursor: pointer; font-size: 14px; font-weight: 600; padding: 6px 0; user-select: none; }
.lt-settings-section { margin: 16px 0; padding-top: 12px; border-top: 1px solid #2a2a2a; }
.lt-settings-section h3 { font-size: 13px; margin: 0 0 8px 0; color: #aaa; text-transform: uppercase; letter-spacing: 0.05em; }
.lt-settings-group { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.lt-settings-group > label { font-size: 12px; color: #ccc; }
.lt-settings-group input[type="text"],
.lt-settings-group input[type="password"],
.lt-settings-group input[type="number"] { padding: 6px 8px; background: #0d0d0d; border: 1px solid #333; color: #eee; border-radius: 4px; }
.lt-settings-group input[type="range"] { width: 200px; }
.lt-channel-row { display: flex; align-items: center; gap: 12px; padding: 4px 0; }
.lt-btn-test { padding: 3px 10px; font-size: 11px; background: #2a2a2a; border: 1px solid #444; color: #ccc; border-radius: 3px; cursor: pointer; }
.lt-btn-test:hover { background: #333; }
.lt-severity-matrix { width: auto; border-collapse: collapse; }
.lt-severity-matrix th, .lt-severity-matrix td { padding: 4px 12px; font-size: 12px; text-align: center; }
.lt-severity-matrix tbody th { text-align: left; color: #ccc; }
.lt-slider-value { font-size: 12px; color: #888; min-width: 40px; display: inline-block; }
.lt-settings-actions { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.lt-btn-primary { padding: 6px 16px; background: #1a4a8a; border: 1px solid #2a5aa0; color: #fff; border-radius: 4px; cursor: pointer; }
.lt-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.lt-settings-status { font-size: 12px; color: #888; }
.lt-settings-status.success { color: #4caf50; }
.lt-settings-status.error { color: #f44336; }

/* Toast container injected by LT.subscribeBrowserToasts */
#lt-toast-container { position: fixed; top: 16px; right: 16px; display: flex; flex-direction: column; gap: 8px; z-index: 9999; pointer-events: none; }
.lt-toast { padding: 12px 16px; background: #1a1a1a; border-left: 4px solid #888; border-radius: 4px; max-width: 360px; pointer-events: auto; box-shadow: 0 2px 12px rgba(0,0,0,0.4); animation: lt-toast-in 0.2s ease-out; }
.lt-toast.critical { border-left-color: #f44336; }
.lt-toast.warning  { border-left-color: #ff9800; }
.lt-toast.info     { border-left-color: #2196f3; }
.lt-toast .lt-toast-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; color: #fff; }
.lt-toast .lt-toast-body  { font-size: 12px; color: #ccc; }
.lt-toast .lt-toast-close { float: right; cursor: pointer; color: #666; margin-left: 8px; }
@keyframes lt-toast-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
```

- [ ] **Step 4: Visual smoke**

Reload the dashboard at http://127.0.0.1:8877. Click the Live Trading tab. Scroll to the bottom. The `<details>` should be collapsed. Click to expand — all sections render; checkboxes and inputs are present (but unwired — that's T14).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
ui(command-center): settings panel markup + CSS for Live Trading tab

Collapsed-by-default <details id="lt-settings"> at bottom of #live-trading.
Sections: Notifications (channel toggles + severity matrix + ntfy/SMTP
fields + audible), Silence detection, Position guardrails, Email digest.
Includes #lt-toast-container for the SSE-driven toast UI (JS in T14).
All controls use data-config="dotted.path" so JS can build the PATCH
payload by walking the DOM.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Settings panel — JS (loadSettings / saveSettings / testChannel / subscribeBrowserToasts)

**Files:**
- Modify: `command_center.html` — extend the existing `LT` IIFE at line 4298

Four new methods added to LT. Settings load on tab activation; save POSTs only changed fields; test buttons fire single-channel events; SSE subscriber renders toasts.

- [ ] **Step 1: Find the IIFE close**

Read `command_center.html` around line 4298 (`LT = (() => { ... })()`) to find the `return { ... }` block + closing `})();`.

- [ ] **Step 2: Add the four methods inside the IIFE before the return block**

```javascript
async function loadSettings() {
  const res = await fetch("/tradelab/live/config");
  const env = await res.json();
  if (env.error) { setSettingsStatus(env.error, "error"); return; }
  const cfg = env.data;
  document.querySelectorAll('#lt-settings [data-config]').forEach(el => {
    const path = el.dataset.config;
    const value = getByPath(cfg, path);
    if (el.type === "checkbox") {
      // Two flavors: list-membership (data-config + value attr) or boolean leaf
      if (el.hasAttribute("value")) {
        el.checked = Array.isArray(value) && value.includes(el.value);
      } else {
        el.checked = !!value;
      }
    } else if (el.type === "range" || el.type === "number") {
      el.value = value ?? "";
      const span = el.parentElement.querySelector(".lt-slider-value");
      if (span) span.textContent = String(value ?? "");
      el.addEventListener("input", () => {
        if (span) span.textContent = el.value;
      });
    } else {
      el.value = value ?? "";
    }
  });
}

async function saveSettings() {
  const btn = document.getElementById("lt-settings-save");
  btn.disabled = true;
  setSettingsStatus("Saving…", "");
  try {
    const payload = {};
    document.querySelectorAll('#lt-settings [data-config]').forEach(el => {
      const path = el.dataset.config;
      let v;
      if (el.type === "checkbox" && el.hasAttribute("value")) {
        // List-membership: gather all sibling checkboxes for this path
        const siblings = document.querySelectorAll(`#lt-settings [data-config="${path}"]`);
        v = Array.from(siblings).filter(s => s.checked).map(s => s.value);
      } else if (el.type === "checkbox") {
        v = el.checked;
      } else if (el.type === "number" || el.type === "range") {
        v = el.value === "" ? null : Number(el.value);
      } else {
        v = el.value;
      }
      // Only include passwords if they're not the masked sentinel
      if (path === "notifications.smtp.password" && v === "******") return;
      setByPath(payload, path, v);
    });
    // Dedupe: list-membership paths get hit once per checkbox
    const res = await fetch("/tradelab/live/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const env = await res.json();
    if (env.error) {
      setSettingsStatus(`Save failed: ${env.error}`, "error");
    } else {
      setSettingsStatus("Settings saved", "success");
      setTimeout(() => setSettingsStatus("", ""), 3000);
    }
  } catch (e) {
    setSettingsStatus(`Save failed: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

async function testChannel(channel, severity = "critical") {
  const res = await fetch("/tradelab/live/config/test-notification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel, severity }),
  });
  const env = await res.json();
  if (env.error) {
    setSettingsStatus(`Test ${channel} failed: ${env.error}`, "error");
  } else {
    setSettingsStatus(`Test event sent to ${channel}`, "success");
    setTimeout(() => setSettingsStatus("", ""), 3000);
  }
}

let _toastSse = null;
function subscribeBrowserToasts() {
  if (_toastSse) return;  // idempotent
  // Inject container if missing
  if (!document.getElementById("lt-toast-container")) {
    const c = document.createElement("div");
    c.id = "lt-toast-container";
    document.body.appendChild(c);
  }
  _toastSse = new EventSource("/tradelab/live/notify-stream");
  _toastSse.onmessage = (ev) => {
    try {
      const event = JSON.parse(ev.data);
      renderToast(event);
    } catch (e) {
      console.warn("[lt] bad notify event:", ev.data);
    }
  };
  _toastSse.onerror = () => {
    // EventSource auto-reconnects; just log
    console.warn("[lt] notify SSE disconnected, will retry");
  };
}

function renderToast(event) {
  const container = document.getElementById("lt-toast-container");
  if (!container) return;
  const div = document.createElement("div");
  div.className = `lt-toast ${event.severity}`;
  div.innerHTML = `
    <span class="lt-toast-close">×</span>
    <div class="lt-toast-title">${escapeHtml(event.title || "")}</div>
    <div class="lt-toast-body">${escapeHtml(event.body || "")}</div>
  `;
  div.querySelector(".lt-toast-close").addEventListener("click", () => div.remove());
  container.appendChild(div);
  // Auto-dismiss INFO after 5s, WARNING after 10s; CRITICAL stays until clicked
  const dismissAfter = event.severity === "critical" ? 0 : (event.severity === "warning" ? 10000 : 5000);
  if (dismissAfter > 0) setTimeout(() => div.remove(), dismissAfter);
}

function getByPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setByPath(obj, path, value) {
  const keys = path.split(".");
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (cur[keys[i]] == null || typeof cur[keys[i]] !== "object") cur[keys[i]] = {};
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
}

function setSettingsStatus(msg, kind) {
  const el = document.getElementById("lt-settings-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "lt-settings-status" + (kind ? " " + kind : "");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
```

- [ ] **Step 3: Add to the IIFE return + wire event handlers**

Inside the IIFE return block:

```javascript
return {
  // ... existing methods ...
  loadSettings,
  saveSettings,
  testChannel,
  subscribeBrowserToasts,
};
```

After the IIFE, add boot wiring:

```javascript
// Slice 4 — boot settings panel + browser toasts
document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("lt-settings")) {
    LT.loadSettings();
    LT.subscribeBrowserToasts();
    document.getElementById("lt-settings-save").addEventListener("click", () => LT.saveSettings());
    document.querySelectorAll('#lt-settings .lt-btn-test').forEach(btn => {
      btn.addEventListener("click", () => LT.testChannel(btn.dataset.channel, "critical"));
    });
  }
});
```

- [ ] **Step 4: Manual smoke**

Restart dashboard, reload page, click Live Trading tab, expand settings:
1. All checkboxes / inputs populate from defaults (browser channel checked, severity matrix shows defaults).
2. Click "Test" next to Browser → toast appears top-right.
3. Toggle Audible → click Save → "Settings saved" → reload page → Audible toggle still on.
4. Open browser DevTools network tab → Test Email → no toast appears (Email not configured) but the request returns 200 (event written to JSONL; dispatcher tries email channel which no-ops because host is empty).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "$(cat <<'EOF'
feat(command-center): settings panel JS + browser toast SSE subscriber

Extends LT IIFE with loadSettings/saveSettings/testChannel/
subscribeBrowserToasts. Settings auto-load on DOMContentLoaded; SSE
subscriber connects to /tradelab/live/notify-stream and renders toasts
in #lt-toast-container with severity-coded border + auto-dismiss
(INFO 5s, WARNING 10s, CRITICAL stays until clicked). Save sends a
single PATCH walking [data-config] DOM nodes; masked password is
omitted from the payload to avoid blanking the stored value.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Pin new JS function names + DOM contracts

**Files:**
- Modify: `tradelab/tests/web/test_command_center_html.py`

Mirror the Slice 3 pattern: add the four new LT methods to the existing `_LT_FUNCTIONS` parametrize list, and add a DOM-contract test that asserts presence + structure of `#lt-settings`.

- [ ] **Step 1: Read existing test file to find the parametrize list**

Read `tradelab/tests/web/test_command_center_html.py` to locate the existing pin list and DOM-contract test patterns.

- [ ] **Step 2: Append new test entries**

Add to the existing `_LT_FUNCTIONS` parametrize source list (or equivalent):

```python
"loadSettings",
"saveSettings",
"testChannel",
"subscribeBrowserToasts",
```

Append a new DOM-contract test:

```python
def test_lt_settings_block_present_with_required_sections(html_text):
    """Settings panel block + 4 sections render in the markup."""
    assert 'id="lt-settings"' in html_text
    for section in ("notifications", "silence", "guardrails", "email_digest"):
        assert f'data-section="{section}"' in html_text


def test_lt_settings_has_test_button_per_channel(html_text):
    for channel in ("browser", "windows_toast", "audible", "ntfy", "email"):
        assert f'data-channel="{channel}"' in html_text


def test_lt_settings_severity_matrix_complete(html_text):
    """3 severities × 5 channels = 15 routing checkboxes."""
    import re
    matches = re.findall(r'data-config="notifications\.severity_routing\.(critical|warning|info)" value="(\w+)"', html_text)
    assert len(matches) == 15
    by_sev = {}
    for sev, chan in matches:
        by_sev.setdefault(sev, set()).add(chan)
    assert by_sev["critical"] == {"browser", "windows_toast", "audible", "ntfy", "email"}
    assert by_sev["warning"] == {"browser", "windows_toast", "audible", "ntfy", "email"}
    assert by_sev["info"] == {"browser", "windows_toast", "audible", "ntfy", "email"}


def test_lt_settings_save_button_present(html_text):
    assert 'id="lt-settings-save"' in html_text
    assert 'id="lt-settings-status"' in html_text


def test_lt_toast_container_styles_present(html_text):
    """CSS for #lt-toast-container + .lt-toast severity variants must be in the embedded <style>."""
    assert "#lt-toast-container" in html_text
    assert ".lt-toast.critical" in html_text
    assert ".lt-toast.warning" in html_text
    assert ".lt-toast.info" in html_text
```

(`html_text` fixture already exists in the test file from Slice 3.)

- [ ] **Step 3: Run, verify PASS**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest tests/web/test_command_center_html.py -v`
Expected: All existing tests still pass + 5 new tests pass + 4 new function-pin entries pass.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts/tradelab
git add tests/web/test_command_center_html.py
git commit -m "$(cat <<'EOF'
test(web): pin Slice 4 LT settings JS functions + DOM contract

Adds loadSettings/saveSettings/testChannel/subscribeBrowserToasts to
the function-pin parametrize list, plus 5 DOM-contract tests:
#lt-settings + 4 sections, per-channel test buttons, full 3×5 severity
matrix, save button + status span, toast CSS rules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Smoke checklist + done doc + Slice 5 handoff

**Files:**
- Create: parent repo `2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md`

Write the Slice 4 done doc following the Slice 3 pattern. Includes: what shipped, pytest baseline + delta, commit list, smoke checklist (with **Step 0: kill+restart receiver AND dashboard before any other smoke** per the Slice 3 lesson — Slice 4 touches both processes), reviewer-flags-declined block, architectural follow-ups, Slice 5 handoff.

- [ ] **Step 1: Run the full pytest baseline**

Run: `cd C:/TradingScripts/tradelab && PYTHONPATH=src pytest -q 2>&1 | tail -10`
Capture the final pass/fail count for the done doc.

- [ ] **Step 2: Write the done doc**

Create `C:\TradingScripts\2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md`:

```markdown
# Direction A Slice 4 — Complete & Handoff

**Date:** 2026-04-25
**Spec:** `tradelab/docs/superpowers/specs/2026-04-25-direction-a-card-management-v1-design.md`
**Plan:** `tradelab/docs/superpowers/plans/2026-04-25-direction-a-slice-4-notifications.md`

## What shipped

- `notify(severity, title, body, channels=None)` entry point — single-line append to `tradelab/live/notify_events.jsonl`
- `Severity` enum (CRITICAL / WARNING / INFO)
- `LiveConfig` (`tradelab/live/live_config.json`, gitignored) — channel toggles, severity routing matrix, ntfy creds, SMTP creds, audible options, max_exposure_pct, silence multipliers, email digest config; default-merged on load; atomic save; SMTP password masked on read
- `NotifyDispatcher` running in dashboard launcher process — watchdog tail of `notify_events.jsonl`, read-from-EOF on start, channel isolation
- 5 channel modules: `audible` (winsound), `windows_toast` (plyer), `ntfy` (urllib.request), `email` (smtplib STARTTLS), `browser` (Broadcaster.broadcast)
- Second `Broadcaster` instance dedicated to notification SSE (`get_notify_broadcaster()`)
- 3 new endpoints — `GET/PATCH /tradelab/live/config`, `POST /tradelab/live/config/test-notification`
- `/tradelab/live/notify-stream` SSE endpoint
- Receiver-side wiring: `guardrail_blocked` and `order_failed` → `notify(CRITICAL, ...)`
- Buying-power max-exposure threshold now reads from `live_config` (was hardcoded 0.90)
- Settings panel — collapsed `<details id="lt-settings">` at bottom of Live Trading tab, with channel toggles, severity matrix, ntfy/SMTP/audible fields, silence sliders, guardrail thresholds, email digest toggles, per-channel "Test" buttons, Save button
- Browser-toast UI — `#lt-toast-container` top-right, severity-coded border, auto-dismiss INFO 5s / WARNING 10s / CRITICAL until clicked
- `plyer>=2.1.0` added to tradelab deps

## Pytest baseline

**<FILL_FROM_STEP_1> passed / 0 failed** (Slice 3 baseline was 544; Slice 4 net delta +<DELTA>).

Net-new tests by file:
- `tests/live/test_live_config.py` (NEW): 8
- `tests/live/test_notify.py` (NEW): 6
- `tests/live/test_notify_dispatcher.py` (NEW): 6
- `tests/live/test_notify_channels.py` (NEW): 15 (3 per channel × 5)
- `tests/live/test_receiver_notify_integration.py` (NEW): 3
- `tests/web/test_live_config_handlers.py` (NEW): 10
- `tests/web/test_command_center_html.py`: +9 (4 new JS function pins + 5 DOM-contract)

## Commits

(Fill in from `git log --oneline ab357d8..HEAD` in tradelab repo + parent repo since the Slice 3 done-doc commit.)

## To smoke (user)

**Step 0 (CRITICAL — Slice 3 lesson):** kill + restart BOTH receiver AND dashboard processes under the latest commits before doing anything else. Slice 4 touches receiver (notify wiring), dashboard handlers (3 endpoints + SSE + dispatcher boot), and `command_center.html` (settings panel + toast subscriber). Stale processes will silently mask wiring bugs.

```bash
# Receiver
netstat -ano | grep ":8878" | grep LISTENING | head -1
powershell -Command "Stop-Process -Id <PID> -Force"
cd C:/TradingScripts/tradelab && PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m uvicorn tradelab.live.receiver:app --host 127.0.0.1 --port 8878 --log-level info

# Dashboard
netstat -ano | grep ":8877" | grep LISTENING | head -1
powershell -Command "Stop-Process -Id <PID> -Force"
cd C:/TradingScripts && PYTHONIOENCODING=utf-8 python launch_dashboard.py
# Look for "[startup] notify_dispatcher started" in stderr
```

**Browser-side (toast UI):**
- [ ] Open dashboard → Live Trading tab → expand "⚙ Notification & Safety Settings" — all sections render, defaults populated (only Browser channel checked)
- [ ] Click "Test" next to Browser → toast appears top-right with `[CRITICAL] Test notification (browser)` title; click × to dismiss
- [ ] Toggle Audible on → Save → "Settings saved" green; reload page; Audible still toggled on
- [ ] Click "Test" next to Audible → system beep plays
- [ ] Click "Test" next to Windows toast → Windows notification appears in tray
- [ ] Fill ntfy topic with `tradelab-smoke-<random>`, enable channel, Save, click "Test" next to ntfy → push arrives on ntfy.sh app or curl `https://ntfy.sh/tradelab-smoke-<random>/json`
- [ ] (Optional, only if SMTP configured) Fill SMTP fields, Save, "Test" Email → email arrives at to_address

**API + receiver integration:**
- [ ] Re-enable smoke-amzn-v1 (status=enabled, daily_limit=0 to force block); fire one webhook → receiver returns 403 `daily_limit_exceeded` AND notify_events.jsonl gets a CRITICAL line AND a toast renders in the dashboard
- [ ] Force order_failed by misconfiguring Alpaca creds temporarily (or by editing alpaca_config.json to bad values); fire a webhook past guardrails → 502 from receiver + CRITICAL toast `Alpaca order failed`
- [ ] Restart dispatcher mid-smoke (kill dashboard, restart) — events emitted DURING dispatcher downtime stay in notify_events.jsonl but do NOT re-fire on restart (read-from-EOF semantics)
- [ ] PATCH `max_exposure_pct: 0.05` via the slider + Save; fire a webhook large enough to exceed 5% exposure → blocked with `insufficient_buying_power` (proves receiver reads live config, not hardcoded)

**Restart procedure** (per Slice 2 §7.3, with Slice 4 addition):

The dashboard now starts a notify_dispatcher thread at boot. On restart, the dispatcher re-reads `notify_events.jsonl` from EOF (does NOT replay history). Every dashboard restart loses any toast events that were in flight to the browser when SSE disconnected — that is intentional (notifications are ephemeral; the source of truth for audit is `alerts.jsonl`).

## Reviewer flags declined (with rationale)

(Fill in during code review.)

## Architectural follow-ups (not blocking Slice 4)

1. **`notify_events.jsonl` has no rotation.** Same constraint as `alerts.jsonl`. Defer rotation to Slice 5+ alongside silence detection (which is the heaviest producer per spec §8.3 cron cadence).
2. **Dispatcher restart loses in-flight events.** A power-cycle or dashboard crash mid-event will drop the event from the toast UI (it stays in the JSONL audit log). Acceptable for v1 — the user is the receiver of the truth and `alerts.jsonl` is canonical.
3. **No backpressure on a flooding producer.** A misconfigured TradingView strategy sending 100 alerts/sec would generate 100 notify events/sec, each fanning out to 5 channels = 500 sends/sec. Channels (especially email) will throttle/block downstream. Worth deduping at the dispatcher (e.g. "same title+body within 60s = collapse") before live-account cutover. Defer.
4. **plyer toast is best-effort but loud.** Each Windows toast lingers in the Action Center until dismissed. CRITICAL fires from a misbehaving card during a fast market could pile up. Consider a per-event throttle in T6's plyer call. Defer.
5. **Email channel is plaintext-only.** No HTML body. Spec §7.4 leaves this open for the daily digest (Slice 7). For instant alerts, plaintext is the right call.
6. **Test buttons always send severity=critical.** Settings panel has no severity selector for Test; the LT.testChannel signature accepts one but UI hardcodes CRITICAL. Add a per-button `<select>` if user complains during smoke. Defer.

## Slice 4 status: COMPLETE ✅ (smoke pending user)

16 of 16 tasks shipped. Pytest baseline <BASELINE> passed / 0 failed. Cleared for Slice 5 once the smoke checklist above passes. Slice 5 plan-write should follow the same pattern: brainstorm questions are already answered in the spec (§8 Silence detection), so go straight to `superpowers:writing-plans`.

## Handoff for Slice 5

Slice 5 = silence detection. Per spec §8:
- `tradelab/live/silence_checker.py` — periodic task in dashboard launcher process; cron 30 min during RTH
- Per-card `cadence` field already populated by Slice 1; silence threshold = `base_unit × multiplier` from `live_config.silence.multipliers`
- For each enabled card past threshold AND not already silent: `notify(WARNING, "Card silent", f"{card_id} hasn't fired in {n} {unit}")` + flip in-memory `silent: true` flag
- On next fire (Slice 1's existing `last_fired_at` write): silent flag clears
- One notification per silence transition — never repeat-fire while silent
- FE: status pill becomes amber when silent; new column or detail-pane chip TBD

`silence_checker` reuses the dispatcher pattern (single consumer in dashboard launcher), and silence multipliers are already exposed in the Slice 4 settings panel — Slice 5 only needs to wire the `<input type="range" data-config="silence.multipliers.intraday">` controls into a working checker.

---

**End of Slice 4 done doc.**
```

- [ ] **Step 3: Commit the plan + done doc**

```bash
cd C:/TradingScripts/tradelab
git add docs/superpowers/plans/2026-04-25-direction-a-slice-4-notifications.md
git commit -m "$(cat <<'EOF'
docs(plan): Direction A Slice 4 — notifications + settings panel

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

cd C:/TradingScripts
git add 2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md
git commit -m "$(cat <<'EOF'
docs: Slice 4 done doc + Slice 5 handoff (smoke pending)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Hand off to user for smoke**

Report to user: "Slice 4 ready for smoke. Step 0: kill + restart BOTH receiver AND dashboard (this slice touches both). Smoke checklist in `2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md` §'To smoke'."

---

## Self-review (run by plan author after writing)

**Spec coverage:**
- §7.1 routing matrix → DEFAULTS in T2 + validator in T11 ✅
- §7.2 event triggers → guardrail_blocked + order_failed in T12; remaining (panic, silence, receiver-down, ngrok-down, daily summary) explicitly out of scope (Slices 5/6/7) ✅
- §7.3 implementation (notify module + 5 channels + best-effort isolation + test endpoint) → T2/T3/T4/T5-T9/T11 ✅
- §7.4 settings panel fields (notifications + silence + guardrails + email digest) → T13/T14 ✅
- §6 new endpoints (GET/PATCH /tradelab/live/config + POST .../test-notification) → T11 ✅
- §6 SSE endpoint (`/tradelab/live/notify-stream`) → T10 ✅
- §4.3 file map (notify.py NEW, live_config.json gitignored, plyer dep, command_center.html settings) → all in File Structure table ✅

**Open questions resolved (spec §14, Slice 4 subset):**
- ntfy default topic suggestion → blank field in T13; user fills (declined to auto-generate; can add later if user complains)
- Email HTML vs plaintext → plaintext (T8) — spec §7.4 leaves this open for digest, instant alerts stay simple

**Placeholder scan:** None. Every step has either concrete code or an explicit `git log` / `pytest` command.

**Type consistency:**
- `Severity` enum used identically across notify.py, dispatcher, integration tests ✅
- Channel send signature `(severity_str, title, body, config_dict) -> bool` consistent across all 5 channels + dispatcher invocation ✅
- `live_config.get()` returns plain dict; mutation via `update()` (deep merge) — never direct dict assignment that would lose other keys ✅
- `_ALLOWED_CHANNELS` in handlers.py validator matches the `CHANNELS` registry keys ✅

**Cross-task references checked:**
- T9 adds `get_notify_broadcaster()` → T10's `handle_notify_sse` imports it ✅
- T10 adds `handle_notify_sse` → launch_dashboard.py route in T10 calls it ✅
- T2 adds `live_config.update()` → T11 PATCH handler uses it ✅
- T13 markup uses `[data-config]` selector → T14 JS queries that exact selector ✅
- T15 DOM-contract tests assert markup IDs/data-attrs that match T13 exactly (`#lt-settings`, `data-channel`, `data-config="notifications.severity_routing.<sev>" value="<chan>"`) ✅
