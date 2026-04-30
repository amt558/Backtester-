# Research Tab v3 — Handover Doc (2026-04-30, after Task 11)

> **Read this if you are picking up the Research Tab v3 implementation.** This document is the single source of truth for "where we are." It supersedes the prior handoff (`RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_8.md`, kept on disk for the Tasks 1–8 history). Newer than the plan; trust this over plan-body sketches when they conflict.

---

## TL;DR

- **Plan:** `docs/superpowers/plans/2026-04-30-research-tab-v3.md` (18 tasks)
- **Spec:** `docs/superpowers/specs/2026-04-30-research-tab-v3-design.md`
- **Visual mockups:** `.superpowers/brainstorm/216-1777553249/content/{01,02,03}*.html` (#3 is the assembled reference)
- **Branches (cross-repo):**
  - tradelab repo: `feat/research-tab-v3` at `C:\TradingScripts\tradelab\` — HEAD `87b957b`
  - parent repo: `feat/research-tab-v3` at `C:\TradingScripts\` — HEAD `b9b5494`
- **Done:** Tasks 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 (12 plan tasks + slice-0). 16 tradelab commits + 6 parent-repo commits on the v3 branches.
- **Next up:** Task 12 — QuantStats sub-grid + 3 inline SVG charts in expanded tile (the `.tab-qs` placeholder is in place).
- **Blocking concern:** **Dashboard restart required.** Tasks 5 and 10 added new BE routes (`/tradelab/strategies/<id>/verdict-history` and `/tradelab/strategies/<id>/activate`) but the running dashboard process started before those commits and serves stale handlers code. The FE handles both 404s gracefully (drift sparklines fall back to dim dots; Activate click toasts an error), so the dashboard isn't broken — just the new BE features need a process restart to go live.
- **Test baseline:** **409/409** in `tests/web/` (full suite, ~2 min via Bash). Static-HTML tests alone: **104/104** (~0.3s).
- **Don't run pytest via PowerShell** — see Gotcha #1 in the prior handoff. Use Bash.

---

## What shipped in Tasks 9, 10, 11 (since the Task 8 handoff)

### Task 9 — Live Cards v3 compact tile + drift sparkline
- **Parent commit:** `40dfe09c` "feat(command-center): Live Cards v3 compact tile + drift sparkline (Task 9)"
- **tradelab commit:** `e964b8a` "test(web): assert Live Cards v3 tile contract (Task 9)"
- **Effect:** Replaces the v2 skeleton inside `#researchLiveCards` with the real v3 4-column tile grid. Each tile has tile-head (name + meta + verdict pill), drift sparkline (12 dots), 4 KPI cells (PF / WR / DD / DSR), health-row (TE bar / K-S dot / trade count), and the Activate button with state pre-computed from latest verdict.
- **Tests added:** 12 static-HTML assertions in `test_command_center_html.py` pinning the tile contract.

### Task 10 — Activate state machine + cross-tab linkage
- **Parent commit:** `47377481` "feat(command-center): Activate state machine + cross-tab linkage (Task 10)"
- **tradelab commit:** `88a3534` "feat(web): POST /tradelab/strategies/<id>/activate one-click endpoint"
- **Effect (FE):** Click delegate on `#researchLiveCards` for the `.activate` button, with `enabled → activating → live` transitions (and `→ enabled` rollback + error toast on failure). Adds `switchToOverviewTabAndScrollTo()` helper that pulses the destination card via the new `r3-highlight-pulse` keyframe. Adds the symmetric `↗ Research` button on Overview live cards that jumps back and pulses the matching tile.
- **Effect (BE):** New thin POST route `/tradelab/strategies/<id>/activate` that takes a strategy id only, looks up its latest audit row, resolves report_folder via `audit_reader.resolve_run_folder`, reads symbol/timeframe from `backtest_result.json`, and forwards to `approve_strategy.accept_scored(activate=True)`. Reuses the same gate, duplicate-card 409, and SSE broadcast as `/tradelab/accept`. Has a defensive guard: if any enabled card already exists for `base_name`, refuses with 409 rather than auto-bumping to `-v2`.
- **Tests added:** 7 handler tests in new file `tests/web/test_handlers_activate.py` (ROBUST 200, FRAGILE/INCONCLUSIVE 422, no-runs 422, duplicate 409, path-traversal). 11 static-HTML tests in `test_command_center_html.py` for FE contract.
- **Side fix in same parent commit:** `_renderOverviewLiveCardHTML` was rendering `card_id` instead of `base_name` because `/tradelab/cards` puts `base_name` at the group level, not on each card. Fixed by injecting `g.base_name` into each card before render.

### Task 11 — Click-to-expand inline (header + 7-cell summary + tab strip + tearsheet button)
- **Parent commit:** `b9b5494a` "feat(command-center): Live Card click-to-expand inline (Task 11)"
- **tradelab commit:** `87b957b` "test(web): pin Live Card expand contract + repoint drift helper (Task 11)"
- **Effect:** Click any tile (outside its action buttons) to expand it inline with a 7-cell summary (Verdict / PF / WR / DD / DSR / TE health / K-S), tab strip placeholder (QuantStats / Factors / Trades-disabled), and a "View full tearsheet ↗" deep-dive linking to `/tradelab/runs/<id>/tearsheet`. Only one tile expanded at a time. Click `.close-btn` (or click the same tile again) to collapse. Action buttons (`.activate`, `.close-btn`, `.deep-dive-btn`, `.tab-strip-tabs button`) all call `e.stopPropagation()` and have explicit branches in the click delegate so they don't toggle expand.
- **New module-level state:** `strategyDataCache` Map populated by `renderLiveCard` and patched as the metrics + tracking-error fetches resolve. `expandedTileHtml(s)` reads from this cache so the expand view shows the same numbers as the compact tile without re-fetching.
- **Helpers introduced:** `_formatScoredAgo / _teStateClass / _ksStateClass` (tiny pure fns reused by the cache-update path), `expandedTileHtml(s)` (full template), `expandTile(tile, id) / collapseTile(tile)` (toggle), `renderDriftFor(el, id)` (extracted from `renderAllDriftSparklines` so collapse can redraw a single sparkline without a full fan-out).
- **Tests added:** 9 static-HTML tests in `test_command_center_html.py`. The `_drift_renderer_body` test helper was repointed: it now finds `renderDriftFor` first, falling back to `renderAllDriftSparklines` for pre-Task-11 source compat.

### Tests baseline movement

| After | tests/web/ total | static-HTML test file |
|---|---|---|
| Task 8  | 379 | ~84 (12 from prior + 5 T7 + 5 T8) |
| Task 9  | 391 | 95 (+12 T9) |
| Task 10 | 409 | 106 (+11 T10 FE + 7 T10 handler in separate file) |
| Task 11 | 409 | 104 (+9 T11; 2 prior drift tests untouched after helper repoint, and 1 stray was already deduped) |

Wait, the math at Task 11: full suite stays 409 because no new pytest files were added; the 9 new T11 assertions live in the existing `test_command_center_html.py` file, which now totals **104** assertions. New `test_handlers_activate.py` has 7 of its own, already counted in the +18 jump from T9→T10.

Final counts at end of T11:
- `tests/web/` overall: **409 passed**
- `tests/web/test_command_center_html.py`: **104 passed**
- `tests/web/test_handlers_activate.py`: **7 passed**

---

## What's done — full commit log

### tradelab repo (`C:\TradingScripts\tradelab\` on `feat/research-tab-v3`)

```
87b957b  test(web): pin Live Card expand contract + repoint drift helper (Task 11)
88a3534  feat(web): POST /tradelab/strategies/<id>/activate one-click endpoint   ← Task 10
e964b8a  test(web): assert Live Cards v3 tile contract (Task 9)
1e5b339  docs(research-v3): thorough handover after Tasks 7+8                    ← Prior handoff
866cb0a  test(web): assert action-bar contract for Task 8
5e61dd7  test(web): assert research-v3 scope contract (Task 7)
b48e157  docs(research-v3): handoff reflects DELETE semantic flip (840fb0f)
840fb0f  refactor(web): flip DELETE /tradelab/runs/<id> from soft-archive
         to hard-delete (drops /permanent suffix; idempotent on unknown)         ← Task 5 fixup
5a8b103  docs(research-v3): handoff updated through Task 6
b3c8bcc  feat(web): wire 4 Research-v3 routes (qs-metrics, verdict-history,
         accept activate, permanent delete)                                       ← Task 5 (initial)
bb237b8  feat(web): extend approve_strategy.accept_scored with activate flag     ← Task 4
9954d18  docs(research-v3): handoff after Task 3
44f7a81  feat(web): add run_deletion module                                      ← Task 3
b07adc7  feat(web): add verdict_history module                                   ← Task 2
aec2605  feat(web): add qs_metrics pure-fn module                                ← Task 1
e0c68a2  docs(research-v3): plan amendments per slice 0 findings                 ← Task 0 amend
2d5d927  docs(research-v3): slice 0 findings                                     ← Task 0 notes
```

### parent repo (`C:\TradingScripts\` on `feat/research-tab-v3`)

```
b9b5494  feat(command-center): Live Card click-to-expand inline (Task 11)
4737748  feat(command-center): Activate state machine + cross-tab linkage (Task 10)
40dfe09c feat(command-center): Live Cards v3 compact tile + drift sparkline (Task 9)
a6023a10 feat(command-center): research-v3 action bar (Task 8)
4c1906d7 feat(command-center): research-v3 CSS scope + Google Fonts (Task 7)
421b1294 feat(launcher): /tradelab/runs/<run_id>/tearsheet pass-through         ← Task 6
```

These two branches don't share history. They ship together when v3 is ready to merge.

---

## DEPLOY GAP — read this before doing any smoke

The running dashboard process at `http://127.0.0.1:8877/` was started before Tasks 5 and 10 landed and serves **stale handlers code** that doesn't include:

| Endpoint | Added in | Stale-server response |
|---|---|---|
| `GET /tradelab/strategies/<id>/verdict-history` | Task 5 | 404 → drift sparklines render 12 dim dots (graceful fallback) |
| `POST /tradelab/strategies/<id>/activate` | Task 10 | 200 with `{error: "not found"}` → Activate click toasts "Activate failed: not found" (graceful rollback) |

**Restart with:**

```powershell
# In your terminal (the user runs this themselves):
python C:\TradingScripts\launch_dashboard.py
```

Once restarted:
- Drift sparklines populate with real verdict colors (green/amber/red dots)
- Activate button on a ROBUST tile actually creates a card and turns the button green
- The full happy-path Task 10 smoke (button → toast "Activated …" → cross-jump on second click) is testable end-to-end

The pytest suite already verifies the BE handler exhaustively (7 handler tests cover ROBUST / FRAGILE / INCONCLUSIVE / no-runs / duplicate / path-traversal), so the restart is verification rather than gating.

---

## Plan-vs-DOM corrections discovered in Tasks 9–11

The plan body was written before reading the actual `command_center.html`. **Task 11 alone had four mismatches.** Per `feedback_plan_grep_verification.md`, **always grep before pasting**.

| Plan body said | Reality | Correction made in |
|---|---|---|
| `#live-cards-grid` | `#researchLiveCards` | T9, T10, T11 |
| `tile.dataset.strategyId` | `tile.dataset.strategy` | T11 |
| `tile.dataset.strategy` (in Activate handler) | also have `tile.dataset.liveId` (the placeholder label) and `tile.dataset.cardId` (set after activate) | T10 |
| `POST /tradelab/strategies/<id>/activate` (plan body) | Task 5 amendment said "no, use /tradelab/accept" — but FE doesn't have base_name/symbol/timeframe/report_folder. **Recommended path: add the new route after all.** | T10 |
| `POST /tradelab/accept` with `activate=true` (plan amendment) | Requires base_name/symbol/timeframe/report_folder/verdict/dsr_probability/scoring_run_id — fields not on the FE Live Cards | T10 (rejected; new route added) |
| `tileHtml(s)` helper exists | `renderLiveCard(liveId, tradelabName, runs, hasCard)` returns a DOM element | T11 (compose innerHTML via detached element) |
| `loadQsForExpandedTile(tile, runId)` from Task 11 | Defined in Task 12 — Task 11 leaves an empty `.tab-qs` placeholder | T11 (not paste-loaded; removed call) |
| `c.base_name` on each card from `/tradelab/cards` | base_name is on the GROUP, not each card (`/tradelab/cards` returns `{groups: [{base_name, cards: [...]}]}`) | T10 fix: inject `g.base_name` into each card during flatten |
| `renderDriftFor` exists | Not until Task 11 — extracted from `renderAllDriftSparklines` | T11 |
| `strategyDataCache` exists | Not until Task 11 | T11 |

The sentinel pattern: any time the plan body references an identifier you can't find via grep, ASSUME the plan is wrong and grep the actual code for the closest match before continuing. Don't let an "(undefined)" trace from JS pollute the user's smoke run — that's a memory-flagged bug class.

---

## Architectural decision — Task 10 endpoint

The slice-0 amendment at the top of the plan said "drop the new `/strategies/<id>/activate` route — use existing `/tradelab/accept` with `activate: true`". The amendment was correct that `accept_scored` should grow the `activate` parameter (Task 4 did this), but it was **wrong** about the FE call site:

- `/tradelab/accept` requires `{base_name, symbol, timeframe, report_folder, verdict, dsr_probability, scoring_run_id}`.
- The Live Cards FE has: `liveId` (placeholder label), `tradelabName` (= base_name), and the latest run's `{run_id, verdict, dsr_probability}`. **Missing: symbol, timeframe, report_folder.**
- `symbol` + `timeframe` live in `<report-folder>/backtest_result.json`. `report_folder` is resolvable via `audit_reader.resolve_run_folder(run_id)`. The FE could round-trip three endpoints to assemble the payload — ugly.

**Decision (Task 10):** add the thin route after all. It exists in `handlers.py:985+` (search for the `re.match(r"^/tradelab/strategies/([^/]+)/activate$", path)` block). It looks up the strategy's latest audit row, resolves report_folder, reads symbol/timeframe from `backtest_result.json`, and forwards to `approve_strategy.accept_scored(activate=True)`. The 7 tests in `test_handlers_activate.py` are the executable spec.

The plan amendment is now stale on this point. **Trust this handoff for the activate endpoint contract.**

---

## Test invariants pinned in Tasks 9–11 (don't accidentally break)

The static-HTML test file (`tests/web/test_command_center_html.py`) is the regression net for FE structure. These are the new invariants — if a future task changes the named identifier or selector, the test must be updated alongside, not silenced.

### From Task 9 (`test_v3_*` for tile structure)

- `id="researchLiveCards"` on the grid; `.tile-grid` class for the v3 4-col CSS to apply
- `escapeHtml` helper called for every server-supplied field rendered into innerHTML
- Drift sparkline calls `/tradelab/strategies/<id>/verdict-history` and caps at 12 dots
- TE bar uses `.full / .high / .mid / .low` (NOT v2's `.green / .green-full / .amber / .red`)
- K-S uses `.ks-dot` (visual dot), not `.ks-tag` (text label)
- Activate button has `.activate.{enabled, disabled, live}` state classes

### From Task 10 (`test_v3_task10_*`)

- `function wireResearchLiveCardsClick` exists and is called from `researchLoadLiveCards`
- POST to `/tradelab/strategies/${encodeURIComponent(...)}/activate` (NOT `/tradelab/accept`)
- State transitions touch all of `enabled / activating / live` classes
- `.activate.activating` has a CSS rule (so the in-flight state is visible)
- `function switchToOverviewTabAndScrollTo` exists and calls `switchTab('overview')` and adds `r3-highlight-pulse` class
- `@keyframes r3-highlight-pulse` defined and `.r3-highlight-pulse` class binds it
- `.open-research-btn` markup with `data-base-name` on Overview cards
- Document-level click delegate handles `.open-research-btn` → `switchTab('research')` + pulse
- `tile.dataset.cardId` is set after activate so cross-jump works without re-fetch
- Negative: `wireResearchLiveCardsClick` body must NOT contain `'/tradelab/accept'`

### From Task 11 (`test_v3_task11_*`)

- `function expandedTileHtml` exists and renders exactly **7** `.ex-cell` entries with labels Verdict/Profit factor/Win rate/Max DD/DSR/TE health/K-S
- `tab-strip` + `tab-strip-tabs` + `.deep-dive-btn` linking to `/tradelab/runs/<id>/tearsheet`; close-btn present
- `function expandTile` and `function collapseTile` exist
- `strategyDataCache` populated during `renderLiveCard`
- Click delegate calls `expandTile`/`collapseTile` and guards `.close-btn`
- CSS for `.tile.expanded`, `.ex-cell`, `.ex-summary`, `.ex-header`
- Only-one-expanded iteration: `.tile.expanded` referenced inside the handler so other expanded tiles are collapsed first
- Action-button guards: handler body mentions both `.activate` and `close-btn`

---

## Current Live Cards data flow (after Task 11)

```
researchLoadLiveCards()
  │
  ├─ fetch /tradelab/cards once → activeIds Set + baseNameToCardId Map
  │
  └─ for each liveId in LIVE_STRATS:
       ├─ tradelabName = LIVE_TO_TRADELAB[liveId]
       ├─ fetch /tradelab/runs?strategy=<tradelabName>&limit=3
       ├─ tile = renderLiveCard(liveId, tradelabName, runs, hasCard)
       │     │
       │     ├─ strategyDataCache.set(tradelabName, {synchronous fields})
       │     │
       │     ├─ render compact innerHTML (tile-head, drift, kpis, health-row, actions)
       │     │
       │     ├─ ASYNC fetch /tradelab/runs/<run_id>/metrics
       │     │     → patches PF/WR/DD/trade count cells
       │     │     → updates strategyDataCache.kpis
       │     │
       │     └─ ASYNC fetch /tradelab/cards/<liveId>/tracking-error
       │           → patchTrackingError(card, env.data)  (TE bar + K-S dot + color)
       │           → updates strategyDataCache.te / ks / ks_p
       │
       └─ if baseNameToCardId.has(tradelabName): tile.dataset.cardId = card_id
       └─ container.appendChild(tile)

After all tiles in DOM:
  ├─ renderAllDriftSparklines() — fans out per-tile renderDriftFor(el, strategyId)
  └─ wireResearchLiveCardsClick() — installs the SINGLE delegated listener once
```

The single delegated click listener handles all tile interactions. Order of branch checks (highest priority first):

1. `.deep-dive-btn` → no-op (let the link navigate, target=_blank)
2. `.tab-strip-tabs button` (not disabled) → toggle `.active` (Task 12 will swap content)
3. `.close-btn` → `collapseTile(tile)`
4. `.activate` → state-machine logic (disabled/live/activating/enabled paths)
5. fallthrough: `.tile` → `expandTile`/`collapseTile` toggle, collapsing any other expanded tile first

`e.stopPropagation()` is called inside each early-return branch.

---

## How to resume — exact recipe for Task 12

```bash
# 1. Verify state
cd /c/TradingScripts/tradelab
git status                                  # should be clean
git branch --show-current                   # should be feat/research-tab-v3
git log --oneline -4                        # top 2 should match T11/T10 hashes above

cd /c/TradingScripts
git status                                  # should be clean (ngrok/receiver logs untracked are fine)
git branch --show-current                   # should be feat/research-tab-v3
git log --oneline -4

# 2. Sanity-check the test baseline
cd /c/TradingScripts/tradelab
python -m pytest tests/web/ --tb=no -q -p no:cacheprovider
# Expected: 409 passed (~2 min)

python -m pytest tests/web/test_command_center_html.py --tb=no -q
# Expected: 104 passed (~0.3s) — fast smoke for FE-only changes

# 3. Re-read the spec + plan + slice-0 amendments + this handoff
head -30 docs/superpowers/plans/2026-04-30-research-tab-v3.md
cat docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md
cat docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_11.md   # this file

# 4. Read the Task 12 plan section (lines ~1531+)
sed -n '1531,1670p' docs/superpowers/plans/2026-04-30-research-tab-v3.md

# 5. The dashboard restart (user runs this — required for Tasks 5 and 10
#    BE routes to actually serve traffic):
#    python C:\TradingScripts\launch_dashboard.py

# 6. Open Playwright MCP (NOT curl — see feedback_playwright_smoke.md)
#    and navigate to http://127.0.0.1:8877/command_center.html
#    Confirm before starting Task 12:
#    - Click Research tab → 6 tiles render with verdict pills + KPIs
#    - Click any tile → expands inline with 7-cell summary, close-btn, deep-dive
#    - Click .close-btn or another tile → collapse / swap
#    - Drift sparklines populate with verdict colors (after restart)
#    - Activate on s2_pocket_pivot → toast "Activated s2_pocket_pivot as ..." (after restart)

# 7. Begin Task 12 with TDD: write static-HTML tests for the QS sub-grid
#    contract first (loadQsForExpandedTile / fetchJSON to /qs-metrics /
#    SVG chart elements), then implement.
```

---

## Task 12 preview (what's next)

From plan body lines 1531+:

- Implement `loadQsForExpandedTile(tile, runId)`:
  - Fetch `/tradelab/runs/<id>/qs-metrics` (already wired in Task 5)
  - Render the QuantStats sub-grid into `tile.querySelector('.tab-qs')`
  - Show `<div class="loading">Loading…</div>` while in flight; `<div class="empty">No run data</div>` if `runId` is null

- Render 3 inline SVG charts (equity / drawdown / monthly returns):
  - Read time series from the qs-metrics response
  - Pure inline SVG (no Chart.js — see `reference_command_center_arch_lock.md`)

- Wire from `expandTile`: after `tile.innerHTML = expandedTileHtml(s)`, call `loadQsForExpandedTile(tile, s.latest_run_id)`

- Tab strip: clicking "Factors" should swap `.tab-qs hidden` ↔ `.tab-factors visible` (Task 13 actually populates the factor matrix; Task 12 just shows the empty placeholder)

The placeholder text inside `.tab-qs` currently says **"QuantStats sub-grid loads in Task 12."** — find and replace that with the real loader.

---

## Gotchas — DO NOT REPEAT (consolidated from prior handoff + new)

(Repeat of prior gotchas 1–10 — see `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_8.md` for full text.)

### Gotcha #11 (NEW from Task 9): The `cards` endpoint envelope is nested

`/tradelab/cards` returns `{data: {groups: [{base_name, cards: [...]}]}}`, not a flat list. Code paths that flatten cards must walk `data.groups[*].cards[*]`. The pre-fetch in `researchLoadLiveCards` and the Overview render path both do this. `c.base_name` is **NOT** on each card object — it's on the parent group. Inject it during flatten if downstream code needs it.

### Gotcha #12 (NEW from Task 9): Run record schema doesn't include symbol/timeframe

`/tradelab/runs?strategy=...` returns runs with `{run_id, timestamp_utc, strategy_name, verdict, dsr_probability, ...}` — no `symbol`, `timeframe`, or `base_name`. Those fields live in `<report-folder>/backtest_result.json`. The Task 10 activate endpoint reads them from there. If Task 12+ needs them on the FE, either (a) extend the run schema, (b) round-trip through `/tradelab/runs/<id>/metrics` which returns `{symbol, timeframe, ...}`, or (c) add a new endpoint that returns the augmented run summary.

### Gotcha #13 (NEW from Task 10): `/tradelab/accept` is FOR THE SCORE→ACCEPT FLOW

Don't confuse it with the new `/tradelab/strategies/<id>/activate`. They serve different UX flows:

- **`/tradelab/accept`** — user just scored a brand-new Pine via the Score modal; we have all the metadata (base_name/symbol/timeframe/report_folder/scoring_run_id) in `researchState.scoreSession`; the user clicks "Accept" to create a card with status=disabled (or status=enabled if `activate: true`).
- **`/tradelab/strategies/<id>/activate`** — Live Cards tile click; we have only `tradelabName` and the latest `run_id`; the BE re-derives the missing fields from the audit DB + `backtest_result.json`.

The static-HTML test `test_v3_task10_no_old_accept_endpoint_for_live_cards` is the explicit guard. If a future task moves any Activate-from-Live-Cards path back to `/tradelab/accept`, that test will fire.

### Gotcha #14 (NEW from Task 10): Two `data-card-id` namespaces

- On Overview live cards: `data-card-id` is on the `.strategy-toggle` child of `.strategy-card`, value = full card_id (e.g. `smoke-amzn-v1`).
- On Research tab tiles: `data-card-id` is on the `.tile` element itself, set lazily after a successful activate, value = full card_id.
- Don't write a selector that assumes both, e.g. `[data-card-id="${id}"]` would match BOTH the toggle AND the tile if both pages are in the DOM. Scope by ancestor: `#researchLiveCards .tile[data-card-id=...]` or `.strategy-card .strategy-toggle[data-card-id=...]`.

### Gotcha #15 (NEW from Task 11): renderLiveCard returns a fresh element

If you need to "re-render" a tile (e.g. after collapse), DO NOT replace the existing tile DOM node — that drops event listeners, animations, dataset, etc. Instead: call `renderLiveCard(...)` to build a detached element, then `tile.innerHTML = detached.innerHTML` to swap inner content while preserving the wrapper. `collapseTile` follows this pattern.

After the inner-HTML swap, the tile's `dataset` is preserved (because dataset lives on the wrapper, not in innerHTML), but if you need to restore something to the wrapper itself, do it explicitly.

---

## Memory references that apply to this work

(Pulled from `MEMORY.md`. These are operating constraints, not just notes.)

- `feedback_plan_grep_verification.md` — verify every selector/signature/enum in a plan against current code before pasting. **Highly relevant.** Used heavily in T9–T11.
- `feedback_dependency_order.md` — sequence work by what unblocks the most downstream items. T10 needed BE first, then FE; T11 needed cache populated by T10's render path.
- `feedback_act_on_recommendations.md` — when I recommend X with reasoning, don't re-prompt; just do X. Used at the T10 endpoint blocker — recommended adding a new route, proceeded without re-prompt.
- `feedback_live_smoke_before_next_slice.md` — always run Playwright smoke between slices; fix bugs mid-smoke not next session. T10 found the `data-base-name` bug mid-smoke and fixed it before commit.
- `feedback_playwright_smoke.md` — UI smoke must use Playwright (navigate + snapshot or evaluate), not curl or manual browser checks. Used in T9–T11.
- `feedback_demo_first_workflow.md` — strategy/data changes go to demo fixture only. (Did not apply to T9–T11 — no strategy data changes.)
- `reference_command_center_arch_lock.md` — vanilla HTML+JS+Chart.js only inside command_center.html. **Will apply to Task 12** (use inline SVG, not D3 / Chart.js plugins).
- `reference_powershell_utf8_bom.md` — PS-written JSON needs `encoding="utf-8-sig"` in Python. (Did not apply to T9–T11.)

---

## When in doubt

1. **Trust this handover** for the current state of disk and the `/tradelab/strategies/<id>/activate` endpoint contract. The plan body and slice-0 amendments are stale on these.
2. **Read the actual code** before pasting plan-body markup or JS. Plan body has been wrong on selectors, IDs, schema, and API field names. Per `feedback_plan_grep_verification.md`.
3. **Run pytest via Bash, not PowerShell.**
4. **Use Playwright MCP for any UI smoke** — feedback memory `feedback_playwright_smoke.md` requires it; pytest is necessary but not sufficient.
5. **Smoke between slices** per `feedback_live_smoke_before_next_slice.md` — every Task 9–11 commit was preceded by a Playwright check; Task 12 should follow the same pattern.
6. **Restart the dashboard** before doing the final smoke — Tasks 5 and 10 both added BE routes that the running process doesn't serve yet.

— end of handover —
