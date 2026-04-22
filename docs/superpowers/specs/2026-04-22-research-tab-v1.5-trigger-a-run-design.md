# Research Tab v1.5 — Trigger-a-Run — Design Spec

**Date:** 2026-04-22
**Status:** Draft — approved section-by-section, awaiting user review before writing-plans
**Owner:** Amit
**Scope version:** v1.5 (Full flavor)
**Prior art:** [`2026-04-22-command-center-research-tab-design.md`](./2026-04-22-command-center-research-tab-design.md) (v1)
**Handoff doc:** [`../RESEARCH_TAB_V1_SUMMARY.md`](../RESEARCH_TAB_V1_SUMMARY.md)

## 1. Problem statement

Research tab v1 (merged 2026-04-22, commit `5de629b`) gave Amit a single browser surface for viewing tradelab audit output, running What-If sliders, and registering new strategies. It did not include any way to **trigger** a backtest, optimize, walk-forward, robustness, or full pipeline run from the web — those still require dropping into the PowerShell launcher and pressing keys (`1` / `2` / `3` / `3r` / `3f`).

Per memory `feedback_web_over_hotkeys`: "Amit prefers browser-based dashboards over PowerShell/launcher hotkeys... a powerful web dashboard is a stated requirement, not a nice-to-have." The remaining context-switch to the PowerShell launcher every time he wants to re-run a strategy is the largest residual UX friction the v1 dashboard left in place.

The v1 handoff doc named trigger-a-run as the **#1 priority for v1.5**, with two sub-flavors (Lite ~1-2 days vs Full ~4-5 days). Amit chose **Full**: buttons + live job tracker + SSE progress + cancellation + persistent job state.

## 2. Goal

Add a **Job Tracker panel** at the top of the Research tab and a **`[Run ▾]` dropdown button** on every Live Strategy card and Pipeline strategy group, exposing all 5 launcher RUN commands (`optimize`, `wf`, `run`, `run --robustness`, `run --full`) over the web. Live progress streams via SSE. Jobs survive dashboard restart. Cancellation works on Windows process trees. Engines stay protected (no edits to `engines/*.py`).

## 3. Non-goals

- **Not adding new robustness tests** (CPCV, PBO, Purged K-Fold). Per `TRADELAB_MASTER_PLAN.md`, CPCV is "massive effort, tiny incremental value" and remains ruled out. PBO is genuinely interesting but is **engine work, not web work** — deferred to its own brainstorm/spec.
- **Not adding new CLI commands.** Only the existing 5 RUN commands gain a web button. `compare`, `gate-check`, `screen`, `overview` are out of scope (some get separate v1.6 work per handoff §5).
- **Not parameterizing dropdown invocations.** No inline overrides for `--trials`, `--start`, etc. The web button uses `tradelab.yaml` defaults exactly as the launcher does. Customization defers to v1.6.
- **Not auto-killing hung jobs.** Surface a yellow stalled-job warning at 15min+ no-progress; user decides. Auto-kill is too easy to misfire on long Optuna trials.
- **Not concurrent jobs.** One running at a time; rest queued. Avoids data-cache contention and CPU thrashing.
- **Not new web frameworks.** Vanilla Python stdlib + pandas + pytest only — same constraint as v1. No `watchdog`, no FastAPI, no SSE library.
- **Not modifying the 4 existing command_center tabs or the 10 safety mechanisms.**

## 4. Architecture

