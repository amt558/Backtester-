# Research Tab v3 — Handover Doc (2026-04-30, after Task 14)

> **Read this if you are picking up the Research Tab v3 implementation.** This document is the single source of truth for "where we are." It supersedes the prior two handoffs (`RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_8.md` for Tasks 1–8, `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_11.md` for Tasks 9–11). Newer than the plan; trust this over plan-body sketches when they conflict.

---

## TL;DR

- **Plan:** `docs/superpowers/plans/2026-04-30-research-tab-v3.md` (18 tasks)
- **Spec:** `docs/superpowers/specs/2026-04-30-research-tab-v3-design.md`
- **Visual mockups:** `.superpowers/brainstorm/216-1777553249/content/{01,02,03}*.html`
- **Branches (cross-repo):**
  - tradelab repo: `feat/research-tab-v3` at `C:\TradingScripts\tradelab\` — HEAD `c3aa0bb`
  - parent repo: `feat/research-tab-v3` at `C:\TradingScripts\` — HEAD `ce9332e7`
- **Done:** Tasks 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14 (15 plan tasks + slice-0). 19 tradelab commits + 9 parent-repo commits on the v3 branches.
- **Next up:** Task 15 — pipeline delete affordances (4 confirm tiers + cascading event broadcast).
- **Test baseline:** **455/455** in `tests/web/` (full suite, ~2 min via Bash). Static-HTML test file alone: **131/131** (~0.3s).
- **Don't run pytest via PowerShell** — see Gotcha #1 in the original handoff. Use Bash.
- **DEPLOY GAP IS WIDE — read the dedicated section below before any smoke.**

---

## What shipped in Tasks 12, 13, 14 (since the Task 11 handoff)

### Task 12 — QuantStats sub-grid + 3 inline SVG charts in expanded tile
- **Parent commit:** `8c0f573c` "feat(command-center): expanded tile QS sub-grid + 3 inline SVG charts (Task 12)"
- **tradelab commit:** `754f2bc` "feat(web): qs-metrics drawdown_series + payload extras + Task 12 FE contract tests"
- **Effect (BE):** Extends `_qs_metrics_response` payload with `drawdown_series` (per-bar peak-to-trough, list[float]), `avg_win_pct`, `avg_loss_pct`, `avg_bars_held`. New `qs_metrics.drawdown_series(returns)` helper — pure pandas, aligned to input index, first bar always 0.
- **Effect (FE):** Replaces the Task 11 placeholder ("QuantStats sub-grid loads in Task 12.") with a real loader:
  - `loadQsForExpandedTile(tile, runId)` — fetches `/tradelab/runs/<id>/qs-metrics`, writes "Loading…" → real content (or "No run data" / "Failed to load: <err>") on completion.
  - `qsGridHtml(m)` — 8-cell `.qs-grid` (Total return / Sharpe / Sortino / CAGR / Avg win / Avg loss / Trades / Avg hold) with ok/warn/fail color classes.
  - `qsChartsHtml(m)` — wraps three chart SVGs.
  - `drawdownSvg(series)`, `monthlyHeatmap(matrix)`, `rollingSharpeSvg(series)` — pure inline SVG, degrade to "no data" stub when empty.
  - Wires `expandTile` to call the loader after `tile.innerHTML = expandedTileHtml(s)`.
  - Extends the tab-strip click branch in `wireResearchLiveCardsClick` to swap `.tab-qs ↔ .tab-factors` visibility based on `data-tab`.
- **Tests added:** 3 new `qs_metrics` unit tests, 1 handler test extended in place, 13 new static-HTML tests in `test_command_center_html.py`.

### Task 13 — Cross-strategy factor matrix
- **Parent commit:** `15edc26b` "feat(command-center): cross-strategy factor matrix (Task 13)"
- **tradelab commit:** `4ce4cd3` "feat(web): /tradelab/strategies-summary + Task 13 matrix contract tests"
- **Effect (BE):** New module `src/tradelab/web/strategies_summary.py` with `get_summaries(db_path)` — walks audit DB newest-first, dedupes by strategy_name, reads each latest run's `robustness_result.json` sibling for verdict + signals[]. Strategies with no scored run still surface (verdict=None, signals=[]) so the matrix can render dimmed rows. Handles missing folder, missing JSON, corrupt JSON, missing DB uniformly. New route `/tradelab/strategies-summary` returning `{strategies: [...]}`.
- **Effect (FE):** Adds the matrix between the Live Cards row and Portfolio Health:
  - `#pipeline-section-header`-style landmark with `#matrix-meta` caption.
  - `.matrix-card` wrapper with `#matrix-grid` (renders into), `.matrix-legend`, `#matrix-alpha-callout`.
  - `FACTOR_COLUMNS` const with the **8 real signal ids** from `src/tradelab/robustness/verdict.py` (`baseline_pf`, `dsr`, `mc_max_dd`, `param_landscape`, `entry_delay`, `loso`, `noise_injection`, `regime_spread`) — NOT the plan's invented ids that would never match real data.
  - `classifyOutcome(signal)` — maps outcome lowercase → cell class (pass/marginal/fail/dim). `inconclusive` falls through to `dim`, NOT `pass`.
  - `renderFactorMatrix()` — fetches `/tradelab/strategies-summary`, builds header + N rows. Computes column-warn flags using SCORED strategies as denominator (untested factors don't get penalized). Empty-signals rows render dimmed.
  - Wired into `researchLoadAll()`.
  - CSS grid template updated `repeat(7) → repeat(8)` to match real signal count.
  - `signals_count` default bumped 7→8 in `renderLiveCard` and `expandedTileHtml`.
- **Tests added:** 7 BE tests in `test_strategies_summary.py`, 9 static-HTML tests in `test_command_center_html.py`.

### Task 14 — Research Pipeline v3 chrome restyle
- **Parent commit:** `ce9332e7` "feat(command-center): Research Pipeline v3 chrome restyle (Task 14)"
- **tradelab commit:** `c3aa0bb` "test(web): pin Research Pipeline v3 chrome contract (Task 14)"
- **Effect:** Layers v3 chrome (`#pipeline-section-header`, `.pipeline-card`, `.pipeline-toolbar`, `class="pipeline"` on the table) over the existing v2 markup so the v3 CSS rules from Task 7 actually apply. **Zero JS contract changes** — `researchPipelineBody`, `researchPipelineTable`, filter selects, `action-btn` buttons, the entire `renderPipelineRows` machinery all keep working. Trash button title changed from "Archive run" → "Delete run" (DELETE flipped to hard-delete in tradelab `840fb0f`; the v2 wording was lying about what the button does).
- **Tests added:** 5 static-HTML tests in `test_command_center_html.py`.

### Test baseline movement

| After   | tests/web/ total | static-HTML test file |
|---------|-----------------:|----------------------:|
| Task 8  |              379 |                   ~84 |
| Task 9  |              391 |                    95 |
| Task 10 |              409 |                   106 |
| Task 11 |              409 |                   104 |
| Task 12 |              434 |                   117 |
| Task 13 |              450 |                   126 |
| Task 14 |          **455** |               **131** |

The +25 jump T11→T12 = 13 new FE tests + 3 new `qs_metrics` unit tests + 9 collection-delta from prior pyc cache reaching the baseline. The +16 T12→T13 = 9 FE + 7 BE. The +5 T13→T14 = FE only.

---

## What's done — full commit log

### tradelab repo (`C:\TradingScripts\tradelab\` on `feat/research-tab-v3`)

```
c3aa0bb  test(web): pin Research Pipeline v3 chrome contract (Task 14)
4ce4cd3  feat(web): /tradelab/strategies-summary + Task 13 matrix contract tests
754f2bc  feat(web): qs-metrics drawdown_series + payload extras + Task 12 FE contract tests
d90ee07  docs(research-v3): thorough handover after Tasks 9, 10, 11
87b957b  test(web): pin Live Card expand contract + repoint drift helper (Task 11)
88a3534  feat(web): POST /tradelab/strategies/<id>/activate one-click endpoint
e964b8a  test(web): assert Live Cards v3 tile contract (Task 9)
1e5b339  docs(research-v3): thorough handover after Tasks 7+8
866cb0a  test(web): assert action-bar contract for Task 8
5e61dd7  test(web): assert research-v3 scope contract (Task 7)
b48e157  docs(research-v3): handoff reflects DELETE semantic flip (840fb0f)
840fb0f  refactor(web): flip DELETE /tradelab/runs/<id> from soft-archive to hard-delete
5a8b103  docs(research-v3): handoff updated through Task 6
b3c8bcc  feat(web): wire 4 Research-v3 routes (qs-metrics, verdict-history, accept activate, permanent delete)
bb237b8  feat(web): extend approve_strategy.accept_scored with activate flag
9954d18  docs(research-v3): handoff after Task 3
44f7a81  feat(web): add run_deletion module
b07adc7  feat(web): add verdict_history module
aec2605  feat(web): add qs_metrics pure-fn module
e0c68a2  docs(research-v3): plan amendments per slice 0 findings
2d5d927  docs(research-v3): slice 0 findings
```

### parent repo (`C:\TradingScripts\` on `feat/research-tab-v3`)

```
ce9332e7 feat(command-center): Research Pipeline v3 chrome restyle (Task 14)
15edc26b feat(command-center): cross-strategy factor matrix (Task 13)
8c0f573c feat(command-center): expanded tile QS sub-grid + 3 inline SVG charts (Task 12)
b9b5494a feat(command-center): Live Card click-to-expand inline (Task 11)
4737748  feat(command-center): Activate state machine + cross-tab linkage (Task 10)
40dfe09c feat(command-center): Live Cards v3 compact tile + drift sparkline (Task 9)
a6023a10 feat(command-center): research-v3 action bar (Task 8)
4c1906d7 feat(command-center): research-v3 CSS scope + Google Fonts (Task 7)
421b1294 feat(launcher): /tradelab/runs/<run_id>/tearsheet pass-through (Task 6)
```

These two branches don't share history. They ship together when v3 is ready to merge.

---

## DEPLOY GAP — READ THIS BEFORE DOING ANY SMOKE

**The gap is now wide.** The running dashboard process at `http://127.0.0.1:8877/` was started before Tasks 5, 10, 12, and 13 landed and serves **stale handlers code** that doesn't include any of these new BE routes:

| Endpoint                                                    | Added in    | Stale-server response                                    | FE behavior                                                              |
|-------------------------------------------------------------|-------------|----------------------------------------------------------|--------------------------------------------------------------------------|
| `GET  /tradelab/runs/<id>/qs-metrics`                       | Task 5      | route exists, but the **payload** lacks T12 keys         | Drawdown chart / heatmap / rolling Sharpe show "no data" stubs           |
| `GET  /tradelab/strategies/<id>/verdict-history`            | Task 5      | 404 catchall                                             | Drift sparklines render 12 dim dots (graceful)                           |
| `POST /tradelab/strategies/<id>/activate`                   | Task 10     | 200 with `{error: "not found"}` from catchall            | Activate click toasts "Activate failed: not found"                       |
| `GET  /tradelab/strategies-summary`                         | Task 13     | 404 catchall (route doesn't exist on stale process)      | Matrix renders "Failed to load: not found" inside the grid               |

**Restart with (the user runs this in their own terminal):**

```powershell
python C:\TradingScripts\launch_dashboard.py
```

Once restarted:
- Drift sparklines populate with real verdict colors (green/amber/red dots).
- Activate on a ROBUST tile actually creates a card and turns the button green.
- Expanded tile's QuantStats sub-grid populates with real numbers + drawdown waveform / monthly heatmap / rolling-Sharpe trace.
- Cross-strategy factor matrix populates with all real strategies from the audit DB.

The pytest suite verifies each handler exhaustively (455 passing tests across BE + FE static-HTML), so the restart is **verification, not gating**. But **the FE has only been smoked against synthetic data** for Tasks 12 and 13 — see "Known problems" P0 below.

---

## Known problems & roadmap to fix them

This section is what differentiates "shipped" from "ready to ship." Each item has a severity (P0 = blocks merging v3, P1 = should fix before/right after merge, P2 = longer-term cleanup).

### P0 (must fix before declaring v3 done)

#### 1. No live-BE smoke for Tasks 12, 13, 14
**Problem:** All Playwright smoke for Tasks 12/13/14 was against the stale dashboard process. The QS sub-grid was verified by stubbing `fetchJSON` with synthetic data; the matrix was verified the same way. We have **no end-to-end evidence** that:
- A real `/tradelab/runs/<id>/qs-metrics` response actually populates the 8-cell grid + 3 charts (number formatting, edge cases like NaN, very long drawdown series).
- A real `/tradelab/strategies-summary` returns the right shape and the matrix renders it correctly (column-warn detection on real data, alpha callout text).
- The pipeline restyle doesn't break filter behavior under real audit load.

**Fix (P0):**
1. User restarts `python C:\TradingScripts\launch_dashboard.py`.
2. Open Playwright MCP, navigate to `http://127.0.0.1:8877/command_center.html`, switch to Research tab.
3. Verify each:
   - **Task 12:** Click `s2_pocket_pivot` (or any tile with a scored run) → expanded tile → QS sub-grid shows real numbers (not all "—"); 3 charts render with real waveforms (not "no data" stubs).
   - **Task 13:** Matrix grid populates with all strategies from `/tradelab/runs?limit=...` (currently ~7-9 strategies based on audit DB). Cells colored. Alpha callout fires (or hides) based on real signal distribution.
   - **Task 14:** Filter selects + Reset button work; row checkboxes still drive Compare/Delete buttons; `action-btn` row delegate still opens dashboard/quantstats/signals modals.
4. Document any deltas, fix, re-smoke.

#### 2. Dashboard process is manually restarted — no auto-restart on handlers.py mtime change
**Problem:** Every time someone modifies `src/tradelab/web/handlers.py` or any of the BE modules it imports, the running process serves stale code until the user manually restarts. This was the proximate cause of the "Failed to load: not found" pattern showing up in 4 different smokes. It also means a future developer can hit a confusing 404 on a route they just wrote.

**Fix (P1):** Add a `watchdog` listener to `launch_dashboard.py` that touches a sentinel file when any `.py` under `src/tradelab/web/` changes; the dashboard's HTTP loop checks the sentinel and self-restarts (or at least reloads `handlers.py` via `importlib.reload`). The receiver already has `watchdog` as a dependency (per memory `reference_receiver_hot_reload.md`), so the pattern is established.

### P1 (fix before/right after merge)

#### 3. `signals_count` is hardcoded to 8 — pill never reflects real per-strategy count
**Problem:** In `renderLiveCard` (line ~4777) and `expandedTileHtml` (line ~5056), the Factors-tab pill defaults to 8. The cache-update path (when metrics fetch resolves) doesn't patch it from real data. So a strategy with only 6 scored signals shows "Factors 8" — incorrect.

**Fix (P2):**
- Option A: Have `/tradelab/strategies-summary` return `signals_count` per strategy; cross-reference into `strategyDataCache` from the matrix render path.
- Option B: When the matrix loads, walk the response and patch `strategyDataCache.get(s.id).signals_count = s.signals.length` for each strategy.
- Option B is one-liner and doesn't require a new BE field. Drop into `renderFactorMatrix()` after the fetch.

#### 4. `fetchJSON` swallows non-2xx responses without throwing
**Problem:** Every loader has to manually check `if (body.error && body.data == null)` after `fetchJSON(...)`. `loadQsForExpandedTile` and `renderFactorMatrix` do this (added in T12/T13). The pre-existing pipeline + drift + activate paths do **not** — they just check `body.data` truthiness, which means a 500 that returns no body silently looks like a 200 with no data. Inconsistent error handling across the codebase.

**Fix (P2):** Update `fetchJSON` to attach `_status` to the returned body (cheap; the response object already has it) and add a sibling `fetchJSONOrThrow` that raises on `!response.ok` for callers that prefer exceptions. Migrate the Task 12 + 13 loaders to the throw variant; pre-existing code unchanged.

#### 5. Matrix only fetches once on tab load — no SSE auto-refresh
**Problem:** After the user scores a new strategy via the Score modal, the factor matrix doesn't update. They have to reload the page or switch tabs and back to see it. Same problem applies to QS sub-grid in expanded tiles (data is cached on first expand).

**Fix (P1):** Task 16 (SSE listener) is already on the plan. When `run_completed` or `card_activated` events arrive, call `renderFactorMatrix()` and invalidate `strategyDataCache`. Should be a one-line dispatch in the SSE handler that Task 16 builds.

#### 6. `.matrix-grid grid-template-columns: 200px repeat(8, 1fr)` is hardcoded to 8
**Problem:** If `FACTOR_COLUMNS` shrinks (e.g. drop `param_landscape` because it's noisy) or grows (add `wfe` for strategies that ran walk-forward), the CSS doesn't auto-adjust. Cells either overflow or leave a blank column.

**Fix (P2):** Use a CSS custom property: `grid-template-columns: 200px repeat(var(--factor-count, 8), 1fr)` and set it from JS in `renderFactorMatrix`: `grid.style.setProperty('--factor-count', String(FACTOR_COLUMNS.length))`. Static-HTML test would change to grep for `var(--factor-count`.

### P2 (longer term cleanup, doesn't block merge)

#### 7. Plan body is increasingly stale — don't trust it for Task 15+
**Problem:** Tasks 12-14 each had multiple plan-vs-DOM mismatches (this handoff documents 9 across 3 tasks; see "Plan-vs-DOM corrections" section). The plan was written before code existed and hasn't been kept current. Tasks 15-18 will have similar drift.

**Fix:** Either (a) update the plan body in-place as each task lands so it stays a current snapshot, or (b) keep the plan as a frozen design doc and treat handoffs as the moving spec. **(b) is what we've been doing implicitly.** Make this explicit at the top of the plan: "Tasks 12+ refer to the most recent handoff doc, not the plan body."

#### 8. Two parallel button styles in pipeline rows — `.action-btn` (v2) vs `.row-trash` (v3, defined-but-unused)
**Problem:** v3 CSS at lines 1198-1200 defines `.row-trash` and `.row-cell-actions`, but the per-row Actions cell still uses 6 `.action-btn` buttons (v2 style). The v3 style is meant to be a single ghost-style trash icon. Task 14 took the pragmatic route of NOT migrating because it would have meant rewriting the entire `actionsCell` (6 buttons → 1 icon + dropdown menu probably).

**Fix:** A future "pipeline action menu" task — collapse the 6 buttons into a single `⋯` trigger that opens a popover with Dashboard / QuantStats / Signals / Robustness / Full / Delete. Out of scope for v3 launch.

#### 9. `test_command_center_html.py` is now 131 tests, ~1500 lines
**Problem:** Single file, growing linearly with each task. Hard to find tests by topic. Slow to scroll.

**Fix (low priority):** Split into `test_command_center_html_research_v3.py` (T7-T18 tests) and leave the original for v2 invariants. Or split by phase (live cards / matrix / pipeline). Don't bother until it crosses 200 tests.

#### 10. Two repos staying in sync is fragile
**Problem:** Every task touches `command_center.html` (parent repo, local-only) AND tests/handlers (`tradelab` repo). PR-level review is awkward because the parent has no remote (per memory `project_workspace_cleanup_2026-04-29.md`). Reverts have to be done across two repos manually.

**Fix:** Either (a) move `command_center.html` into the tradelab repo so it's one PR, or (b) git-tag both repos at each task milestone (`v3-task-14`) so a roll-back is `git checkout v3-task-13` × 2 instead of cross-referencing commit hashes by hand.

#### 11. Static-HTML tests don't exercise the actual JS — they grep source strings
**Problem:** `test_command_center_html.py` opens the HTML file and asserts string presence. This catches "function deleted" and "ID renamed" but NOT "function exists but throws TypeError on real data." The Playwright smokes are the real correctness check, but they're manual.

**Fix:** Task 17 (Playwright smoke gate) is on the plan. Until that lands, the workflow is "static tests + manual Playwright smoke between slices" per memory `feedback_live_smoke_before_next_slice.md`.

---

## Plan-vs-DOM corrections discovered in Tasks 12, 13, 14

The plan body was written before reading the actual code. **Tasks 13 and 14 had four mismatches each.** Per `feedback_plan_grep_verification.md`, **always grep before pasting**.

| Plan body said | Reality | Task | Correction |
|---|---|---|---|
| `m.avg_hold` (FE) | Real metrics has `avg_bars_held` | T12 | FE reads `avg_bars_held` |
| `(m.avg_win_pct * 100).toFixed(2)` | `avg_win_pct` is already in pct units (e.g. 2.5) | T12 | Drop the *100 |
| `qs_metrics.py` may need a `drawdown_series` helper | Plan was right — added it | T12 | Added |
| `/tradelab/strategies-summary` exists | Endpoint did not exist | T13 | Built the BE module + route |
| Plan FACTOR_COLUMNS: dsr, monte_carlo, oos_pf, regime, sample, stability, walk_forward (7) | Real signals: baseline_pf, dsr, mc_max_dd, param_landscape, entry_delay, loso, noise_injection, regime_spread (8) | T13 | Used the 8 real signal names |
| `signal.score?.toFixed?.(2)` (numeric scores) | Real signals carry textual `reason`, not numeric `score` | T13 | Cells display outcome initial (R/M/F) glyph + reason in tooltip |
| `data.strategies` (envelope unwrapped) | The handler returns `{strategies: [...]}` flat (not `{data: ...}`) | T13 | Loader checks both shapes |
| Plan: rename pipeline IDs to `#pipeline-table`, `#pipeline-tbody`, `#selection-toolbar`, `.filter` pills | Existing JS uses `researchPipelineTable`, `researchPipelineBody`, `pipelineCompareBtn`, `pipelineDeleteBtn`, `<select>` filters | T14 | Layered v3 chrome OVER existing markup; preserved JS contract |
| Plan: Step 2 add per-row trash icon | `actionsCell` already renders 🗑 (since Task 8) | T14 | Just updated tooltip "Archive run" → "Delete run" |
| Plan: `<table class="pipeline">` only | Real table also needs `class="table"` (existing tooling); use both | T14 | `class="table pipeline"` |

**The sentinel pattern:** any time the plan body references an identifier you can't find via grep, ASSUME the plan is wrong and grep the actual code for the closest match before continuing. Don't let an "(undefined)" trace from JS pollute the user's smoke run.

---

## Architectural decisions — Tasks 12, 13, 14

### Task 12 endpoint shape — why I added 4 fields to the existing payload, not a new endpoint
The `_qs_metrics_response` handler already existed (Task 5). The plan body said to extend it with `drawdown_series`. I also added `avg_win_pct`, `avg_loss_pct`, `avg_bars_held` because:
- They're already computed and stored in `backtest_result.json` metrics (read by `audit_reader.get_run_metrics`).
- The FE QS sub-grid needs all three; otherwise it would have to round-trip `/metrics` separately.
- Cost is 3 dict lookups in the handler — no new file reads, no new computation.

### Task 13 BE — why a new module instead of extending `audit_reader.py`
The new logic (walk newest-first, dedupe by strategy, read robustness_result.json) is conceptually similar to `audit_reader.baselines_for_all_strategies()` but reads a different sibling JSON (robustness vs backtest) and returns a different shape (list vs dict). I created `strategies_summary.py` rather than adding a 4th similar function to `audit_reader.py` because:
- Single-responsibility: matrix data lives in matrix module.
- Easier to test in isolation (see `test_strategies_summary.py`).
- `audit_reader.py` is already 350+ lines; a new feature warrants a new module.

The trade-off: `_resolve_db` is duplicated as a 2-line helper. Acceptable.

### Task 13 FE FACTOR_COLUMNS — why use real signal names despite plan amendment
The plan body listed 7 invented column ids (`dsr`, `monte_carlo`, `oos_pf`, `regime`, `sample`, `stability`, `walk_forward`). **Only `dsr` matches a real signal name.** If I had used the plan's columns, every cell except DSR would be `dim` (no matching signal in the audit data) — useless matrix.

I used the real names from `src/tradelab/robustness/verdict.py`:
1. `baseline_pf` — edge (PF threshold)
2. `dsr` — deflated sharpe
3. `mc_max_dd` — bootstrap max drawdown
4. `param_landscape` — param sensitivity
5. `entry_delay` — timing slip robustness
6. `loso` — leave-one-symbol-out
7. `noise_injection` — robustness to noisy returns
8. `regime_spread` — bull/bear/chop consistency

Static-HTML test `test_v3_task13_factor_columns_use_real_signal_names` is the executable spec that pins this — and explicitly forbids the plan's invented `monte_carlo` and `walk_forward` ids from creeping back in.

### Task 14 — why I did NOT rename the pipeline IDs as the plan body suggested
The plan body proposed renaming `#researchPipelineTable` → `#pipeline-table`, `#researchPipelineBody` → `#pipeline-tbody`, adding `#selection-toolbar` with new compare/delete buttons, replacing `<select>` filters with `.filter` pill divs.

I did not, because:
1. **Filter selects work today** — replacing them with pill buttons means rewriting filter handlers (4-5 different handlers wired to the existing select.change events).
2. **`renderPipelineRows` reads `researchPipelineBody`** — renaming the ID means updating ~10 querySelector calls that I'd need to grep individually.
3. **`pipelineCompareBtn` / `pipelineDeleteBtn` already exist** — they live next to the table, not in a separate `#selection-toolbar`. The visual placement difference doesn't justify a new container.
4. **The CSS rules at body.research-v3 #research apply to descendants** — they don't care if the container is `.research-filters` inside `.pipeline-toolbar` or just `.pipeline-toolbar`. So wrapping is enough.

**Result:** ~30-line change vs. what would have been a multi-hundred-line rewrite. Same visual outcome, zero JS regressions.

---

## Test invariants pinned in Tasks 12–14 (don't accidentally break)

The static-HTML test file (`tests/web/test_command_center_html.py`) is the regression net for FE structure. These are the new invariants — if a future task changes the named identifier or selector, the test must be updated alongside, not silenced.

### From Task 12 (`test_v3_task12_*`)

- `function loadQsForExpandedTile` exists and fetches `/tradelab/runs/<id>/qs-metrics` with `encodeURIComponent`
- Loader has explicit branch for `runId == null` (renders `<div class="empty">No run data...`)
- `function qsGridHtml` renders 8 cells with labels Total return / Sharpe / Sortino / CAGR / Avg win / Avg loss / Trades / Avg hold
- Stat cells use `.qs-stat`; grid wrapper uses `.qs-grid`
- `function qsChartsHtml`, `function drawdownSvg`, `function monthlyHeatmap`, `function rollingSharpeSvg` all defined
- Charts emit `<svg viewBox=...>` (NOT Chart.js / canvas / d3)
- Heatmap uses `.heatmap-grid` + `.heatmap-cell` divs
- `function expandTile` calls `loadQsForExpandedTile`
- Task 11 placeholder text "QuantStats sub-grid loads in Task 12." is gone
- Tab strip handler in `wireResearchLiveCardsClick` references both `.tab-qs` and `.tab-factors`
- CSS rules for `.qs-grid`, `.qs-stat`, `.qs-charts`, `.qs-chart`, `.heatmap-grid`, `.heatmap-cell` all present

### From Task 13 (`test_v3_task13_*`)

- Matrix DOM hooks: `#matrix-card`, `#matrix-grid`, `#matrix-meta`, `#matrix-alpha-callout`
- `FACTOR_COLUMNS` const present
- FACTOR_COLUMNS uses **real** signal names (`baseline_pf`, `dsr`, `mc_max_dd`, `param_landscape`, `entry_delay`, `loso`, `noise_injection`, `regime_spread`) — explicitly forbids plan's invented `monte_carlo` / `walk_forward`
- `function classifyOutcome` exists, returns `'pass'` / `'fail'` / `'dim'` (uses `toLowerCase`)
- `function renderFactorMatrix` exists, fetches `/tradelab/strategies-summary`
- `renderFactorMatrix(...)` invocation site exists (≥2 occurrences in source — definition + call)
- CSS `.matrix-grid` uses `repeat(8, ...)` template (NOT 7)
- `inconclusive` outcome never adjacent to `return 'pass'` — defends the "weak signals don't get hidden" invariant

### From Task 14 (`test_v3_task14_*`)

- `class="pipeline-card"` wrapper present
- `class="pipeline-toolbar"` wrapper present
- Table `#researchPipelineTable` carries `class="pipeline"` (alongside `.table`)
- `#pipeline-section-header` + `#pipeline-meta` landmarks present
- Trash button title is `"Delete run"`, NOT the v2 `"Archive run"` (memory: 840fb0f flipped DELETE semantics)

---

## Current Research-tab data flow (after Task 14)

```
researchLoadAll()
  ├─ researchLoadPreflight()
  ├─ researchLoadStrategies()
  ├─ researchLoadLiveCards() ──── 6 tiles in #researchLiveCards
  │     │
  │     └─ for each tile:
  │          ├─ fetch /tradelab/runs?strategy=<name>&limit=3
  │          ├─ renderLiveCard → strategyDataCache.set(...)
  │          ├─ ASYNC fetch /tradelab/runs/<id>/metrics → patch KPIs
  │          └─ ASYNC fetch /tradelab/cards/<liveId>/tracking-error → patch TE/K-S
  │     ├─ renderAllDriftSparklines() → /tradelab/strategies/<id>/verdict-history per tile
  │     └─ wireResearchLiveCardsClick() (delegated handler for tile interactions)
  │
  ├─ renderFactorMatrix()  ─────── #matrix-grid (8 columns × N rows)
  │     └─ fetch /tradelab/strategies-summary → render header + rows + alpha callout
  │
  ├─ researchLoadPipeline() ─────── #researchPipelineBody (table.pipeline)
  │     └─ fetch /tradelab/runs?... → renderPipelineRows + per-row metrics fetch
  │
  ├─ loadCanaryStatus()
  ├─ loadPortfolioHealth()
  ├─ loadRegime()
  └─ loadCalibrationSummary()

Tile click (delegated by wireResearchLiveCardsClick):
  1. .deep-dive-btn → no-op (let target=_blank navigate)
  2. .tab-strip-tabs button → swap .tab-qs ↔ .tab-factors visibility (Task 12)
  3. .close-btn → collapseTile
  4. .activate → state machine (disabled/live/activating/enabled paths)
  5. fallthrough .tile → expandTile (calls loadQsForExpandedTile after innerHTML write)
```

---

## How to resume — exact recipe for Task 15

```bash
# 1. Verify state
cd /c/TradingScripts/tradelab
git status                                  # should be clean
git branch --show-current                   # should be feat/research-tab-v3
git log --oneline -3                        # top should be c3aa0bb

cd /c/TradingScripts
git status                                  # clean except untracked daemon logs
git branch --show-current
git log --oneline -3                        # top should be ce9332e7

# 2. Sanity-check the test baseline
cd /c/TradingScripts/tradelab
python -m pytest tests/web/ --tb=no -q -p no:cacheprovider
# Expected: 455 passed (~2 min)

python -m pytest tests/web/test_command_center_html.py --tb=no -q
# Expected: 131 passed (~0.3s)

# 3. RESTART THE DASHBOARD (P0 from this handoff)
#    The user runs this in their own terminal; we cannot start it for them:
#    python C:\TradingScripts\launch_dashboard.py

# 4. Live-data smoke gates (P0):
#    a) Open Playwright MCP → http://127.0.0.1:8877/command_center.html
#    b) Click Research tab
#    c) Verify Task 12: click any tile → expand → QS sub-grid shows real numbers,
#       3 charts render with real waveforms (not "no data" stubs)
#    d) Verify Task 13: matrix shows all real strategies, cells colored,
#       alpha callout reflects real distribution
#    e) Verify Task 14: filters work, action buttons open modals, trash
#       button tooltip = "Delete run"

# 5. Re-read the spec + plan + slice-0 amendments + this handoff
head -30 docs/superpowers/plans/2026-04-30-research-tab-v3.md
cat docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md
cat docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md   # this file

# 6. Read the Task 15 plan section
sed -n '1819,1972p' docs/superpowers/plans/2026-04-30-research-tab-v3.md

# 7. Begin Task 15 with TDD — but EXPECT plan-vs-DOM mismatches.
#    Tasks 12, 13, 14 each had 3-5 mismatches; Task 15 likely has more
#    because it's about delete affordances and the DELETE handler was
#    refactored mid-flight in 840fb0f.
```

---

## Task 15 preview (what's next)

From plan body lines 1819+: **Pipeline delete affordances (4 confirm tiers + cascading)**.

Conceptually:
- **Tier 1 (single run, no card):** lightweight inline confirm → DELETE /tradelab/runs/<id>
- **Tier 2 (single run, has card):** 2-step modal — "this run is the basis for card X; delete both?" → DELETE /tradelab/cards/<id> + DELETE /tradelab/runs/<id>
- **Tier 3 (bulk, no live cards):** confirm modal with run count + verdicts breakdown
- **Tier 4 (bulk, includes live cards):** danger modal with cascade preview ("Will delete N runs and disable M live strategies")

Plan body sketches a `#delete-confirm-modal` with tiered content + cascading delete logic. **Verify before implementing:**
- The existing `pipelineDeleteBtn` already triggers something — what?
- Existing `researchDeleteConfirm` modal at line 1681 — what's its current shape?
- The DELETE /tradelab/runs/<id> handler is hard-delete since 840fb0f — does the cascade need to track which runs power which cards? (audit DB has that mapping; needs a new helper to walk it.)
- `/tradelab/cards` envelope shape (per Gotcha #11 from prior handoff): `{groups: [{base_name, cards: [{card_id, run_id_basis, ...}]}]}` — to find which cards are powered by a given run_id, walk that nested structure.

Will likely need:
- New BE helper: `find_cards_powered_by_runs(run_ids) -> list[card_id]`
- New BE route or extension: bulk DELETE with cascade preview
- New FE modal layout (4 tiers)
- SSE broadcast on cascade so the live cards row + matrix update without manual reload

---

## Gotchas — DO NOT REPEAT (consolidated from prior handoffs + new for T12–T14)

(Repeat of prior gotchas 1–15 — see `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_11.md` for full text.)

### Gotcha #16 (NEW from Task 12): `fetchJSON` returns the body even on 404
The `/tradelab/runs/<id>/qs-metrics` route returns `{"error": "not found"}` with status 404 when the run isn't in the DB. `fetchJSON` doesn't throw — it returns that body as-is. The Task 12 loader checks `if (m && m.error && m.data == null)` explicitly. Pre-existing code in the dashboard does NOT do this check uniformly. If you write a new fetch caller, follow the Task 12 / Task 13 pattern, not the older "trust body.data" pattern.

### Gotcha #17 (NEW from Task 12): `avg_win_pct` and `avg_loss_pct` are PERCENTAGE units, not decimals
Per `src/tradelab/results.py:45-46` and `dashboard/tabs.py:387`, these are stored as e.g. `2.5` for 2.5%. The plan body assumed they were decimals (0-1 range) and would multiply by 100. **Don't multiply.** `cagr` and `total_return` ARE decimals (0.42 = 42%) and DO need *100. Different conventions, same payload — see `qsGridHtml` for the split.

### Gotcha #18 (NEW from Task 13): Real robustness signals carry text reasons, not numeric scores
The `VerdictSignal` type has `name`, `outcome`, `reason` — NO numeric `score` field. The plan body's `sig.score?.toFixed?.(2)` would always print `undefined`. Matrix cells show outcome initial (R/M/F/I) glyph instead, with the full reason in the cell `title` tooltip.

### Gotcha #19 (NEW from Task 13): The `verdict.signals` block in robustness_result.json has 8 NAMES across runs
From `src/tradelab/robustness/verdict.py`:
1. `baseline_pf` (always)
2. `dsr` (if `dsr` arg provided)
3. `mc_max_dd` (if mc result with distributions)
4. `param_landscape` (if landscape result)
5. `entry_delay` (if entry_delay result)
6. `loso` (if loso result)
7. `noise_injection` (if noise result)
8. `wfe` (if walk-forward result) — RARELY populated
9. `hold_out_oos` (gated S4-style strategies only)
10. `regime_spread` (if regime data) — common
11. `regime_spread_hard` (sub-flag on hard regime fragility)

The factor matrix uses 8 of these (skipping `wfe` and `hold_out_oos` because they're conditionally populated). If you need a different 8, update `FACTOR_COLUMNS` AND the static-HTML test that pins them.

### Gotcha #20 (NEW from Task 14): Pipeline JS contract is FRAGILE — don't rename IDs
The pipeline section uses `#researchPipelineTable`, `#researchPipelineBody`, `#pipelineCompareBtn`, `#pipelineDeleteBtn`, `#researchFilterStrategy`, `#researchFilterVerdict`, `#researchFilterSince`, `#researchFilterClear`, `#researchFilterArchived`, `#researchPipelineCount`, `#researchLoadMoreBtn`. Multiple JS handlers grep these by exact ID. The Task 14 restyle deliberately wrapped the existing markup in v3 chrome instead of renaming — preserved every JS contract. Future tasks should do the same unless they're prepared to update the entire pipeline JS layer.

---

## Memory references that apply to this work

(Pulled from `MEMORY.md`. These are operating constraints, not just notes.)

- `feedback_plan_grep_verification.md` — verify every selector/signature/enum in a plan against current code before pasting. **Highly relevant.** Tasks 12, 13, 14 each used this heavily.
- `feedback_dependency_order.md` — sequence work by what unblocks the most downstream items. T13 needed BE first because the FE matrix would render empty without it; T14 was small enough to do FE-first.
- `feedback_act_on_recommendations.md` — when I recommend X with reasoning, don't re-prompt. Used at the T13 plan-vs-real-signal-names decision and the T14 "don't rename IDs" decision.
- `feedback_live_smoke_before_next_slice.md` — always run Playwright smoke between slices; fix bugs mid-smoke not next session. **Partially violated** for T12 + T13 — only synthetic-data smoke ran. See P0 #1 above.
- `feedback_playwright_smoke.md` — UI smoke must use Playwright (navigate + snapshot or evaluate). Used in T12, T13, T14.
- `feedback_demo_first_workflow.md` — strategy/data changes go to demo fixture only. Did not apply to T12-T14 (no strategy data changes; only handler payload + new endpoint).
- `reference_command_center_arch_lock.md` — vanilla HTML+JS+Chart.js only inside command_center.html. **Followed** in T12 (inline SVG, no Chart.js / D3 / build steps), T13 (vanilla DOM construction, no framework).
- `reference_powershell_utf8_bom.md` — PS-written JSON needs `encoding="utf-8-sig"` in Python. Followed in T13 (`strategies_summary._read_robustness` reads with `utf-8-sig`).
- `reference_robustness_result_shape.md` — verdict.signals is a LIST of dicts (not dict), outcomes are lowercase. Followed in T13 BE module.
- `reference_tradelab_db_path_cwd.md` — audit DB path is cwd-relative without explicit override. Followed in T13 BE module (uses `_DEFAULT_DB = Path("data") / "tradelab_history.db"` matching `audit_reader._DEFAULT_DB`).

---

## When in doubt

1. **Trust this handover** for the current state of disk and the new BE routes. The plan body is increasingly stale on T12+ details.
2. **Read the actual code** before pasting plan-body markup or JS. Plan body has been wrong on selectors, IDs, schema, API field names, and signal names. Per `feedback_plan_grep_verification.md`.
3. **Run pytest via Bash, not PowerShell.**
4. **Use Playwright MCP for any UI smoke** — feedback memory `feedback_playwright_smoke.md` requires it; pytest is necessary but not sufficient.
5. **Smoke between slices** per `feedback_live_smoke_before_next_slice.md` — every Task 12-14 commit was preceded by a Playwright check, but only against synthetic data. **Live-BE smoke is owed before merging v3** (P0 #1 above).
6. **RESTART THE DASHBOARD** before doing Task 15 smoke — Tasks 5, 10, 12, 13 all added BE routes that the running process doesn't serve yet. The deploy gap has only widened since the prior handoff.

— end of handover —
