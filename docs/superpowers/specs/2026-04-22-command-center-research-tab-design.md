# Command Center Research Tab — Design Spec

**Date:** 2026-04-22
**Status:** Draft — approved section-by-section, awaiting user review before writing-plans
**Owner:** Amit
**Scope version:** v1 B++

## 1. Problem statement

Amit is a full-time active trader running live paper-trading automation (AlgoTrade Command Center, port 8877) and a separate strategy-discovery pipeline (tradelab CLI + PowerShell launcher). The two systems are loosely linked but operationally fragmented: optuna-dashboard, tradelab per-run HTML reports, QuantStats tearsheets, command_center.html, and a PowerShell launcher all live in separate windows. Managing them across three monitors is cognitively expensive and obscures the research-to-live decision path.

The current plan in memory (tradelab_web_dashboard) was to build a separate FastAPI+Jinja2+HTMX dashboard on port 8500. That plan predated full awareness of the existing command_center.html — which already provides a polished, Alpaca-wired, dark-themed surface with 10 safety mechanisms. Building a second dashboard alongside it would add, not reduce, fragmentation.

## 2. Goal

Add a **Research tab** to the existing `command_center.html`, turning one browser surface into the single daily driver for both live trading and research. Keep the existing four tabs (Overview / Calendar P&L / Strategy Performance / Settings) completely untouched. Reuse the existing dark-theme palette for visual cohesion. Retire the need to open optuna-dashboard, per-run HTML tabs, QuantStats tabs, and the PowerShell launcher for day-to-day work.

## 3. Non-goals

- **Not replacing `tradelab` CLI.** All tradelab commands (`run`, `backtest`, `optimize`, `wf`, `doctor`, etc.) remain. The Research tab views their output and can trigger a subset, but the CLI stays authoritative.
- **Not generating alpha directly.** The dashboard's alpha contribution is via *better selection* (seeing which strategies are ROBUST before promoting, catching drift on live strategies early, running fast sensitivity analysis via sliders). It is not a signal generator or trading engine.
- **Not a rewrite of command_center.html.** Changes are strictly additive: one new tab, one new CSS class prefix (`.research-`), new backend endpoints appended to the existing launcher.
- **Not touching the 10 safety mechanisms.** All existing guardrails documented in `Dashboard_Safety_Mechanisms.pdf` stay functionally identical.
- **Not FastAPI, not Streamlit, not React.** Vanilla JS fetch() + the existing `launch_dashboard.py` http.server. Matches the existing command_center's no-build-step ethos.
- **Not multi-user, not LAN-exposed.** Localhost-only, single-user, same trust model as the existing command_center.

## 4. Architecture

One process, one URL, one browser tab. `launch_dashboard.py` stays the single server on port 8877 and adds new `/tradelab/*` endpoints. It imports tradelab as a Python library — no subprocesses, no separate process supervision, no cross-process serialization.

```
┌─ One-click desktop .bat ──────────────────────────────────┐
│  starts launch_dashboard.py if not running, opens browser │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌─── launch_dashboard.py (port 8877) ─────────────────────┐
  │                                                         │
  │  Existing routes (UNCHANGED):                           │
  │   /               → command_center.html                 │
  │   /api/*          → Alpaca REST proxy                   │
  │   /config         → GET/PUT alpaca_config.json          │
  │                                                         │
  │  NEW routes for Research tab:                           │
  │   GET  /tradelab/runs?strategy=&verdict=&since=&limit=  │
  │   GET  /tradelab/runs/<run_id>/metrics                  │
  │   GET  /tradelab/runs/<run_id>/verdict                  │
  │   GET  /tradelab/strategies                             │
  │   GET  /tradelab/ranges/<strategy_name>                 │
  │   GET  /tradelab/data-freshness                         │
  │   POST /tradelab/whatif                                 │
  │   POST /tradelab/new-strategy                           │
  │   POST /tradelab/refresh-data                           │
  │   GET  /tradelab/reports/<path>  (already served        │
  │                                   via static default)   │
  └─────────────────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
  ┌───────────┐      ┌─────────────┐   ┌─────────────────┐
  │  Alpaca   │      │  tradelab   │   │  Twelve Data    │
  │  (REST)   │      │  (library)  │   │   (via tradelab)│
  └───────────┘      └─────────────┘   └─────────────────┘
```

