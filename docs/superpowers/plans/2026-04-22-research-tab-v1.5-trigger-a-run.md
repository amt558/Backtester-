# Research Tab v1.5 — Trigger-a-Run — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add web buttons that trigger any of the 5 RUN commands (`optimize`, `wf`, `run`, `run --robustness`, `run --full`) from the Research tab, with live SSE progress, persistent job state, cancellation, and a job tracker panel.

**Architecture:** `launch_dashboard.py` (port 8877) gains 4 new routes wired into a new `tradelab.web.{jobs,progress,sse}` module trio. Each job is a `subprocess.Popen` of the Typer CLI with a new `--progress-log <path>` flag; the CLI orchestrator emits JSON-line stage events; a stdlib tail loop reads them and broadcasts over SSE. Engines (`engines/*.py`) stay protected — only `cli.py` / `cli_run.py` / `cli.py`-mounted commands gain the flag.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `threading`, `queue`, `json`, `uuid`, `pathlib`, `signal`, `os`), Typer (existing CLI framework), pytest (existing test framework), vanilla JS `EventSource` in `command_center.html`. **No new dependencies.**

**Spec:** [`../specs/2026-04-22-research-tab-v1.5-trigger-a-run-design.md`](../specs/2026-04-22-research-tab-v1.5-trigger-a-run-design.md)

---

## Repo layout note

Two repositories are involved:
- **`C:\TradingScripts\tradelab\`** (this repo) — Python package, tests, specs/plans
- **`C:\TradingScripts\`** (parent, NOT a git repo) — `launch_dashboard.py`, `command_center.html`, `research_dashboard.bat`

When the plan says "modify `launch_dashboard.py`" or "modify `command_center.html`", those files are at `C:\TradingScripts\<file>`, not inside the tradelab repo. Backup pattern: copy to `<file>.bak-2026-04-22-v1.5` before first edit.

---

## File structure

### New files (in tradelab repo)

| Path | Responsibility | LOC |
|---|---|---|
| `src/tradelab/web/jobs.py` | Job manager: spawn `subprocess.Popen`, FIFO serial queue, persist `.cache/jobs.json`, atomic write, cancel via `CTRL_BREAK_EVENT`, restart recovery (PID alive vs dead), spam-click dedupe | ~250 |
| `src/tradelab/web/progress.py` | Tail loop for `.cache/jobs/<id>/progress.jsonl`, JSON-line parser tolerant of corruption, polls every 500ms, calls `sse.broadcast` on each new event | ~120 |
| `src/tradelab/web/sse.py` | SSE client list + broadcast: handles connect/disconnect, broken-pipe pruning, replays current state per active job on reconnect, emits `retry: 3000` hint | ~80 |
| `tests/web/_fake_cli.py` | Mock CLI that writes a scripted JSONL event sequence to a path and exits with a configurable code. Used by every test that needs a "subprocess" without spinning up real tradelab | ~60 |
| `tests/web/test_jobs.py` | ~12 tests | ~250 |
| `tests/web/test_progress.py` | ~8 tests | ~150 |
| `tests/web/test_sse.py` | ~6 tests | ~150 |
| `tests/web/test_handlers_jobs.py` | ~10 tests | ~250 |
| `tests/cli/test_progress_log.py` | ~5 tests | ~120 |

### Modified files (in tradelab repo)

| Path | Change |
|---|---|
| `src/tradelab/web/handlers.py` | Add `handle_post_with_status(path, body) -> (body, status)`. Add 4 route branches: `POST /tradelab/jobs`, `GET /tradelab/jobs`, `POST /tradelab/jobs/<id>/cancel`. Also add `handle_sse(path, wfile)` for `GET /tradelab/jobs/stream`. |
| `src/tradelab/cli_run.py` | Add `progress_log: str = typer.Option("", ...)` to `run()`. Wrap stage transitions with emitter calls. |
| `src/tradelab/cli.py` | Add `progress_log` Typer option to `optimize_cmd` and `walkforward_cmd`. |
| `.gitignore` | Add `.superpowers/` line so brainstorm mockup files don't get tracked. |

### Modified files (in `C:\TradingScripts\` — NOT in tradelab repo)

| Path | Change |
|---|---|
| `launch_dashboard.py` | `dispatch_tradelab_post` switches to `handle_post_with_status`. New `do_GET` branch for `/tradelab/jobs/stream` calls `_handlers.handle_sse(self.path, self.wfile)` directly (SSE bypasses the JSON envelope). New `dispatch_tradelab_sse` method. |
| `command_center.html` | Add Job Tracker panel HTML/CSS at top of Research tab. Add `[Run ▾]` dropdown to each Live Strategy card. Add `[Run ▾]` button to each Pipeline strategy group (one per unique strategy in visible page). Add 3f confirmation modal. Add EventSource client + handlers. |
| `CHANGELOG-research-tab.txt` | Append v1.5 entry. |

---

## Phase 0: Pre-implementation prep

Pre-implementation work that requires user input or sets up the workspace. The implementing agent should pause and ask the user if any of these are blocked.

### Task 0.1: Confirm tradelab repo working state

**Files:** none

- [ ] **Step 1: Check git status**

```bash
cd /c/TradingScripts/tradelab && git status --short
```

Expected: 24 modified files + 18 untracked items (per the v1 handoff doc §6).

- [ ] **Step 2: Confirm with user**

Ask: "The tradelab repo has 24 modified files + 18 untracked items uncommitted. The v1 handoff doc flagged that `config.py` makes `paths.data_dir` optional and without that commit `/tradelab/strategies` returns a pydantic error. Should I (a) wait while you commit, (b) work in a fresh git worktree from `master` (clean), or (c) proceed in this working tree at risk of mixing your in-progress work with v1.5 changes?"

**Recommended: option (b)** — git worktree from master. Cleanest isolation; v1.5 implementation never touches Amit's WIP files; merge happens via PR or `git merge` from the worktree branch.

- [ ] **Step 3: Once decided, set up the working environment**

If (b): `git worktree add ../tradelab-v1.5 -b research-tab-v1.5 master` then `cd ../tradelab-v1.5`. Subsequent file paths in this plan still use `src/tradelab/...` etc.; just be aware they resolve under the worktree directory.

If (a) or (c): proceed in `C:\TradingScripts\tradelab\` directly.

- [ ] **Step 4: Activate venv**

```bash
source /c/TradingScripts/.venv-vectorbt/Scripts/activate
```

Verify: `python -c "import tradelab; print(tradelab.__file__)"` resolves to the working repo's `src/tradelab/__init__.py`.

### Task 0.2: Verify v1 baseline still passes

**Files:** none

- [ ] **Step 1: Run web tests**

```bash
cd /c/TradingScripts/tradelab && pytest tests/web/ -v
```

Expected: 29 passed, 1 known flaky (`test_whatif_returns_metrics_and_equity_curve`). If anything else fails, STOP — investigate before adding new code.

- [ ] **Step 2: Quick smoke that launch_dashboard.py boots**

```bash
cd /c/TradingScripts && python launch_dashboard.py --no-browser &
sleep 3
curl -s http://localhost:8877/tradelab/runs?limit=1 | head -100
kill %1
```

Expected: JSON envelope `{"error":null,"data":{"runs":[...],"total":N}}`. If empty `runs:[]` that's fine — confirms the route works.

### Task 0.3: Create backups for the two `C:\TradingScripts\` files

**Files:**
- Backup: `C:\TradingScripts\command_center.html` → `command_center.html.bak-2026-04-22-v1.5`
- Backup: `C:\TradingScripts\launch_dashboard.py` → `launch_dashboard.py.bak-2026-04-22-v1.5`

- [ ] **Step 1: Copy backups**

```bash
cp /c/TradingScripts/command_center.html /c/TradingScripts/command_center.html.bak-2026-04-22-v1.5
cp /c/TradingScripts/launch_dashboard.py /c/TradingScripts/launch_dashboard.py.bak-2026-04-22-v1.5
```

- [ ] **Step 2: Verify both backup files exist and match originals**

```bash
diff /c/TradingScripts/command_center.html /c/TradingScripts/command_center.html.bak-2026-04-22-v1.5 && echo "html backup ok"
diff /c/TradingScripts/launch_dashboard.py /c/TradingScripts/launch_dashboard.py.bak-2026-04-22-v1.5 && echo "py backup ok"
```

Expected: no diff output, both "ok" lines printed.

### Task 0.4: Add `.superpowers/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Check current state**

```bash
grep -n superpowers /c/TradingScripts/tradelab/.gitignore
```

