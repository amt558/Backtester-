# Post-v1.5 Stabilization — Session Summary

**For a future Claude session.** This doc covers the stabilization session that
happened **2026-04-22 evening**, *after* the v1.5 Research tab merge. Read this
AND `RESEARCH_TAB_V1.5_SUMMARY.md` AND `RESEARCH_TAB_V1_SUMMARY.md` first if
you're picking up the work. The v1.5 summary is the feature handoff; this doc
is the "what broke in the first 6 hours of use, and how we hardened it" recap.

**Dashboard PID at session end:** 7592 (detached; will have changed by next session).

---

## 1. TL;DR

Amit booted the dashboard after the v1.5 merge, got **"no data showing up"**
on every tab, and reached out. The research tab was silently offline, the
Alpaca 401 predicted in v1.5 §10.2 had landed, and an unrelated config-path
AttributeError kept turning the `Refresh Data` button into a dead-end.

We fixed **4 real bugs**, shipped **3 integrity improvements**, added **1
memory reference** for future sessions, and committed everything. All tests
green (72/72 web + progress-log). Dashboard healthy. Research tab usable.

One loose end: the `C:\TradingScripts` repo has a misaligned `origin`
(points at APEX's repo due to a force-push on Amit's side). Local commits
stay local for now. See §10.

---

## 2. What was broken on arrival

| Symptom | Root cause | Where |
|---|---|---|
| `/tradelab/jobs` → `503 "No module named 'tradelab.web'"` | Launcher's `import tradelab` probe matched `C:\TradingScripts\tradelab\` as a **PEP-420 namespace package** (no `__init__.py` at the repo root, but the directory is on `sys.path` from the script's cwd). Probe succeeded with an empty namespace, so `sys.path.insert(0, tradelab/src)` was skipped. Real package never loaded. | `launch_dashboard.py` |
| Every `POST /tradelab/jobs` → `503 "missing --progress-log"` | `supports_progress_log()` shells out `python -m tradelab.cli run --help`. Child subprocesses don't inherit runtime `sys.path` — only `PYTHONPATH`. Parent fixed its own path, child still couldn't find tradelab. Cached `False` result meant every POST was rejected. | `launch_dashboard.py` (interaction with `tradelab.web.__init__`) |
| `↻ Refresh Data` → `AttributeError: 'DefaultsConfig' object has no attribute 'universe'` | Handler referenced `cfg.defaults.universe`; that field never existed on the pydantic model. Latent bug — the endpoint was written but its happy path was never exercised post-merge. | `handlers.py:312` |
| Every `/api/v2/*` → `401` (Command Center tabs all blank) | Alpaca had rotated the API keys; `alpaca_config.json` still held the old pair. Exactly the risk flagged in v1.5 §10.2. | `alpaca_config.json` |
| After Amit pasted new keys into `alpaca_config.json`, `↻ Refresh Data` on the Command Center top-right *still* returned blank data | **Command Center bypassed the `/api/*` proxy entirely.** JS called `fetch('https://paper-api.alpaca.markets/...')` directly from the browser using keys stored in **localStorage**. Those were the pre-rotation keys. Server-side fix didn't touch them. | `command_center.html` |
| `test_whatif_returns_metrics_and_equity_curve` failing (known flake per v1.5 §7) | `_extract_metrics` did `isinstance(m, dict)`; `BacktestResult.metrics` is typed as `BacktestMetrics` (pydantic BaseModel), not dict — isinstance was False, returned `{}`. Not a flake; a real contract mismatch. | `whatif.py:88-101` |

---

## 3. Bug fixes shipped

| # | Title | Commit | Files |
|---|---|---|---|
| 1 | Launcher probe rejects namespace-package false positive | *(uncommitted — file lives at `C:\TradingScripts\launch_dashboard.py`, now in git at TradingScripts `74a5789`)* | `launch_dashboard.py` |
| 2 | Launcher propagates `PYTHONPATH` to subprocesses | same as #1 | `launch_dashboard.py` |
| 3 | refresh-data uses `_resolve_active_universe()` | tradelab `f9bd404` | `src/tradelab/web/handlers.py` |
| 4 | whatif unpacks `BacktestMetrics` pydantic model | tradelab `2a96007` | `src/tradelab/web/whatif.py` |

### Fix 1+2: Launcher probe

The v1.5 launcher probe was:

