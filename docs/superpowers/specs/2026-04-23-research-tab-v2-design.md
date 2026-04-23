# Research Tab v2.0 — Research Velocity Bundle

**Status:** Draft 2026-04-23 · supersedes the withdrawn `2026-04-22-compare-n-runs-design.md`.
**Scope:** One coherent release reshaping the Research tab around the decision surfaces that actually drive alpha.
**Successor to:** v1 (2026-04-22, `5de629b`) and v1.5 (2026-04-22, `8ef3153` / merge `10bf2c4`).

---

## 1. Goal

Make the Research tab **the centerpiece of tradelab alpha discovery** by:

1. **Cutting wasted runs.** Preflight blocks the common FAILED causes (wrong universe, stale cache, import error, no TD key) before a job ever spawns.
2. **Closing the failure-triage loop.** When runs do fail, the reason surfaces inline — no more opening the log to see "No symbols provided."
3. **Unlocking variant comparison.** Pick ≥2 runs with a checkbox, click "Compare," get a side-by-side tearsheet in a new tab. Ends the "open modal, close, open next modal" dance.
4. **Turning the Pipeline into a decision surface, not a list.** Prioritization heat, "Why FRAGILE?" tooltips, and per-strategy sparklines answer *"what's worth iterating on next?"* at a glance — without drilling into the modal.
5. **Reshaping the tab's visual proportions** to match actual cognitive weight. The Pipeline (where decisions happen) becomes dominant; the Live Cards (deployment context) become a thin supporting strip; the Freshness banner is absorbed into Preflight chips.

Net: every element either feeds into, supports, or extends the Pipeline decision surface. No duplicated information. No dead real estate.

## 2. Constraints honoured (inherited)

From v1 + v1.5 + POST_V1.5 rules:

- **No new web framework.** Vanilla JS, single-file `command_center.html`, `launch_dashboard.py` proxy pattern.
- **No modification to the 4 pre-existing Command Center tabs** or the 10 AlgoTrade safety mechanisms.
- **No engine changes.** `tradelab/src/tradelab/engines/*.py` untouched. All new backend code lives in `tradelab/src/tradelab/web/`.
- **No schema changes.** Audit DB, `jobs.json`, `progress.jsonl`, `backtest_result.json` formats stay as-is.
- **No new dependencies.** Python stdlib + pandas + pytest.
- **Restart required after backend changes** (v1.5 §4.4) — document in release notes.

New constraint for v2:

- **Feature-flagged compressed-cards layout** for 48h post-merge so the compressed strip can be toggled back to the fat grid if it feels too dense in practice. Flag removed after 48h of use.

## 3. Architecture snapshot

### Today (v1.5)

```
Research tab, top to bottom:
  Freshness banner                           ~30px
  Job Tracker (hidden when idle)             0-120px
  Live Strategies — fat card grid (6 cards)  ~1080px  ← dominates
  Research Pipeline filters                  ~50px
  Research Pipeline table                    ~600-800px
```

Pipeline is effectively below the fold on a standard 1080p display.

### After v2

```
Research tab, top to bottom:
  Preflight chip cluster + action buttons    ~60px    ← absorbs Freshness
  Job Tracker (hidden when idle)             0-120px  ← adds failure hints
  Live Strategies — horizontal strip (6 rows) ~280px  ← compressed from 1080px
  Research Pipeline filters                  ~50px
  Research Pipeline (checkbox + heat + spark + tooltip) ~remaining viewport
    └─ "Compare Selected (N)" button appears when ≥2 checked
```

Pipeline now sits above the fold. Freed ~800px of real estate goes to showing more audit rows + the new affordances.

### Server-side additions