### Why same process / same port
- **Simplest ops.** One PID to start/stop, one log, one dependency graph.
- **Cheap tradelab access.** `from tradelab.audit import history; from tradelab.engines.backtest import run_backtest` — no serialization cost.
- **No CORS / cross-origin.** Browser fetches both `/api/*` (Alpaca proxy) and `/tradelab/*` from the same origin.
- **Soft dependency.** If `import tradelab` fails at server startup, the Research tab shows "Research offline" and all existing command_center tabs remain fully functional. Tradelab is additive to, never load-bearing for, the live-trading surface.

### Port
`8877` — unchanged. No competing claim.

### Startup cost
Importing tradelab adds 1-2 seconds to `launch_dashboard.py` boot. Acceptable for a daily-restart workflow.

## 5. Data flow

Four data sources, one read path each.

| UI element | Endpoint(s) | Backing store | Refresh cadence |
|------------|-------------|---------------|-----------------|
| Freshness banner | `GET /tradelab/data-freshness` | `.cache/ohlcv/1D/*.parquet` mtime | Every 60s (cheap stat) |
| Live Strategies cards (6) | `GET /tradelab/runs?strategy=<name>&limit=3` one call per card | `data/tradelab_history.db` + `reports/<run>/backtest_result.json` | Tab open + manual refresh |
| Research Pipeline table | `GET /tradelab/runs?limit=50&...filters` | Same as above, paginated | Tab open + manual refresh |
| Dashboard tab in modal | iframe src `/tradelab/reports/<run>/dashboard.html` | Existing tradelab HTML output | Lazy on tab select |
| QuantStats tab in modal | iframe src `/tradelab/reports/<run>/quantstats_tearsheet.html` | Existing tradelab HTML output | Lazy on tab select |
| What-If tab in modal | `GET /tradelab/ranges/<strategy>`, `POST /tradelab/whatif` | `claude_ranges.json` sidecar, live backtest | 300ms-debounced on slider drag |
| New Strategy modal | `POST /tradelab/new-strategy` | Writes `.cache/new_strategy_staging/<name>.py`, runs smoke_5 | On explicit Test/Register click |

### Intentional design choices

**No auto-refresh on runs data.** Tradelab runs are not high-frequency events (a few per day at most). Auto-refresh every 15s (matching Overview tab) would be wasted compute and cause distracting re-renders while you read. Fetch on tab-open + manual refresh button only.

**What-If is the only compute-heavy endpoint.** Single-symbol backtest in ~3-5s via `run_backtest` import. Slider drag is debounced 300ms; rapid drags do not flood. `Ctrl+Enter` bypasses debounce for power users.

**Error contract.** All new `/tradelab/*` endpoints return `200 {data, error}` on expected paths. `error` is `null` on success, a string on failure. Frontend shows errors inline in the relevant panel. Server startup failure on `import tradelab` → endpoints return `503 {error: "..."}`, Research tab banner reads "Research offline — see logs," other tabs unaffected.

## 6. Research tab visual layout

### 6.1 Tab registration

Added as fifth tab in `command_center.html` tab row (line 232-237):

```html
<div class="tabs">
  <div class="tab active" data-tab="overview">Overview</div>
  <div class="tab" data-tab="calendar">Calendar P&L</div>
  <div class="tab" data-tab="performance">Strategy Performance</div>
  <div class="tab" data-tab="settings">Settings</div>
  <div class="tab" data-tab="research">Research</div>  <!-- NEW -->
</div>
```

Tab-content panel added alongside existing `<div id="tab-research" class="tab-content">`. All tab-switching JS at line 826 already handles new tabs via `data-tab` attribute — no JS changes for the tab switcher.

### 6.2 Layout inside the Research tab