```python
try:
    import tradelab as _tl_probe
    del _tl_probe
except ImportError:
    if os.path.isdir(TRADELAB_SRC) and TRADELAB_SRC not in sys.path:
        sys.path.insert(0, TRADELAB_SRC)
```

This was defensive against shadowing a worktree editable install. Problem:
a PEP-420 namespace match (the repo root has no `__init__.py`, so the
`tradelab/` directory is discoverable as an implicit namespace) makes the
probe succeed with an empty, submodule-less namespace. Patched to:

```python
try:
    import tradelab as _tl_probe
    if getattr(_tl_probe, "__file__", None) is None:
        raise ImportError("matched as namespace package, not real package")
    del _tl_probe
except ImportError:
    sys.modules.pop("tradelab", None)
    if os.path.isdir(TRADELAB_SRC) and TRADELAB_SRC not in sys.path:
        sys.path.insert(0, TRADELAB_SRC)
        _existing_pp = os.environ.get("PYTHONPATH", "")
        os.environ["PYTHONPATH"] = (
            TRADELAB_SRC + (os.pathsep + _existing_pp if _existing_pp else "")
        )
```

Two changes in one block: the `__file__` check (fix 1) and the
`PYTHONPATH` propagation (fix 2). The `sys.modules.pop` is essential —
inserting to `sys.path` after a namespace match doesn't invalidate the
cached module; the subsequent `from tradelab.web import handlers` would
otherwise reuse the namespace.

### Fix 3: refresh-data resolver

Was:
```python
universe_name = payload.get("universe") or cfg.defaults.universe
```

Now:
```python
universe_name = payload.get("universe") or _resolve_active_universe()
if not universe_name:
    return _err("no universe selected and no default available")
if universe_name not in cfg.universes:
    return _err(f"unknown universe: {universe_name!r}")
```

`_resolve_active_universe()` was already the pattern used by job submission
(reads `.cache/launcher-state.json::activeUniverse` with utf-8-sig, falls
through to first yaml universe). refresh-data now matches.

### Fix 4: whatif metrics extraction

Was:
```python
m = result.metrics if hasattr(result, "metrics") else {}
if isinstance(m, dict):
    return { ... }
return {}
```

`BacktestResult.metrics` is typed `BacktestMetrics` (pydantic) — never a
dict, so this always returned `{}`. Now:

```python
m = getattr(result, "metrics", None)
if m is None:
    return {}
if hasattr(m, "model_dump"):
    m = m.model_dump()
if not isinstance(m, dict):
    return {}
return { ... }
```

---

## 4. Integrity improvements shipped

| # | Title | Commit | Files |
|---|---|---|---|
| A | Dashboard files under version control + `.gitignore` hardening | TradingScripts `74a5789` | `launch_dashboard.py`, `command_center.html`, `.gitignore` |
| B | Browser Alpaca fetches routed through `/api/*` proxy | TradingScripts `f593ab8` | `launch_dashboard.py`, `command_center.html` |
| C | Boot-time self-check of tradelab.web handlers | TradingScripts `f593ab8` *(bundled with B — should have been its own commit)* | `launch_dashboard.py` |
| D | 3 orphan strategy files tracked in tradelab repo | tradelab `33ab47f` | `strategies/frog.py`, `strategies/qullamaggie_ep.py`, `strategies/s7_rdz_momentum.py` |

### A: Version control for `launch_dashboard.py` + `command_center.html`