```
tradelab/src/tradelab/web/
  preflight.py          NEW — universe/cache/strategy/TD checks
  compare.py            NEW — thin subprocess wrapper over `tradelab compare`
  failure_hint.py       NEW — progress.jsonl last-error parser
  handlers.py           CHANGED — 3 new route branches
  __init__.py           CHANGED — expose _preflight helper for reuse

tests/web/
  test_preflight.py     NEW — ~6 tests
  test_compare.py       NEW — ~7 tests
  test_failure_hint.py  NEW — ~4 tests
```

No changes to `audit_reader`, `freshness`, `ranges`, `whatif`, `new_strategy`, `jobs`, `sse`, `progress`, or `progress_events`.

### Client-side additions

```
command_center.html
  ├─ CSS (new classes)
  │   .preflight-chip{...}             — header chip cluster
  │   .live-strip-row{...}             — compressed live card
  │   .pipeline-heat-*{...}            — verdict heat coloring
  │   .pipeline-sparkline{...}         — inline SVG sparkline
  │   .pipeline-row-select{...}        — checkbox column
  │   .job-failure-hint{...}           — inline error in job row
  │
  ├─ HTML (changed sections)
  │   Remove:  <Freshness banner>
  │   Change:  <Live Strategies>  fat grid → horizontal strip
  │   Change:  <Pipeline table>  add checkbox col, sparkline col, heat on verdict pill
  │   Add:     <Preflight chip cluster>  top-of-tab
  │   Add:     <Compare Selected (N) button>  above Pipeline, hidden when <2 checked
  │
  └─ JS (new functions)
      researchLoadPreflight()
      renderCompactLiveStrip()            — replaces renderLiveCard for v2
      renderSparkline(runs)               — inline SVG, 3-run trend
      renderHeatClass(verdict, dsr, pf)   — CSS class for row background
      renderFragileTooltip(run)           — hover reason text
      handleRowSelect(runId, checked)     — maintains researchState.selectedRunIds
      researchSubmitCompare()             — POST /tradelab/compare
      renderJobFailureHint(job)           — per-job inline error
      featureFlag('v2-layout')            — 48h toggle guard
```

## 4. Per-feature design

### 4.1 Preflight chips (absorbs Freshness banner)

**Problem:** The failure modes visible during v1.5 smoke (POST_V1.5 §2) are dominated by four preventable causes:
1. `launcher-state.json` missing or unreadable → no universe passed → "No symbols provided" exit 2
2. Parquet cache stale/missing for the active universe → run produces 0 trades or crashes
3. Strategy module has an import error → exit 1 before backtest starts
4. TD API key unset or rate-limited → data download fails silently

All four are cheap to check beforehand.

**API:**

```
GET /tradelab/preflight
→ 200
  {
    "error": null,
    "data": {
      "universe":  {"status": "ok"|"warn"|"red", "label": "nasdaq_100", "detail": "42 symbols"},
      "cache":     {"status": ..., "label": "2h 14m old",       "detail": "42/42 symbols fresh"},
      "strategy":  {"status": ..., "label": "all importable",    "detail": "6 strategies OK"},
      "tdapi":     {"status": ..., "label": "key present",       "detail": "TWELVEDATA_API_KEY set"}
    }
  }
```

Status values:
- `ok` — green, nothing to do
- `warn` — yellow, proceed allowed but flagged
- `red` — blocks Run with a clear reason

**Check logic** (in `preflight.py`):

| Check | Red | Warn | OK |
|---|---|---|---|
| `universe` | no active universe resolvable, OR resolved universe has 0 symbols | unknown universe in yaml | ≥1 symbol, name resolved |
| `cache` | >0 symbols missing parquet files | parquet age >24h, or 1-5 symbols missing | all symbols <24h old |
| `strategy` | ≥1 registered strategy fails `importlib.import_module` | — | all registered strategies import clean |
| `tdapi` | `TWELVEDATA_API_KEY` env var unset | — | env var set (no network ping — too slow) |

All checks are **synchronous, fast** (<100ms total). No network calls. Purely disk-local inspection.

**UI — chip cluster** (replaces Freshness banner):