```
┌─ Browser (command_center.html) ──────────────────────────────────┐
│  Existing Research tab (UNCHANGED)                                │
│   + Job tracker panel       (NEW · top of Research tab)           │
│   + [Run ▾] dropdown        (NEW · per Live card + per Pipeline   │
│                              strategy group)                      │
│   + EventSource client      (NEW · subscribes to                  │
│                              /tradelab/jobs/stream)               │
│   + 3f confirm modal        (NEW · 10-min job warning)            │
└────────────────────┬───────────────────────────┬─────────────────┘
                     │ HTTP                      │ SSE
                     ▼                           ▼
┌─ launch_dashboard.py (port 8877, ThreadedHTTPServer · UNCHANGED) ─┐
│  New routes wired into tradelab.web.handlers:                     │
│    POST /tradelab/jobs            (start)                         │
│    GET  /tradelab/jobs            (list active + recent)          │
│    POST /tradelab/jobs/<id>/cancel                                │
│    GET  /tradelab/jobs/stream     (SSE)                           │
│                                                                    │
│  New modules in src/tradelab/web/:                                │
│   ┌──────────────────┐  ┌─────────────────────┐  ┌──────────────┐│
│   │ jobs.py          │  │ progress.py         │  │ sse.py       ││
│   │ ─ spawn Popen   │  │ ─ tail .jsonl files│  │ ─ SSE clients││
│   │ ─ serial queue  │  │ ─ parse events     │  │ ─ broadcast  ││
│   │ ─ persist state │  │ ─ feed sse.py      │  │              ││
│   │ ─ cancel        │  │                     │  │              ││
│   └────────┬─────────┘  └─────────▲───────────┘  └──────────────┘│
│            │ subprocess.Popen     │ tails per-job file            │
└────────────┼──────────────────────┼───────────────────────────────┘
             ▼                      │
┌─ tradelab CLI subprocess ─────────┼───────────────────────────────┐
│   tradelab run <name> --robustness --progress-log <path>          │
│                                    │                               │
│   Light additive change to cli.py / cli_run.py:                   │
│   ─ accept --progress-log flag                                    │
│   ─ orchestrator emits JSON-line stage events at known checkpoints│
│   ─ engines/*.py UNTOUCHED (protected per memory)                 │
└────────────────────────────────────┼───────────────────────────────┘
                                     │ writes JSON lines
                                     ▼
┌─ Filesystem state ──────────────────────────────────────────────┐
│   .cache/jobs.json                  ← job manifest (persists)    │
│   .cache/jobs/<id>/progress.jsonl   ← per-job event stream       │
│   reports/<run>/...                  ← existing artifacts (unchgd)│
└──────────────────────────────────────────────────────────────────┘
```

### 4.1 Key invariants

- **One PID, one log.** `launch_dashboard.py` stays the only long-running dashboard process. Jobs are short-lived child subprocesses.
- **Engines stay protected.** `engines/{backtest,optimizer,walkforward}.py` get zero edits. Only `cli.py`/`cli_run.py` learn the `--progress-log` flag.
- **tradelab is still a soft dep.** If import fails, the Job tracker panel hides and the rest of the dashboard works. Same fallback pattern as v1.
- **Stdlib only.** Uses `subprocess`, `threading`, `queue`, `json`, `uuid`, `pathlib`. No `watchdog`, no SSE library, no FastAPI. Pure-Python tail loop polls progress files at 500ms.
- **Crash-safe restart.** On dashboard restart, `jobs.py` reads `.cache/jobs.json`, reconciles by checking each PID still exists, marks orphaned jobs as `interrupted`.

### 4.2 Files affected

| File | Change | Approx LOC |
|---|---|---|
| `src/tradelab/web/jobs.py` | NEW · job manager (spawn, queue, persist, cancel) | ~250 |
| `src/tradelab/web/progress.py` | NEW · tail loop, JSON-line parser | ~120 |
| `src/tradelab/web/sse.py` | NEW · SSE client list, broadcast | ~80 |
| `src/tradelab/web/handlers.py` | EXTEND · 4 new routes | ~120 |
| `src/tradelab/cli.py` + `cli_run.py` (and `cli_optimize.py`/`cli_wf.py` if separate) | EXTEND · `--progress-log` flag + JSON-line emitter at stage transitions | ~80 |
| `command_center.html` | EXTEND · job tracker panel + Run dropdown + SSE client + confirm modal | ~400 |
| `tests/web/test_jobs.py` | NEW | ~12 tests |
| `tests/web/test_progress.py` | NEW | ~8 tests |
| `tests/web/test_sse.py` | NEW | ~6 tests |
| `tests/web/test_handlers_jobs.py` | NEW | ~10 tests |
| `tests/cli/test_progress_log.py` | NEW | ~5 tests |

## 5. Job lifecycle

### 5.1 State machine