Both files previously lived at `C:\TradingScripts\` with no git coverage —
only protected by ad-hoc `.bak-*` sidecars. Losing that dir lost them.

`.gitignore` at `C:\TradingScripts\` gained two rules:
- `alpaca_config.json` — prevents API keys from ever being committed
- `*.bak-*` — manual backup sidecars are noise, not source of truth

Scanned both repos' history beforehand: `alpaca_config.json` was never
tracked in tradelab *or* TradingScripts, so no credential leak risk from
existing commits.

### B: `/api/*` proxy routing

**Problem v1.5 inherited:** the Command Center's `alpacaFetch()` called
Alpaca directly from the browser (`https://paper-api.alpaca.markets`,
`https://data.alpaca.markets`) using keys stored in **localStorage**. This
meant rotating Alpaca keys required updating *both* `alpaca_config.json`
(server-side) *and* localStorage (browser-side). When only one was
updated, refresh silently returned 401 → `null` → blank UI.

**Change:**
- `alpacaFetch()` now hits `'/api' + endpoint` — no Alpaca hostname, no
  localStorage headers. The server-side proxy adds the real auth headers.
- `proxy_alpaca()` in the launcher gained dual-host routing:
  `/v2/stocks/*` → `data.alpaca.markets`, everything else → `paper-api.alpaca.markets`.
- Dead constants `BASE` and `DATA_BASE` removed from the HTML.
- `refreshData()`'s client-side `if (!API_KEY)` gate removed; the
  `showNoCreds()` message is now called when the proxy itself returns
  null (401 from server → null account → show the "no creds" UI).

**Verified live:** all 5 Alpaca endpoints (`/v2/account`, `/v2/positions`,
`/v2/orders`, `/v2/account/portfolio/history`, `/v2/stocks/SPY/bars`)
return 200 via the proxy.

**UX note:** the credential-entry UI is now vestigial — what the user
types is stored in localStorage but never sent over the wire. The
"connectionDot" indicator still toggles on localStorage presence. Leaving
for later cleanup; the behavioral bug class is gone.

### C: Boot self-check

New function `self_check()` in `launch_dashboard.py`, called from `main()`
immediately after handlers load. It calls `_handlers.handle_get_with_status(...)`
for 4 routes (`/tradelab/jobs`, `/tradelab/strategies`, `/tradelab/data-freshness`,
`/tradelab/runs`) *directly, in-process* (no HTTP round-trip). Any `status >= 400`
or exception is captured and printed to stderr after the banner. The banner's
`Research:` line shows `ONLINE (self-check: N issue/s)` if any were detected.

Both Fix #1 (namespace-package) and Fix #3 (cfg.defaults.universe) would
have been caught here on the *next* dashboard start, instead of at
user-click time.

Intentionally skipped: testing POST routes (side effects like
`download_symbols()`) and proxying through Alpaca (network dependency).
GETs are sufficient for the bug class we care about.

### D: Orphan strategies

Per v1.5 summary §10.1, three strategy modules (`frog.py`,
`qullamaggie_ep.py`, `s7_rdz_momentum.py`) existed on disk and were
registered in `tradelab.yaml` but weren't in git. `git clean -fd` could
have silently deleted them. Now tracked. File contents unchanged — this
was pure hygiene.

**Note:** two *other* strategy files surfaced in my first read —
`cg_tfe_v15.py` and `viprasol_v83.py`. Initially miscounted as 5
orphans; both were actually already tracked. Corrected.

---

## 5. Architecture changes from v1.5

### Before (v1.5 merge state)

```
Browser → https://paper-api.alpaca.markets (direct, localStorage-keyed)
Browser → https://data.alpaca.markets      (direct, localStorage-keyed)
Browser → http://localhost:8877/tradelab/* (proxy via handlers.py)
Browser → http://localhost:8877/api/v2/*   (proxy — but nothing called this!)
Browser → http://localhost:8877/config     (proxy)
```

The `/api/*` proxy existed and *worked* (tested via curl), but no JS
client code hit it. Vestigial infrastructure nobody was using.

### After this session

```
Browser → http://localhost:8877/api/v2/*   ──► server-side proxy ──► paper-api.alpaca.markets
                                                                  OR data.alpaca.markets (routed on /v2/stocks/*)
Browser → http://localhost:8877/tradelab/*  (unchanged)
Browser → http://localhost:8877/config      (unchanged)
```

One host touched by the browser (localhost:8877). Keys live only in
`alpaca_config.json`. Single place to rotate.

### Boot flow (new self-check)

```
1. Probe `import tradelab`; reject namespace-package matches; insert TRADELAB_SRC into sys.path
2. Set PYTHONPATH so subprocesses can find tradelab
3. chdir to TRADELAB_ROOT
4. Import tradelab.web.handlers (soft — research tab disables if this fails)
5. Run cleanup_old_staging()
6. Load alpaca_config.json
7. Build ThreadedHTTPServer
8. ── NEW ── self_check() runs 4 handler GETs, captures issues
9. Print banner; any self-check issues go to stderr under it
10. serve_forever()
```

---

## 6. New gotchas (beyond v1.5 §4)

### 6.1. PEP-420 namespace-package probe

Documented in detail in §3 fix 1. Short version: `import tradelab` from
`C:\TradingScripts` cwd matches `C:\TradingScripts\tradelab\` as a
namespace package. Always check `__file__ is not None` before assuming
the probe found a real package.

### 6.2. `sys.path` doesn't propagate to child processes

Runtime `sys.path.insert(0, ...)` affects the current process only.
`subprocess.Popen([sys.executable, "-m", "tradelab.cli", ...])` gets a
fresh Python with default `sys.path` + whatever is in the `PYTHONPATH`
env var. Always set both.

### 6.3. `BacktestResult.metrics` is pydantic, not dict

If new code in `tradelab.web` wants to poke at metrics fields, call
`result.metrics.model_dump()` or access fields directly via attribute
(`result.metrics.profit_factor`). Don't `isinstance(m, dict)` and
bail — that was the `whatif.py` bug.

### 6.4. Alpaca keys must be rotated in *two* places (pre-Fix B)

This is fixed now — only `alpaca_config.json` matters. But if someone
reverts Fix B, they re-inherit the bug. Documented for posterity.

---

## 7. Test baseline

`pytest tests/web/ tests/cli/test_progress_log.py` → **72 passed, 0 failed**.

Was 71+1 at v1.5 merge (whatif flake). Whatif flake fixed in this session
(Fix 4). Clean signal.

Pre-existing baseline failures outside the web+progress-log suites that
I didn't touch this session:
- `tests/cli/test_cli_run.py::test_cli_run_orchestrates_download_backtest_report`
  — FileNotFoundError. Pre-dates v1.5.
- `tests/cli/test_cli_universes.py::test_cli_run_universe_resolves_symbol_list`
  — same FileNotFoundError pattern.

---

## 8. Commits made

### tradelab (amt558/Backtester-, `master`, **pushed**)

```
2a96007 fix(web): whatif unpacks BacktestMetrics pydantic model
33ab47f chore(strategies): track frog, qullamaggie_ep, s7_rdz_momentum
f9bd404 fix(web): refresh-data uses _resolve_active_universe
b61efae docs: v1.5 summary + v1.6 handoff          ← v1.5 summary doc commit
8ef3153 fix(web): force UTF-8 in supports_progress_log probe   ← last pre-session commit
```

3 new commits pushed to `origin/master`.

### C:\TradingScripts (**local only**, see §10)

```
f593ab8 feat: route Command Center Alpaca fetches through /api proxy    ← also contains self-check
74a5789 chore: track dashboard launcher and Command Center HTML
41593ee feat: Viprasol v8.3 Universe Screener ...                      ← pre-session
```

2 new commits. Not pushed — see §10.

---

## 9. Memory added

One new memory file at `C:\Users\AAASH\.claude\projects\C--Users-AAASH\memory\`:

- `reference_launch_dashboard_probe.md` — documents the two gotchas from
  §6.1 and §6.2 so a future session doesn't rediscover them from scratch.
  Indexed in `MEMORY.md`.

No other memory changes. Existing memory (project_tradelab_web_dashboard,
project_tradelab, feedback_web_over_hotkeys, reference_powershell_utf8_bom)
left untouched.

---

## 10. TradingScripts remote divergence — loose end

**Status:** `C:\TradingScripts\` has two local commits (`74a5789`, `f593ab8`)
that are NOT pushed.

**Why not:** mid-session I ran `git fetch origin main` and discovered the
remote (`https://github.com/aaasharma870-art/Optuna-Screener.git`) had
taken a **forced update** — the old Viprasol-base (`41593ee`) was replaced
with ~20 commits of unrelated **APEX pipeline** code (apex/, CPCV, PBO,
DSR, etc.). See `project_apex_pipeline.md` memory.

In other words: the Optuna-Screener GitHub repo is APEX's repo now, not
the dashboard's. Pushing my 2 dashboard commits there would pollute APEX.

**Amit said "SKIP ALL THIS"** when offered the option to create a new
GitHub repo (`algotrade-dashboard`). So the commits live local-only.

**Implication for the next session:**
- `C:\TradingScripts\`'s `origin` points at APEX's repo (misleading).
- A careless `git push` will reject (remote is ahead) — **not** a silent
  pollution risk.
- If the next session wants a dashboard remote, offer option 1 again:
  create a new GitHub repo, repoint `origin`, push. Or `git remote remove origin`
  to drop the misleading pointer entirely.

---

## 11. How to resume

If a future Claude session picks this up:

1. **Read the three summary docs in order**: `RESEARCH_TAB_V1_SUMMARY.md`,
   `RESEARCH_TAB_V1.5_SUMMARY.md`, then this one.
2. **Confirm live state**:
   ```powershell
   netstat -ano | findstr ":8877"    # is the dashboard running?
   curl http://localhost:8877/tradelab/jobs   # should be 200
   curl http://localhost:8877/api/v2/account  # should be 200 if Alpaca keys fresh
   ```
3. **Confirm repo state**:
   ```powershell
   cd C:\TradingScripts\tradelab ; git log --oneline -5       # top should be 2a96007
   cd C:\TradingScripts         ; git log --oneline -5        # top should be f593ab8
   cd C:\TradingScripts         ; git remote -v               # origin = APEX repo (don't push)
   ```
4. **Confirm test baseline**:
   ```powershell
   cd C:\TradingScripts\tradelab
   $env:PYTHONPATH = "src"
   $env:PYTHONIOENCODING = "utf-8"
   python -m pytest tests/web/ tests/cli/test_progress_log.py -q
   # expected: 72 passed
   ```
5. **Restart the dashboard** (the original PID won't survive across reboots):
   ```powershell
   $env:PYTHONIOENCODING = "utf-8"
   Start-Process -FilePath 'C:\Users\AAASH\AppData\Local\Microsoft\WindowsApps\python.exe' `
     -ArgumentList 'C:\TradingScripts\launch_dashboard.py' `
     -WorkingDirectory 'C:\TradingScripts' -WindowStyle Hidden -PassThru
   ```

### Do NOT

- Re-introduce the bare `import tradelab` probe in `launch_dashboard.py`
  without the `__file__ is None` check — you'll re-create the v1.6-era silent offline bug.
- Skip the `PYTHONPATH` propagation — every child subprocess (JobManager,
  probes) needs it.
- Add `APCA-API-*` headers back into the browser `alpacaFetch` — keys
  live in `alpaca_config.json` only now.
- Push `C:\TradingScripts\main` to `origin` without first checking whether
  `origin` still points at APEX. See §10.
- Commit the ~15 pre-existing modified files in the tradelab working
  tree (cli.py, engines/*, dashboard/*, tradelab.yaml, TRADELAB_MASTER_PLAN.md,
  etc.) — those are Amit's WIP from prior sessions, not this one's work.

### Open items (prioritized)

1. **Decide TradingScripts remote** — create a dashboard repo, or nuke the
   misleading origin pointer. Unblocks future pushes.
2. **Remove the vestigial credential-entry UI** from Command Center — the
   fields/localStorage-save are now pure theater. Low priority, pure cleanup.
3. **v1.5 §7 backlog** — 5 perf/style items (probe-on-boot, resolver
   error logging, JobManager cwd, private-attr cleanup, SSE threading.Event).
   ~3–4 hrs total. None are urgent.
4. **2 pre-existing tests/cli/ FileNotFoundError failures** (pre-dates v1.5).
   Low priority.

---

## 12. References

**In this repo:**
- This doc: `tradelab/docs/superpowers/POST_V1.5_STABILIZATION_SUMMARY.md`
- v1.5 handoff: `tradelab/docs/superpowers/RESEARCH_TAB_V1.5_SUMMARY.md`
- v1 handoff: `tradelab/docs/superpowers/RESEARCH_TAB_V1_SUMMARY.md`

**Outside this repo:**
- `C:\TradingScripts\launch_dashboard.py` — now tracked in `C:\TradingScripts`'s git repo
- `C:\TradingScripts\command_center.html` — same
- Backups from before this session: `launch_dashboard.py.bak-2026-04-22-v16fix`,
  `command_center.html.bak-2026-04-22-v1.5`

**Memory (for future Claude sessions):**
- `reference_launch_dashboard_probe.md` — §6.1 + §6.2 gotchas (NEW this session)
- `project_tradelab_web_dashboard.md` — v1 + v1.5 decisions
- `project_apex_pipeline.md` — explains what's in the Optuna-Screener remote now
- `feedback_web_over_hotkeys.md` — Amit prefers web over launcher hotkeys
- `reference_powershell_utf8_bom.md` — the BOM gotcha from v1.5 §4.2