```html
<section id="preflight-chips">
  <span class="preflight-chip preflight-ok">
    <span class="preflight-dot"></span> Universe: nasdaq_100 (42)
  </span>
  <span class="preflight-chip preflight-warn" title="42/42 symbols but cache is 18h old">
    <span class="preflight-dot"></span> Cache: 18h
  </span>
  <span class="preflight-chip preflight-ok">
    <span class="preflight-dot"></span> Strategies: 6 OK
  </span>
  <span class="preflight-chip preflight-ok">
    <span class="preflight-dot"></span> TD API ✓
  </span>
  <button class="btn btn-ghost">Refresh Data</button>
  <button class="btn btn-ghost">New Strategy</button>
</section>
```

Clicking a chip → tooltip with `detail` text. Clicking "Refresh Data" → existing refresh handler.

**Run-modal integration:**

The v1.5 3f confirmation modal opens when a user clicks a Run ▾ command. v2 extends it:

- Before the modal renders its body, it calls `/tradelab/preflight` and reads back the 4 statuses.
- If **any status is `red`**: the Start button is disabled; the modal shows the `detail` text for each red status with a "Fix and retry" help link (deep-links to the appropriate doc section for universe/cache/strategy/TD).
- If **any status is `warn`**: Start button stays enabled but the modal shows a yellow warning row with detail.
- If **all `ok`**: modal shows a one-line green "preflight OK" row and Start is enabled.

**Persistence:** preflight chips at the top refresh on tab activation and whenever the Run modal closes. No polling.

### 4.2 Failure hints in Job Tracker

**Problem:** When a job ends FAILED in the Job Tracker panel, the row currently just shows "failed" status. To find out *why*, you have to open `.cache/jobs/<id>/progress.jsonl` or `reports/<strategy>_<ts>/` and grep. Time sink — most failures have the same causes.

**API:** No new endpoint. The existing `GET /tradelab/jobs` already returns a per-job record. v2 adds a `failure_hint` field to each job's JSON record when its state is `FAILED`:

```json
{
  "id": "job_20260423_093241_abc",
  "strategy": "s2_pocket_pivot",
  "command": "run --robustness",
  "state": "FAILED",
  "exit_code": 2,
  "started_at": "...",
  "finished_at": "...",
  "failure_hint": "exit 2 · 'No symbols provided' — universe not resolved"
}
```

**Hint derivation** (in `failure_hint.py`):

1. Parse `.cache/jobs/<id>/progress.jsonl` line by line.
2. Find the last `error` or `stage` event with `.ok == false`.
3. Extract `error_type` + `message` (truncate message to 80 chars).
4. Fall back to exit code if no parseable error event: `"exit <N>: <best-guess label>"`.

Label table for common exit codes (best-guess):
- 0 → "success (but state=FAILED — possible orchestration bug)"
- 1 → "Python exception (see log)"
- 2 → "CLI arg error"
- 3 → "timeout"
- -1073741510 / 3221225786 → "cancelled (CTRL_BREAK)"
- other → "exit N: see log"

If the last event has `error_type == "NoSymbolsProvided"`, hint is `"universe not resolved — check preflight"`.

**UI change in Job Tracker row:** append `<span class="job-failure-hint">{hint}</span>` for FAILED jobs. Orange text, 12px, under the strategy name.

### 4.3 Compare-N-runs

*(Rollover from the withdrawn 2026-04-22 spec — updated for v2 context.)*

**Problem:** You ran variants A/B/C of the same strategy. You want to see the equity curves + metrics side by side. Today requires opening 3 modals sequentially, closing each.

**API:**

```
POST /tradelab/compare
Content-Type: application/json
{
  "run_ids": ["s2_pocket_pivot_2026-04-21_122955", "s2_pocket_pivot_2026-04-21_152409"],
  "benchmark": "SPY"
}
→ 200 {"error": null, "data": {"report_path": "reports/compare_20260423_093045.html"}}
→ 400 on invalid input / ineligible runs
→ 500 on subprocess failure
```