Expected: no output (line doesn't exist yet).

- [ ] **Step 2: Append the line**

```bash
echo ".superpowers/" >> /c/TradingScripts/tradelab/.gitignore
```

- [ ] **Step 3: Verify**

```bash
tail -5 /c/TradingScripts/tradelab/.gitignore
```

Expected: `.superpowers/` is the last line.

- [ ] **Step 4: Commit**

```bash
cd /c/TradingScripts/tradelab && git add .gitignore && git commit -m "chore: ignore .superpowers/ brainstorm artifacts

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1: CLI `--progress-log` flag

Add the additive `--progress-log <path>` Typer option to `run`, `optimize`, and `wf` commands. Implement an emitter helper. Wire it into `cli_run.py` orchestrator stage transitions. Backward compatible — when the flag is absent, behavior is identical to today.

### Task 1.1: Define the progress event schema module

**Files:**
- Create: `src/tradelab/web/progress_events.py`

Yes — this lives in `tradelab.web` even though the CLI imports it. The web module is the consumer; the CLI is just an emitter. This avoids `tradelab.cli` importing from `tradelab.web` (cleaner direction).

- [ ] **Step 1: Write the module**

```python
# src/tradelab/web/progress_events.py
"""Shared progress event schema for CLI emitters and web tail consumers.

The CLI side imports `ProgressEmitter` from here when --progress-log is set.
The web side imports `parse_event` from here in progress.py to validate lines.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

# Allowed event types
EVENT_START = "start"
EVENT_PROGRESS = "progress"
EVENT_COMPLETE = "complete"
EVENT_DONE = "done"
EVENT_ERROR = "error"

# Allowed stage names
STAGES = {
    "backtest", "optuna", "walk_forward", "monte_carlo",
    "loso", "regime", "cost_sweep", "tearsheet",
}


class ProgressEmitter:
    """Append-only JSON-line writer for a single subprocess job.

    Line-buffered so events are visible to a tail reader immediately.
    Safe to call when path is empty/None — becomes a no-op (backward compat).
    """

    def __init__(self, path: str | os.PathLike | None):
        self.path: Optional[Path] = Path(path) if path else None
        self._fh = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Line-buffered text mode so the tail loop sees each line immediately
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    def emit(self, type_: str, **fields: Any) -> None:
        if not self._fh:
            return
        event = {"ts": _ts(), "type": type_, **fields}
        self._fh.write(json.dumps(event) + "\n")

    def start(self, stage: str) -> None:
        self.emit(EVENT_START, stage=stage)

    def complete(self, stage: str, duration_s: float | None = None) -> None:
        if duration_s is None:
            self.emit(EVENT_COMPLETE, stage=stage)
        else:
            self.emit(EVENT_COMPLETE, stage=stage, duration_s=round(duration_s, 2))

    def progress(self, stage: str, i: int, total: int) -> None:
        self.emit(EVENT_PROGRESS, stage=stage, i=i, total=total)

    def done(self, exit_code: int = 0) -> None:
        self.emit(EVENT_DONE, exit=exit_code)

    def error(self, message: str) -> None:
        self.emit(EVENT_ERROR, message=message)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def parse_event(line: str) -> Optional[dict]:
    """Parse one JSONL line into an event dict, or None if invalid.

    Tolerant: returns None on JSONDecodeError or missing 'type' field.
    Tolerant of unknown event types and unknown extra fields (forward-compat).
    """
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(ev, dict) or "type" not in ev:
        return None
    return ev


def _ts() -> str:
    """ISO-8601 UTC timestamp with second precision."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
```

- [ ] **Step 2: Quick syntax check**

```bash
cd /c/TradingScripts/tradelab && python -c "from tradelab.web.progress_events import ProgressEmitter, parse_event; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd /c/TradingScripts/tradelab && git add src/tradelab/web/progress_events.py && git commit -m "feat(web): progress event schema + emitter for --progress-log

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.2: Test the ProgressEmitter

**Files:**
- Create: `tests/cli/test_progress_log.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/cli/test_progress_log.py
"""Tests for the --progress-log JSONL emitter contract.

Owned by tradelab.web.progress_events but tested here because the CLI is
the consumer. Backward-compat (no flag) tested via integration in
tests/web/test_handlers_jobs.py.
"""
from __future__ import annotations

import json

from tradelab.web.progress_events import ProgressEmitter, parse_event


def test_emitter_writes_jsonl_and_each_line_is_parseable(tmp_path):
    log = tmp_path / "progress.jsonl"
    em = ProgressEmitter(log)
    em.start("backtest")
    em.complete("backtest", duration_s=1.4)
    em.start("monte_carlo")
    em.progress("monte_carlo", i=100, total=500)
    em.done(exit_code=0)
    em.close()

    lines = log.read_text().splitlines()
    assert len(lines) == 5
    for ln in lines:
        ev = parse_event(ln)
        assert ev is not None
        assert "type" in ev
        assert "ts" in ev


def test_emitter_with_empty_path_is_noop_no_file_created(tmp_path):
    """Backward compat: when --progress-log is absent (empty string), emit() does nothing."""
    em = ProgressEmitter("")
    em.start("backtest")
    em.done()
    em.close()

    # No new files in tmp_path (we passed empty string, not a tmp path)
    assert list(tmp_path.iterdir()) == []


def test_emitter_is_line_buffered_event_visible_before_close(tmp_path):
    """Tail loop should see each event immediately, not at process exit."""
    log = tmp_path / "progress.jsonl"
    em = ProgressEmitter(log)
    em.start("backtest")
    # Read while emitter is still open — would fail if buffered until close()
    content = log.read_text()
    assert "backtest" in content
    em.close()


def test_parse_event_tolerates_corrupted_lines():
    assert parse_event('{"type":"start","stage":"backtest"}') is not None
    assert parse_event('not json at all') is None
    assert parse_event('{"missing_type":true}') is None
    assert parse_event('') is None
    assert parse_event('   ') is None
    # Forward-compat: unknown type + extra fields still parse
    ev = parse_event('{"type":"future_thing","extra":42}')
    assert ev is not None
    assert ev["type"] == "future_thing"


def test_parse_event_rejects_non_object_json():
    """JSON arrays/scalars at top level should be rejected."""
    assert parse_event('[1,2,3]') is None
    assert parse_event('"string"') is None
    assert parse_event('42') is None
```

- [ ] **Step 2: Run tests, verify they fail or pass appropriately**

```bash
cd /c/TradingScripts/tradelab && pytest tests/cli/test_progress_log.py -v
```

Expected: 5 PASSED. (The implementation from Task 1.1 should already satisfy these.)

If anything fails, fix the implementation in `progress_events.py`, not the tests.

- [ ] **Step 3: Commit**

```bash
cd /c/TradingScripts/tradelab && git add tests/cli/test_progress_log.py && git commit -m "test(cli): cover progress event emitter and parser contract

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.3: Add `--progress-log` to `cli_run.py::run`

**Files:**
- Modify: `src/tradelab/cli_run.py` (line 73-74 area, after the existing `open_dashboard` option)

- [ ] **Step 1: Add the new Typer option**

In `src/tradelab/cli_run.py`, find the function signature for `run()` (starts at line 37). After the `open_dashboard: bool = typer.Option(...)` parameter (around line 74), add:

```python
    progress_log: str = typer.Option(
        "", "--progress-log",
        help="Path to JSONL file for stage progress events (used by the web Job Tracker)."
    ),
```

- [ ] **Step 2: Instantiate the emitter at the top of the function body**

After the `# --- mega-flag: --full implies all four pillars ---` block (around line 79-84), add:

```python
    from .web.progress_events import ProgressEmitter
    _emit = ProgressEmitter(progress_log)
```

- [ ] **Step 3: Wrap stage calls with start/complete events**

Find each major stage call site in `cli_run.py` and wrap it. Example pattern (apply to backtest, optuna optimize, walk-forward, cost-sweep, robustness — exact line numbers vary; search for the function calls):

```python
    # before:
    bt_result = run_backtest(...)
    # after:
    _emit.start("backtest")
    import time as _t; _t0 = _t.time()
    bt_result = run_backtest(...)
    _emit.complete("backtest", duration_s=_t.time() - _t0)
```

Repeat for: `run_optimization`, `run_walkforward`, `run_cost_sweep`, `run_robustness_suite`. The exact existing call lines: search with `grep -n "run_backtest\|run_optimization\|run_walkforward\|run_cost_sweep\|run_robustness_suite" src/tradelab/cli_run.py`.

If a stage is conditional (e.g., `if optimize:` block), put the `start/complete` inside the block so we don't emit phantom events.

- [ ] **Step 4: Emit done at the end of the function**

At the very end of `run()`, before the function returns implicitly, add:

```python
    _emit.done(exit_code=0)
    _emit.close()
```

- [ ] **Step 5: Wrap the whole body in try/except to emit error on failure**

Restructure (pseudocode shape — preserve all existing logic):

```python
def run(...):
    from .web.progress_events import ProgressEmitter
    _emit = ProgressEmitter(progress_log)
    try:
        # existing body here, including the start/complete wraps from step 3
        _emit.done(exit_code=0)
    except typer.Exit as e:
        _emit.done(exit_code=int(e.exit_code or 0))
        raise
    except Exception as e:
        _emit.error(str(e))
        _emit.done(exit_code=1)
        raise
    finally:
        _emit.close()
```

- [ ] **Step 6: Smoke test backward compat (no flag)**

```bash
cd /c/TradingScripts/tradelab && python -m tradelab.cli run --help | grep progress-log
```

Expected: line containing `--progress-log` and the help text. Then run an actual cheap command without the flag:

```bash
python -m tradelab.cli list
```

Expected: existing behavior unchanged (lists strategies). If `list` fails, STOP — something else is broken.

- [ ] **Step 7: Smoke test with the flag (using a no-op strategy or canary)**

```bash
cd /c/TradingScripts/tradelab && python -m tradelab.cli run rand_canary --symbols AAPL --start 2024-01-01 --end 2024-01-15 --no-tearsheet --no-open-dashboard --progress-log /tmp/test_progress.jsonl
```

Expected: subprocess runs, exits 0, `/tmp/test_progress.jsonl` contains JSONL events including `{"type":"start","stage":"backtest"...}`, `{"type":"complete","stage":"backtest"...}`, and final `{"type":"done","exit":0}`.

- [ ] **Step 8: Verify event content**

```bash
cat /tmp/test_progress.jsonl | python -c "import sys, json; [print(json.loads(l)) for l in sys.stdin if l.strip()]"
```

Expected: each line parses as a dict with `ts`, `type`, and (for stage events) `stage`.

- [ ] **Step 9: Commit**

```bash
cd /c/TradingScripts/tradelab && git add src/tradelab/cli_run.py && git commit -m "feat(cli): emit JSONL progress events when --progress-log is set

Backward compatible: empty path = no-op. Engines untouched; events are
emitted from the orchestrator only. Stage names match progress_events.STAGES.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 1.4: Add `--progress-log` to `optimize_cmd` and `walkforward_cmd`

**Files:**
- Modify: `src/tradelab/cli.py` (lines 245 and 330 areas)

- [ ] **Step 1: Find the two function signatures**

```bash
grep -n "^def optimize_cmd\|^def walkforward_cmd" src/tradelab/cli.py
```

Expected: line numbers for both (approx 245 and 330).

- [ ] **Step 2: Add the same Typer option to each function**

For both `optimize_cmd` and `walkforward_cmd`, append this parameter at the end of the signature (just before the closing `) -> None:`):

```python
    progress_log: str = typer.Option(
        "", "--progress-log",
        help="Path to JSONL file for stage progress events (used by the web Job Tracker)."
    ),
```

- [ ] **Step 3: Wrap each function body the same way as Task 1.3 step 5**

For `optimize_cmd`: wrap the body so that `_emit.start("optuna")` fires before `run_optimization`, `_emit.complete("optuna", duration_s=...)` after, and `_emit.done(...)` at end. Same try/except/finally shape.

For `walkforward_cmd`: same with `_emit.start("walk_forward")` / `_emit.complete("walk_forward", ...)`.

- [ ] **Step 4: Smoke both**

```bash
python -m tradelab.cli optimize --help | grep progress-log
python -m tradelab.cli wf --help | grep progress-log
```

Expected: both show the `--progress-log` line.

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab && git add src/tradelab/cli.py && git commit -m "feat(cli): add --progress-log to optimize and wf commands

Mirrors the implementation from cli_run.py::run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: Job manager (`tradelab.web.jobs`)

The serial-queue job manager. Tracks `(queued|running|done|failed|cancelled|interrupted)` state in memory and persists to `.cache/jobs.json`. Spawns subprocesses with the right Windows `creationflags`. Handles cancel via `CTRL_BREAK_EVENT`. Recovers cleanly across dashboard restarts.

### Task 2.1: Job dataclass + status enum + atomic write helper

**Files:**
- Create: `src/tradelab/web/jobs.py` (initial — module skeleton)
- Create: `tests/web/_fake_cli.py` (test helper)

- [ ] **Step 1: Write the test helper first**

```python
# tests/web/_fake_cli.py
"""Mock CLI used in lieu of real tradelab.cli for fast tests.

Invoked as: python tests/web/_fake_cli.py --progress-log <path> --script <script_name>

Each script_name maps to a deterministic sequence of events written to <path>,
followed by an exit code. Lets every test assert "subprocess emitted these
events and exited cleanly" without spinning up real backtests.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# We import from the real package — we only need the emitter
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tradelab.web.progress_events import ProgressEmitter


SCRIPTS = {
    "happy_short": [
        ("start", {"stage": "backtest"}),
        ("complete", {"stage": "backtest", "duration_s": 0.01}),
        ("done", {"exit_code": 0}),
    ],
    "happy_with_progress": [
        ("start", {"stage": "monte_carlo"}),
        ("progress", {"stage": "monte_carlo", "i": 100, "total": 500}),
        ("progress", {"stage": "monte_carlo", "i": 320, "total": 500}),
        ("complete", {"stage": "monte_carlo", "duration_s": 0.05}),
        ("done", {"exit_code": 0}),
    ],
    "fails_immediately": [
        ("error", {"message": "synthetic failure for testing"}),
        ("done", {"exit_code": 1}),
    ],
    "no_events_then_crashes": [],  # exits 1 with no emit
    "long_running": [
        # caller controls duration via SLEEP_S env var; default 10s
        ("start", {"stage": "monte_carlo"}),
    ],
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--progress-log", default="")
    p.add_argument("--script", required=True)
    p.add_argument("--exit", type=int, default=None,
                   help="Override final exit code (used by fails_immediately etc.)")
    args = p.parse_args()

    if args.script not in SCRIPTS:
        print(f"unknown script: {args.script}", file=sys.stderr)
        return 2

    em = ProgressEmitter(args.progress_log)
    final_exit = 0
    for type_, fields in SCRIPTS[args.script]:
        if type_ == "done":
            final_exit = fields.get("exit_code", 0)
            em.done(exit_code=final_exit)
        else:
            em.emit(type_, **fields)

    if args.script == "long_running":
        import os
        sleep_s = int(os.environ.get("SLEEP_S", "10"))
        try:
            time.sleep(sleep_s)
        except KeyboardInterrupt:
            em.error("cancelled")
            em.done(exit_code=130)
            em.close()
            return 130
        em.done(exit_code=0)

    if args.exit is not None:
        final_exit = args.exit
    em.close()
    return final_exit


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing test for the dataclass / status / atomic write**

```python
# tests/web/test_jobs.py
"""Tests for tradelab.web.jobs — job manager."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tradelab.web import jobs


