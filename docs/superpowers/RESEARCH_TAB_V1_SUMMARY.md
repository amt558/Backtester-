# Research Tab v1 — Summary & v1.5 Handoff

**For a future Claude session.** This document recaps what v1 shipped, what was deliberately left out, and where v1.5 should pick up. Read this file first if you're continuing this work, along with `TRADELAB_CONTEXT.md` and the project memory files.

**Shipped:** 2026-04-22 · Merged to `master` at commit `5de629b`.

---

## 1. TL;DR

Amit runs **two trading systems** on his three monitors:

| System | Purpose | URL / entry |
|--------|---------|-------------|
| **AlgoTrade Command Center** | Live paper-trading on Alpaca, 6 strategies, 10 safety mechanisms | `C:\TradingScripts\command_center.html` served by `launch_dashboard.py` on port 8877 |
| **tradelab CLI + PowerShell launcher** | Strategy discovery, backtesting, robustness gauntlet, audit DB | `C:\TradingScripts\tradelab\` with `tradelab-launch.bat` |

Before v1, these two systems were loosely linked (`#` launcher key opened the command center in a browser) but otherwise separate. Research artifacts lived as scattered HTML files in `tradelab/reports/*/dashboard.html`. Managing them across monitors was cognitively expensive.

**v1 adds a fifth "Research" tab to `command_center.html`** that surfaces tradelab audit output inside the existing dashboard. It is purely additive — zero changes to the four existing tabs or the 10 safety mechanisms. Everything localhost-only, no new process, no new port.

---

## 2. What v1 delivered

### New tab in `command_center.html`

- **Freshness banner** (top) — parquet cache age, color-coded (green <24h / amber <72h / red stale), with `Refresh Data` + `New Strategy` buttons
- **Live Strategies cards** (6 cards, one per live AlgoTrade strategy) — verdict pill, PF / WR / DD / DSR, 3-run trend, `⚠ degraded` flag, Dashboard + QS buttons
- **Research Pipeline table** — 8 columns (Strategy, Verdict, PF, WR, DD, Trades, DSR, Date), filter chips (strategy / verdict / date range), pagination ("Show 50 more"), click-row-to-open-modal
- **Modal overlay** (90vw × 90vh) with 3 tabs:
  - **Dashboard** — iframe to `reports/<run>/dashboard.html`
  - **QuantStats** — iframe to `reports/<run>/quantstats_tearsheet.html`
  - **What-If** — Claude-recommended slider tuning (hidden if no `claude_ranges.json` exists). 300ms debounced single-symbol backtest, equity curve redraws, "Save as variant" button promotes the sliders' config to a new registered strategy
- **New Strategy modal** — paste Python code + type name, Test runs smoke_5 validation (~15s), Register writes to `src/tradelab/strategies/` + appends to `tradelab.yaml` + auto-fires `tradelab run <name> --robustness` in the background
- **Name normalization** — input accepts hyphens + uppercase (`TEST-A5`), stored as snake_case (`test_a5`) for Python module validity

### Backend — new `tradelab.web` package

All files at `src/tradelab/web/`:

| File | Responsibility |
|------|----------------|
| `audit_reader.py` | Read `data/tradelab_history.db` + join `reports/<run>/backtest_result.json` |
| `freshness.py` | Parquet cache age for the banner |
| `ranges.py` | Read `strategies/<name>/claude_ranges.json` sidecar |
| `whatif.py` | Single-symbol backtest runner for slider debouncing |
| `new_strategy.py` | Paste → stage → validate → register pipeline |
| `handlers.py` | HTTP route dispatcher (all `/tradelab/*` routes) |

Tests at `tests/web/` — 29 passing (1 integration test flakes on real data; low priority).

### `launch_dashboard.py` rewrite

Now imports `tradelab.web.handlers` and dispatches `/tradelab/*` routes. Runs as `ThreadedHTTPServer` with daemon threads (was single-threaded; would have blocked under any concurrency). Uses `subprocess.Popen` with `DETACHED_PROCESS` for browser-open on Windows (avoids GIL stall in `serve_forever`). Tradelab is a soft dep — if `import tradelab` fails at startup, the Research tab shows "Research offline" and the live-trading tabs keep working.