```
GET /tradelab/compare-report?path=<relpath>
→ 200 text/html with the rendered HTML file
→ 400 on path traversal attempt or nonexistent file
```

**Handler** (`compare.py`):

```python
def run_compare(run_ids: list[str], benchmark: str = "SPY",
                timeout_s: int = 60) -> tuple[dict, int]:
    """Resolve run_ids → folders, run `tradelab compare`, return (body, status)."""
```

- Validates `run_ids` is a list of ≥2 strings matching `^[A-Za-z0-9_\-]+$`.
- Resolves each via `audit_reader.get_run_folder(run_id)`. If `None` or folder lacks `backtest_result.json` → collect into `ineligible` list.
- If `ineligible` non-empty → `(err("N runs predate JSON persistence: <list>"), 400)`.
- Else builds argv: `[sys.executable, "-m", "tradelab.cli", "compare", *folder_paths, "--output", out_path, "--benchmark", benchmark, "--no-open"]`.
- `out_path = Path("reports") / f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"`.
- `subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", timeout=60, cwd=<tradelab_root>)`.
- On timeout / non-zero exit → `(err("compare exited N: <stderr tail>"), 500)`.
- On success → `({"error": None, "data": {"report_path": str(out_path)}}, 200)`.

**Compare-report route** (in `handlers.py`):

- Validate `path` query param:
  - Resolve to absolute path
  - Must be under `reports/`
  - Filename must match `^compare_\d{8}_\d{6}\.html$`
  - No `..` in raw input
- On valid: return file bytes with `Content-Type: text/html; charset=utf-8`.

### 4.4 Pipeline polish

Four small additions to the existing Pipeline table, collectively transforming it from list → decision surface.

#### 4.4.1 Checkbox column

New `<th></th>` at column 0. Each `<tr>` prepends `<td><input type="checkbox" class="pipeline-row-select" data-run-id="${r.run_id}"></td>`.

State: `researchState.selectedRunIds = new Set()`.