```
┌─ Freshness banner (full width) ───────────────────────────────┐
│  Data cache: 4h old ✓   Universe: tier1 (120 symbols)         │
│  Last tradelab run: 2026-04-21 14:22                          │
│  [ ↻ Refresh Data ]  [ + New Strategy ]                       │
└───────────────────────────────────────────────────────────────┘

─── LIVE STRATEGIES — tradelab health ──────────────────────────

[Live card 1] [Live card 2] [Live card 3]   ← 3 columns on wide
[Live card 4] [Live card 5] [Live card 6]     screens, 2 medium, 1 narrow

─── RESEARCH PIPELINE ──────────────────────────────────────────

Filter: [Strategy ▾] [Verdict ▾] [Last 30 days ▾] [Clear]

┌─ 8-col table ────────────────────────────────────────────────┐
│ Strategy │ Verdict │ PF │ WR │ DD │ Trd │ DSR │ Date │      │
│ ...                                                          │
│ [Dashboard][QS][What-If]  ← buttons on hover per row         │
│ Showing 1-50 of N   [ Show 50 more ]                         │
└──────────────────────────────────────────────────────────────┘
```

### 6.3 Freshness banner

- Full-width card at top of tab
- Background color gated by cache age:
  - `<24h`: `--green-bg` border `--green-border`
  - `24-72h`: `--amber-bg` border `--amber-border`
  - `>72h`: `--red-bg` border `--red-border`
- Shows universe name and symbol count
- `Refresh Data` button: triggers `POST /tradelab/refresh-data`; shows spinner on button + toast while downloading via Twelve Data
- `New Strategy` button: opens the paste modal (Section 8)

### 6.4 Live Strategies cards (6 cards, one per live AlgoTrade strategy)

Each card shows the tradelab health of one of the 6 strategies running in `alpaca_trading_bot.py`: S2, S4, S7, S8, S10, S12.

Card contents (top to bottom):
- Header: strategy ID badge + short name + verdict pill (ROBUST / MARGINAL / FRAGILE)
- 4 stats: PF, WR, DD, DSR — color-coded by value
- Trend: last 3 verdicts as R/M/F letters (oldest → newest, left → right)
- Drift flag (conditional): `⚠ degraded` if latest verdict is worse than prior
- Date of latest run
- Two action buttons: `[Dashboard]` `[QS]` — both open the modal (Section 7), on respective tabs

Card border-left color mirrors verdict:
- ROBUST → `--green-border`
- MARGINAL → `--amber-border`
- FRAGILE → `--red-border`
- No data → `--border` (neutral)

When the `⚠ degraded` flag is set, the card adds a subtle `pulse-amber` animation matching existing `.approaching-limit` cards.

**No What-If button on Live Strategies cards.** What-If is deep-work; Live cards are quick-glance. To reach What-If for a live strategy, click `[Dashboard]` → switch to What-If tab inside the modal.

### 6.5 Research Pipeline table

- Renders with `.table-wrapper` + `.table` classes (existing command_center.html styles)
- 8 columns: Strategy, Verdict, PF, WR, DD, Trades, DSR, Date
- Verdict pill colored by value
- PF color-graded: `>1.3` green, `1.0-1.3` amber, `<1.0` red
- DD color-graded: `<-15%` red, `-10 to -15%` amber, else neutral
- Row hover reveals three inline action buttons: `[Dashboard] [QS] [What-If]` (all open modal on respective tabs)
- What-If button is hidden on rows for strategies without a `claude_ranges.json` sidecar
- Sortable by any column (click header)
- Pagination: default 50 rows, `[Show 50 more]` button appends next page. No page-number navigation.
- Row count: `Showing X-Y of N` text below table

### 6.6 Filter chips

Above the table:
- **Strategy**: multi-select dropdown; all registered strategies
- **Verdict**: multi-select; ROBUST / MARGINAL / FRAGILE / INCONCLUSIVE
- **Date Range**: single-select; Last 7d / 30d / 90d / All (default 30d)
- **Clear**: resets to defaults

Filter state persists in URL hash: `#tab=research&strategy=s2,s4&verdict=ROBUST`. Bookmarkable.

### 6.7 Loading / empty / error states

- **Empty state** (no rows in audit DB matching filter): centered card: "No tradelab runs found. Run `tradelab run <strategy>` or click New Strategy to get started."
- **Loading**: skeleton placeholders (grey bars with shimmer animation) for cards and table rows
- **Error**: red banner at top of tab with `[Retry]` button; rest of tab stays intact where possible

## 7. Modal behavior (Dashboard / QuantStats / What-If)