### One-click launcher

- `C:\TradingScripts\research_dashboard.bat` — checks port 8877, starts server if not running, opens browser to `#tab=research`
- **Desktop shortcut** at `C:\Users\AAASH\OneDrive\Desktop\AlgoTrade Research.lnk` pointing at the .bat

### Safety / rollback

- Backups at `C:\TradingScripts\command_center.html.bak-2026-04-22` and `C:\TradingScripts\launch_dashboard.py.bak-2026-04-22`
- Change log at `C:\TradingScripts\CHANGELOG-research-tab.txt`
- Rollback plan in the design spec section 12

### Reference docs in the repo

| Path | Purpose |
|------|---------|
| `docs/superpowers/specs/2026-04-22-command-center-research-tab-design.md` | 564-line design spec |
| `docs/superpowers/plans/2026-04-22-command-center-research-tab.md` | 3165-line implementation plan (15 tasks) |
| `docs/superpowers/RESEARCH_TAB_V1_SUMMARY.md` | This file |

---

## 3. Architecture snapshot

```
┌─ Desktop shortcut ─────────────────────────────────────────┐
│  AlgoTrade Research.lnk → research_dashboard.bat           │
└─────────────────────────────┬──────────────────────────────┘
                              ▼
┌─ launch_dashboard.py (port 8877, ThreadedHTTPServer) ──────┐
│                                                             │
│  Existing routes (UNCHANGED):                              │
│    /               → command_center.html                   │
│    /api/*          → Alpaca REST proxy                     │
│    /config         → GET/PUT alpaca_config.json            │
│                                                             │
│  NEW routes for Research tab:                              │
│    GET  /tradelab/runs                                     │
│    GET  /tradelab/runs/<id>/metrics                        │
│    GET  /tradelab/runs/<id>/folder                         │
│    GET  /tradelab/data-freshness                           │
│    GET  /tradelab/strategies                               │
│    GET  /tradelab/ranges/<name>                            │
│    POST /tradelab/whatif                                   │
│    POST /tradelab/new-strategy (test | register | discard) │
│    POST /tradelab/save-variant                             │
│    POST /tradelab/refresh-data                             │
│    GET  /tradelab/reports/*  (static iframe fodder)        │
└────────────┬──────────────────────┬────────────────────────┘
             ▼                      ▼
      ┌───────────┐         ┌─────────────┐
      │  Alpaca   │         │  tradelab   │
      │  (REST)   │         │  (library)  │
      └───────────┘         └─────────────┘
```

**Guarantee:** `launch_dashboard.py` imports tradelab as a library. No subprocesses per request, no cross-process state, no new services. One PID, one log.

---

## 4. What was deliberately omitted

Critical context for v1.5 planning — these were explicit non-goals, not oversights.

### 4.1 Backtest-trigger buttons

**Nothing in the web UI fires `tradelab backtest`, `tradelab optimize`, `tradelab wf`, `tradelab run --robustness`, or `tradelab run --full`.** The Research tab *views* backtest output; it does not *trigger* runs (except two narrow cases: What-If slider compute, and auto-firing robustness when a brand-new strategy is registered).

All trigger actions still go through:
- `tradelab <cmd>` from the CLI, or
- The PowerShell launcher keys `1`/`2`/`3`/`3r`/`3f`

Doing this well requires a background task runner, process supervision, and either SSE progress streaming or polling. That is v1.5's main territory (see §5).

### 4.2 Optuna dashboard integration

Amit explicitly said he doesn't create many Optuna studies and the optuna-dashboard UI is not useful to him. The `.cache/optuna_studies.db` still exists and the `tradelab optimize` CLI still uses it, but **no web surface** reads or displays Optuna studies. The launcher menu's optuna-dashboard keys (`5`, `k`) remain available via the PowerShell launcher.

### 4.3 Shadow-trading logger

Dropped from the earlier scoped plan. The Alpaca paper account is already wired (via `alpaca_config.json`), but there is no separate logger that paper-trades research strategies before promotion. **Planned for v1.5 if Amit wants automatic alpha validation of candidates before live deploy.**

### 4.4 Cross-strategy correlation analysis

