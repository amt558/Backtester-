# Research Tab v1.5 — Summary & v1.6 Handoff

**For a future Claude session.** This doc recaps what v1.5 shipped, where the code lives, gotchas you'll re-hit if you forget them, and the v1.6 backlog. Read this AND `RESEARCH_TAB_V1_SUMMARY.md` first if you're picking up the work.

**Shipped:** 2026-04-22 · Merged to `master` at commit `8ef3153` (merge commit `10bf2c4`).

---

## 1. TL;DR

v1 of the Research tab (shipped earlier 2026-04-22) gave Amit a single browser surface for *viewing* tradelab audit output. **v1.5 adds the ability to *trigger* tradelab CLI runs from the web** — five RUN commands (`optimize` / `wf` / `run` / `run --robustness` / `run --full`) become `[Run ▾]` dropdowns on every Live Strategy card and on each Pipeline strategy group. Live progress streams via Server-Sent Events. Jobs survive dashboard restart. Cancellation works on Windows via `CTRL_BREAK_EVENT`.

Bottom line: Amit no longer has to drop into PowerShell launcher hotkeys to fire a backtest. Everything is one click in the browser.

---

## 2. What v1.5 delivered

### New backend modules (in `tradelab/src/tradelab/web/`)

| File | Responsibility | LOC |
|---|---|---|
| `jobs.py` | `JobManager` — spawn `subprocess.Popen` per job, FIFO serial queue, atomic state persistence, restart recovery via PID liveness check, cancel via `CTRL_BREAK_EVENT` then `TerminateProcess` after 5s grace, spam-click dedupe via `DuplicateJobError` | ~400 |
| `progress.py` | `ProgressTailer` — polling tail loop for `.cache/jobs/<id>/progress.jsonl`, tolerant of missing files / corrupted JSON / partial writes / file truncation | ~88 |
| `sse.py` | `Broadcaster` — SSE pub-sub, snapshot-iterate to remain safe under concurrent subscribe, broken-pipe pruning, retry hint + initial-state replay | ~85 |
| `progress_events.py` | Shared schema: `ProgressEmitter` (used by CLI) + `parse_event` (used by `progress.py`) + `STAGES` set | ~95 |

### Backend extensions

- `handlers.py` — added `handle_post_with_status(path, body) → (body, status)`, `handle_sse(wfile)`, `_resolve_active_universe()`, `_build_tradelab_argv()`, `_post_job()`, `_cancel_job()`. New routes: `POST /tradelab/jobs`, `GET /tradelab/jobs`, `POST /tradelab/jobs/<id>/cancel`, `GET /tradelab/jobs/stream`.
- `__init__.py` — eager singletons `_broadcaster` and `_job_manager` wired so JobManager state changes broadcast over SSE. `supports_progress_log()` cached probe.
- `cli.py` + `cli_run.py` — added `--progress-log <path>` Typer option to `run`, `optimize`, `wf` commands. Wraps each function body in `try/except/finally` with stage emit calls (start/complete around each major step, done/error in the wrap).

### Frontend (in `C:\TradingScripts\command_center.html`)

Added 333 lines extending the Research tab only. Other 4 tabs and the 10 safety mechanisms untouched.

- Job Tracker panel (top of Research tab, hidden until ≥1 job)
- `[Run ▾]` dropdown on each Live Strategy card with all 5 commands
- Grouped `[Run ▾]` on Pipeline rows (one per unique strategy in visible page)
- 3f confirmation modal with ~10-min wording, **Escape-to-close**, strategy name in heading
- EventSource client subscribed to `/tradelab/jobs/stream`
- Cancel button per active job
- Toast helper for 409 ("Already queued") / 503 ("rebuild tradelab") / generic failures
- `switchTab` calls `refreshJobs()` when user returns to Research tab (re-syncs after tab switching)

### Launcher integration (in `C:\TradingScripts\launch_dashboard.py`, NOT in any git repo)