### 7.1 Modal shell

- 90vw × 90vh, max-width 1800px, centered
- Background `--card` (`#1e2028`), 10px border radius, same shadow as existing `.dialog-box`
- Backdrop: `rgba(0,0,0,0.75)` full-screen behind modal
- Close via: `×` button, ESC key, or clicking backdrop outside modal
- Deep link: opening modal sets URL hash `#run=<run_id>&view=<dashboard|quantstats|whatif>`. Refresh keeps you in the same modal + tab. Closing clears the hash.

### 7.2 Modal header

```
  <Strategy name>  ·  <Verdict pill>  ·  <Run date>       [×]
  [Dashboard] [QuantStats] [What-If]
```

- Strategy-name click: closes modal, sets Pipeline filter to just that strategy
- Verdict-pill click: no-op in v1 (reserved for future "why this verdict" popover)
- Tab bar uses `.tab` class; same styling/behavior as main command_center tab bar

### 7.3 Tab gating

| Strategy type | Dashboard tab | QuantStats tab | What-If tab |
|---------------|---------------|----------------|-------------|
| `single_symbol` with `claude_ranges.json` | ✓ | ✓ | ✓ |
| `single_symbol` without `claude_ranges.json` | ✓ | ✓ | hidden |
| `portfolio` or `sector_rotation` | ✓ | ✓ | hidden |
| No data | ✓ (shows error) | ✓ (shows error) | hidden |

What-If is **hidden** (not grayed out) when not applicable. Two-tab or three-tab header; no disabled UI.

### 7.4 Dashboard tab

- `<iframe src="/tradelab/reports/<run_folder>/dashboard.html">`, lazy (loaded when tab first selected)
- Fills `90vh - 110px` (accounting for modal header + tab bar)
- Background matches `--card` so iframe blends visually
- Loading state: centered skeleton with "Loading dashboard..." text
- Error: banner inside tab + `[Retry]` button

### 7.5 QuantStats tab

- Same iframe pattern, src `/tradelab/reports/<run>/quantstats_tearsheet.html`
- QuantStats tearsheets are long and scroll inside the iframe
- THEME_CSS is already injected into QuantStats output (per tradelab conventions), so visual blending is native

### 7.6 What-If tab

Layout:

```
Symbol: [NVDA ▾]    Test on: [2024-04 to 2026-04 ▾]

┌─ Claude's recommended ranges ──────────────────────────┐
│  atr_period       [==●=====] 14  (Claude: 12-16)       │
│  rsi_threshold    [======●=] 42  (Claude: 38-45)       │
│  stop_atr_mult    [===●====] 1.5 (Claude: 1.3-1.8)     │
│                                                         │
│  💡 Hover each slider for Claude's note                 │
└─────────────────────────────────────────────────────────┘

┌─ Live metrics ───────┬─ Live equity curve ─────────────┐
│  PF     1.42 +0.03   │                                 │
│  WR     58%          │     ─╱╲__╱‾‾\___                │
│  DD    -6.8%         │                                 │
│  Trades 44           │                                 │
└──────────────────────┴──────────────────────────────────┘

[Save as variant]  [Reset to defaults]
```

**Slider data source.** `claude_ranges.json` sidecar per strategy, at `src/tradelab/strategies/<name>/claude_ranges.json`. Schema:

```json
{
  "atr_period": {
    "min": 10,
    "max": 20,
    "default": 14,
    "step": 1,
    "claude_note": "stable plateau 12-16; noisy below 12"
  },
  "rsi_threshold": {
    "min": 25,
    "max": 45,
    "default": 30,
    "step": 1,
    "claude_note": "cliff below 28 — don't go lower"
  }
}
```

No file = What-If tab hidden. File written by Claude (in a separate analysis session) when asked to tune a strategy. The sliders are Claude's recommendation surface, not raw `tunable_params` exposure.

**Live compute loop.**
1. User drags a slider; displayed value updates immediately
2. After 300ms of no further change, frontend POSTs `/tradelab/whatif` with `{strategy, symbol, params, date_range}`
3. Metrics cards dim to 0.5 opacity, equity curve overlays "computing..."
4. Response arrives (~3-5s), metrics populate with delta badges (`PF 1.42 +0.03` green if improved vs defaults, red if worse), equity curve redraws
5. `Ctrl+Enter` bypasses debounce for instant re-compute