Dropped. The hypothesis was that side-by-side correlation of entry dates / symbol overlap would prevent redundant deployments (e.g., three strategies all longing AAPL at the same time). Not built in v1.

### 4.5 Portfolio-MC rollup

Dropped. A portfolio-level Monte Carlo that rolls up per-strategy MC into a portfolio drawdown distribution was in the earlier plan; cut for scope.

### 4.6 Compare-N-runs view

Dropped. The existing `tradelab compare <folders...>` CLI produces a comparison HTML; no multi-select in the web Pipeline table hooks into it.

### 4.7 Gate-check / screener panels

Dropped. `tradelab gate-check` and `tradelab screen` are valuable CLI tools for indicator correlation and per-symbol screening; neither has a web view.

### 4.8 Progress streaming (SSE / WebSocket)

Not built. All compute feedback is synchronous request/response. The current New-Strategy register flow fires a background subprocess and the Pipeline table will *eventually* show the new row when it refreshes — but the user has no live progress indicator.

### 4.9 `claude_ranges.json` population workflow

The What-If tab reads `src/tradelab/strategies/<name>/claude_ranges.json`, but no UI or Claude-invocation helper **writes** those files. Amit is expected to ask Claude (in a separate session) to produce them by pasting strategy source. Once a strategy has no sidecar, the What-If tab is simply hidden.

---

## 5. Next target — v1.5 brainstorm seeds

Ordered by expected alpha / UX value per day of build effort.

### 5.1 Trigger-a-run (highest priority)

**The headline v1.5 feature.** Most valuable for Amit's stated "prefer web over hotkeys" preference.

Two increments possible:

- **Lite** (~1-2 days): `[Run ▾]` dropdown on each Live Strategy card and Pipeline row with options `Backtest / Optimize / Walk-forward / Robustness / Full`. Fires `subprocess.Popen([python, -m, tradelab.cli, run, <name>, <flag>])`. Pipeline auto-polls every 30s while any tracked subprocess is alive. No progress bar; no cancellation; new rows appear when the CLI finishes writing to the audit DB.
- **Full** (~4-5 days): Same buttons + a job-tracker table at the top of the tab showing "Running" / "Queued" / "Done" / "Failed" with live progress via SSE. Each strategy's card gets a small spinner while its job is active. Cancel button kills the subprocess. Job state persists across server restarts via a `.cache/jobs.json` file.

**Design question for the brainstorm:** which CLI flags actually matter to Amit day-to-day? The PowerShell launcher exposes `1/2/3/3r/3f` — mapping those to web buttons is simple, but maybe he only really uses `3r` and `3f`. Leaner is better.

### 5.2 `claude_ranges.json` authoring loop

Right now this file type is a dead hook — no way to produce one from the web. Ideas:

- A "Tune via Claude" button on any strategy card/row that copies the strategy source to the clipboard with a pre-baked prompt that asks Claude (in Claude Desktop/Code) to return a `claude_ranges.json`. User pastes the JSON back.
- Or a server endpoint that accepts a pasted JSON and writes it to `src/tradelab/strategies/<name>/claude_ranges.json`, then the What-If tab becomes visible.

Cheap (~1 day), unlocks the What-If tab for every strategy.

### 5.3 Shadow-trading panel

Before promoting a research strategy to the live Alpaca bot, auto-paper-trade it against live signals for N weeks. Log to a sidecar DB, surface in a new Pipeline column "Shadow P&L (4w)". Adds real alpha — catches strategies that backtest well but decay under live execution conditions.

Medium effort (~2-3 days). Requires a scheduler + signal generator running alongside the existing `alpaca_trading_bot.py`. Reuse the same Alpaca credentials.

### 5.4 Cross-strategy correlation panel

Heatmap of per-pair entry correlation / symbol overlap. Click a hot cell → see the dates of overlap. Small addition to the Research tab below the Pipeline table.

~1 day. Low immediate urgency unless Amit starts running more than 6 live strategies.

### 5.5 Compare-N-runs

Multi-select checkboxes in Pipeline rows → `Compare` button fires `tradelab compare <folders>` and opens the resulting HTML in the modal.

~0.5 day. Matches existing CLI capability.

### 5.6 Gate-check + screener panels