```
                  POST /tradelab/jobs
                          │
                          ▼
                    ┌──────────┐  (queue not empty & another job running)
                    │  queued  │ ─────────────────────────────────────┐
                    └────┬─────┘                                       │
       (queue empty │    │ (worker picks up)                           │
        AND no job  │    ▼                                             │
        running)    │ ┌─────────┐  subprocess.terminate() then kill()  │
                    │ │ running │ ─────────────────────────► ┌──────────┐
                    │ └────┬────┘                            │cancelled │
                    │      │                                 └──────────┘
                    │      ├─── exit 0 ──► ┌──────┐
                    │      │               │ done │
                    │      │               └──────┘
                    │      ├─── exit ≠ 0 ──► ┌────────┐
                    │      │                 │ failed │
                    │      │                 └────────┘
                    │      └─── PID gone after │
                    │           dashboard restart                ┌──────────────┐
                    │                                            │ interrupted  │
                    └────────────────────────────────────────────►              │
                                                                 └──────────────┘
```

### 5.2 End-to-end flow (click → Pipeline row appears)

1. **User** clicks `[Run ▾ → Robustness]` on MOMO card.
2. **Browser** `POST /tradelab/jobs {strategy:"momo", command:"run --robustness"}`.
3. **`jobs.py`**:
   - generate `uuid` (`job_id`)
   - `mkdir .cache/jobs/<id>/`
   - append job to `.cache/jobs.json` with `status=queued`
   - if no other running job: promote to `running`, else stay `queued`
   - when running: `subprocess.Popen([python, -m, tradelab.cli, run, momo, --robustness, --progress-log, .cache/jobs/<id>/progress.jsonl], creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP, cwd=repo_root)`
   - record `pid` + `started_at` into `jobs.json`
   - return `201 {job_id, status, position_in_queue}`
4. **CLI subprocess**: `cli_run.py` orchestrator opens `progress.jsonl` line-buffered. Emits at each known checkpoint (no engine code touched):
   ```json
   {"ts":"...","type":"start","stage":"backtest"}
   {"ts":"...","type":"complete","stage":"backtest","duration_s":1.4}
   {"ts":"...","type":"start","stage":"monte_carlo"}
   {"ts":"...","type":"progress","stage":"monte_carlo","i":320,"total":500}
   {"ts":"...","type":"done","exit":0}
   ```
5. **`progress.py`** tail loop polls `.cache/jobs/<id>/progress.jsonl` every 500ms, parses new lines, calls `sse.broadcast(job_id, event)`.
6. **`sse.py`** keeps a list of connected EventSource clients. Formats each event as `data: {...}\n\n`, writes to each client's wfile. Broken-pipe → drop client.
7. **Browser** EventSource `onmessage` → updates job tracker panel + flips card spinner state + on `done`, refetches `/tradelab/runs` so the new Pipeline row appears immediately.
8. **`jobs.py`** on subprocess exit:
   - set `ended_at`, `exit_code`, `status` (`done` | `failed` | `cancelled`)
   - flush `jobs.json`
   - promote next queued job to `running`

## 6. Data schemas

### 6.1 `.cache/jobs.json` — manifest (overwritten on every change, atomic write)

```json
{
  "schema_version": 1,
  "jobs": [
    {
      "id": "8c2e...",
      "strategy": "momo",
      "command": "run --robustness",
      "argv": ["run", "momo", "--robustness"],
      "status": "running",
      "started_at": "2026-04-22T15:30:01Z",
      "ended_at": null,
      "pid": 12345,
      "exit_code": null,
      "progress_log": ".cache/jobs/8c2e.../progress.jsonl",
      "last_event_summary": "MC 320/500"
    },
    { "id": "...", "status": "queued", "...": "..." },
    { "id": "...", "status": "done", "exit_code": 0, "...": "..." }
  ],
  "queue": ["queued-id-1", "queued-id-2"],
  "running_id": "8c2e..."
}
```

**Retention:** last 50 done/failed/cancelled jobs kept. Older purged on every write.
**Status values:** `queued` | `running` | `done` | `failed` | `cancelled` | `interrupted`.
**Atomic write:** write to `jobs.json.tmp`, then `os.replace`. Single `threading.Lock` owned by `jobs.py` serializes all writes.

### 6.2 `.cache/jobs/<id>/progress.jsonl` — append-only event stream

```jsonl
{"ts":"2026-04-22T15:30:01Z","type":"start","stage":"backtest"}
{"ts":"2026-04-22T15:30:02Z","type":"complete","stage":"backtest","duration_s":1.4}
{"ts":"2026-04-22T15:30:02Z","type":"start","stage":"monte_carlo"}
{"ts":"2026-04-22T15:30:18Z","type":"progress","stage":"monte_carlo","i":100,"total":500}
{"ts":"2026-04-22T15:30:42Z","type":"progress","stage":"monte_carlo","i":320,"total":500}
{"ts":"2026-04-22T15:31:05Z","type":"complete","stage":"monte_carlo","duration_s":42.1}
{"ts":"2026-04-22T15:31:05Z","type":"start","stage":"loso"}
{"ts":"2026-04-22T15:32:14Z","type":"done","exit":0}
```