**Save as variant.**
- Opens small dialog: "Save these params as `<original_name>_v2`?" (name pre-filled, editable)
- On confirm: server reads `src/tradelab/strategies/<original_name>.py`, rewrites the default params dict in the `__init__` method's `params or {...}` block with the current slider values, and submits the modified source to `POST /tradelab/new-strategy` as a fresh registration. Original file untouched on disk.
- New variant appears in Pipeline after next refresh (Pipeline auto-polls every 30s while a known background registration is in flight)

**Reset to defaults.**
- Sliders snap back to `default` values from `claude_ranges.json`
- Automatically triggers a re-compute (same debounced path)

### 7.7 Keyboard

- `ESC`: close modal (save dialog takes precedence if open)
- `Tab`: cycle Dashboard → QuantStats → What-If → close → Dashboard
- Arrow keys on focused slider: adjust by `step`
- `Ctrl+Enter` in What-If: bypass debounce

### 7.8 Error states

- Iframe 404: inline error banner inside tab with `[Retry]`; other tabs unaffected
- `/tradelab/whatif` failure: inline error in metrics area, `[Retry]` button, equity curve stays on last successful render
- Claude ranges file malformed: What-If tab hidden + console warning; don't crash modal

## 8. New Strategy paste flow

### 8.1 Entry

`[+ New Strategy]` button in the Research tab's freshness banner. Opens modal shell (same 90vw × 90vh as drill-down modal, titled "New Strategy").

### 8.2 Modal contents

```
New Strategy                                                [×]
─────────────────────────────────────────────────────────────

Strategy name:  [my_momentum_breakout____]  (snake_case)

┌─ Paste Python strategy code ──────────────────────────┐
│  (large monospace textarea, ~45 visible lines)        │
└───────────────────────────────────────────────────────┘

ℹ Expected structure  [▾ show scaffold]

[ Test (smoke_5, ~15s) ]      [ Cancel ]
```

After Test completes successfully, the bottom button row is replaced with:

```
✓ Import check passed
✓ Smoke_5 backtest complete (14.2s)

┌─ Metrics ──────┬─ Equity curve (5 symbols overlaid) ──┐
│ PF     1.18    │                                       │
│ WR     54%     │     <chart>                           │
│ DD    -8.3%    │                                       │
│ Trades 28      │                                       │
└────────────────┴───────────────────────────────────────┘

[ Register + run full robustness ]   [ Discard ]
```

### 8.3 Validation pipeline

`POST /tradelab/new-strategy` with `{name, code}` runs:

1. Validate name regex `^[a-z][a-z0-9_]+$` and no collision with existing strategies → 400 if fails
2. Write code to `tradelab/.cache/new_strategy_staging/<name>.py`
3. `importlib` import check → 200 `{error, stage: "import"}` on failure
4. Discover exactly one `Strategy` subclass → 200 `{error, stage: "discover"}` on failure
5. Instantiate with default params → 200 `{error, stage: "instantiate"}` on failure
6. Run `run_backtest` against tradelab's existing `smoke_5` universe (AAPL/NVDA/MSFT/AMZN/TSLA, default 2-year window) → 200 `{error, stage: "backtest"}` on failure
7. Return `{metrics, equity_curves_by_symbol, issues: []}` on success

### 8.4 Register

`POST /tradelab/new-strategy` with `{name, action: "register"}`:
- Atomic rename: `.cache/new_strategy_staging/<name>.py` → `src/tradelab/strategies/<name>.py`
- Appends to tradelab strategy registry
- Kicks off background subprocess: `tradelab run <name> --robustness`
- Returns immediately; Pipeline table auto-polls for new row every 30s while a known background job is running

### 8.5 Discard

`POST /tradelab/new-strategy` with `{name, action: "discard"}`:
- Deletes staging file
- Nothing persisted

### 8.6 Staging hygiene

- Folder is in `.cache/` → gitignored
- Server startup clears files older than 24h (catches abandoned stagings from crashed sessions)
- Modal close without Register or Discard leaves the staging file in place for current session — supports "accidentally closed, reopen and click Register" recovery