@pytest.fixture
def jm(tmp_path, monkeypatch):
    """Fresh JobManager with state under tmp_path/.cache."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    return jobs.JobManager(cache_root=cache)


def test_job_dataclass_has_expected_fields():
    j = jobs.Job(
        id="abc",
        strategy="momo",
        command="run --robustness",
        argv=["run", "momo", "--robustness"],
        status=jobs.JobStatus.QUEUED,
    )
    assert j.id == "abc"
    assert j.status == jobs.JobStatus.QUEUED
    assert j.pid is None
    assert j.exit_code is None
    assert j.started_at is None
    assert j.ended_at is None


def test_atomic_write_creates_then_replaces(tmp_path):
    target = tmp_path / "jobs.json"
    jobs._atomic_write_json(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text())["hello"] == "world"
    # second write replaces
    jobs._atomic_write_json(target, {"hello": "again"})
    assert json.loads(target.read_text())["hello"] == "again"
    # tmp file should not be left behind
    assert not (tmp_path / "jobs.json.tmp").exists()
```

- [ ] **Step 3: Run, verify failure**

```bash
pytest tests/web/test_jobs.py::test_job_dataclass_has_expected_fields -v
```

Expected: `ImportError: cannot import name 'jobs'` or `AttributeError: module ... has no attribute 'JobManager'`.

- [ ] **Step 4: Write the initial `jobs.py` skeleton**

```python
# src/tradelab/web/jobs.py
"""Job manager for the Research tab Trigger-a-Run feature.

Spawns subprocess.Popen for each tradelab CLI invocation, manages a serial
FIFO queue (one job running at a time), persists state to .cache/jobs.json
with atomic writes, recovers from dashboard restarts by checking PID liveness.
"""
from __future__ import annotations

import enum
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


SCHEMA_VERSION = 1
RETENTION_TERMINAL_JOBS = 50


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass
class Job:
    id: str
    strategy: str
    command: str          # human-readable: "run --robustness"
    argv: list[str]       # the actual ["run", "momo", "--robustness"] passed to tradelab.cli
    status: JobStatus = JobStatus.QUEUED
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    progress_log: Optional[str] = None
    last_event_summary: Optional[str] = None
    error_tail: Optional[str] = None  # last 100 lines of stderr if failed

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d["status"] = JobStatus(d["status"])
        return cls(**d)


class JobManager:
    """Serial-queue job manager. Thread-safe via a single Lock."""

    def __init__(self, cache_root: Path | str):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queue: list[str] = []
        self._running_id: Optional[str] = None
        self._processes: dict[str, subprocess.Popen] = {}
        # event hook — wired by sse.py to push state changes
        self._on_state_change = None
        self._load_or_init()

    # ─── State persistence ──────────────────────────────────────────

    def _state_path(self) -> Path:
        return self.cache_root / "jobs.json"

    def _load_or_init(self) -> None:
        p = self._state_path()
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw.get("schema_version") != SCHEMA_VERSION:
                # forward-incompat — start fresh, don't lose old file
                _backup_corrupted(p, reason="schema_mismatch")
                return
            self._jobs = {j["id"]: Job.from_dict(j) for j in raw.get("jobs", [])}
            self._queue = list(raw.get("queue", []))
            self._running_id = raw.get("running_id")
        except (json.JSONDecodeError, KeyError, ValueError):
            _backup_corrupted(p, reason="parse_error")

    def _persist(self) -> None:
        # caller must hold self._lock
        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in self._jobs.values()],
            "queue": list(self._queue),
            "running_id": self._running_id,
        }
        _atomic_write_json(self._state_path(), data)


# ─── Module helpers ──────────────────────────────────────────────────


def _atomic_write_json(target: Path, data: dict) -> None:
    """Write to target atomically: write .tmp, then os.replace."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _backup_corrupted(path: Path, reason: str) -> None:
    """Rename a corrupted state file out of the way; log loudly."""
    bak = path.with_suffix(f".broken-{reason}-{int(time.time())}.json")
    try:
        path.rename(bak)
        print(f"[jobs] corrupted state file backed up to {bak}", file=sys.stderr)
    except OSError:
        pass
```

- [ ] **Step 5: Run tests — both should pass**

```bash
pytest tests/web/test_jobs.py::test_job_dataclass_has_expected_fields tests/web/test_jobs.py::test_atomic_write_creates_then_replaces -v
```

Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /c/TradingScripts/tradelab && git add src/tradelab/web/jobs.py tests/web/_fake_cli.py tests/web/test_jobs.py && git commit -m "feat(web): JobManager skeleton with atomic state persistence

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.2: Test + implement `submit_job` (queue + dedupe)

**Files:**
- Modify: `tests/web/test_jobs.py`
- Modify: `src/tradelab/web/jobs.py`

- [ ] **Step 1: Add tests**

Append to `tests/web/test_jobs.py`:

```python
def test_submit_first_job_promotes_to_running(jm):
    job_id, status = jm.submit("momo", "run --robustness", _fake_argv())
    assert status == jobs.JobStatus.RUNNING
    assert jm.get(job_id).status == jobs.JobStatus.RUNNING
    assert jm._running_id == job_id
    jm.cancel(job_id); jm.wait_for_terminal(job_id, timeout=5)


def test_submit_second_job_stays_queued(jm):
    a_id, _ = jm.submit("momo", "run --robustness", _fake_argv("long_running"))
    b_id, b_status = jm.submit("mean_rev", "run --robustness", _fake_argv())
    assert b_status == jobs.JobStatus.QUEUED
    assert jm._running_id == a_id
    assert b_id in jm._queue
    jm.cancel(a_id); jm.cancel(b_id)


def test_duplicate_strategy_command_returns_existing_409(jm):
    a_id, _ = jm.submit("momo", "run --robustness", _fake_argv("long_running"))
    with pytest.raises(jobs.DuplicateJobError) as exc:
        jm.submit("momo", "run --robustness", _fake_argv())
    assert exc.value.existing_job_id == a_id
    jm.cancel(a_id)


def _fake_argv(script: str = "happy_short") -> list[str]:
    """Build argv that points at the fake CLI."""
    return [
        sys.executable,
        str(Path(__file__).parent / "_fake_cli.py"),
        "--script", script,
    ]
```

- [ ] **Step 2: Run, verify failure**

Expected: `AttributeError: 'JobManager' object has no attribute 'submit'`.

- [ ] **Step 3: Implement `submit`, `get`, `cancel`, `wait_for_terminal`, `DuplicateJobError`**

Append to `src/tradelab/web/jobs.py`:

```python
class DuplicateJobError(Exception):
    """Raised when a (strategy, command) pair is already running or queued."""
    def __init__(self, existing_job_id: str):
        super().__init__(f"job already in flight: {existing_job_id}")
        self.existing_job_id = existing_job_id


# Inside JobManager:

    def submit(self, strategy: str, command: str, argv: list[str]) -> tuple[str, JobStatus]:
        """Submit a new job. Returns (job_id, status) where status is RUNNING or QUEUED.

        Raises DuplicateJobError if a job with the same (strategy, command)
        is already RUNNING or QUEUED.
        """
        with self._lock:
            # dedupe
            for jid, j in self._jobs.items():
                if (
                    j.strategy == strategy
                    and j.command == command
                    and j.status in (JobStatus.RUNNING, JobStatus.QUEUED)
                ):
                    raise DuplicateJobError(existing_job_id=jid)

            job_id = uuid.uuid4().hex
            progress_path = self.cache_root / "jobs" / job_id / "progress.jsonl"
            progress_path.parent.mkdir(parents=True, exist_ok=True)

            # rewrite argv to inject --progress-log if not already present
            argv_with_log = list(argv)
            if "--progress-log" not in argv_with_log:
                argv_with_log.extend(["--progress-log", str(progress_path)])

            job = Job(
                id=job_id,
                strategy=strategy,
                command=command,
                argv=argv_with_log,
                progress_log=str(progress_path),
            )
            self._jobs[job_id] = job

            if self._running_id is None:
                self._start(job_id)
                status = JobStatus.RUNNING
            else:
                self._queue.append(job_id)
                status = JobStatus.QUEUED

            self._persist()
            return job_id, status

    def _start(self, job_id: str) -> None:
        """Spawn subprocess. Caller must hold self._lock."""
        job = self._jobs[job_id]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        proc = subprocess.Popen(
            job.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            cwd=str(self.cache_root.parent) if self.cache_root.parent.name == "tradelab" else None,
        )
        self._processes[job_id] = proc
        job.pid = proc.pid
        job.started_at = _ts()
        job.status = JobStatus.RUNNING
        self._running_id = job_id
        # start a watcher thread that flips status when subprocess exits
        threading.Thread(target=self._watch, args=(job_id,), daemon=True).start()

    def _watch(self, job_id: str) -> None:
        """Block on subprocess exit, then update state."""
        proc = self._processes.get(job_id)
        if proc is None:
            return
        try:
            stderr_bytes = proc.communicate()[1] or b""
        except Exception:
            stderr_bytes = b""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.exit_code = proc.returncode
            job.ended_at = _ts()
            if job.status == JobStatus.CANCELLED:
                pass  # already set by cancel()
            elif proc.returncode == 0:
                job.status = JobStatus.DONE
            else:
                job.status = JobStatus.FAILED
                tail = stderr_bytes.decode(errors="replace").splitlines()[-100:]
                job.error_tail = "\n".join(tail)
            self._processes.pop(job_id, None)
            self._running_id = None
            # promote next queued job
            if self._queue:
                next_id = self._queue.pop(0)
                self._start(next_id)
            self._persist()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        """Cancel a job. Returns True if cancellation was attempted, False if no-op."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status == JobStatus.QUEUED:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                job.status = JobStatus.CANCELLED
                job.ended_at = _ts()
                self._persist()
                return True
            if job.status != JobStatus.RUNNING:
                return False
            proc = self._processes.get(job_id)
            if proc is None:
                return False
            job.status = JobStatus.CANCELLED  # set before signaling so _watch sees it
            self._persist()
        # release lock before signaling — kill is potentially slow
        try:
            if sys.platform == "win32":
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        return True

    def wait_for_terminal(self, job_id: str, timeout: float = 30.0) -> bool:
        """Block until the job is in a terminal state (test helper). Returns True if reached."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return False
                if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                    return True
            time.sleep(0.05)
        return False


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
```

- [ ] **Step 4: Run new tests**

```bash
pytest tests/web/test_jobs.py::test_submit_first_job_promotes_to_running tests/web/test_jobs.py::test_submit_second_job_stays_queued tests/web/test_jobs.py::test_duplicate_strategy_command_returns_existing_409 -v
```

Expected: 3 PASSED. If `test_submit_first_job_promotes_to_running` flakes on the cancel cleanup, the issue is likely the fake_cli not honoring `CTRL_BREAK_EVENT` — debug by raising the timeout, then check `tests/web/_fake_cli.py` `long_running` script.

- [ ] **Step 5: Commit**

```bash
cd /c/TradingScripts/tradelab && git add src/tradelab/web/jobs.py tests/web/test_jobs.py && git commit -m "feat(web): JobManager submit/cancel/queue with subprocess spawn

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.3: Test + implement queue promotion on exit

**Files:**
- Modify: `tests/web/test_jobs.py`

- [ ] **Step 1: Add test**

```python
def test_queue_promotes_next_on_exit(jm):
    a_id, _ = jm.submit("momo", "run", _fake_argv("happy_short"))
    b_id, b_status = jm.submit("mean_rev", "run", _fake_argv("happy_short"))
    assert b_status == jobs.JobStatus.QUEUED

    # wait for A to exit and B to be promoted + finish
    assert jm.wait_for_terminal(a_id, timeout=10)
    assert jm.wait_for_terminal(b_id, timeout=10)
    assert jm.get(a_id).status == jobs.JobStatus.DONE
    assert jm.get(b_id).status == jobs.JobStatus.DONE
    assert jm._running_id is None
    assert jm._queue == []
```

- [ ] **Step 2: Run, verify pass (logic was implemented in Task 2.2)**

```bash
pytest tests/web/test_jobs.py::test_queue_promotes_next_on_exit -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/web/test_jobs.py && git commit -m "test(web): cover queue promotion on subprocess exit

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.4: Test + implement restart recovery

**Files:**
- Modify: `tests/web/test_jobs.py`
- Modify: `src/tradelab/web/jobs.py`

- [ ] **Step 1: Add tests**

```python
def test_restart_recovery_pid_alive_reattaches(tmp_path, monkeypatch):
    """If the dashboard restarts but the subprocess is still alive,
    JobManager should re-load the running job and treat it as still in flight."""
    cache = tmp_path / ".cache"
    cache.mkdir()

    # Manually craft jobs.json as if a prior dashboard left a running job
    # Use os.getpid() — guaranteed to be alive
    own_pid = os.getpid()
    state = {
        "schema_version": jobs.SCHEMA_VERSION,
        "jobs": [{
            "id": "abc",
            "strategy": "momo",
            "command": "run",
            "argv": ["echo"],
            "status": "running",
            "started_at": "2026-04-22T10:00:00Z",
            "ended_at": None,
            "pid": own_pid,
            "exit_code": None,
            "progress_log": str(cache / "jobs/abc/progress.jsonl"),
            "last_event_summary": None,
            "error_tail": None,
        }],
        "queue": [],
        "running_id": "abc",
    }
    (cache / "jobs.json").write_text(json.dumps(state))

    jm = jobs.JobManager(cache_root=cache)
    # Re-loaded job should be present and still RUNNING because PID is alive
    assert jm.get("abc").status == jobs.JobStatus.RUNNING
    assert jm._running_id == "abc"