- `dispatch_tradelab_post` switched to `handle_post_with_status` and propagates returned status code (was always 200)
- New `/tradelab/jobs/stream` branch in `do_GET` (placed BEFORE the broader `/tradelab/` branch so SSE doesn't get JSON-wrapped)
- New `dispatch_tradelab_sse` method writes SSE response headers (`text/event-stream`, no `Content-Length`) then calls `handle_sse(self.wfile)` — broadened except clause logs unexpected exceptions to stderr

### Tests

42 new pytest tests across 5 files. Total `tests/web/` + `tests/cli/test_progress_log.py` is 101 passing on master post-merge (3 pre-existing failures: 1 known whatif flake + 2 `tests/cli/` FileNotFoundError tests that were already broken on master baseline).

| File | Tests |
|---|---|
| `tests/web/test_jobs.py` | 14 |
| `tests/web/test_progress.py` | 6 |
| `tests/web/test_sse.py` | 7 |
| `tests/web/test_handlers_jobs.py` | 10 |
| `tests/cli/test_progress_log.py` | 5 |
| `tests/web/_fake_cli.py` | (test helper, not a test file) |

---

## 3. Architecture snapshot

```
┌─ Browser (command_center.html) ──────────────────────────────────┐
│  Existing Research tab (UNCHANGED)                                │
│   + Job tracker panel       (NEW)                                 │
│   + [Run ▾] dropdown        (NEW · per Live card + Pipeline group)│
│   + EventSource client      (NEW · /tradelab/jobs/stream)         │
│   + 3f confirm modal        (NEW · ~10-min gate, Esc to close)    │
└────────────────────┬───────────────────────────┬─────────────────┘
                     │ HTTP                      │ SSE
                     ▼                           ▼
┌─ launch_dashboard.py (port 8877, ThreadedHTTPServer) ─────────────┐
│  POST /tradelab/jobs            → 201/400/409/503                 │
│  GET  /tradelab/jobs            → 200 {jobs, running_id, queue}   │
│  POST /tradelab/jobs/<id>/cancel → 200/404/410                    │
│  GET  /tradelab/jobs/stream     → SSE (retry: 3000 + replay)      │
│                                                                    │
│  All v1 routes UNCHANGED (Alpaca proxy, /config, /tradelab/runs,  │
│  /tradelab/whatif, /tradelab/new-strategy, etc.)                  │
└────────────┬──────────────────────┬───────────────────────────────┘
             ▼                      │
┌─ tradelab CLI subprocess ─────────┼───────────────────────────────┐
│   python -m tradelab.cli run <name> --robustness                  │
│         --universe <from launcher-state.json>                     │
│         --progress-log .cache/jobs/<id>/progress.jsonl            │
│                                    │                               │
│   Engines/*.py UNTOUCHED (protected per memory rule)              │
└────────────────────────────────────┼───────────────────────────────┘
                                     │ writes JSON lines
                                     ▼
┌─ Filesystem state (in tradelab/.cache/) ─────────────────────────┐
│   jobs.json                  ← manifest (atomic write, schema=1) │
│   jobs/<id>/progress.jsonl   ← per-job event stream              │
│   launcher-state.json        ← shared with PowerShell launcher;  │
│                                read by web for activeUniverse    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. The 4 gotchas that bit during smoke (don't repeat them)

These are documented in commits `afd49b6`, `4bbb713`, `a229ce7`, `8ef3153`. If you're making similar changes in v1.6+, watch for these:

### 4.1 Subprocess argv must include `--universe`

The CLI's `run`/`optimize`/`wf` commands require `--symbols` or `--universe` (no auto-fallback to a default). The PowerShell launcher passes `$activeUniverse` from its state file. The web equivalent reads `.cache/launcher-state.json::activeUniverse`. See `_resolve_active_universe()` in `handlers.py`. Without this, every job exits 2 with "No symbols provided".

### 4.2 PowerShell writes UTF-8 with BOM

`launcher-state.json` is written by `tradelab-launch.ps1` with a UTF-8 BOM (`﻿`). Reading it with `read_text(encoding="utf-8")` reads the BOM as a literal char, `json.loads` rejects it with `JSONDecodeError`, and a bare `try/except` swallows the failure silently — making the resolver fall through to the wrong universe. **Fix**: always use `encoding="utf-8-sig"` for files that PowerShell may have written. (Memory: `reference_powershell_utf8_bom.md`.)

### 4.3 `subprocess.run(..., text=True)` uses locale encoding (cp1252 on Windows)

The `supports_progress_log()` probe shells out to `python -m tradelab.cli run --help` and greps for `--progress-log` in the output. `text=True` defaults to the locale codec (cp1252), which crashes on Unicode chars Rich/Typer emit (table borders, etc.). The except sets `_supports_pl = False`, then every POST `/tradelab/jobs` returns 503. **Fix**: pass `encoding="utf-8", errors="replace"` to `subprocess.run` whenever capturing CLI output on Windows.

### 4.4 The dashboard caches modules at startup

If you change `handlers.py`, `__init__.py`, or any other Python module under `tradelab.web`, the running dashboard process won't see the change. **Always Ctrl+C and re-launch `launch_dashboard.py` after editing backend Python.** No hot-reload.

---

## 5. How to run / restart / debug

**Start dashboard** (post-merge — no `PYTHONPATH` override needed):
```powershell
python C:\TradingScripts\launch_dashboard.py
```
Opens on port 8877. Banner shows `Research: ONLINE` if `tradelab.web` imported cleanly.

**Start dashboard from worktree** (only needed when iterating on a v1.6 branch in a different worktree):
```powershell
$env:PYTHONPATH = "C:\TradingScripts\<worktree-name>\src"
python C:\TradingScripts\launch_dashboard.py
```

**Quick health check** (in another shell):
```powershell
curl http://localhost:8877/tradelab/jobs   # → {"error":null,"data":{...}}
curl http://localhost:8877/api/v2/account  # → 200 if Alpaca creds valid, else 401
```

**Submit a job from CLI** (bypasses browser, useful for debugging):
```powershell
$body = '{"strategy":"s2_pocket_pivot","command":"run"}'
Invoke-RestMethod -Method POST -Uri http://localhost:8877/tradelab/jobs -Body $body -ContentType "application/json"
```

**Inspect job state**:
```powershell
type C:\TradingScripts\tradelab\.cache\jobs.json
type C:\TradingScripts\tradelab\.cache\jobs\<id>\progress.jsonl
```

**Stop a stuck dashboard process**:
```powershell
netstat -ano | findstr ":8877"      # find PID
Stop-Process -Id <PID> -Force
```

---

## 6. Files that exist outside the git repo

These are **not in any git repo** but were modified during v1.5. Backups exist with `.bak-2026-04-22-v1.5` suffix:

- `C:\TradingScripts\command_center.html` (2669 → 3002 lines)
- `C:\TradingScripts\launch_dashboard.py` (extended `do_GET`, `dispatch_tradelab_post`, added `dispatch_tradelab_sse`)

If you ever need to roll back v1.5: `cp <file>.bak-2026-04-22-v1.5 <file>` for both, then `git revert 10bf2c4..8ef3153` in the tradelab repo (or `git reset --hard c0398f1` if you want the pre-v1.5 master back).

---

## 7. v1.6 backlog (in priority order)

These are real issues the final code review surfaced. None blocked the merge but each is worth fixing before the codebase grows further.

| # | Issue | Fix shape | Effort |
|---|---|---|---|
| 1 | `supports_progress_log` probe runs on first POST instead of dashboard boot — gives ~1s hang on user's first click | Move probe to module init in `__init__.py` after singletons | 10 min |
| 2 | `_resolve_active_universe` silently fails when launcher-state.json is missing/unreadable; user gets generic FAILED with no hint why | Log to stderr (NOT raise — keep fallback) when file missing or BOM read fails | 15 min |
| 3 | `JobManager._start` uses `cwd_root.parent.name == "tradelab"` heuristic to set subprocess cwd — fragile if anyone names a worktree something other than "tradelab" | Pass explicit `tradelab_root` into `JobManager.__init__` from `web.__init__` | 30 min |
| 4 | `handlers.py` reads `jm._running_id` and `jm._queue` private attrs; tests do same | Add `JobManager.running_id()` / `queue_snapshot()` public accessors; refactor consumers | 30 min |
| 5 | `handle_sse` polls `is_subscribed(token)` every 1s — disconnect detected up to 1s late, thread holds entire wait | Use `threading.Event` woken by broadcaster on prune; subscriber blocks on `event.wait()` | 1-2 hr |

Plus 2 pre-existing master baseline test failures someone should chase (not v1.5's fault but they reduce signal):

- `tests/cli/test_cli_run.py::test_cli_run_orchestrates_download_backtest_report` — FileNotFoundError on `reports/<strategy>_<ts>/backtest_result.json`. Was already failing before v1.5. May need fix for tmp_path + cwd interaction in the test.
- `tests/cli/test_cli_universes.py::test_cli_run_universe_resolves_symbol_list` — same FileNotFoundError pattern.

---

## 8. What was deliberately omitted from v1.5

These were in the v1.5 brainstorm and explicitly rejected:

- **CPCV** (Combinatorial Purged Cross-Validation) — Amit raised it; per `TRADELAB_MASTER_PLAN.md` it's "massive effort, tiny incremental value for this data structure" and was explicitly ruled out at master plan time. Decision held.
- **PBO** (Probability of Backtest Overfitting) — genuinely interesting (single overfitting probability, pairs with existing DSR), but is **engine work, not web work**. Deferred to its own brainstorm/spec — not bundled into v1.5 to avoid scope creep.
- **Per-strategy parameter overrides** in the Run dropdown — uses `tradelab.yaml` defaults only. Customization (`--trials N`, `--start YYYY-MM-DD`) defers to v1.6+.
- **Concurrent jobs** — v1.5 is serial (one running, rest queued). Avoids data-cache contention. v1.6 may add opt-in concurrent if Amit hits queue waits often.
- **Auto-cleanup of cancelled `reports/<id>/` partials** — v1.5 leaves them. v1.6 may add a "Clean partials" button.
- **Compare-N-runs button** — Pipeline already has multi-select infrastructure from v1; adding a `Compare` button that fires `tradelab compare <folders>` is ~0.5 day in v1.6.

---

## 9. References (read these first if picking up v1.6)

In repo:
- **Spec:** `tradelab/docs/superpowers/specs/2026-04-22-research-tab-v1.5-trigger-a-run-design.md`
- **Plan:** `tradelab/docs/superpowers/plans/2026-04-22-research-tab-v1.5-trigger-a-run.md`
- **v1 summary:** `tradelab/docs/superpowers/RESEARCH_TAB_V1_SUMMARY.md`
- **This doc:** `tradelab/docs/superpowers/RESEARCH_TAB_V1.5_SUMMARY.md`

Outside repo:
- **Changelog:** `C:\TradingScripts\CHANGELOG-research-tab.txt` (v1.5 entry appended)
- **Backups:** `C:\TradingScripts\command_center.html.bak-2026-04-22-v1.5`, `C:\TradingScripts\launch_dashboard.py.bak-2026-04-22-v1.5`

Memory (for future Claude sessions):
- `project_tradelab.md` — overall project context
- `project_tradelab_web_dashboard.md` — v1 + v1.5 dashboard decisions
- `feedback_web_over_hotkeys.md` — Amit prefers web UI over launcher hotkeys
- `reference_powershell_utf8_bom.md` — the BOM gotcha from §4.2

---

## 10. Pre-existing risks the v1.5 work surfaced (worth fixing separately from v1.6)

Not introduced by v1.5, but visible enough during the work that they're worth flagging:

1. **Three strategy source files are git-untracked**: `src/tradelab/strategies/{frog,qullamaggie_ep,s7_rdz_momentum}.py`. They're registered in `tradelab.yaml` but only exist on disk. A `git clean -fd` would delete them permanently. Fix: `git add -f` them and commit.

2. **Alpaca credentials in `alpaca_config.json` are returning 401** when called both via the dashboard proxy AND directly to `paper-api.alpaca.markets`. Live-trading "Command Center [Alpaca]" is showing OFFLINE. Likely cause: API key was regenerated on Alpaca's web dashboard since this file was written. Fix: regenerate keys at https://app.alpaca.markets → Paper Trading → API Keys, paste new pair into `alpaca_config.json`.

3. **`qullamaggie_ep` and `frog` strategies have zero audit history** (never been backtested). Once the dashboard restart picks up the encoding fix, fire `[Run ▾ → Robustness]` on each from the Research tab — that puts them into the Pipeline.

---

## 11. How to resume v1.6

If you're a fresh Claude session continuing this work:

1. **Read this doc** + `RESEARCH_TAB_V1_SUMMARY.md` + the 4 memory files in §9
2. **Confirm master state**: `cd C:\TradingScripts\tradelab && git log --oneline -3 → should show 8ef3153 at HEAD`
3. **Confirm tests baseline**: `pytest tests/web/ tests/cli/ -q` → 101 pass + 3 known pre-existing failures
4. **Pick one v1.6 backlog item from §7** (or ask Amit which one matters most)
5. **Brainstorm → spec → plan → execute** in a fresh worktree, same pattern v1.5 used. Use `superpowers:brainstorming` to start.

### Do NOT

- Re-brand the Research tab
- Modify the 10 AlgoTrade safety mechanisms
- Add dependencies — vanilla Python stdlib + pandas + pytest only
- Modify `engines/*.py` (protected per memory rule)
- Break the `.bat` launcher or the 8877 port
- Merge any branch to master without restoring tests to baseline (101 pass + 3 known failures)
- Propose Streamlit, FastAPI, or any new web framework — the "single-file `command_center.html` + `launch_dashboard.py`" pattern is locked
- Skip the manual smoke after backend changes — the spec compliance reviewer + code quality reviewer subagents missed several Phase 7 issues that only surfaced at smoke time
- Forget to restart `launch_dashboard.py` after editing backend Python (see §4.4)