### 8.7 Security

Localhost-only, single-user, trusted-pasted-code trust model — same as tradelab's existing `ns` launcher flow. No additional sandboxing. The only practical risk is user pasting their own broken code; that's what the validation pipeline catches.

### 8.8 Edge cases

- Name collision while Test → Register: fails with "name now taken" error; user picks new name, staging file preserved, re-registers
- Stale universe data: data-freshness banner warns at top of modal if cache >72h
- Import passes but runtime errors on first symbol: shows full traceback with line number; doesn't pretend partial success
- Multiple Strategy subclasses: error "expected exactly one Strategy subclass, found: A, B"
- Non-strategy code: error "no Strategy subclass found" + inline scaffold reference

### 8.9 Scaffold reference (shown on [show scaffold] toggle)

```python
from tradelab.strategies.base import Strategy
import pandas as pd

class MyMomentumBreakout(Strategy):
    # Class name: PascalCase. File name (snake_case) set in the field above.

    def __init__(self, name=None, params=None):
        super().__init__(name=name, params=params or {
            "lookback": 20,
            "vol_mult": 1.5,
        })

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # df columns: open, high, low, close, volume; indexed by timestamp
        # Return df with 'entry' (bool) and optional 'stop' (float) columns
        ...
        return df
```

## 9. One-click launcher

Single `.bat` file (`research_dashboard.bat`) placed on desktop:

```bat
@echo off
title AlgoTrade Command Center + Research
cd /d C:\TradingScripts

:: Start server only if not already running on port 8877
netstat -an | findstr :8877 >nul
if %errorlevel%==0 (
    start "" "http://localhost:8877/#tab=research"
) else (
    start "" python launch_dashboard.py
    timeout /t 2 /nobreak >nul
    start "" "http://localhost:8877/#tab=research"
)
```

Opens directly to Research tab via URL hash (Section 6.6 hash-based filter state doubles as deep-linking).

Existing `Launch_Dashboard.bat` can stay for compatibility; the new `.bat` is the preferred daily driver.

## 10. Scope boundary check — what Research tab does NOT do