def test_restart_recovery_pid_dead_marks_interrupted(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    # PID 999999 is overwhelmingly likely to not exist
    state = {
        "schema_version": jobs.SCHEMA_VERSION,
        "jobs": [{
            "id": "abc", "strategy": "momo", "command": "run",
            "argv": ["echo"], "status": "running",
            "started_at": "2026-04-22T10:00:00Z", "ended_at": None,
            "pid": 999999, "exit_code": None,
            "progress_log": None, "last_event_summary": None, "error_tail": None,
        }],
        "queue": [], "running_id": "abc",
    }
    (cache / "jobs.json").write_text(json.dumps(state))

    jm = jobs.JobManager(cache_root=cache)
    j = jm.get("abc")
    assert j.status == jobs.JobStatus.INTERRUPTED
    assert j.ended_at is not None
    assert jm._running_id is None


def test_corrupted_jobs_json_is_renamed_and_fresh_state_starts(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "jobs.json").write_text("{not valid json")

    jm = jobs.JobManager(cache_root=cache)
    assert jm.list_jobs() == []
    # backup file with .broken- prefix should exist
    backups = list(cache.glob("jobs.broken-*.json"))
    assert len(backups) == 1
```

- [ ] **Step 2: Run, see what fails**

Expected: `test_restart_recovery_pid_alive_reattaches` and `test_restart_recovery_pid_dead_marks_interrupted` fail (recovery logic not implemented yet). Corrupted-JSON test should already pass via `_backup_corrupted`.

- [ ] **Step 3: Add recovery to `_load_or_init`**

In `src/tradelab/web/jobs.py`, modify `_load_or_init` to perform liveness check on any RUNNING job after parsing:

```python
    def _load_or_init(self) -> None:
        p = self._state_path()
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw.get("schema_version") != SCHEMA_VERSION:
                _backup_corrupted(p, reason="schema_mismatch")
                return
            self._jobs = {j["id"]: Job.from_dict(j) for j in raw.get("jobs", [])}
            self._queue = list(raw.get("queue", []))
            self._running_id = raw.get("running_id")
        except (json.JSONDecodeError, KeyError, ValueError):
            _backup_corrupted(p, reason="parse_error")
            return

        # Liveness check: any RUNNING job whose PID is dead → INTERRUPTED
        if self._running_id:
            running = self._jobs.get(self._running_id)
            if running is None or running.pid is None:
                self._running_id = None
            elif not _pid_alive(running.pid):
                running.status = JobStatus.INTERRUPTED
                running.ended_at = _ts()
                self._running_id = None
                self._persist()


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            # On Windows, os.kill(pid, 0) raises if dead, returns None if alive
            os.kill(pid, 0)
            return True
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False
```

- [ ] **Step 4: Re-run all 3 tests**

```bash
pytest tests/web/test_jobs.py::test_restart_recovery_pid_alive_reattaches tests/web/test_jobs.py::test_restart_recovery_pid_dead_marks_interrupted tests/web/test_jobs.py::test_corrupted_jobs_json_is_renamed_and_fresh_state_starts -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/jobs.py tests/web/test_jobs.py && git commit -m "feat(web): JobManager restart recovery (PID liveness + corrupted state backup)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.5: Test + implement bounded retention

**Files:**
- Modify: `tests/web/test_jobs.py`
- Modify: `src/tradelab/web/jobs.py`

- [ ] **Step 1: Add test**

```python
def test_bounded_retention_only_keeps_last_50_terminal(jm):
    # Spam 60 short jobs
    for i in range(60):
        jid, _ = jm.submit(f"strat_{i}", "run", _fake_argv())
        assert jm.wait_for_terminal(jid, timeout=10)

    # All 60 finished, but only the last 50 should remain
    assert len(jm.list_jobs()) == jobs.RETENTION_TERMINAL_JOBS  # 50
```

- [ ] **Step 2: Run, expect failure**

Expected: assertion fails — list has 60 items because retention isn't trimmed.

- [ ] **Step 3: Implement trim in `_persist`**

In `src/tradelab/web/jobs.py`, modify `_persist` to drop the oldest terminal jobs when over `RETENTION_TERMINAL_JOBS`:

```python
    def _persist(self) -> None:
        # caller must hold self._lock
        terminal_states = {
            JobStatus.DONE, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.INTERRUPTED,
        }
        active = [j for j in self._jobs.values() if j.status not in terminal_states]
        terminal = [j for j in self._jobs.values() if j.status in terminal_states]
        terminal.sort(key=lambda j: j.ended_at or "")
        if len(terminal) > RETENTION_TERMINAL_JOBS:
            drop = terminal[: len(terminal) - RETENTION_TERMINAL_JOBS]
            for j in drop:
                self._jobs.pop(j.id, None)
            terminal = terminal[len(terminal) - RETENTION_TERMINAL_JOBS:]

        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in (active + terminal)],
            "queue": list(self._queue),
            "running_id": self._running_id,
        }
        _atomic_write_json(self._state_path(), data)
```

- [ ] **Step 4: Re-run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/jobs.py tests/web/test_jobs.py && git commit -m "feat(web): bounded retention — keep last 50 terminal jobs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.6: Test cancel of a running job

**Files:**
- Modify: `tests/web/test_jobs.py`

- [ ] **Step 1: Add test (Windows-specific)**

```python
@pytest.mark.skipif(sys.platform != "win32", reason="CTRL_BREAK_EVENT is Windows-specific")
def test_cancel_running_job_uses_ctrl_break_then_kill(jm):
    """Spawn a long_running fake CLI, cancel it, verify status flips to CANCELLED."""
    job_id, _ = jm.submit("momo", "run", _fake_argv("long_running"))
    # Give it a moment to actually start
    time.sleep(0.5)
    assert jm.cancel(job_id) is True
    assert jm.wait_for_terminal(job_id, timeout=10)
    assert jm.get(job_id).status == jobs.JobStatus.CANCELLED


def test_cancel_queued_job_removes_from_queue(jm):
    a_id, _ = jm.submit("momo", "run", _fake_argv("long_running"))
    b_id, _ = jm.submit("mean_rev", "run", _fake_argv())
    assert jm.get(b_id).status == jobs.JobStatus.QUEUED
    assert jm.cancel(b_id) is True
    assert jm.get(b_id).status == jobs.JobStatus.CANCELLED
    assert b_id not in jm._queue
    # Cleanup A
    jm.cancel(a_id); jm.wait_for_terminal(a_id, timeout=10)


def test_cancel_unknown_job_returns_false(jm):
    assert jm.cancel("does-not-exist") is False
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/web/test_jobs.py::test_cancel_running_job_uses_ctrl_break_then_kill tests/web/test_jobs.py::test_cancel_queued_job_removes_from_queue tests/web/test_jobs.py::test_cancel_unknown_job_returns_false -v
```

Expected: 3 PASSED on Windows; 1 skipped + 2 PASSED on Linux/macOS.

- [ ] **Step 3: Commit**

```bash
git add tests/web/test_jobs.py && git commit -m "test(web): cover JobManager.cancel for running, queued, unknown jobs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2.7: Run the full jobs test suite

- [ ] **Step 1: All jobs tests**

```bash
pytest tests/web/test_jobs.py -v
```

Expected: ~12 tests, all PASS (one may skip on non-Windows).

- [ ] **Step 2: Confirm no regressions in v1 tests**

```bash
pytest tests/web/ -v --ignore=tests/web/test_jobs.py
```

Expected: 29 PASSED, 1 known flaky.

---

## Phase 3: Progress tail loop (`tradelab.web.progress`)

A polling tail loop that reads new lines from `.cache/jobs/<id>/progress.jsonl` every 500ms and broadcasts each parsed event via a callback. Tolerant of corruption, missing files, partial writes, and process exit.

### Task 3.1: Test + implement basic tail behavior

**Files:**
- Create: `src/tradelab/web/progress.py`
- Create: `tests/web/test_progress.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/web/test_progress.py
"""Tests for the progress.jsonl tail loop."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from tradelab.web import progress


def test_tail_reads_existing_lines_and_calls_callback(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.write_text(
        json.dumps({"type": "start", "stage": "backtest"}) + "\n"
        + json.dumps({"type": "done", "exit": 0}) + "\n"
    )
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    # Allow a couple of poll cycles
    time.sleep(0.3)
    tailer.stop()
    assert len(received) == 2
    assert received[0]["type"] == "start"
    assert received[1]["type"] == "done"


def test_tail_picks_up_appended_lines_within_500ms(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.touch()
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.1)
    with log.open("a") as f:
        f.write(json.dumps({"type": "start", "stage": "backtest"}) + "\n")
    # Wait up to 600ms for the event
    deadline = time.time() + 0.6
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_skips_corrupted_lines_does_not_crash(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.write_text(
        '{"type":"start","stage":"backtest"}\n'
        'this is not json\n'
        '{"type":"done","exit":0}\n'
    )
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.3)
    tailer.stop()
    # Bad line skipped, two valid events received
    assert len(received) == 2


def test_tail_silent_until_file_appears(tmp_path):
    log = tmp_path / "progress.jsonl"  # does not exist yet
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.2)
    assert received == []
    log.write_text('{"type":"start","stage":"backtest"}\n')
    deadline = time.time() + 0.4
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_partial_line_safe(tmp_path):
    """A line written without trailing newline should not be parsed until newline arrives."""
    log = tmp_path / "progress.jsonl"
    log.write_text('{"type":"start","stage":"backtest"')  # no newline yet, no closing }
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.2)
    assert received == []  # partial line not parsed
    with log.open("a") as f:
        f.write('}\n')
    deadline = time.time() + 0.4
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_stops_cleanly(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.touch()
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    tailer.stop()
    # No exceptions, no thread leak
    assert not tailer._thread.is_alive() if tailer._thread else True
```

- [ ] **Step 2: Implement `progress.py`**

```python
# src/tradelab/web/progress.py
"""Polling tail reader for .cache/jobs/<id>/progress.jsonl.

Stdlib-only — no `watchdog` dependency. Polls the file every 500ms, reads
any new bytes since last position, splits on \n, parses each complete line,
and invokes a callback per valid event.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .progress_events import parse_event


class ProgressTailer:
    """Tails a JSONL file in a background thread.

    Use:
        t = ProgressTailer(path, on_event=lambda ev: ...)
        t.start()
        ...
        t.stop()  # blocks until thread exits
    """

    def __init__(
        self,
        path: Path,
        on_event: Callable[[dict], None],
        poll_interval_s: float = 0.5,
    ):
        self.path = Path(path)
        self.on_event = on_event
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        position = 0
        buffer = ""
        while not self._stop.is_set():
            try:
                if self.path.exists():
                    size = self.path.stat().st_size
                    if size > position:
                        with self.path.open("r", encoding="utf-8") as f:
                            f.seek(position)
                            chunk = f.read(size - position)
                            position = size
                        buffer += chunk
                        # process complete lines
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            ev = parse_event(line)
                            if ev is not None:
                                try:
                                    self.on_event(ev)
                                except Exception:
                                    # callback errors must not kill the tailer
                                    pass
                    elif size < position:
                        # file shrank (truncated/rotated) — restart from 0
                        position = 0
                        buffer = ""
            except (OSError, IOError):
                pass  # transient disk error — retry next poll
            self._stop.wait(timeout=self.poll_interval_s)
```

- [ ] **Step 3: Run all 6 tests**

```bash
pytest tests/web/test_progress.py -v
```

Expected: 6 PASSED.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/progress.py tests/web/test_progress.py && git commit -m "feat(web): polling tail loop for progress.jsonl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3.2: Wire ProgressTailer into JobManager start

**Files:**
- Modify: `src/tradelab/web/jobs.py`

- [ ] **Step 1: Add tailer lifecycle to `_start` and `_watch`**

In `src/tradelab/web/jobs.py`, modify `_start` to also kick off a `ProgressTailer` per job, and `_watch` to stop it on subprocess exit.

Add at top of file:
```python
from .progress import ProgressTailer
```

Add to `JobManager.__init__`:
```python
        self._tailers: dict[str, ProgressTailer] = {}
```

In `_start`, after starting the watcher thread, also start the tailer:
```python
        # tail progress.jsonl and route events to last_event_summary + sse
        if job.progress_log:
            tailer = ProgressTailer(
                Path(job.progress_log),
                on_event=lambda ev, jid=job_id: self._on_progress_event(jid, ev),
            )
            tailer.start()
            self._tailers[job_id] = tailer
```

In `_watch`, after popping from `self._processes`, also stop+pop the tailer:
```python
            tailer = self._tailers.pop(job_id, None)
            if tailer is not None:
                # stop in background — don't block _watch
                threading.Thread(target=tailer.stop, daemon=True).start()
```

Add new method to `JobManager`:
```python
    def _on_progress_event(self, job_id: str, event: dict) -> None:
        """Callback fired by ProgressTailer for each parsed event."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            # update last_event_summary for the UI
            job.last_event_summary = _summarize_event(event)
        # call the SSE hook outside the lock
        if self._on_state_change:
            try:
                self._on_state_change(job_id, event)
            except Exception:
                pass
```

Add module-level helper:
```python
def _summarize_event(event: dict) -> str:
    """Compact human-readable summary like 'MC 320/500'."""
    t = event.get("type", "")
    stage = event.get("stage", "")
    if t == "progress" and "i" in event and "total" in event:
        return f"{stage} {event['i']}/{event['total']}"
    if t == "start":
        return f"{stage} starting"
    if t == "complete":
        return f"{stage} done"
    if t == "done":
        return "done"
    if t == "error":
        return "error"
    return ""
```

- [ ] **Step 2: Add test**

Append to `tests/web/test_jobs.py`:

```python
def test_progress_events_update_last_event_summary(jm):
    job_id, _ = jm.submit("momo", "run", _fake_argv("happy_with_progress"))
    assert jm.wait_for_terminal(job_id, timeout=10)
    j = jm.get(job_id)
    # The last summary depends on the script — happy_with_progress ends with done
    assert j.last_event_summary in ("monte_carlo done", "done")
```

- [ ] **Step 3: Run**

```bash
pytest tests/web/test_jobs.py::test_progress_events_update_last_event_summary -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/jobs.py tests/web/test_jobs.py && git commit -m "feat(web): wire ProgressTailer into JobManager lifecycle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4: SSE broadcaster (`tradelab.web.sse`)

A simple SSE pub-sub. Connected EventSource clients are kept in a list; broadcast iterates the list, formats each event in the SSE wire format (`data: {...}\n\n`), and writes to each client's `wfile`. Broken-pipe errors prune dead clients.

### Task 4.1: Test + implement core broadcast

**Files:**
- Create: `src/tradelab/web/sse.py`
- Create: `tests/web/test_sse.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/web/test_sse.py
"""Tests for the SSE broadcaster."""
from __future__ import annotations

import io
import json
import threading
import time

from tradelab.web import sse


class FakeWfile:
    """Minimal wfile substitute that captures writes."""
    def __init__(self, raise_after_n: int | None = None):
        self.buffer = io.BytesIO()
        self.writes = 0
        self.raise_after_n = raise_after_n

    def write(self, data: bytes) -> int:
        self.writes += 1
        if self.raise_after_n is not None and self.writes > self.raise_after_n:
            raise BrokenPipeError("simulated client disconnect")
        return self.buffer.write(data)

    def flush(self) -> None:
        pass


def test_broadcaster_starts_with_no_clients():
    b = sse.Broadcaster()
    assert b.client_count() == 0


def test_subscribe_returns_connection_token_increments_count():
    b = sse.Broadcaster()
    wf = FakeWfile()
    token = b.subscribe(wf)
    assert b.client_count() == 1
    b.unsubscribe(token)
    assert b.client_count() == 0


def test_broadcast_writes_sse_formatted_event_to_all_clients():
    b = sse.Broadcaster()
    wf1 = FakeWfile()
    wf2 = FakeWfile()
    b.subscribe(wf1)
    b.subscribe(wf2)
    b.broadcast({"job_id": "abc", "event": {"type": "start", "stage": "backtest"}})
    out1 = wf1.buffer.getvalue().decode()
    out2 = wf2.buffer.getvalue().decode()
    assert out1.startswith("data: ")
    assert out1.endswith("\n\n")
    assert "abc" in out1 and "backtest" in out1
    assert out1 == out2


def test_broken_pipe_removes_client_from_list():
    b = sse.Broadcaster()
    wf_good = FakeWfile()
    wf_bad = FakeWfile(raise_after_n=0)  # raises on first write
    b.subscribe(wf_good)
    b.subscribe(wf_bad)
    assert b.client_count() == 2
    b.broadcast({"job_id": "abc", "event": {"type": "start"}})
    # Bad client should be pruned; good one remains
    assert b.client_count() == 1


def test_initial_state_replay_sends_one_event_per_active_job():
    b = sse.Broadcaster()
    wf = FakeWfile()
    b.subscribe(wf, initial_state=[
        {"job_id": "a", "event": {"type": "state", "status": "running", "summary": "MC 100/500"}},
        {"job_id": "b", "event": {"type": "state", "status": "queued"}},
    ])
    out = wf.buffer.getvalue().decode()
    # retry hint at top, then 2 data events
    assert out.startswith("retry: 3000\n\n")
    assert out.count("data: ") == 2


def test_concurrent_broadcast_modification_safe():
    """Subscribing while broadcast iterates must not raise."""
    b = sse.Broadcaster()
    for _ in range(10):
        b.subscribe(FakeWfile())
    errs = []
    def writer():
        try:
            for _ in range(100):
                b.broadcast({"job_id": "a", "event": {"type": "tick"}})
        except Exception as e:
            errs.append(e)
    def subscriber():
        try:
            for _ in range(100):
                b.subscribe(FakeWfile())
                time.sleep(0.001)
        except Exception as e:
            errs.append(e)
    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=subscriber)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert errs == []
```

- [ ] **Step 2: Implement `sse.py`**

```python
# src/tradelab/web/sse.py
"""SSE (Server-Sent Events) broadcaster for the Job Tracker.

Each subscriber is an HTTP response wfile that the server keeps open.
Broadcast iterates a snapshot of the subscriber list (not the live list)
to remain safe under concurrent subscribe()/unsubscribe().
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Optional


SSE_RETRY_MS = 3000


class Broadcaster:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients: dict[str, Any] = {}  # token -> wfile

    def subscribe(self, wfile: Any, initial_state: Optional[list[dict]] = None) -> str:
        """Add a client. Optionally replay an initial state to that client only.

        Returns a token to use with unsubscribe().
        """
        token = uuid.uuid4().hex
        with self._lock:
            self._clients[token] = wfile

        # Send retry hint + any initial state events to this client only.
        try:
            wfile.write(f"retry: {SSE_RETRY_MS}\n\n".encode("utf-8"))
            if initial_state:
                for ev in initial_state:
                    wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
            try:
                wfile.flush()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError, OSError):
            with self._lock:
                self._clients.pop(token, None)
            return token  # caller can still unsubscribe — it's idempotent

        return token

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._clients.pop(token, None)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, event: dict) -> None:
        """Write one SSE-formatted event to every connected client.

        Iterates a snapshot of the client list so concurrent subscribe()
        does not raise. Broken-pipe clients are pruned during the write.
        """
        payload = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        with self._lock:
            snapshot = list(self._clients.items())

        dead: list[str] = []
        for token, wfile in snapshot:
            try:
                wfile.write(payload)
                try:
                    wfile.flush()
                except Exception:
                    pass
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.append(token)

        if dead:
            with self._lock:
                for t in dead:
                    self._clients.pop(t, None)
