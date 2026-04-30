# Research Tab v3 — Tribunal Design

**Date:** 2026-04-30
**Author:** Amit + Claude (brainstorm session 2026-04-30)
**Status:** Draft — pending user spec review before implementation plan
**Branch (proposed):** `feat/research-tab-v3`

**Successor to:**
- v1 shipped 2026-04-22 (`5de629b`) — current live state of `command_center.html`
- v1.5 shipped 2026-04-23 — preflight chips, compare-N, failure hints, compressed live-card strip
- v2.0 / v2.1 — drafted, not all built; this spec subsumes the unbuilt parts where they match v3 scope, leaves the rest deferred
- 2026-04-25 slide-pane spec — its delete-affordance section is folded directly into §7 here

**Visual reference:** Three browser mockups from this session, persisted in
`.superpowers/brainstorm/216-1777553249/content/`:
`01-live-card-tile.html`, `02-matrix-and-pipeline.html`, `03-assembled-research-tab.html`.

**Source design language:** the trading-desk mockup at
`../../../trading-desk/docs/superpowers/specs/2026-04-28-trading-desk-mockup.html` —
ported verbatim (typography, palette, tile shape, expanded layout) into vanilla HTML/CSS
inside `command_center.html`.

---

## 1. Summary

The Research tab v3 is a **Tribunal** — the surface where every "should this strategy
deploy?" decision is rendered, justified, and audited. v3 strips the current Research
tab from six stacked sections (Engine Canaries, Market Regime, Verdict Calibration, Live
Strategies, Portfolio Health, Pipeline) down to four (Action Bar, Live Cards, Cross-strategy
Factor Matrix, Pipeline), and grafts the trading-desk editorial design (Fraunces / Geist /
JetBrains Mono on warm-dark with copper accent) into `command_center.html` as vanilla
HTML/CSS. Two new capabilities differentiate v3 from anything else in the stack: the
**cross-strategy factor matrix** (correlated-weakness detection) and the **Activate** button
(formal promotion gate from research to live).

Bottom line: zero engine changes, zero schema changes, zero new dependencies,
~200 LoC of new backend, ~600 LoC of new frontend (within `command_center.html`).
The architectural lock (vanilla HTML+JS+Chart.js inside `command_center.html`,
no React/Vite/Tailwind/build step) is preserved.

---

## 2. Motivation

The current Research tab packs six concerns onto one surface, only one of which gates a
deploy decision (the Pipeline). The others are either:
- **Information that doesn't gate decisions** (Market Regime is labeled "INFORMATIONAL ONLY
  — does not control bot" in v2's own UI; Engine Canaries matter only when red).