**Event types:** `start` | `progress` | `complete` | `done` | `error`.
**Schema discipline:** strict types (above), but `progress.py` tolerates unknown fields for forward compatibility.
**Stages emitted:** `backtest`, `optuna`, `walk_forward`, `monte_carlo`, `loso`, `regime`, `cost_sweep`, `tearsheet`. The exact set per command depends on which CLI subcommand and flags are in play.

### 6.3 SSE wire format

```
retry: 3000

data: {"job_id":"8c2e...","event":{"type":"progress","stage":"monte_carlo","i":320,"total":500}}

data: {"job_id":"8c2e...","event":{"type":"complete","stage":"monte_carlo","duration_s":42.1}}
```

On client connect: server immediately writes one synthetic `state` event per active job summarizing current status (no full event history replay).

## 7. Concurrency & queue rules

- **One running job at a time.** Avoids data-cache contention and CPU thrashing on Optuna parallelism. Queue is FIFO.
- **SSE broadcast covers ALL clients.** Open the dashboard on monitor 2 and monitor 3 — both stay in sync.
- **Multiple browsers can submit jobs.** Last-write-wins on `jobs.json` under a single `threading.Lock` owned by `jobs.py`.
- **Cancel is graceful first (Windows-only target platform):** `os.kill(pid, signal.CTRL_BREAK_EVENT)` reaches the whole process tree because the subprocess is spawned with `creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP` (matches §5.2). 5s grace, then `process.kill()` (Windows `TerminateProcess`) as fallback. Partial `reports/<id>/` is left in place.
- **Spam-click dedupe:** if a job with the same `(strategy, command)` is already `running` or `queued`, `POST /tradelab/jobs` returns `409 Conflict` with `{existing_job_id}`. Frontend toasts "Already queued" instead of stacking 5 identical jobs.

## 8. Error handling & edge cases

### 8.1 Subprocess failures

| Scenario | Behavior |
|---|---|
| Subprocess crashes mid-run (OOM, exception, killed externally) | `jobs.py` polls `process.poll()` every 1s. Non-None exit → `status=failed`, capture last 100 lines of stderr into `jobs.json.error_tail`, push `{"type":"error","tail":"..."}` over SSE. Job tracker shows red "Failed · view stderr" link. |
| Subprocess hangs (no progress event for > 15min on a job whose typical runtime < 10min) | **No auto-kill in v1.5.** Yellow "stalled — no progress 15m+" warning on tracker entry. User decides. Auto-kill is too easy to misfire on long Optuna trials. |
| Corrupted JSON line in `progress.jsonl` | `progress.py` wraps each `json.loads` in try/except. Bad lines logged to `launch_dashboard.log` and skipped. Tail loop never crashes. |
| Subprocess writes no progress events at all (crashed before first emit) | Status flips to `failed` via exit-code path. Tracker shows "Failed · 0 events emitted" — itself a useful debugging hint. |
| Subprocess exits 0 but produces no audit DB row | Status stays `done`; Pipeline doesn't gain a row. User can spot the discrepancy. No special handling in v1.5. |

### 8.2 Dashboard restart & state recovery

| Scenario | Behavior |
|---|---|
| Dashboard restarts while a job is running | On startup, `jobs.py` reads `jobs.json`, finds running entries. For each: check if PID alive (`os.kill(pid, 0)`). Alive → re-attach, resume tailing. Dead → `status=interrupted`, `ended_at=now`. |
| `jobs.json` mid-write when dashboard crashes | Atomic write: write to `jobs.json.tmp`, `os.replace`. OS guarantees old or new file, never partial. |
| `jobs.json` corrupted (manual edit, disk error) | On parse error: rename to `jobs.json.broken-<ts>`, log loud warning, start fresh. Dashboard still boots. |
| `.cache/` directory missing | `jobs.py` creates on init with `parents=True, exist_ok=True`. Same pattern as v1's freshness module. |

### 8.3 SSE / browser failures