```

- [ ] **Step 3: Run all 6 SSE tests**

```bash
pytest tests/web/test_sse.py -v
```

Expected: 6 PASSED.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/sse.py tests/web/test_sse.py && git commit -m "feat(web): SSE broadcaster with broken-pipe pruning

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4.2: Wire Broadcaster into JobManager state-change hook

**Files:**
- Modify: `src/tradelab/web/jobs.py`
- Modify: `src/tradelab/web/__init__.py` (export module-level singletons)

- [ ] **Step 1: Add module-level singletons**

Append to `src/tradelab/web/__init__.py` (or create if minimal):

```python
"""tradelab.web — web dashboard backend modules."""
from __future__ import annotations

from pathlib import Path

from . import audit_reader, freshness, handlers, new_strategy, ranges, whatif  # noqa: F401
from .jobs import JobManager
from .sse import Broadcaster

# Module-level singletons used by handlers.py.
# Cache root is .cache/ relative to current working directory; launch_dashboard.py
# chdirs to the tradelab repo root before importing handlers, so this resolves to
# tradelab/.cache/.
_broadcaster = Broadcaster()
_job_manager: JobManager | None = None


def get_broadcaster() -> Broadcaster:
    return _broadcaster


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager(cache_root=Path(".cache"))
        # wire JobManager → Broadcaster on every event
        def _broadcast_event(job_id: str, event: dict) -> None:
            _broadcaster.broadcast({"job_id": job_id, "event": event})
        _job_manager._on_state_change = _broadcast_event
    return _job_manager