- Does not trigger `tradelab backtest`, `optimize`, or `wf` from arbitrary parameters (What-If is the one exception, and it's single-symbol only)
- Does not show optuna-dashboard content (intentionally retired from UI per user preference)
- Does not implement shadow-trading integration (deferred from the earlier locked plan — reconsider in v1.5)
- Does not implement cross-strategy correlation analysis (same — v1.5)
- Does not implement portfolio-MC analysis (same — v1.5)
- Does not surface or modify the PowerShell launcher's HOME/STRATEGY/RUN/HEALTH/UTIL/DATA/EXTERNAL/META menu
- Does not expose `alpaca_config.json` editing (that stays in existing Settings tab)

## 11. Testing strategy

### 11.1 Regression smoke (manual, ~5 min, every merge)

- [ ] Overview tab: KPIs populate, strategy cards render, flatten modal opens and cancels
- [ ] Calendar P&L tab: grid renders with coloring
- [ ] Strategy Performance tab: selector changes strategy, chart updates
- [ ] Settings tab: API key fields load, Emergency Flatten dialog opens and cancels
- [ ] All 10 safety mechanisms fire per `Dashboard_Safety_Mechanisms.pdf`
- [ ] Research tab loads, freshness banner shows, 6 Live cards render, Pipeline table shows ≥1 row
- [ ] Modal opens from row click, all applicable tabs render, ESC closes
- [ ] Data refresh button completes without blocking UI
- [ ] New Strategy modal opens, validation rejects bad inputs, test-then-discard leaves no residue in staging folder

### 11.2 Pytest for new endpoints (automated, `tests/web/test_research_endpoints.py`)

- `test_runs_list_returns_audit_db_rows`
- `test_runs_list_filters_by_strategy`
- `test_runs_metrics_reads_backtest_json`
- `test_data_freshness_returns_cache_age`
- `test_whatif_runs_single_symbol_backtest` (completes in <10s)
- `test_whatif_rejects_unknown_strategy`
- `test_new_strategy_rejects_bad_name`
- `test_new_strategy_staging_cleanup_on_discard`
- `test_new_strategy_register_moves_file`

All tests fixture-based; no Alpaca creds, no Twelve Data calls. Total runtime <30s.

### 11.3 Manual What-If verification (one-off)

- Drag each slider end-to-end on a strategy with a known `claude_ranges.json`; confirm metrics change and equity curve redraws
- Confirm 300ms debounce works (no request flood on rapid drag; check Network tab)
- Click "Save as variant" → new strategy appears in Pipeline on next refresh
- Trigger intentional backend error → inline error banner shown, not browser alert

### 11.4 Definition of Done

1. All three test layers above pass
2. `command_center.html` loads without console errors in Chrome/Edge
3. `tradelab doctor` still passes (web-layer imports didn't break tradelab)
4. One-click `.bat` opens the dashboard on fresh reboot

### 11.5 Non-goals for v1 testing

- No Playwright / Selenium E2E (overkill for solo-use tool)
- No load testing
- No visual regression
- No expansion of tests covering existing command_center routes

## 12. Rollback

All changes are additive; rollback is file-level:

| Change | Rollback |
|--------|----------|
| New tab in `command_center.html` | Git revert the single edit (additive div + additive tab-content block) |
| New endpoints in `launch_dashboard.py` | Git revert the route additions |
| New `src/tradelab/web/` package (if any) | Delete folder |
| New `.bat` launcher | Delete file |
| `claude_ranges.json` files | Delete (optional — doesn't block anything if left) |
| `.cache/new_strategy_staging/` | Delete folder (gitignored — safe) |

No schema migrations. No data loss risk. Existing `command_center.html` tabs, Alpaca config, position_map, audit DB all untouched.

## 13. Open questions / deferred to v1.5+

- **Shadow-trading integration**: log paper Alpaca trades for non-live strategies → revive when user wants to promote strategies with more confidence
- **Cross-strategy correlation analysis panel**: show which strategies overlap symbols / entry timing — prevents redundant deployments
- **Portfolio-MC**: roll up per-strategy Monte Carlo into a portfolio-level drawdown distribution
- **One-click CLI triggers** (Option C from brainstorming): web-triggered `tradelab run --robustness`, `tradelab wf`, etc. with SSE progress. Revisit if PowerShell launcher still feels like friction after v1 lands.
- **Portfolio-aware What-If**: multi-symbol parameter sliding for portfolio / sector-rotation strategies
- **Optuna integration in UI**: currently retired. Could return as a "Claude-driven optimization" panel if slider-based tuning proves insufficient.
- **Audit log of web-triggered actions**: record who clicked Register/Refresh/What-If-save and when

## 14. Effort estimate

~7-8 development days for v1 B++, distributed roughly:

| Day | Deliverable |
|-----|-------------|
| 1 | New endpoints skeleton in `launch_dashboard.py`; audit DB + backtest JSON reader; Research tab stub loads |
| 2 | Freshness banner, Research Pipeline table (table + filters + pagination) |
| 3 | Live Strategies cards (6), drift flag logic, modal shell |
| 4 | Modal Dashboard + QuantStats tabs (iframes), keyboard/ESC handling |
| 5 | What-If tab: sliders from `claude_ranges.json`, live metrics + equity curve, 300ms debounce |
| 6 | New Strategy paste flow: validation pipeline, Register/Discard, staging hygiene |
| 7 | Data refresh endpoint wiring to Twelve Data; background robustness subprocess; `.bat` launcher |
| 8 | Regression smoke pass, pytest suite, fixes, final polish |

## 15. References

- `C:\TradingScripts\ALGOTRADE_CONTEXT.md` — command_center.html + alpaca_trading_bot.py details
- `C:\TradingScripts\STRATEGY_CONTROLS_PLAN.md` — per-strategy flatten/disable pattern (precedent for additive changes)
- `C:\TradingScripts\tradelab\TRADELAB_CONTEXT.md` — tradelab conventions, never-propose list
- `C:\TradingScripts\tradelab\src\tradelab\audit\history.py` — audit DB schema reference
- `C:\TradingScripts\command_center.html` — theme palette (lines 9-17), tab system (lines 43-50, 232-237)
- `C:\TradingScripts\Dashboard_Safety_Mechanisms.pdf` — 10 guardrails that must remain functional