Checkbox change handler:
- Toggles `run_id` in the set.
- Updates "Compare Selected (N)" button's label and visibility.
- Click does NOT bubble to row (stopPropagation, so the modal doesn't open when ticking).

On pagination/filter/re-render: re-apply `checked` state to rows whose run_id is in the set.

#### 4.4.2 Prioritization heat on the verdict pill

Extend the existing `.verdict-pill` class with heat intensity based on a composite health score:

```
score = f(verdict, dsr, pf, max_dd_pct)

ROBUST  + dsr ≥ 0.70 + pf ≥ 1.30  → heat-level-5  (strong green)
ROBUST  otherwise                   → heat-level-4  (mild green)
MARGINAL + dsr ≥ 0.40              → heat-level-3  (amber)
MARGINAL otherwise                  → heat-level-2  (dim amber)
INCONCLUSIVE / small-n              → heat-level-1  (gray)
FRAGILE                             → heat-level-0  (dim red)
```

Pure CSS: add `.heat-0` through `.heat-5` backgrounds to existing `.verdict-pill`. No JS logic beyond picking the class in `renderPipelineRows`.

#### 4.4.3 "Why FRAGILE?" tooltip

For rows where `verdict === "FRAGILE"` or `"MARGINAL"`: the verdict pill's `title` attribute lists the top ≤2 gate failures:

```
FRAGILE — reasons:
  · low trade count (n=23, threshold 50)
  · regime-worst PF 0.71 (threshold 0.90)
```

**Source of reasons:** existing `GET /tradelab/runs/<run_id>/metrics` already returns `gate_failures` (array of strings). If that field doesn't exist in the current endpoint, v2 adds it. Check before implementation.

*(Implementation detail: if the endpoint response lacks `gate_failures`, plan task will add the field by reading `backtest_result.json`'s `gate_failures` array — which `cli_run` already writes.)*

No new endpoint. Just a `title` attribute populated from existing data.

#### 4.4.4 Per-strategy sparkline column

New column `<th>Trend</th>` between DSR and Date. Shows 3-run trend as a tiny inline SVG sparkline (not the letter string the Live Cards used — a true visual sparkline).

**Data source:** fetched lazily per strategy, cached. When a row renders, if we haven't already loaded the sparkline data for its strategy, fire `GET /tradelab/runs?strategy=<name>&limit=3` once and cache. Subsequent rows for the same strategy reuse.

**SVG generation** (pure frontend):

```
renderSparkline(runs) → <svg width="60" height="18">
  <polyline points="..." stroke="..." fill="none"/>
</svg>
```

Data mapped: y-axis = normalized PF (range-stretch across 3 runs), color = latest verdict tint. Degenerate cases (1 run, same value) render as a short horizontal line.

### 4.5 Live Cards compression

**Design:** fat 180px cards in a 3-column grid → single horizontal strip with one 38px row per live strategy.

**Before** (per card, 1080px total for 6):
```
┌────────────────────┐
│ s2_pocket_pivot    │
│        ROBUST      │
│ PF 1.41 WR 52%     │
│ DD 8%  DSR 0.82    │
│ Trend: R → R → M   │
│ ⚠ degraded         │
│ [Dash] [QS] [Run▾] │
└────────────────────┘
```

**After** (per strip row, ~280px total for 6):
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ s2_pocket_pivot  [ROBUST]  ▇▅▄ (spark)  PF 1.41 WR 52% DD 8% DSR 0.82  [D][Q][R▾]│
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Unique functions preserved:**
- `LIVE_TO_TRADELAB` name mapping — still applied (left column is the live name)
- 3-run trend — now a real sparkline (inline SVG, same renderer as Pipeline sparkline column)
- `⚠ degraded` indicator — if present, prepends an amber dot to the left of the verdict pill
- Dashboard / QS / Run ▾ action cluster — kept, horizontal right-side

**Responsive behavior:** at narrow widths, the stats row wraps under the verdict-pill; action buttons collapse to a `···` overflow menu.

**Feature flag:** new CSS class `body.v2-layout` controls whether the compressed strip or legacy cards render. Default on. Toggle: `localStorage.setItem('researchLayoutLegacy', '1')` → reload renders fat grid. 48h grace window; flag removed in a follow-up commit once confirmed.

## 5. Error handling summary

| Condition | HTTP | Body |
|---|---|---|
| `/tradelab/preflight` — all checks pass | 200 | all `status: "ok"` |
| `/tradelab/preflight` — any check fails | 200 | per-check `status: "warn"` or `"red"` |
| `/tradelab/compare` — fewer than 2 run_ids | 400 | `"at least 2 runs required"` |
| `/tradelab/compare` — invalid run_id pattern | 400 | `"invalid run_id: <id>"` |
| `/tradelab/compare` — unknown run_id | 400 | `"unknown run_id: <id>"` |
| `/tradelab/compare` — run folder missing backtest_result.json | 400 | `"N runs predate JSON persistence: ..."` |
| `/tradelab/compare` — subprocess timeout | 500 | `"compare timeout after 60s"` |
| `/tradelab/compare` — subprocess non-zero exit | 500 | `"compare exited N: <stderr tail>"` |
| `/tradelab/compare-report` — path traversal attempt | 400 | `"invalid report path"` |
| `/tradelab/compare-report` — file not found | 404 | `"report not found: <path>"` |
| Run modal submit while preflight red | client blocks POST | — |
| Run modal submit while preflight warn | server accepts | record `preflight_at_submit` in job metadata for audit |

## 6. Testing plan

### New test files

| File | Tests | Coverage |
|---|---|---|
| `tests/web/test_preflight.py` | ~6 | all 4 status computations, red/warn/ok transitions, missing state files |
| `tests/web/test_compare.py` | ~7 | input validation, happy path, ineligible runs, path traversal |
| `tests/web/test_failure_hint.py` | ~4 | parse progress.jsonl, exit-code label fallback, NoSymbolsProvided mapping |

### Extended tests

- `tests/web/test_handlers_jobs.py` — add assertion that FAILED job records include `failure_hint` field.
- `tests/web/test_handlers.py` — add `/tradelab/preflight` + `/tradelab/compare` + `/tradelab/compare-report` route tests.

### Baseline target

Current: 72 passing (`tests/web/` + `tests/cli/test_progress_log.py`).
After v2: ~90 passing (adds ~17 tests across preflight/compare/failure_hint + handler extensions).

### Manual smoke checklist

After merge, before declaring success:

1. Open dashboard → Research tab. Confirm preflight chips render all green on fresh setup.
2. Break universe: delete `launcher-state.json` → chip turns red, Run modal blocks.
3. Break cache: `Stop-Service` on Twelve Data cache, test staleness → chip turns yellow.
4. Break strategy: edit `frog.py` to have a syntax error → chip turns red.
5. Fire a run that succeeds → Job Tracker row clears to DONE.
6. Fire a run that fails (e.g., `--symbols` to an unknown symbol) → Job Tracker shows failure hint inline.
7. In Pipeline, check 2 rows → "Compare Selected (2)" appears. Click → new tab opens comparison report.
8. Verify compressed Live strip renders 6 rows with correct names, verdicts, sparklines, buttons.
9. Toggle `localStorage.researchLayoutLegacy = '1'` → reload → fat grid renders. Toggle back.
10. Hover a FRAGILE verdict pill → tooltip shows gate failures.

## 7. Rollback / risk controls

**Rollback unit:** one merge commit. Revert it → all v2 features gone, v1.5 behavior restored.

**Pre-commit checkpoints:**
- Phase-1 commit (`preflight` + chips): feature is isolated, can ship alone if later phases regress.
- Phase-2 commit (failure hints): additive to Job Tracker, no dependency on preflight.
- Phase-3 commit (compare): backend + frontend paired; no dep on phases 1-2.
- Phase-4 commit (pipeline polish): pure frontend; no dep on other phases.
- Phase-5 commit (live card compression): pure frontend behind feature flag.

Each phase is independently revertable.

**Feature flag** for the compressed-cards layout: `localStorage.researchLayoutLegacy` — set to `'1'` to render legacy fat grid. Documented in release notes. Removed after 48h.

**Backup files:** Create `.bak-2026-04-23-v2` sidecars for `command_center.html` and `launch_dashboard.py` before merging, per v1.5 convention.

## 8. Out of scope (explicit defers)

**Deferred to v2.1+ or later:**

- **Shift-click range select, "select all" checkbox** in Pipeline — YAGNI until usage justifies.
- **Persisted comparison history** — each compare produces ephemeral `reports/compare_*.html`. No audit DB row, no history panel.
- **Per-run benchmark override** in the compare UI — hardcoded `SPY`; a form field is a v2.1 item.
- **Auto-fixing preflight reds** — e.g., a "Refresh cache now" button that actually runs the refresh. v2 surfaces the problem; fixing is still user-triggered.
- **TD API network ping in preflight** — too slow (>100ms); v2 only checks env-var presence. A background health poll is a future item.
- **Concurrent jobs** (v1.5 §8 deferred) — gated on real queue-wait data from Phase 2 observation.
- **Studies tab** (new tab for cross-cutting analyses like PBO, correlation, portfolio MC) — opens in v1.7 once we have ≥2 analyses ready.
- **Per-strategy param overrides in Run modal** — requires P-hacking audit log; v2.1+.
- **Factoring Research-tab JS out of `command_center.html`** into a sibling `research_tab.js` — separate cleanup concern.
- **§7 backlog items #1/3/4/5** (probe-on-boot, cwd param, public accessors, SSE threading.Event) — fold in opportunistically; none block v2.

**Explicitly not building:**
- No migration of any of the 4 existing AlgoTrade tabs.
- No changes to the 10 safety mechanisms.
- No changes to `engines/*.py`.
- No new dependencies.

## 9. Effort estimate

| Phase | Feature | Dev | Tests | Smoke |
|---|---|---|---|---|
| 1 | Preflight chips + route + Run-modal integration | 1 day | 0.3 day | 0.2 day |
| 2 | Failure hint parser + Job Tracker row extension | 0.5 day | 0.2 day | 0.1 day |
| 3 | Compare-N-runs (backend + frontend + route) | 1 day | 0.3 day | 0.2 day |
| 4 | Pipeline polish (checkbox + heat + tooltip + sparkline) | 1 day | 0.2 day | 0.2 day |
| 5 | Live card compression (CSS + renderer + feature flag) | 0.5 day | 0.1 day | 0.2 day |
| - | Bundle docs + changelog + v2 summary | — | — | 0.3 day |

**Total: ~5-6 calendar days.** One worktree, one merge.

## 10. Rollout

1. Create worktree: `C:\TradingScripts\tradelab\.claude\worktrees\research-v2` (via `EnterWorktree`).
2. Implement phases 1-5 sequentially, commit per phase.
3. Run full test suite after each phase; block phase commit on regression.
4. Manual smoke (§6 checklist) after phase 5.
5. Create `.bak-2026-04-23-v2` sidecars for `command_center.html` and `launch_dashboard.py`.
6. Merge to `master` as one merge commit with a descriptive summary.
7. Write `RESEARCH_TAB_V2_SUMMARY.md` in `docs/superpowers/` per the v1/v1.5 pattern.
8. Add/update memory: `project_tradelab_web_dashboard.md` gets a v2 line; flag file is 48h lifetime.
9. Push tradelab repo to `origin` (`amt558/Backtester-`).
10. `C:\TradingScripts\` commits (launch_dashboard.py changes only) stay local until the origin remote decision is revisited (per POST_V1.5 §10; origin was removed this session).

## 11. References

**In repo:**
- v1 summary: `docs/superpowers/RESEARCH_TAB_V1_SUMMARY.md`
- v1.5 summary: `docs/superpowers/RESEARCH_TAB_V1.5_SUMMARY.md`
- Post-v1.5 stabilization: `docs/superpowers/POST_V1.5_STABILIZATION_SUMMARY.md`
- `tradelab compare` CLI: `src/tradelab/cli.py:463-512`
- `tradelab.web.audit_reader.get_run_folder`: `src/tradelab/web/audit_reader.py:125-141`
- `tradelab.web._resolve_active_universe`: `src/tradelab/web/handlers.py:33-59`

**Outside repo:**
- `C:\TradingScripts\command_center.html` (2669→3002 after v1.5; will reach ~3400 after v2)
- `C:\TradingScripts\launch_dashboard.py` (preflight route + compare route additions)

**Memory (for future Claude sessions):**
- `project_tradelab.md` — fragility-first philosophy; threshold logic
- `project_tradelab_web_dashboard.md` — v1+v1.5+v2 decisions
- `reference_launch_dashboard_probe.md` — PEP-420 + PYTHONPATH gotchas
- `reference_powershell_utf8_bom.md` — BOM read pitfall
- `feedback_web_over_hotkeys.md` — primacy of web UI

---

## Appendix A — Layout comparison (raw)

**v1.5 (current):**
```
┌─ Freshness banner (2h old · parquet cache healthy) ──────────────┐
│ [Refresh Data] [New Strategy]                                     │
├──────────────────────────────────────────────────────────────────┤
│ Live Strategies — tradelab health                                 │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐                         │
│ │ s2_pocket│  │ s7_rdz   │  │ frog     │                         │
│ │  ROBUST  │  │  FRAGILE │  │  ...     │                         │
│ │ PF 1.41  │  │ PF 0.91  │  │          │                         │
│ │ WR 52%   │  │ WR 44%   │  │          │                         │
│ │ DD 8%    │  │ DD 14%   │  │          │                         │
│ │ DSR 0.82 │  │ DSR 0.11 │  │          │                         │
│ │ R→R→M    │  │ R→F→F    │  │          │                         │
│ │ [D][Q]   │  │ [D][Q]   │  │          │                         │
│ │ [Run▾]   │  │ [Run▾]   │  │          │                         │
│ └──────────┘  └──────────┘  └──────────┘                         │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐                         │
│ │ qulla... │  │ viprasol │  │ ...      │                         │
│ │          │  │          │  │          │                         │
│ └──────────┘  └──────────┘  └──────────┘    ← ~1080px            │
├──────────────────────────────────────────────────────────────────┤
│ Research Pipeline                                                 │
│ [Strategy ▾] [Verdict ▾] [Since 30d ▾] [Clear]                    │
│ ┌─────────────────────────────────────────────────────────────┐  │
│ │ Strategy     Verdict  PF    WR   DD   Trd  DSR  Date   Run │  │
│ │ s2_pocket    ROBUST  1.41  52%  8%   47  0.82  4-22  ▾    │  │
│ │ s2_pocket    MARGIN  1.19  49%  11%  41  0.38  4-21       │  │
│ │ s7_rdz_...   FRAGILE 0.91  44%  14%  29  0.11  4-20  ▾    │  │
│ │ ...                                                          │  │
│ │ [Show 50 more]                                              │  │
│ └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**v2 (proposed):**
```
┌─ [◉ Universe: nasdaq_100 (42)] [◐ Cache 18h] [◉ Strategies 6 OK] [◉ TD API ✓] ─┐
│ [Refresh Data] [New Strategy]                                                   │
├───────────────────────────────────────────────────────────────────────────────┤
│ Live Strategies — deployment health                                            │
│ s2_pocket_pivot  ROBUST  ▇▅▄  PF 1.41 WR 52% DD 8% DSR 0.82     [D][Q][Run▾] │
│ s7_rdz_momentum  FRAGILE ▂▄▇  PF 0.91 WR 44% DD 14% DSR 0.11    [D][Q][Run▾] │
│ frog             INCONC  ───  (no runs)                         [D][Q][Run▾] │
│ qullamaggie_ep   INCONC  ───  (no runs)                         [D][Q][Run▾] │
│ viprasol_v83     ROBUST  ▆▆▇  PF 1.22 WR 48% DD 9%  DSR 0.68    [D][Q][Run▾] │
│ s4_inside_day    MARGIN  ▄▅▆  PF 1.15 WR 51% DD 10% DSR 0.42    [D][Q][Run▾] │
├───────────────────────────────────────────────────────────────────────────────┤
│ Research Pipeline                                                              │
│ [Strategy ▾] [Verdict ▾] [Since 30d ▾] [Clear]  [Compare Selected (2)]         │
│ ┌──────────────────────────────────────────────────────────────────────────┐ │
│ │ ☐  Strategy      Verdict  PF   WR   DD   Trd  DSR   Trend  Date   Run  │ │
│ │ ☑  s2_pocket     ROBUST🟩 1.41 52%  8%   47  0.82   ▂▄▆▇  4-22  ▾    │ │
│ │ ☑  s2_pocket     MARGIN🟨 1.19 49%  11%  41  0.38   ▇▆▄▂  4-21       │ │
│ │ ☐  s7_rdz_...    FRAGILE🟥*0.91 44%  14%  29  0.11   ▂▄▇▅  4-20  ▾    │ │
│ │                                        * hover → "low trades (29), DSR 0.11"│ │
│ │ ... (12 more rows now visible above the fold)                           │ │
│ └──────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```