| Scenario | Behavior |
|---|---|
| Browser disconnects mid-stream (tab close, sleep) | SSE write fails → broken-pipe caught → client removed from broadcast list. Subprocess keeps running. Reopen → fresh GET `/tradelab/jobs` rehydrates state, EventSource reconnects. |
| Network blip / proxy timeout | EventSource auto-reconnects (browser default). On reconnect, server emits `retry: 3000` and replays current state per active job (one synthetic event each, not full history). |
| Many tabs / multi-monitor | Each tab is an independent EventSource client. Broadcast iterates a list — 3 monitors = 3 connections. `jobs.json` is the single source of truth fetched on connect. |

### 8.4 User-action edge cases

| Scenario | Behavior |
|---|---|
| Spam-click `[Run ▾ → Robustness]` 5x on MOMO | Server-side dedupe — see §7. Returns `409 Conflict` with existing `{job_id}`. Toast "Already queued". |
| Cancel a job between `running` and exit-code processing | Per-job lock during state transitions. Cancel-while-finishing returns the final status, not `cancelled`. Cancel of `queued` removes from queue, no subprocess to kill. |
| Cancel a process tree (CLI spawned an Optuna sampler child) | Windows: `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` reaches whole tree. `process.kill()` (TerminateProcess) fallback if process tree survives 5s. |
| 3f confirmation modal — user closes browser before confirming | Modal is purely client-side. Closing the browser drops the modal — no job submitted. Server doesn't know the click happened. |

### 8.5 Backward compatibility

- **Old tradelab without `--progress-log`:** dashboard probes via one-shot `tradelab --help | grep progress-log` at startup. If missing: hides the Job tracker panel, falls back to v1 behavior, loud warning in `launch_dashboard.log`.
- **Existing v1 routes are untouched.** All four existing tabs and the 10 AlgoTrade safety mechanisms get zero edits.

## 9. UI defaults

- **Run buttons live on:** Live Strategy cards (one per card) **and** Pipeline rows (grouped — one button per unique strategy in the visible page, not per row).
- **Dropdown options:** all 5 launcher RUN commands — `optimize`, `wf`, `run`, `run --robustness`, `run --full`.
- **3f keeps a confirmation modal** with the launcher's wording: "Full run (optuna + wf + cost-sweep + robustness) takes ~10 min. Proceed?". No checkbox to skip in v1.5.
- **No inline parameter overrides** — uses `tradelab.yaml` defaults exactly as the launcher does. Customization defers to v1.6.

## 10. Testing strategy

### 10.1 New test files (~41 tests total)

| File | Tests | Coverage focus |
|---|---|---|
| `tests/web/test_jobs.py` | ~12 | State machine: queued→running→done/failed/cancelled/interrupted. Serial queue promotion. Atomic `jobs.json` write. Restart recovery (PID alive vs dead). Bounded retention. Corruption → rename + fresh start. |
| `tests/web/test_progress.py` | ~8 | Tail loop: new lines in < 500ms, corrupted JSON skipped + logged, partial write safe, missing file silent until appears, subprocess-exit + 2s grace then stops tailing. |
| `tests/web/test_sse.py` | ~6 | Client add/remove on connect/disconnect. Broken-pipe handled. Concurrent-modification safe broadcast. Reconnect replays current state per active job. `retry: 3000` hint emitted. |
| `tests/web/test_handlers_jobs.py` | ~10 | POST `/tradelab/jobs` 201, invalid command 400, duplicate `(strategy, command)` 409, GET list active+recent, POST cancel 200, cancel-on-done 410, SSE Content-Type. Old-tradelab probe → POST 503. |
| `tests/cli/test_progress_log.py` | ~5 | CLI emits expected checkpoint events. Line-buffered (event visible mid-run). Backward-compat: works without flag. Non-zero exit still emits final `error` event. JSONL parseable. |

Total: brings `tests/web/` from 29 baseline → ~70.

### 10.2 Patterns & mocks

- **Mock the subprocess.** A fake-CLI helper at `tests/web/_fake_cli.py` writes a scripted JSONL event sequence to a path passed via stdin (simulates `--progress-log`) and exits 0/1/SIGTERM. Every test runs in < 100ms with deterministic events.
- **`tmp_path` fixture.** Each test gets fresh `tmp_path/.cache` so state files don't collide.
- **Time control.** `monkeypatch` on `time.time` for the stalled-job 15min+ logic. No `time.sleep` in tests.
- **SSE testing.** Use Python's `http.client` against a `ThreadedHTTPServer` (existing pattern in v1's `conftest.py`). Read response stream byte-by-byte for SSE frames.
- **Windows-only / Unix-only.** `@pytest.mark.skipif(sys.platform != "win32")` for `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` cancel test.