- **Aggregations one level too coarse** (Portfolio Health shows aggregate metrics; the
  decision-relevant signal is per-factor weakness across strategies, which Portfolio Health
  doesn't expose).
- **Engine self-test** (Verdict Calibration is meta-engine information; collapse to a
  single chip, don't take a section).

The redesign's job is to **make the deploy/don't-deploy decision the headline of the page**
and surface two unique-to-this-stack views that move money:

1. **Cross-strategy factor matrix** — surfaces *correlated portfolio weakness* (e.g., 4 of 7
   strategies fail Walk-Forward consistency = one portfolio-level cause, not five separate
   problems). No QuantStats or per-strategy report in the current stack shows this.
2. **Verdict drift sparklines** — per-strategy 12-dot history of recent verdicts, surfacing
   regime degradation *before* live P&L would.

Combined with formal activation discipline (Q5 contract: ROBUST-only gate, frozen
activation snapshot, never-auto-disable), these three are the alpha levers — not from new
signals, but from refusal discipline plus correlated-weakness visibility plus drift detection.

---

## 3. Decisions log

Each row is a settled question from the brainstorm session.

| # | Decision | Why |
|---|---|---|
| Q3 | Thesis: Research tab = Tribunal. Alpha = refusal discipline + correlated weakness detection + drift detection + research velocity hygiene | Strips noise, foregrounds the only views that move money |
| Q3 | Cut: Engine Integrity Canaries (full strip), Market Regime, Portfolio Health, Verdict Calibration as a section | Demoted to status icon / removed entirely / replaced by Factor Matrix / folded into a chip — none gate per-strategy decisions |
| Q3 | Keep untouched: Refresh Data, New Strategy, Score New Strategy buttons | User constraint; labels and click handlers unchanged, only visual chrome adapts |
| Q3 | Include in scope: S2/S4/S7/S8/S10/S12 alongside Pine cards | Bot strategies are also "under research" — user is iterating + optimizing them |
| Q3 | Factor matrix dims rows for strategies with no run data | Visual representation of "not yet scored" without hiding the row |
| Q4 | Live Cards = same strategy seen through two lenses; Research = analytical, Overview = operational | Don't duplicate; transclude. Cross-tab links instead. |
| Q4 | Class A (Pine cards) vs Class B (S2–S12 bot) treated uniformly in Research; backend resolves the activation target per class on POST | The decision question is identical for both; class only matters operationally. **Implementation plan must nail down the exact write target for Class B** — current Overview "Live Strategies — Tradelab Health" tiles read from a config file/path that needs identification before Activate for Class B can be wired (see §11.0 below). |
| Q4 | Delete: per-row trash + multi-select bulk + typed-confirm above 10 rows + live-card escalation | Friction calibrated to blast radius |
| Q4 | Hard-delete only; audit via append-only `data/deletions.log` JSONL | Soft-delete doubles schema cost for low-frequency need |
| Q4 | Delete cascades atomically (DB row + on-disk folder + log + SSE broadcast) | Single backend transaction; frontend re-derives in place via SSE |
| Q5 | Activate gate: ROBUST-only | Refusal discipline; MARGINAL-with-confirm corrodes the gate |
| Q5 | Activate writes to `cards.json` (Class A) or bot strategy-enable file (Class B) with `executing=false`, `activated_verdict`, `activated_at` | Activation is promotion only; live trading is a separate Overview-tab decision |
| Q5 | Overview card shows both `Activated: <verdict>` and `Latest: <verdict>` with ⚠ on divergence; never auto-disable on FRAGILE re-score | Show the divergence; trader judges; auto-disable would over-react to transient noise |
| Q5 | Iteration = delete card from Overview + re-Activate from Research | Matches Option H "frozen at approval, iteration = delete + recreate" |

---

## 4. Architecture

Two layers of work:

1. **`command_center.html`** — the single-file dashboard. v3 adds a `body.research-v3`
   class scope so the editorial typography and palette apply only to the Research tab,
   leaving Overview / Calendar / Settings / Live Trading visually unchanged. All new
   markup is inside the existing `#tab-research` container. Vanilla HTML, vanilla JS,
   Chart.js already loaded if needed (sparklines and inline charts use hand-crafted SVG,
   not Chart.js, to match the trading-desk mockup; Chart.js stays available for future use).

2. **`launch_dashboard.py`** — the localhost launcher. v3 adds three new routes:
   - `GET /tradelab/runs/<run_id>/tearsheet` — serves the QuantStats HTML tradelab already
     produces at `reports/<strategy>_<ts>/quantstats_tearsheet.html`
   - `GET /tradelab/runs/<run_id>/qs-metrics` — returns the 8-cell QS sub-grid + 3 chart series
     as JSON, computed from the existing equity curve in `<run>/equity_curve.csv`
   - `GET /tradelab/strategies/<id>/verdict-history` — last 12 verdict outcomes per
     strategy from `tradelab_history.db` for the drift sparkline
   - `POST /tradelab/strategies/<id>/activate` — gate-validated card creation
   - `DELETE /tradelab/runs/<run_id>` — atomic on-disk + DB delete with audit log + SSE

A small `tradelab/src/tradelab/web/qs_metrics.py` module owns the QS sub-grid math (Sharpe,
Sortino, CAGR, max DD, monthly returns matrix, rolling Sharpe). Pure functions on
`pd.Series`. No I/O.

Three non-negotiables that fall out of the architectural lock:

- **No new dependencies in `tradelab` or `command_center.html`.** QuantStats already in;
  watchdog already in; everything else is in stdlib.
- **No engine touches.** No changes under `src/tradelab/engines/` or `src/tradelab/canaries/`.
- **No breaking schema changes.** `cards.json` gains two additive fields
  (`activated_verdict`, `activated_at`) — old cards without these fields parse identically;
  Overview just renders the divergence ⚠ as absent. `tradelab_history.db` is read-only
  here except for DELETE, which removes whole rows.

---

## 5. The four sections

### 5.1 Action Bar

A single horizontal strip at the top of `#tab-research`:

```
[Refresh Data] [New Strategy] [Score New Strategy] | Universe Cache Strategies TD-API | Calibration trust 0.84 | (canary icon) ⚠
```

- The three protected buttons keep their existing IDs (`#refresh-data-btn`, `#new-strategy-btn`,
  `#score-new-strategy-btn`) and click handlers; only their CSS class is updated to
  `.ab-btn` / `.ab-btn.primary` for visual consistency with the rest of the bar.
- The four preflight chips (`#preflight-universe`, `#preflight-cache`, `#preflight-strategies`,
  `#preflight-tdapi`) come from v2.0's preflight module — already shipped, just re-skinned.
- **Calibration trust chip** — single number `[0.0–1.0]` derived from the existing verdict-calibration counters
  (the v2 section we're cutting). Replaces the full Verdict Calibration section with one chip.
- **Canary status icon** — single ⚠ icon, visible only when any engine canary is degraded.
  Hidden at all-pass. Click opens a small popover with the canary detail. Replaces the full
  Engine Canaries strip.

### 5.2 Live Cards row

A 4-column responsive grid of compact tiles. One tile per strategy "under research"
(Pine cards + bot strategies S2/S4/S7/S8/S10/S12). Each compact tile shows:

- Strategy name (mono) + meta (`SYMBOL · TIMEFRAME · pine|bot`)
- Verdict pill (top-right): ROBUST / MARGINAL / FRAGILE / INCONCLUSIVE
- 12-dot drift sparkline (last 12 re-scores; oldest left, newest right; dim dots for
  unscored history)
- 4 KPIs: PF / WR / DD / DSR (mono, color-coded)
- TE-bar (5 segments) + K-S dot + trade count
- **Activate button** (4 states — see §6)

Click anywhere on a compact tile (except the Activate button) toggles `tile.expanded`,
which sets `grid-column: 1 / -1` so the expanded view spans the row. The expanded view
contains:

- 7-cell summary: Verdict / PF / WR / Max DD / DSR / TE health / K-S
- Tab strip: **QuantStats** (active by default) / **Factors** / Trades (disabled, "v1.5" pill)
- "View full tearsheet ↗" button → opens `/tradelab/runs/<latest_run_id>/tearsheet` in a new tab
- 8-cell QuantStats sub-grid: Total return / Sharpe / Sortino / CAGR / Avg win / Avg loss / Trades / Avg hold
- Three inline SVG charts: Drawdown 2y / Monthly heatmap (12×3 grid) / Rolling Sharpe 30d
- Factors tab: horizontal bars per signal (DSR / Monte Carlo / OOS PF / Regime / Sample / Stability /
  Walk-Fwd) with pass / marginal / fail coloring and a vertical pass-cutoff line at 0.60

### 5.3 Cross-strategy Factor Matrix

A single grid card. 200px row-label column on the left + 7 equal-width factor columns
on the right. One row per strategy under research. Cells:

- Pip bar (`width: 70%`, `height: 6px`) colored by outcome: green pass / amber marginal /
  red fail / dim no-data
- Score below the pip in mono (e.g., `0.83`, `312`, `—`)
- Hover: tooltip with the signal definition + raw score

Header columns flagged amber (`column-warn` class) when ≥ 50% of scored rows are
marginal-or-fail on that signal — automatic correlated-weakness detection.

Below the matrix: legend (Pass / Marginal / Fail / No data) + alpha-callout in amber
when correlated weakness is present, narrating the read ("Walk-Fwd fails on 4 of 7;
Sample marginal across all — deepen backtest history before re-scoring").

Data source: each strategy's `<latest_run>/robustness_result.json`, specifically the
`signals` list (per `reference_robustness_result_shape.md`). No new computation; just
grid layout + threshold check.

### 5.4 Research Pipeline

The existing v2 pipeline table, restyled to match the editorial typography:

- Filter bar: Strategy / Verdict / Since / Reset / Show only ROBUST checkbox
- Selection toolbar (visible when ≥ 1 row selected): "N runs selected" + Compare Selected (N) + **Delete N runs ▸**
- Table columns: ☐ / Status / Strategy / Verdict / Hold-out / Cover / PF / WR / DD / Trd / DSR / [actions]
- Row states: queued / running / done / failed (existing v2 `JobStatus` enum)
- Per-row actions: trash icon (delete) for done/failed; ⊘ (cancel) for queued/running; ↻ (re-run) for failed

---

## 6. Activation contract

The complete behavioral contract for the Activate button.

### 6.1 Button states

| State | Visual | Trigger | Click behavior |
|---|---|---|---|
| Enabled | Copper-soft bg, copper text, copper border | latest verdict ∈ {ROBUST} AND no card exists for this strategy | POST `/tradelab/strategies/<id>/activate`; transitions to **Activating** |
| Disabled — gate | Transparent, dim text, line border, hover tooltip with reason | latest verdict ∉ {ROBUST} OR no runs yet | No-op; tooltip explains: "Latest verdict is FRAGILE — re-score required before activation" |
| Activating | Spinner + Copper-soft bg | POST in flight | Resolves to **Already live** on 200, back to **Enabled** with toast on error |
| Already live | Green-soft bg, green text, green border, "● Already live ↗" | card exists for this strategy in `cards.json` | Jumps to Overview tab + scrolls to + briefly highlights the matching tile |

### 6.2 Backend route

`POST /tradelab/strategies/<id>/activate`:

1. Validate: latest run for `<id>` exists and verdict is ROBUST. Reject 422 if not.
2. Validate: no card with `id == <id>` already exists in `cards.json`. Reject 409 if it does.
3. Compute payload:
   ```json
   {
     "id": "<id>",
     "executing": false,
     "activated_verdict": "ROBUST",
     "activated_at": "2026-04-30T14:32:00",
     "snapshot": { /* relevant fields from latest robustness_result.json */ }
   }
   ```
4. Atomic write: append to `cards.json` (or call existing card-create helper if one exists).
5. Append JSONL to `data/activations.log`.
6. Broadcast SSE `card_activated` event with the new card.
7. Return 200 + payload. Receiver on `:8878` hot-reloads `cards.json` via watchdog;
   Overview tab sees the new card on next refresh / SSE tick.

### 6.3 Cross-tab linkage

- Compact tile in Research, when activated: replace Activate button with `● Already live ↗`
  link that, on click, switches to Overview and scrolls the matching card into view with a
  brief highlight pulse.
- Overview tab card: gain a small `↗ Research` link in the top row that, on click, switches
  to Research and scrolls + highlights the matching tile.
- Both jumps use a shared `scrollToStrategy(id)` helper that reads `data-strategy-id` attributes.

### 6.4 Drift after activation

The activation snapshot (`activated_verdict`) is **immutable**. Re-scoring updates the
strategy's *latest* run data; the card's recorded `activated_verdict` does not rewrite.

On the Overview card:
- Display both: `Activated: ROBUST 2026-04-30 · Latest: <latest verdict>`
- ⚠ icon on the card when `latest_verdict != activated_verdict`
- Live trading is **never auto-disabled** by a re-score. Trader decides via Overview's
  Enable toggle.

---

## 7. Delete contract

### 7.1 Affordances

- **Per-row trash icon** in the action cell of every done/failed row. Click → small
  inline confirm popup ("Delete this run? [Delete] [Cancel]") at the action cell.
- **Multi-select via row checkboxes**. When ≥ 1 selected, the selection toolbar reveals
  "Delete N runs ▸" alongside the existing v2 "Compare Selected (N)" button.
- **Strategy-level sweep**: filter to one strategy, select all rows, click Delete N runs.
  No separate "remove strategy" action.

### 7.2 Confirmation tiers

| Tier | When | UI |
|---|---|---|
| Inline | 1 row | Small popup at the trash icon. 1 click confirm. |
| Modal | 2–10 rows | Modal listing all selected rows + timestamps. 1 click confirm. |
| Modal + typed | > 10 rows | Modal + input requiring user to type `DELETE` literally. Delete button stays disabled until exact match. |
| Live-card escalation | Any tier where the deletion would strand a live Card with no robustness history | Modal with three actions: `Disable card + Delete` (recommended), `Delete anyway` (red), `Cancel` |

### 7.3 Backend route

`DELETE /tradelab/runs/<run_id>`, atomic:

1. Look up the run in `tradelab_history.db`. If no row, 404.
2. Resolve the on-disk folder path: `reports/<strategy>_<ts>/`.
3. Begin transaction:
   - DELETE the DB row.
   - `shutil.rmtree(folder)`.
   - Append JSONL to `data/deletions.log`:
     `{"ts":"...", "run_id":"...", "strategy":"...", "deleted_by":"ui", "paths_removed":[...]}`
4. Commit. On any step failure, abort and 500.
5. Broadcast SSE `run_deleted` event with `{run_id, strategy}`.

### 7.4 Cascading frontend updates

On `run_deleted` SSE event:

- Pipeline table: remove the row by `data-run-id`.
- Factor matrix: re-derive the affected strategy's row from the next-most-recent run for that
  strategy. If no runs remain, dim the row (cells render as dashes).
- Live Cards tile: re-derive verdict pill, drift sparkline, 4 KPIs, TE/K-S health row from
  the next-most-recent run. If no runs remain, render an empty-state tile ("Not yet scored",
  no expand).
- Drift sparkline: drop the deleted run's dot; remaining dots shift right.
- "View full tearsheet ↗" button on the expanded tile: re-points to the new latest run's
  tearsheet path. The deleted run's tearsheet HTML is gone with `rmtree`.
- Calibration trust chip: recomputes lazily on next page load; no immediate refresh.

---

## 8. Backend additions — file inventory

New files:
- `tradelab/src/tradelab/web/qs_metrics.py` — pure functions: `sharpe`, `sortino`, `cagr`,
  `max_drawdown`, `monthly_returns_matrix`, `rolling_sharpe`. Operate on `pd.Series` of
  daily returns. ~80 LoC.
- `tradelab/src/tradelab/web/activation.py` — `validate_activation_gate`,
  `create_card_for_strategy`, `route_to_class_b_bot_config`. ~60 LoC.
- `tradelab/src/tradelab/web/run_deletion.py` — `delete_run_atomic`,
  `append_deletion_log`. ~50 LoC.
- `tradelab/src/tradelab/web/verdict_history.py` — `get_recent_verdicts(strategy_id, n=12)`
  reads from `tradelab_history.db`. ~30 LoC.

Modified files:
- `tradelab/src/tradelab/web/handlers.py` — five new route branches (tearsheet, qs-metrics,
  verdict-history, activate, delete). ~50 LoC additional.
- `C:\TradingScripts\launch_dashboard.py` — pass-through routes for tearsheet HTML
  serving (mirrors existing `/tradelab/compare-report` shape). ~20 LoC.
- `C:\TradingScripts\command_center.html` — new `body.research-v3` CSS scope; new
  Research-tab markup (action bar, Live Cards row with click-expand, factor matrix,
  restyled pipeline). ~600 LoC additional. The current Research tab markup is replaced
  in place; existing element IDs preserved where possible (`#refresh-data-btn`,
  `#new-strategy-btn`, `#score-new-strategy-btn`, `#preflight-*`).

Total new code: ~890 LoC. No new dependencies. No engine touches.

---

## 9. Tests

Backend (pytest, in `tradelab/tests/web/`):
- `test_qs_metrics.py` — fixture equity curves; assert each metric matches QuantStats output
  to 1e-6 (regression test, not redundant with QuantStats itself).
- `test_activation.py` — gate validation: ROBUST → 200, MARGINAL → 422, no-runs → 422,
  duplicate card → 409. `cards.json` write integrity. Activations log appends correctly.
- `test_run_deletion.py` — atomic delete (DB row + folder + log). Failure cases:
  missing folder, missing DB row, partial failure rollback. Deletions log JSONL valid.
- `test_verdict_history.py` — fixture DB; recent N rows in correct order.
- `test_handlers.py` (extend) — five new route branches with happy-path + 404/409/422 cases.

Frontend (existing static-HTML pytest pattern, in `tradelab/tests/web/test_command_center_html.py`):
- Element-presence assertions for the four new sections (action-bar, tile-grid,
  matrix-card, pipeline-card).
- XSS regression: server-supplied strings in tile names + verdict labels go through
  `textContent` / `escapeHtml`, never raw template interpolation. (Lessons from v2 audit B3.)
- Static parse: CSS variables defined; Google Fonts `<link>` present; no React/Tailwind/Vite imports.

UI smoke (manual, per memory note "Use playwright MCP for all smoke gates"):
- Action bar renders all 3 protected buttons + 4 chips + calibration chip + canary icon
  conditionally.
- Click each Activate state and verify state machine transitions match §6.1.
- Click a tile → expand inline; QuantStats tab renders 8 cells + 3 charts; "View full
  tearsheet" opens the QS HTML.
- Multi-select 3 rows → "Delete N runs ▸" shows; click → modal lists 3 rows.
- Multi-select 12 rows → typed-confirm modal; type wrong word → button stays disabled;
  type `DELETE` exactly → button enables.
- Delete a run that affects an activated card → escalation modal renders correctly.

---

## 10. Out of scope (deliberately deferred)

Considered during the brainstorm and **explicitly cut from v3**:

- **Soft-delete / restore-from-trash.** Hard-delete + JSONL audit only. Add only if
  accidental deletes become an actual problem.
- **Auto-disable on FRAGILE re-score.** Never. Trader decides via Overview Enable toggle.
- **"Run again with params" quick-action on pipeline rows.** Stays a v2 feature carry; not
  re-designed here.
- **Persistent Compare sets.** Per-session selections only.
- **Engine-side `gate_failures` field.** Factor matrix derives client-side from the existing
  `signals[]` list in `robustness_result.json`.
- **Backend benchmark override pool.** SPY only; future configurability is post-v3.
- **Auth / RBAC.** localhost-only dashboard; no change.
- **Chart.js for Live Card or Matrix charts.** All inline SVG to match the trading-desk mockup
  fidelity 1:1. Chart.js stays available for future use.
- **Class-A vs Class-B badge on the tile.** No `pine` / `bot` badge; uniform UI. Add only if
  a class difference becomes a decision input.
- **Sticky action bar on scroll.** Out of scope; revisit if vertical scroll fatigue surfaces.
- **Redesign of Overview tab "Live Strategies — Tradelab Health" S2–S12 section.** Flagged
  as a follow-up in §11 but not done here. v3 only restructures Research; Overview
  stays operationally unchanged.

---

## 11. Follow-ups (post-v3)

These are *not* part of this spec but became visible during the brainstorm. Each merits its
own spec when it's the right time:

0. **Class B activation target identification** — first task of the implementation plan.
   Locate the file/path the bot reads to determine which of S2/S4/S7/S8/S10/S12 are enabled.
   Once identified, document its schema and add it to the activation contract in §6.2 step 4.
   Until this is nailed down, Class B Activate buttons in the v3 mockup cannot be wired
   end-to-end — they should render Disabled with a "wiring pending" tooltip in the
   first slice rather than be left non-functional.
1. **Overview tab simplification** — fold "Live Strategies — Tradelab Health" into "LIVE CARDS"
   so there's one operational live-card surface, not two. Once v3 owns the analytical lens,
   Overview can flatten its dual-section layout.
2. **Cross-tab scroll-to-and-highlight helper** generalized across other strategy mentions in
   the dashboard.
3. **Velocity strip** above the pipeline — runs/day bar + yield rate (% reaching ROBUST) for
   the last 30 days. Mentioned in the brainstorm; cut from v3 to keep scope tight.
4. **Equity curve in expanded tile** as a fourth chart alongside drawdown / monthly / rolling Sharpe.
5. **Live trading verdict-divergence ⚠ icon on Overview cards** — surfaces drift even when
   the trader hasn't visited Research.

---

## 12. References

- Brainstorm transcript: this file's session, 2026-04-30.
- Visual mockups: `.superpowers/brainstorm/216-1777553249/content/{01..03}*.html`.
- Trading-desk mockup (source design language):
  `../../../trading-desk/docs/superpowers/specs/2026-04-28-trading-desk-mockup.html`.
- Trading-desk design (separate-project version):
  `../../../trading-desk/docs/superpowers/specs/2026-04-28-trading-desk-design.md`.
- v2.0 summary: `../RESEARCH_TAB_V2_SUMMARY.md`.
- v2 audit (silent-failure findings): `../RESEARCH_TAB_V2_AUDIT.md`.
- 2026-04-25 slide-pane spec (delete affordances precursor):
  `2026-04-25-research-tab-slide-pane-design.md`.
- Memory notes consulted:
  - `command_center.html §6 architectural lock` — vanilla HTML+JS+Chart.js inside command_center.html
  - `Receiver hot-reloads cards.json via watchdog` — receiver on :8878 picks up card changes
  - `robustness_result.json shape` — verdict outcomes lowercase, signals is a list
  - `Use playwright MCP for all smoke gates` — UI smoke verification approach
  - `Apply Trading Desk mods to demo fixture first` — strategy data changes go to demo fixtures
  - `Option H workflow design` — Pine→tradelab→Alpaca, immutable cards, iteration = delete + recreate

---

## 13. How to resume implementation

When picking this up to build:

1. Read this spec end-to-end.
2. Open the three mockup HTML files in a browser side-by-side with the current
   `command_center.html` Research tab — that's the visual diff.
3. Invoke `superpowers:writing-plans` to break this spec into an ordered, slice-able
   implementation plan. The plan should slice along: (a) backend routes one at a time;
   (b) action bar restyle; (c) Live Cards row markup + compact tile + drift sparkline;
   (d) expanded tile + QS sub-grid + 3 charts + tearsheet button; (e) factor matrix; (f)
   pipeline restyle + selection toolbar + delete affordances; (g) cross-tab linkage;
   (h) tests at each slice boundary.
4. Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
   actually build, with smoke gates between slices per the memory note.
5. **Protected paths (DO NOT TOUCH):** `src/tradelab/engines/*`, `src/tradelab/canaries/*`,
   the Refresh Data / New Strategy / Score New Strategy click handlers in `command_center.html`,
   the 4 pre-v1 Command Center tabs (Overview / Calendar P&L / Settings / Live Trading),
   the 10 AlgoTrade safety mechanisms.