`tradelab gate-check` output → a correlation matrix view. `tradelab screen` → per-symbol view. Both benefit from being in the web UI but are less load-bearing than trigger-a-run.

~1-2 days total.

### 5.7 Optuna study views (cautious — previously declined)

Amit said Optuna is not useful *because he doesn't run studies manually*. If trigger-a-run makes it easier to kick off optimization, Optuna view utility may change. Re-evaluate during v1.5 brainstorm.

---

## 6. How to resume

### If you are a fresh Claude session picking up v1.5:

**Read first:**
1. This file (`docs/superpowers/RESEARCH_TAB_V1_SUMMARY.md`)
2. `TRADELAB_CONTEXT.md` at the tradelab repo root
3. Memory: `project_tradelab.md`, `project_tradelab_web_dashboard.md`, `feedback_web_over_hotkeys.md`

**Then start with the brainstorming skill.** Do not dive into implementation. Ask Amit:

> "v1 of the Research tab is live. For v1.5, the highest-value target is **trigger-a-run buttons** — clicking Run/Robustness/Full from the web without the PowerShell launcher. Two flavors: Lite (~1-2 days, no progress bar) or Full (~4-5 days with SSE progress + cancellation + job state). Which flavor fits what you actually need day-to-day? Or is a different deferred item (shadow-trading, claude_ranges authoring, correlation, compare) higher on your list right now?"

### Before touching code

- Amit has **uncommitted mid-work** in `src/tradelab/cli.py`, `cli_doctor.py`, `cli_run.py`, `config.py`, `pyproject.toml`, and several others. His `config.py` makes `paths.data_dir` optional; without that commit, `/tradelab/strategies` returns a pydantic error. Ask him to commit or at least confirm which uncommitted file states are intentional before you start.
- The Optuna dashboard and launcher keys `5` and `k` remain available but are not a v1 responsibility.
- All of §4 is negotiable for v1.5 — revisit the "deliberately omitted" list during brainstorm; some items (like Optuna) may have changed value now that the Research tab exists.

### Do NOT

- Re-brand the tab
- Modify the 10 AlgoTrade safety mechanisms
- Add dependencies — vanilla Python stdlib + pandas + pytest only
- Break the `.bat` launcher or the 8877 port
- Merge work to master without running `pytest tests/web/` and confirming the baseline (~29 passing + 1 flaky integration)
- Propose Streamlit, FastAPI, or any new web framework. The "single-file command_center.html + launch_dashboard.py" pattern is locked per Amit's preference.
- Build features outside the scope Amit picks during brainstorm — v1 already ate a day of scope creep via unplanned Windows fixes, name-normalization, and bug patches. Stay focused.

### Known v1 rough edges worth polishing during v1.5

- **`tests/web/test_whatif.py::test_whatif_returns_metrics_and_equity_curve`** — integration test asserts on real-data results; replace with a mocked-backtest unit test
- **Live Strategy → tradelab mapping** is hardcoded in `command_center.html` as `LIVE_TO_TRADELAB`. If Amit renames a live strategy or adds/removes from the bot's six, this dict becomes stale. Better: derive from `alpaca_config.json` strategy IDs + a naming rule
- **Strategy filter dropdown empty** until Amit commits his `config.py` work — either prompt him or add a fallback that lists strategies directly from filesystem scan
- **Banner still uses Unicode box-drawing chars** in launch_dashboard.py. `research_dashboard.bat` sets `PYTHONIOENCODING=utf-8` as workaround. Could replace with ASCII
- **Save as variant** rewrites `default_params` via regex in the source file. Fragile if the strategy uses unusual formatting. Could use libcst instead

---

## 7. Contacts / conventions (reminder)

- **Single user, localhost-only, single-machine** — no auth, no LAN exposure, no multi-tenancy
- **Dark theme palette** (`--bg #0f1117`, `--accent #22c55e`, Inter font) is shared between command_center.html and tradelab's per-run dashboards — reuse, don't redefine
- **Err toward FRAGILE verdict** — the research philosophy from tradelab's master plan applies here too. A v1.5 feature that hides or softens fragility signals is a red flag
- **No hot-reload, no build step** — one restart of `launch_dashboard.py` after any backend change, one hard-reload of the browser after any HTML/CSS/JS change
