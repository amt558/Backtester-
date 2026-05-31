# Python-only Strategy Lifecycle in Command Center — Design Spec

**Date:** 2026-05-31
**Status:** Approved (design); pending implementation plan
**Branch:** `feat/research-tab-v3` (tradelab repo) + `validation-suite` (root repo, `command_center.html`)

## Goal

Make the Command Center a single, Python-only strategy lifecycle:

> Develop a strategy in Python → **import** it in the Command Center → **test** it
> (backtest + gates + QuantStats) → **manually accept** it → **toggle** it onto the
> Overview tab as a card **linked to Alpaca** for trading.

Pine Script and TradingView-CSV input are retired from the UI. Python is the only
authoring and backtest path.

## Confirmed decisions

1. **Input method = Method A + auto-discovery (C).** No Pine, no CSV, no browser
   upload of code. Strategies are authored as `.py` files in
   `src/tradelab/strategies/`; the Command Center discovers and imports them.
2. **Accept gating = advisory.** The qualification badge (from gate pass/fail)
   informs; the user's manual judgment decides. The Accept toggle is always
   available, but accepting a non-ROBUST strategy requires an explicit confirm.
3. **Accept toggle → Alpaca enrollment, paper-default.** Accepting enrolls the
   strategy into the existing live-trading roster, defaulting to **paper** and
   protected by the existing `kill_switch`. No real-money orders until the user
   explicitly goes live.

## Components

### 1. Import (retire Pine/CSV; Python auto-discovery)

- **Backend** `GET /tradelab/strategies/discoverable`: scan
  `src/tradelab/strategies/*.py` for `Strategy` subclasses (importlib + subclass
  check) whose name is **not** already in `tradelab.yaml`'s `strategies:`. Return
  `[{module, class_name, suggested_name, timeframe, requires_benchmark}]`.
- **Backend** `POST /tradelab/strategies/import`: given a chosen
  `{module, class_name, name}`, append a `strategies:` entry to `tradelab.yaml`
  (reuse the existing registration helper used by `new_strategy`). Idempotent;
  refuse duplicates.
- **Frontend:** the "Score New Strategy (CSV + Pine)" modal becomes **"Import
  Strategy"** — a dropdown of discoverable strategies + an **Import** button. The
  Pine-source and CSV inputs/handlers are removed from this modal.
- **Unwire (do not delete):** the inbox watcher, `csv_scoring`, Pine-lint, and
  `/tradelab/new-strategy` Pine path remain in the repo but are no longer reachable
  from the dashboard UI.

### 2. Test

- Selecting an imported strategy + **Test** runs the existing engine path
  (`tradelab run <name> --full` or a lighter test profile) producing: backtest →
  robustness verdict → **Validation Suite** (8 report-only checks) → **QuantStats
  tearsheet** → `validation.json` / `robustness_result.json`.
- No new engine work; reuse `cli_run` and the job manager (runs are already async
  CLI subprocesses tracked by `JobManager`).

### 3. Qualify + manually accept

- A **qualification badge** per tested strategy, derived from gate pass/fail:
  the robustness **verdict** (ROBUST/INCONCLUSIVE/FRAGILE) and validation outcomes.
- **Accept toggle** (advisory): always available; if the latest run's verdict is
  not ROBUST, the toggle requires an explicit "accept anyway" confirm. Acceptance
  state persists (config or a sidecar) keyed by strategy name + accepted run_id.

### 4. Accept → Overview card linked to Alpaca

- Accepting creates/links an **Overview card** for the strategy.
- The card **enrolls the strategy into the live roster** via the existing
  `disabled_strategies`/enabled + `kill_switch` machinery the Alpaca bot reads,
  defaulting to **paper**. The card shows live status/positions/P&L.
- Un-accepting removes the card and disables the strategy in the live roster.
- **PLANNING TASK (must verify against code, not assume):** the exact contract by
  which `alpaca_trading_bot.py` + `tradelab/live/` pick up an enabled strategy and
  generate/place orders. The design assumes the bot reads the enabled set + kill
  switch from `alpaca_config.json`/config; the plan must confirm this and the
  paper/live flag before any wiring.

### 5. QuantStats

- Verify `reporting`'s `render_backtest_tearsheet` produces a working
  `quantstats_tearsheet.html` for a Python-strategy run; fix whatever is broken
  (the "make sure QuantStats sheets are working" item). Add a regression check.

## Data flow

```
author .py in strategies/  →  GET /strategies/discoverable  →  [Import] POST /strategies/import
   → tradelab.yaml entry  →  [Test] tradelab run (JobManager)  →  backtest_result.json,
   robustness_result.json, validation.json, quantstats_tearsheet.html
   → qualification badge (verdict + validation)  →  [Accept toggle, advisory]
   → Overview card + live-roster enrollment (paper, kill-switch)  →  Alpaca bot trades
```

## Error handling

- Discovery: skip files that fail to import or contain no `Strategy` subclass; never
  crash the scan. Malformed `tradelab.yaml` → 500 with a clear message.
- Import: refuse duplicate names (409); validate the class is a `Strategy` subclass.
- Accept of a non-ROBUST run: blocked behind an explicit confirm, never silent.
- Alpaca enrollment failures must NOT place orders; default-safe (paper, disabled).

## Testing

- Backend: discovery (finds new subclass, skips registered/broken), import
  (writes yaml, idempotent, rejects dup), accept persistence, the discoverable/
  import/validation routes.
- QuantStats: a regression that asserts a tearsheet renders for a known run.
- Frontend: the existing `test_command_center_html.py` contract style — assert the
  Import modal has the dropdown + Import button and no Pine/CSV inputs; Accept
  toggle present; reuse dark/green styling.

## Out of scope / parked

- Real-money go-live (separate explicit user action beyond this build).
- Pine/CSV deletion (only unwired from UI).
- The parked validation tests (standalone slippage; time-of-day).

## Open items to resolve in the plan (verify against code)

1. Exact Alpaca live-roster contract (`alpaca_trading_bot.py` + `tradelab/live/`).
2. Where acceptance state persists (config vs sidecar) and how the Overview-card
   renderer reads it.
3. Whether "Test" uses `--full` or a lighter default test profile.