### 10.3 Manual UI smoke checklist

1. Click `[Run ▾ → Robustness]` on MOMO card → tracker appears, spinner on card.
2. Wait ~3 min → progress events tick ("MC 320/500"), status flips to Done, new Pipeline row appears.
3. Click `[Run ▾ → 3f Full]` → confirmation modal with "10 min" wording → Confirm → enters tracker.
4. Cancel a running job → status flips to Cancelled within 5s. Partial `reports/<id>/` left in place.
5. Spam-click 5x → toast "Already queued". Only 1 entry in tracker.
6. Open second browser tab → both tabs identical, both update on next event.
7. Restart `launch_dashboard.py` mid-job → on reload, tracker shows job re-attached (or Interrupted if PID died).
8. Trigger an intentional failure (strategy with syntax error) → status Failed, "view stderr" link shows last 100 lines.

### 10.4 Out of scope for tests

- Tradelab CLI engine correctness (already covered upstream). We test the orchestrator's emit calls, not engine math.
- Real Twelve Data API calls (fixture parquet files, same as v1).
- Long-running jobs in CI (fake-CLI replays scripted events in milliseconds).
- The pre-existing v1 flaky test `test_whatif_returns_metrics_and_equity_curve` — separate cleanup item, not v1.5 scope.

### 10.5 Acceptance gates before merge to master

- `pytest tests/web/` — all ~70 green (29 baseline + ~41 new), 0 new flakes.
- `pytest tests/cli/test_progress_log.py` — all 5 green.
- Manual smoke checklist — every item checked off in person.
- One real `--full` end-to-end run on a non-canary strategy with the dashboard open and a Pipeline row appearing on completion.

## 11. Rollback plan

- Same backup pattern as v1. Pre-implementation: copy `command_center.html` → `command_center.html.bak-2026-04-22-v1.5` and `launch_dashboard.py` → `launch_dashboard.py.bak-2026-04-22-v1.5`.
- All new files (`jobs.py`, `progress.py`, `sse.py`, new test files) can be deleted with no impact on v1.
- `cli.py` / `cli_run.py` `--progress-log` flag is additive and optional — no rollback needed if untouched.
- `command_center.html` and `launch_dashboard.py` rollback by file copy from the v1.5 backup.
- Append rollback steps to `C:\TradingScripts\CHANGELOG-research-tab.txt`.

## 12. Open questions / deferred to v1.6

- **Per-strategy parameter overrides.** v1.5 uses `tradelab.yaml` defaults only. v1.6 may add an "advanced" expander on the Run dropdown for ad-hoc `--trials N`, `--start YYYY-MM-DD` overrides.
- **Concurrent job execution.** v1.5 is serial-only. If Amit hits queue waits often, v1.6 can add an opt-in concurrent mode (with explicit data-cache lock around `marketdata.download_symbols`).
- **Auto-cleanup of partial cancelled `reports/<id>/`.** v1.5 leaves them. v1.6 may add a "Clean partials" button on the Pipeline.
- **Compare-N-runs button** (v1 deferred §5.5) — natural follow-up since the queue infrastructure is now in place.
- **PBO + CPCV revisit** — separate brainstorm/spec, scheduled after v1.5 ships. PBO is the higher-value candidate per the cpcv-pbo brainstorm screen.
- **Live Strategy → tradelab mapping** still hardcoded in `command_center.html` as `LIVE_TO_TRADELAB`. v1 known rough edge — orthogonal to v1.5 but worth fixing in the same window.

## 13. Pre-implementation checklist (from v1 handoff §6)

- **Confirm uncommitted mid-work in tradelab repo.** `git status` shows 24 modified files + 18 untracked items. Per v1 handoff §6: `config.py` makes `paths.data_dir` optional; without that commit, `/tradelab/strategies` returns a pydantic error. Ask Amit to commit or confirm intentional state before implementation begins.
- **Add `.superpowers/` to `tradelab/.gitignore`.** Currently absent — brainstorm mockup files would otherwise leak into git.
- **Verify v1 baseline still passes:** `pytest tests/web/` → 29 passing + 1 known flaky.