```

- [ ] **Step 2: No new tests (this is wiring; covered by integration tests in Phase 5)**

- [ ] **Step 3: Smoke check imports work**

```bash
cd /c/TradingScripts/tradelab && python -c "from tradelab.web import get_job_manager, get_broadcaster; print(get_broadcaster().client_count())"
```

Expected: `0`.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/__init__.py && git commit -m "feat(web): module-level singletons wire JobManager to Broadcaster

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5: HTTP routes (`handlers.py` + `launch_dashboard.py`)

Add `handle_post_with_status` parallel to the existing `handle_get_with_status`. Add 4 new branches: POST start job, GET list jobs, POST cancel job, GET stream (SSE).

### Task 5.1: Test + implement POST `/tradelab/jobs` (start)

**Files:**
- Create: `tests/web/test_handlers_jobs.py`
- Modify: `src/tradelab/web/handlers.py`

- [ ] **Step 1: Failing test**

```python
# tests/web/test_handlers_jobs.py
"""Tests for the /tradelab/jobs HTTP handlers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tradelab.web import handlers, get_job_manager


@pytest.fixture(autouse=True)
def fresh_job_manager(tmp_path, monkeypatch):
    """Replace the module singleton with a tmp-rooted JobManager per test."""
    from tradelab.web import jobs
    cache = tmp_path / ".cache"
    cache.mkdir()
    jm = jobs.JobManager(cache_root=cache)

    # Patch the singleton reference
    import tradelab.web as web_pkg
    monkeypatch.setattr(web_pkg, "_job_manager", jm)
    # Also wire to the broadcaster
    bc = web_pkg.get_broadcaster()
    jm._on_state_change = lambda jid, ev: bc.broadcast({"job_id": jid, "event": ev})
    yield jm


def _fake_argv():
    return [sys.executable, str(Path(__file__).parent / "_fake_cli.py"), "--script", "happy_short"]


def test_post_jobs_creates_job_returns_201(fresh_job_manager, monkeypatch):
    # Patch the argv builder used by handlers
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda strategy, command: _fake_argv())

    body = json.dumps({"strategy": "momo", "command": "run --robustness"}).encode()
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 201
    payload = json.loads(body_str)
    assert payload["error"] is None
    assert "job_id" in payload["data"]
    assert payload["data"]["status"] in ("running", "queued")
    fresh_job_manager.wait_for_terminal(payload["data"]["job_id"], timeout=10)


def test_post_jobs_invalid_command_returns_400(fresh_job_manager):
    body = json.dumps({"strategy": "momo", "command": "rm -rf /"}).encode()
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 400
    payload = json.loads(body_str)
    assert "invalid command" in payload["error"].lower()


def test_post_jobs_missing_fields_returns_400(fresh_job_manager):
    body = json.dumps({"strategy": "momo"}).encode()  # missing command
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 400


def test_post_jobs_duplicate_returns_409(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    body = json.dumps({"strategy": "momo", "command": "run --robustness"}).encode()
    _, status1 = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status1 == 201

    body_str2, status2 = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status2 == 409
    payload = json.loads(body_str2)
    assert "existing_job_id" in payload["data"]

    # Cleanup
    fresh_job_manager.cancel(payload["data"]["existing_job_id"])
```

- [ ] **Step 2: Run, expect import error first**

```bash
pytest tests/web/test_handlers_jobs.py::test_post_jobs_creates_job_returns_201 -v
```

Expected: `AttributeError: module 'tradelab.web.handlers' has no attribute 'handle_post_with_status'`.

- [ ] **Step 3: Implement `handle_post_with_status` and the new route in handlers.py**

In `src/tradelab/web/handlers.py`, add at module level:

```python
# Allowed (strategy-agnostic) commands the web tracker can launch.
# Maps "run --robustness" → ["run", "--robustness"] argv tail.
_ALLOWED_COMMANDS = {
    "optimize":         ["optimize"],
    "wf":               ["wf"],
    "run":              ["run"],
    "run --robustness": ["run", "--robustness"],
    "run --full":       ["run", "--full"],
}


def _build_tradelab_argv(strategy: str, command: str) -> list[str] | None:
    """Build the subprocess argv for a (strategy, command) pair.

    Returns None if the command is not in _ALLOWED_COMMANDS.
    Strategy must match a-z0-9_ pattern (no shell metacharacters).
    """
    if command not in _ALLOWED_COMMANDS:
        return None
    if not re.match(r"^[a-z0-9_]+$", strategy):
        return None
    cmd_argv = _ALLOWED_COMMANDS[command]
    # tradelab CLI is `python -m tradelab.cli <subcommand> <strategy> [flags]`
    return [sys.executable, "-m", "tradelab.cli", cmd_argv[0], strategy, *cmd_argv[1:]]
```

Then add the new dispatcher:

```python
def handle_post_with_status(path: str, body: bytes) -> Tuple[str, int]:
    """POST dispatcher with explicit status. Mirrors handle_get_with_status.

    Routes that need explicit status codes (201/400/409/410) live here.
    Other POSTs delegate to the legacy handle_post() for backward compat.
    """
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    if path == "/tradelab/jobs":
        return _post_job(payload)

    if path.startswith("/tradelab/jobs/") and path.endswith("/cancel"):
        job_id = path[len("/tradelab/jobs/"):-len("/cancel")]
        return _cancel_job(job_id)

    # Fallback to legacy POST dispatcher for everything else
    return handle_post(path, body), 200


def _post_job(payload: dict) -> Tuple[str, int]:
    from tradelab.web import get_job_manager
    from tradelab.web import jobs as jobs_mod

    strategy = payload.get("strategy", "")
    command = payload.get("command", "")
    if not strategy or not command:
        return _err("strategy and command required"), 400

    argv = _build_tradelab_argv(strategy, command)
    if argv is None:
        return _err(f"invalid command or strategy name: {command!r} / {strategy!r}"), 400

    jm = get_job_manager()
    try:
        job_id, status = jm.submit(strategy, command, argv)
    except jobs_mod.DuplicateJobError as e:
        return _err("job already in flight",
                    data={"existing_job_id": e.existing_job_id}), 409

    return _ok({
        "job_id": job_id,
        "status": status.value,
    }), 201


def _cancel_job(job_id: str) -> Tuple[str, int]:
    from tradelab.web import get_job_manager
    jm = get_job_manager()
    job = jm.get(job_id)
    if job is None:
        return _err("job not found"), 404
    if job.status.value not in ("queued", "running"):
        return _err(f"job is in terminal state {job.status.value!r}"), 410
    jm.cancel(job_id)
    return _ok({"job_id": job_id, "status": "cancelled"}), 200
```

- [ ] **Step 4: Run all the test_handlers_jobs tests for POST**

```bash
pytest tests/web/test_handlers_jobs.py -v -k "post or duplicate or invalid or missing"
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/handlers.py tests/web/test_handlers_jobs.py && git commit -m "feat(web): POST /tradelab/jobs route with allow-list, dedupe, status codes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.2: Test + implement GET `/tradelab/jobs` (list)

**Files:**
- Modify: `tests/web/test_handlers_jobs.py`
- Modify: `src/tradelab/web/handlers.py`

- [ ] **Step 1: Add test**

```python
def test_get_jobs_returns_active_and_recent(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda s, c: _fake_argv())
    # Submit one job, let it finish
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    fresh_job_manager.wait_for_terminal(job_id, timeout=10)

    body_str, status = handlers.handle_get_with_status("/tradelab/jobs")
    assert status == 200
    payload = json.loads(body_str)
    jobs_list = payload["data"]["jobs"]
    assert any(j["id"] == job_id for j in jobs_list)
```

- [ ] **Step 2: Add GET branch to `handle_get_with_status`**

In `src/tradelab/web/handlers.py`, in the `handle_get_with_status` function, add:

```python
    if path == "/tradelab/jobs":
        from tradelab.web import get_job_manager
        jm = get_job_manager()
        return _ok({
            "jobs": [j.to_dict() for j in jm.list_jobs()],
            "running_id": jm._running_id,
            "queue": list(jm._queue),
        }), 200
```

- [ ] **Step 3: Run**

```bash
pytest tests/web/test_handlers_jobs.py::test_get_jobs_returns_active_and_recent -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/handlers.py tests/web/test_handlers_jobs.py && git commit -m "feat(web): GET /tradelab/jobs route returns full state

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.3: Test + implement POST `/tradelab/jobs/<id>/cancel`

**Files:**
- Modify: `tests/web/test_handlers_jobs.py`

- [ ] **Step 1: Add tests** (cancel logic was already added in Task 5.1's `handle_post_with_status`)

```python
def test_post_cancel_running_job_returns_200(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    import time; time.sleep(0.3)

    body_str, status = handlers.handle_post_with_status(f"/tradelab/jobs/{job_id}/cancel", b"")
    assert status == 200
    fresh_job_manager.wait_for_terminal(job_id, timeout=5)
    assert fresh_job_manager.get(job_id).status.value == "cancelled"


def test_post_cancel_done_job_returns_410(fresh_job_manager, monkeypatch):
    monkeypatch.setattr(handlers, "_build_tradelab_argv", lambda s, c: _fake_argv())
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    body_str, _ = handlers.handle_post_with_status("/tradelab/jobs", body)
    job_id = json.loads(body_str)["data"]["job_id"]
    fresh_job_manager.wait_for_terminal(job_id, timeout=10)

    body_str, status = handlers.handle_post_with_status(f"/tradelab/jobs/{job_id}/cancel", b"")
    assert status == 410


def test_post_cancel_unknown_job_returns_404(fresh_job_manager):
    body_str, status = handlers.handle_post_with_status("/tradelab/jobs/does-not-exist/cancel", b"")
    assert status == 404
```

- [ ] **Step 2: Run**

```bash
pytest tests/web/test_handlers_jobs.py -v -k "cancel"
```

Expected: 3 PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/web/test_handlers_jobs.py && git commit -m "test(web): cover POST cancel for running, done, unknown jobs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.4: Implement SSE handler

**Files:**
- Modify: `src/tradelab/web/handlers.py`
- Modify: `tests/web/test_handlers_jobs.py`

- [ ] **Step 1: Add `handle_sse` to handlers.py**

In `src/tradelab/web/handlers.py`, append:

```python
def handle_sse(wfile) -> None:
    """SSE endpoint for /tradelab/jobs/stream.

    Called by launch_dashboard.py's do_GET branch directly. Subscribes the
    connection to the broadcaster and blocks until the client disconnects.

    The caller (HTTP server) is responsible for sending the response headers
    (200 OK, Content-Type: text/event-stream, Cache-Control: no-cache,
    Connection: keep-alive) before invoking this.
    """
    from tradelab.web import get_broadcaster, get_job_manager

    bc = get_broadcaster()
    jm = get_job_manager()

    # Build the initial-state replay: one synthetic event per active job
    initial_state = []
    for j in jm.list_jobs():
        if j.status.value in ("running", "queued"):
            initial_state.append({
                "job_id": j.id,
                "event": {
                    "type": "state",
                    "status": j.status.value,
                    "summary": j.last_event_summary or "",
                    "strategy": j.strategy,
                    "command": j.command,
                },
            })

    token = bc.subscribe(wfile, initial_state=initial_state)
    # Block until the client disconnects. The subscribe() call already wrote
    # the retry hint + initial state. We need to keep this thread blocking
    # so the http.server doesn't close the connection.
    import threading
    stop = threading.Event()
    # When broadcast prunes us (broken pipe), we'll know via client_count;
    # poll occasionally to detect that, or wait for an explicit shutdown.
    while not stop.is_set():
        if not bc.is_subscribed(token):
            break
        stop.wait(timeout=1.0)
    bc.unsubscribe(token)
```

- [ ] **Step 2: Add `is_subscribed` to Broadcaster**

In `src/tradelab/web/sse.py`, add to `Broadcaster`:

```python
    def is_subscribed(self, token: str) -> bool:
        with self._lock:
            return token in self._clients
```

And add a test for it in `tests/web/test_sse.py`:

```python
def test_is_subscribed_returns_true_for_active_token():
    b = sse.Broadcaster()
    wf = FakeWfile()
    token = b.subscribe(wf)
    assert b.is_subscribed(token) is True
    b.unsubscribe(token)
    assert b.is_subscribed(token) is False
```

- [ ] **Step 3: Add SSE smoke test in test_handlers_jobs.py**

```python
def test_handle_sse_writes_retry_hint_and_initial_state(fresh_job_manager, monkeypatch):
    """Sanity: subscribing to SSE writes the retry hint and replays state."""
    import io, threading
    monkeypatch.setattr(handlers, "_build_tradelab_argv",
                        lambda s, c: [sys.executable, str(Path(__file__).parent / "_fake_cli.py"),
                                      "--script", "long_running"])
    # Submit one job so initial_state is non-empty
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    handlers.handle_post_with_status("/tradelab/jobs", body)
    import time; time.sleep(0.2)

    # Use a buffered wfile substitute. handle_sse blocks, so run in a thread
    # and "disconnect" by removing the subscription.
    class W:
        def __init__(self): self.buf = io.BytesIO(); self.writes = 0
        def write(self, b): self.writes += 1; return self.buf.write(b)
        def flush(self): pass

    wf = W()
    t = threading.Thread(target=handlers.handle_sse, args=(wf,), daemon=True)
    t.start()
    time.sleep(0.3)  # let subscribe + initial-state writes happen

    out = wf.buf.getvalue().decode()
    assert "retry: 3000" in out
    assert "data: " in out  # at least the one running job

    # Force unsubscribe by clearing all clients
    from tradelab.web import get_broadcaster
    get_broadcaster()._clients.clear()
    t.join(timeout=2)

    # Cleanup the long_running job
    for j in fresh_job_manager.list_jobs():
        if j.status.value == "running":
            fresh_job_manager.cancel(j.id)
            fresh_job_manager.wait_for_terminal(j.id, timeout=5)
```

- [ ] **Step 4: Run all SSE tests**

```bash
pytest tests/web/test_sse.py tests/web/test_handlers_jobs.py::test_handle_sse_writes_retry_hint_and_initial_state -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/handlers.py src/tradelab/web/sse.py tests/web/test_sse.py tests/web/test_handlers_jobs.py && git commit -m "feat(web): SSE endpoint handler with initial-state replay

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.5: Wire new routes into launch_dashboard.py

**Files:**
- Modify: `C:\TradingScripts\launch_dashboard.py`

- [ ] **Step 1: Switch `dispatch_tradelab_post` to use `handle_post_with_status`**

Find `dispatch_tradelab_post` in `C:\TradingScripts\launch_dashboard.py` (around line 126). Replace its body with:

```python
    def dispatch_tradelab_post(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            body_out, status = _handlers.handle_post_with_status(self.path, body)
        except Exception as e:
            body_out = _handlers._err(f"server error: {e}")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_out.encode())))
        self.end_headers()
        self.wfile.write(body_out.encode())
```

- [ ] **Step 2: Add SSE branch to `do_GET`**

In the `do_GET` method, before the existing `/tradelab/` branch, add a special case for the SSE stream:

```python
            if self.path == "/tradelab/jobs/stream":
                self.dispatch_tradelab_sse()
                return
```

Then add the new method after `serve_tradelab_static`:

```python
    def dispatch_tradelab_sse(self):
        """SSE endpoint — keeps connection open and streams events."""
        if _handlers is None:
            self.send_error(503, "tradelab not loaded")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            _handlers.handle_sse(self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected — normal
```

- [ ] **Step 3: Smoke test by starting the dashboard**

```bash
cd /c/TradingScripts && python launch_dashboard.py --no-browser &
sleep 3
# POST a job
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"strategy":"momo","command":"run"}' \
  http://localhost:8877/tradelab/jobs
echo
# List jobs
curl -s http://localhost:8877/tradelab/jobs | python -m json.tool | head -30
kill %1
```

Expected: POST returns `{"error":null,"data":{"job_id":"...","status":"running"|"queued"}}` (or 400 if `momo` strategy isn't actually registered — that's also fine, just means the subprocess fails fast). GET shows the submitted job.

If the actual subprocess fails (because `momo` isn't a real strategy), the job will appear with `status: "failed"` and `error_tail` set — this is the correct behavior.

- [ ] **Step 4: Commit**

(`launch_dashboard.py` lives at `C:\TradingScripts\` which is NOT a git repo. No commit. Just retain the backup from Task 0.3.)

### Task 5.6: Backward-compat probe for old tradelab

**Files:**
- Modify: `src/tradelab/web/handlers.py` OR `C:\TradingScripts\launch_dashboard.py`

- [ ] **Step 1: Add startup probe in `tradelab.web.__init__`**

In `src/tradelab/web/__init__.py`, append a probe function:

```python
def supports_progress_log() -> bool:
    """Return True if the installed tradelab CLI knows the --progress-log flag.

    Cached on first call. Used by handlers to short-circuit POST /tradelab/jobs
    with 503 if the local tradelab is too old.
    """
    global _supports_pl
    try:
        return _supports_pl  # type: ignore[name-defined]
    except NameError:
        pass
    import subprocess as _sp
    import sys as _sys
    try:
        out = _sp.run(
            [_sys.executable, "-m", "tradelab.cli", "run", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        _supports_pl = "--progress-log" in (out.stdout + out.stderr)
    except Exception:
        _supports_pl = False
    return _supports_pl
```

- [ ] **Step 2: Use it in `_post_job`**

In `src/tradelab/web/handlers.py`, at the top of `_post_job`:

```python
def _post_job(payload: dict) -> Tuple[str, int]:
    from tradelab.web import get_job_manager, supports_progress_log
    from tradelab.web import jobs as jobs_mod

    if not supports_progress_log():
        return _err(
            "this tradelab build is missing --progress-log; rebuild from current master"
        ), 503
    # ... rest unchanged
```

- [ ] **Step 3: Add test**

In `tests/web/test_handlers_jobs.py`:

```python
def test_post_jobs_returns_503_if_progress_log_unsupported(fresh_job_manager, monkeypatch):
    import tradelab.web as web_pkg
    monkeypatch.setattr(web_pkg, "supports_progress_log", lambda: False)
    body = json.dumps({"strategy": "momo", "command": "run"}).encode()
    _, status = handlers.handle_post_with_status("/tradelab/jobs", body)
    assert status == 503
```

- [ ] **Step 4: Run**

```bash
pytest tests/web/test_handlers_jobs.py::test_post_jobs_returns_503_if_progress_log_unsupported -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/__init__.py src/tradelab/web/handlers.py tests/web/test_handlers_jobs.py && git commit -m "feat(web): backward-compat probe — POST jobs returns 503 if --progress-log unsupported

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5.7: Run the full backend test suite

- [ ] **Step 1: Run tests/web/ + tests/cli/test_progress_log.py**

```bash
pytest tests/web/ tests/cli/test_progress_log.py -v
```

Expected: ~70 passing (29 v1 baseline + ~41 new). 1 known flaky (`test_whatif_returns_metrics_and_equity_curve`).

If any new test fails, debug before moving to frontend work — frontend changes assume the backend is solid.

---

## Phase 6: Frontend (`command_center.html`)

All changes scoped to the existing Research tab in `C:\TradingScripts\command_center.html`. No new tabs, no edits to the other 4 tabs, no edits to safety mechanisms.

### Task 6.1: Add Job Tracker panel HTML + CSS

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Locate the Research tab content container**

```bash
grep -n "id=\"tab-research\"\|tab-research\|research-tab" /c/TradingScripts/command_center.html | head -10
```

Note the line number where the Research tab content begins.

- [ ] **Step 2: Add the Job Tracker panel as the FIRST child of the Research tab**

Insert this block immediately after the freshness banner block in the Research tab:

```html
<!-- v1.5: Job Tracker Panel -->
<section id="research-job-tracker" class="research-section" hidden>
  <header class="research-section-header">
    <h2>Active Jobs <span id="job-tracker-count" class="research-pill">0</span></h2>
    <span class="research-meta" id="job-tracker-status">idle</span>
  </header>
  <div id="job-tracker-list"></div>
</section>
```

- [ ] **Step 3: Add CSS for the panel**

In the `<style>` section of `command_center.html`, append:

```css
/* v1.5: Job Tracker */
#research-job-tracker {
  background: #1f2937;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
  border: 1px solid #374151;
}
#research-job-tracker[hidden] { display: none; }
.job-row {
  display: grid;
  grid-template-columns: 1fr 80px 100px 80px;
  gap: 12px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #374151;
}
.job-row:last-child { border-bottom: 0; }
.job-row .strategy { font-weight: 600; }
.job-row .command { color: #94a3b8; font-size: 0.85em; font-family: monospace; }
.job-row .progress-text { color: #94a3b8; font-size: 0.85em; }
.job-row .progress-bar {
  background: #0f1117; border-radius: 3px; height: 6px; overflow: hidden;
}
.job-row .progress-bar > .fill {
  background: #22c55e; height: 100%; transition: width 200ms;
}
.job-row .status-pill {
  padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: 600;
}
.status-pill.running   { background: #22c55e; color: #0f1117; }
.status-pill.queued    { background: #374151; color: #94a3b8; }
.status-pill.done      { background: #1e3a8a; color: #dbeafe; }
.status-pill.failed    { background: #7f1d1d; color: #fee2e2; }
.status-pill.cancelled { background: #57534e; color: #d6d3d1; }
.status-pill.interrupted { background: #78350f; color: #fed7aa; }
.cancel-btn {
  background: #7f1d1d; color: #fee2e2; border: 0; padding: 4px 10px;
  border-radius: 4px; cursor: pointer; font-size: 0.78em;
}
.cancel-btn:hover { background: #991b1b; }
.cancel-btn:disabled { opacity: 0.4; cursor: not-allowed; }
```

- [ ] **Step 4: Reload browser, confirm panel appears (empty)**

Visit `http://localhost:8877/#tab=research`. The Job Tracker section should be present in the DOM but `hidden` until at least one job exists. (We'll wire the show/hide and rendering in Task 6.5.)

### Task 6.2: Add Run dropdown to Live Strategy cards

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Locate the Live Strategy card template**

```bash
grep -n "live-strategy-card\|LIVE_TO_TRADELAB\|renderLiveCard" /c/TradingScripts/command_center.html | head -10
```

- [ ] **Step 2: Add the [Run ▾] dropdown to the card markup**

In the card template (or render function), add after the existing `[Dash][QS]` button row:

```html
<div class="card-actions">
  <button class="card-btn" data-action="dashboard">Dash</button>
  <button class="card-btn" data-action="qs">QS</button>
  <details class="run-dropdown" data-strategy="${strategy}">
    <summary class="card-btn run-btn">Run ▾</summary>
    <div class="run-menu">
      <button data-cmd="optimize">Optimize (1)</button>
      <button data-cmd="wf">Walk-forward (2)</button>
      <button data-cmd="run">Run (3)</button>
      <button data-cmd="run --robustness">Robustness (3r)</button>
      <button data-cmd="run --full" class="run-3f">Full (3f) — 10 min</button>
    </div>
  </details>
</div>
```

- [ ] **Step 3: Add CSS for the dropdown**

```css
.run-dropdown { position: relative; display: inline-block; }
.run-dropdown summary { list-style: none; cursor: pointer; }
.run-dropdown summary::-webkit-details-marker { display: none; }
.run-btn {
  background: #22c55e; color: #0f1117; font-weight: 600;
  padding: 4px 10px; border-radius: 4px;
}
.run-menu {
  position: absolute; top: 100%; right: 0; background: #1f2937;
  border: 1px solid #374151; border-radius: 6px; padding: 4px 0;
  min-width: 180px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  z-index: 10;
}
.run-menu button {
  display: block; width: 100%; text-align: left; background: transparent;
  border: 0; color: #e2e8f0; padding: 8px 12px; cursor: pointer;
  font-size: 0.85em;
}
.run-menu button:hover { background: #374151; }
.run-menu button.run-3f { border-top: 1px solid #374151; }
```

- [ ] **Step 4: Reload, click around — verify the dropdown opens/closes (no submit yet)**

### Task 6.3: Add Run button to Pipeline strategy groups

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Locate the Pipeline table row template**

```bash
grep -n "renderPipelineRow\|pipeline-row\|tradelab/runs" /c/TradingScripts/command_center.html | head -10
```

- [ ] **Step 2: Group rows by strategy in the render function**

Modify the rendering JS so that the FIRST row of each strategy gets a `[Run ▾]` button in a new column (or merged with an existing column). Subsequent rows in the same strategy show an empty cell.

Pseudocode:

```javascript
let prevStrategy = null;
runs.forEach(run => {
  const showRun = run.strategy !== prevStrategy;
  const cell = showRun
    ? `<details class="run-dropdown" data-strategy="${run.strategy}">
         <summary class="card-btn run-btn">Run ▾</summary>
         <div class="run-menu">
           <button data-cmd="optimize">Optimize (1)</button>
           <button data-cmd="wf">Walk-forward (2)</button>
           <button data-cmd="run">Run (3)</button>
           <button data-cmd="run --robustness">Robustness (3r)</button>
           <button data-cmd="run --full" class="run-3f">Full (3f)</button>
         </div>
       </details>`
    : '';
  // ... existing row markup, with cell appended
  prevStrategy = run.strategy;
});
```

- [ ] **Step 3: Reload, verify only one Run dropdown per unique strategy in the visible page**

### Task 6.4: 3f confirmation modal

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add modal markup at the bottom of the body**

```html
<div id="modal-3f-confirm" class="modal-overlay" hidden>
  <div class="modal-dialog">
    <h3>Full pipeline — confirm</h3>
    <p>This runs <code>--full</code>: Optuna + walk-forward + cost-sweep + robustness.
    Typical duration is <strong>~10 minutes</strong>.</p>
    <p>Proceed?</p>
    <div class="modal-actions">
      <button id="modal-3f-cancel" class="card-btn">Cancel</button>
      <button id="modal-3f-confirm" class="run-btn">Run --full</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add CSS**

```css
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal-overlay[hidden] { display: none; }
.modal-dialog {
  background: #1f2937; padding: 24px 28px; border-radius: 8px;
  max-width: 440px; border: 1px solid #374151;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 16px; }
```

### Task 6.5: EventSource client + DOM update wiring

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add the JS state + fetcher**

In the `<script>` section of the Research tab JS:

```javascript
// v1.5: Job Tracker state
const jobState = {
  jobs: new Map(),  // job_id -> {strategy, command, status, summary}
  eventSource: null,
};

async function refreshJobs() {
  const r = await fetch('/tradelab/jobs');
  const j = await r.json();
  jobState.jobs.clear();
  for (const job of (j.data?.jobs || [])) {
    jobState.jobs.set(job.id, {
      strategy: job.strategy,
      command: job.command,
      status: job.status,
      summary: job.last_event_summary || '',
    });
  }
  renderJobTracker();
}

function renderJobTracker() {
  const panel = document.getElementById('research-job-tracker');
  const list = document.getElementById('job-tracker-list');
  const count = document.getElementById('job-tracker-count');
  const active = [...jobState.jobs.values()].filter(j => j.status === 'running' || j.status === 'queued');
  count.textContent = active.length;
  panel.hidden = jobState.jobs.size === 0;

  // Render newest-first; active before terminal
  const sorted = [...jobState.jobs.entries()].sort(([, a], [, b]) => {
    const order = { running: 0, queued: 1, failed: 2, interrupted: 3, cancelled: 4, done: 5 };
    return (order[a.status] ?? 9) - (order[b.status] ?? 9);
  });
  list.innerHTML = sorted.map(([id, j]) => `
    <div class="job-row">
      <div>
        <span class="strategy">${j.strategy}</span>
        <span class="command">${j.command}</span>
        <div class="progress-text">${j.summary || '—'}</div>
      </div>
      <div class="progress-bar"><div class="fill" style="width:${guessPct(j.summary)}%"></div></div>
      <span class="status-pill ${j.status}">${j.status}</span>
      <button class="cancel-btn" data-job-id="${id}"
        ${(j.status !== 'running' && j.status !== 'queued') ? 'disabled' : ''}>
        Cancel
      </button>
    </div>
  `).join('');
}

function guessPct(summary) {
  // Parse "MC 320/500" -> 64
  const m = (summary || '').match(/(\d+)\/(\d+)/);
  if (!m) return 0;
  return Math.round(100 * parseInt(m[1]) / parseInt(m[2]));
}

function startEventSource() {
  if (jobState.eventSource) return;
  jobState.eventSource = new EventSource('/tradelab/jobs/stream');
  jobState.eventSource.onmessage = (msg) => {
    let payload;
    try { payload = JSON.parse(msg.data); } catch { return; }
    const { job_id, event } = payload;
    let job = jobState.jobs.get(job_id);
    if (!job) {
      // Unknown job — refetch full list
      refreshJobs();
      return;
    }
    if (event.type === 'progress' || event.type === 'start' || event.type === 'complete') {
      job.summary = summarizeEvent(event);
    } else if (event.type === 'state') {
      job.status = event.status;
      job.summary = event.summary || '';
    } else if (event.type === 'done') {
      job.status = (event.exit === 0) ? 'done' : 'failed';
      // After a job finishes, refresh the Pipeline so the new row appears
      if (typeof refreshPipeline === 'function') refreshPipeline();
    } else if (event.type === 'error') {
      job.status = 'failed';
      job.summary = event.message || 'error';
    }
    renderJobTracker();
  };
  jobState.eventSource.onerror = () => {
    // EventSource auto-reconnects; nothing to do
  };
}

function summarizeEvent(event) {
  if (event.type === 'progress') return `${event.stage} ${event.i}/${event.total}`;
  if (event.type === 'start') return `${event.stage} starting`;
  if (event.type === 'complete') return `${event.stage} done`;
  return '';
}

// Boot
document.addEventListener('DOMContentLoaded', () => {
  refreshJobs();
  startEventSource();
});
```

- [ ] **Step 2: Reload browser, open DevTools Network tab, verify EventSource connection to `/tradelab/jobs/stream`**

Expected: `EventSource` connection in Network tab, type `eventsource`. Status: `pending` (kept open). Headers show `Content-Type: text/event-stream`.

### Task 6.6: Wire Run dropdown clicks → POST + 3f confirmation

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add click delegation for run buttons**

```javascript
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.run-menu button');
  if (!btn) return;
  const dropdown = btn.closest('.run-dropdown');
  const strategy = dropdown.dataset.strategy;
  const command = btn.dataset.cmd;
  // Close the dropdown
  dropdown.removeAttribute('open');

  if (command === 'run --full') {
    // Show 3f confirmation modal
    const modal = document.getElementById('modal-3f-confirm');
    modal.hidden = false;
    document.getElementById('modal-3f-cancel').onclick = () => { modal.hidden = true; };
    document.getElementById('modal-3f-confirm').onclick = async () => {
      modal.hidden = true;
      await submitJob(strategy, command);
    };
    return;
  }
  await submitJob(strategy, command);
});

async function submitJob(strategy, command) {
  const r = await fetch('/tradelab/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strategy, command }),
  });
  if (r.status === 409) {
    toast(`Already queued for ${strategy}`);
    return;
  }
  if (r.status === 503) {
    toast(`tradelab CLI is missing --progress-log; rebuild required`);
    return;
  }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    toast(`Failed: ${j.error || r.status}`);
    return;
  }
  await refreshJobs();
}

// Reuse existing toast() if defined; otherwise add:
function toast(msg) {
  let el = document.getElementById('research-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'research-toast';
    el.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1f2937;border:1px solid #374151;color:#e2e8f0;padding:10px 18px;border-radius:6px;z-index:200;';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 3500);
}
```

### Task 6.7: Wire cancel button

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add cancel handler**

```javascript
document.addEventListener('click', async (e) => {
  if (!e.target.classList.contains('cancel-btn')) return;
  const jobId = e.target.dataset.jobId;
  e.target.disabled = true;
  const r = await fetch(`/tradelab/jobs/${jobId}/cancel`, { method: 'POST' });
  if (!r.ok) {
    toast(`Cancel failed (${r.status})`);
    e.target.disabled = false;
    return;
  }
  await refreshJobs();
});
```

- [ ] **Step 2: Reload, manual smoke**

Click Run on a Live Strategy card → job appears in tracker. Click Cancel → status flips to Cancelled within ~5s.

---

## Phase 7: Manual smoke + final acceptance

### Task 7.1: Run the 8-step manual smoke checklist

**Source:** Spec §10.3.

- [ ] **Step 1:** Click `[Run ▾ → Robustness]` on MOMO card → tracker appears, spinner on card.
- [ ] **Step 2:** Wait ~3 min → progress events tick ("MC 320/500"), status flips to Done, new Pipeline row appears.
- [ ] **Step 3:** Click `[Run ▾ → 3f Full]` → confirmation modal with "10 min" wording → Confirm → enters tracker.
- [ ] **Step 4:** Cancel a running job → status flips to Cancelled within 5s. Partial `reports/<id>/` left in place (verify via filesystem `ls reports/<id>/`).
- [ ] **Step 5:** Spam-click 5x → toast "Already queued". Only 1 entry in tracker.
- [ ] **Step 6:** Open second browser tab → both tabs identical, both update on next event.
- [ ] **Step 7:** Restart `launch_dashboard.py` mid-job → on reload, tracker shows job re-attached (or Interrupted if PID died).
- [ ] **Step 8:** Trigger an intentional failure (run a strategy with a syntax error in its source) → status Failed, "view stderr" link shows last 100 lines.

If any step fails, fix the bug and re-run the affected steps. Do NOT skip a failed step.

### Task 7.2: Final test run — all green

- [ ] **Step 1: Backend tests**

```bash
cd /c/TradingScripts/tradelab && pytest tests/ -v --tb=short
```

Expected: ~70 passed (29 v1 baseline + ~41 new), 1 known flaky (`test_whatif_returns_metrics_and_equity_curve`). Zero new flakes.

If any new test flakes intermittently, re-run 3x to confirm. New flakes block merge.

- [ ] **Step 2: One real --full end-to-end run**

```bash
# In the browser, click [Run ▾ → Full] on a non-canary strategy
# (e.g., s2_pocket_pivot or any registered production strategy).
# Confirm modal, click Confirm.
# Wait ~10 min.
```

Expected:
- Progress ticks meaningfully through optuna, walk_forward, monte_carlo, loso stages
- Status flips to Done
- New row appears in Pipeline within 1s of done event (no manual refresh needed)
- The dashboard for the new run is browseable via the modal Dashboard tab

### Task 7.3: Append to changelog and commit final state

**Files:**
- Modify: `C:\TradingScripts\CHANGELOG-research-tab.txt`

- [ ] **Step 1: Append v1.5 entry**

```
2026-04-22 v1.5 — Trigger-a-Run

* New: Job Tracker panel above Live Strategies cards in the Research tab.
* New: [Run ▾] dropdown on every Live Strategy card and Pipeline strategy
  group. Exposes the 5 launcher RUN commands (1, 2, 3, 3r, 3f).
* New: Live SSE progress stream at GET /tradelab/jobs/stream.
* New: Cancellation via CTRL_BREAK_EVENT + TerminateProcess fallback.
* New: Persistent job state at .cache/jobs.json. Survives dashboard restart.
* New: 3f confirmation modal — preserves the launcher's "10 min" gate.
* CLI:  --progress-log <path> flag added to run, optimize, wf commands.
        Backward compatible — empty path is a no-op.
* Backend: src/tradelab/web/{jobs,progress,sse,progress_events}.py (new).
        handlers.py extended with handle_post_with_status + handle_sse.
* Frontend: command_center.html extended; engines, other 4 tabs, and
        the 10 safety mechanisms unchanged.
* Rollback: copy *.bak-2026-04-22-v1.5 files back over the originals;
        delete the new tradelab/web/ files; revert .gitignore line.
```

- [ ] **Step 2: Commit final tradelab repo state (any pending tracked changes)**

```bash
cd /c/TradingScripts/tradelab && git status --short
```

If anything's still pending, stage and commit per the v1.5 work scope.

---

## Self-review (run this last, before handoff)

### 1. Spec coverage check

Walk through each spec section and confirm there's a task for it:

- §2 Goal — Phases 1-6 (full feature)
- §3 Non-goals — No tasks (intentional exclusions)
- §4 Architecture / 4.1 Invariants — Tasks 1.1, 2.1, 4.2 (jobs.py, sse.py, __init__.py wiring)
- §4.2 Files affected — All Phase 1-6 tasks
- §5 Job lifecycle / state machine — Tasks 2.2-2.6
- §6 Data schemas — Tasks 1.1 (events), 2.1 (manifest), 4.1 (SSE wire)
- §7 Concurrency / queue — Tasks 2.2, 2.3, 5.1 (dedupe)
- §8.1 Subprocess failures — Tasks 2.2 (watch), 5.1 (validation), 6.5 (UI failure rendering)
- §8.2 Restart recovery — Task 2.4
- §8.3 SSE / browser failures — Tasks 4.1, 6.5
- §8.4 User-action edges — Tasks 2.6, 5.1, 6.6
- §8.5 Backward compat — Task 5.6
- §9 UI defaults — Tasks 6.1-6.6
- §10 Testing — Phases 1-5 (TDD throughout) + Task 7.1 (manual smoke)
- §11 Rollback plan — Task 0.3 (backups), Task 7.3 (changelog)
- §12 Open questions / v1.6 — No tasks (deferred)
- §13 Pre-implementation — Tasks 0.1, 0.2, 0.4

All sections covered.

### 2. Placeholder scan

Search for forbidden patterns: `TBD`, `TODO`, `implement later`, `appropriate error handling`, `similar to Task N`, `etc.`

```bash
grep -nE "TBD|TODO|implement later|appropriate error|similar to task|fill in" docs/superpowers/plans/2026-04-22-research-tab-v1.5-trigger-a-run.md
```

Expected: no matches (or matches only inside code comments that explain WHY, not as placeholders).

### 3. Type / signature consistency

Cross-check that names used across tasks match exactly:

- `JobManager.submit(strategy, command, argv) -> (job_id, JobStatus)` — Tasks 2.2, 5.1, tests in 5.1
- `JobManager.cancel(job_id) -> bool` — Tasks 2.2, 2.6, 5.3
- `JobManager.list_jobs() -> list[Job]` — Tasks 2.1, 5.2
- `ProgressEmitter(path).start/complete/progress/done/error/close` — Task 1.1, used in 1.3, 1.4, _fake_cli.py
- `Broadcaster.subscribe(wfile, initial_state=None) -> token`, `unsubscribe(token)`, `broadcast(event)`, `client_count()`, `is_subscribed(token)` — Task 4.1 (basic), 5.4 (initial_state, is_subscribed)
- `ProgressTailer(path, on_event, poll_interval_s)` — Task 3.1 + 3.2
- `handlers.handle_post_with_status(path, body) -> (body, status)` — Task 5.1, 5.2, 5.3
- `handlers.handle_sse(wfile)` — Task 5.4
- `progress_events.parse_event(line) -> dict | None` — Task 1.1
- `_ALLOWED_COMMANDS` keys: `"optimize"`, `"wf"`, `"run"`, `"run --robustness"`, `"run --full"` — Task 5.1, mirrored in frontend Task 6.2 dropdown markup

All consistent.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-research-tab-v1.5-trigger-a-run.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a plan this size (~30 tasks across 7 phases).

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
