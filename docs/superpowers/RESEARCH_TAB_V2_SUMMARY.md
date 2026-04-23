# Research Tab v2.0 — Summary & v2.1 Handoff

**For a future Claude session.** This doc recaps what v2.0 shipped, where the code lives, gotchas surfaced during execution, and the v2.1 backlog. Read this AND `RESEARCH_TAB_V1_SUMMARY.md` + `RESEARCH_TAB_V1.5_SUMMARY.md` first if picking up the work.

**Shipped:** 2026-04-23 · Branch `research-v2` in the tradelab worktree (`C:\TradingScripts\tradelab\.claude\worktrees\research-v2`), not yet merged to master (Task 20 pending user sign-off after UI smoke).

---

## 1. TL;DR

v1.5 let Amit *trigger* tradelab runs from the browser. **v2.0 makes the Research tab the decision surface** — preflight blocks bad runs before they spawn, failure hints close the triage loop, `Compare Selected` lets 2+ runs be diffed in a new tab, and the Pipeline gains heat-coloring, "Why FRAGILE?" tooltips, and sparklines. Live Strategy cards compress into a horizontal strip behind a 48h feature flag so the Pipeline dominates the page.

Bottom line: every element of the Research tab now feeds into, supports, or extends the Pipeline decision surface. Zero engine changes, zero schema changes, zero new dependencies.

---

## 2. What v2.0 delivered

| Feature | Backend | Frontend | Tests |
|---|---|---|---|
| Preflight chips + Run-modal integration | `web/preflight.py` (4 checks + aggregator), `GET /tradelab/preflight` | `researchLoadPreflight()`, `renderPreflightInModal()`, chip cluster replaces Freshness banner, Start-button-disable on red | 6 module + 1 handler = 7 |
| Failure hints in Job Tracker | `web/failure_hint.py` (parser + exit-code fallback), `Job.to_dict()` extension | Failure hint line under FAILED job rows | 4 module + 2 dict = 6 |
| Compare-N-runs | `web/compare.py` (validates run_ids, subprocesses CLI), `POST /tradelab/compare`, `GET /tradelab/compare-report` (raw HTML in launcher) | Checkbox col + `Compare Selected (N)` button, `researchState.selectedRunIds` Set, delegated change listener, opens report in new tab | 7 |
| Pipeline polish (heat + FRAGILE tooltip + sparkline) | — (all client-side derivation) | `verdictHeatClass()`, `fragileReasons()`, `renderSparkline()`, `getSparklineRuns()` cache, new Trend column | — |
| Live Cards compression | — | `body.v2-layout` CSS, rewritten `renderLiveCard()` with event-delegation wiring, `localStorage.researchLayoutLegacy` toggle | — |

### Tests

Test count evolved: `tests/web/ + tests/cli/test_progress_log.py` went from **77 passed / 1 skipped** (post-v1.5) to **91 passed / 1 skipped**. Net +14 tests, 0 regressions.

| File | Tests added |
|---|---|
| `tests/web/test_preflight.py` | 6 |
| `tests/web/test_handlers.py` | +1 (`test_get_preflight_returns_all_four_statuses`) |
| `tests/web/test_failure_hint.py` | 4 |
| `tests/web/test_handlers_jobs.py` | +2 (`test_failed_job_to_dict_includes_failure_hint`, `test_running_job_to_dict_omits_failure_hint`) |
| `tests/web/test_compare.py` | 7 |

---

## 3. Architecture snapshot (v1.5 → v2.0)

```
tradelab/src/tradelab/web/
├── handlers.py        (+3 route branches: preflight GET, compare POST)
├── jobs.py            (+3 LOC: to_dict sets failure_hint when status==FAILED)
├── preflight.py       [NEW] — 4 disk-local checks + compute_preflight()
├── failure_hint.py    [NEW] — parse progress.jsonl last error + exit-code fallback
└── compare.py         [NEW] — run_compare(run_ids, benchmark) returns (dict, int)

C:\TradingScripts\
├── command_center.html (+413 diff lines, all within Research tab + modal)
└── launch_dashboard.py (+21 lines: serve_compare_report helper method)
```

No engine changes. No canary changes. No schema changes. No dependencies added.

---

## 4. Gotchas surfaced during execution

**Worth remembering — these bit us this session and will bite again:**

1. **Plan accuracy — `handle_get_with_status` signature.** The plan's test code called `handle_get_with_status("/path", {})` with two args, but the actual signature is single-arg (`path_with_query`). Fixed in Tasks 3 and 7.

2. **Plan accuracy — `JobState` vs `JobStatus`.** Plan referenced `self.state == JobState.FAILED` but the real code is `self.status == JobStatus.FAILED`, with enum value `"failed"` (lowercase via `.value`). Serialized key is `status`, not `state`. Relevant at both the backend (Task 7) and frontend (`j.status === 'failed'` in Task 8, not `j.state === 'FAILED'`).

3. **Plan accuracy — Start button selector.** Plan prescribed `modalBody.querySelector('[data-action="start"]')` for the Run-modal Start button, but the real button is `#modal-3f-confirm` with no `data-action` attribute. Without the fix (commit `2380635`), red preflight silently did nothing.

4. **XSS pattern in plan templates.** Three of the plan's prescribed JS snippets used `innerHTML` with raw interpolation of server-supplied strings (`r.label`, `r.detail`, and `renderLiveCard`'s inline `onclick="openResearchModal('${tradelabName}', ...)"`). All rewritten to use `textContent`/`createTextNode`/`document.createElement`/`dataset` + `addEventListener` + `escapeHtml()`. Commits `8ef29ed`, `2380635`, and `9e7e4ef` carry the fixes.

5. **`btn-ghost` class is prescribed but undefined.** The Preflight refresh/new-strategy buttons use `class="btn btn-ghost"` (plan + implementation). `btn` exists; `btn-ghost` doesn't. Buttons render with base `btn` styling — functional, not visually distinct. Deferred to v2.1 (add the `btn-ghost` style, or drop the class).

6. **Latent bug in old `renderLiveCard`.** Pre-v2 code kicked off `fetchJSON(...metrics).then(...)` *before* `card.innerHTML = ...` overwrote the elements the callback targeted. Metrics silently never populated. v2's rewrite sets innerHTML first, then fires the lazy fetch. Fixed incidentally in commit `9e7e4ef`.

7. **Run-dropdown delegation change.** The compressed-card rewrite drops inline `data-strategy="..."` from `<details class="run-dropdown">`. The global delegated handler now reads `dropdown.dataset.strategy || dropdown.closest('.research-card')?.dataset.strategy` so pipeline-table dropdowns (still carry inline `data-strategy`) keep working AND live-card dropdowns resolve via parent `.research-card`.

8. **`colspan` sync.** The pipeline table added 2 columns across v2 (checkbox in Task 12, Trend in Task 15). Skeleton/empty-state `<tr>` colspans went `9 → 10 → 11`. Positions table has its own `colspan="9"` that was NOT bumped — it's a separate table.

---

## 5. How to run / restart / debug

Inherits v1.5 procedure. No changes except:

- **After merge, first browser load:** preflight chips fetch `GET /tradelab/preflight` on tab activation. If they don't appear, check browser console for `preflight load failed` warning.
- **Feature-flag toggle:** `localStorage.setItem('researchLayoutLegacy', '1')` → reload → fat-grid live cards return. `localStorage.removeItem('researchLayoutLegacy')` → reload → compressed strip.
- **Force a restart** after any backend change (same as v1.5). Front-only changes (CSS/HTML/JS in `command_center.html`) only need a browser hard-refresh.

Regression command:
```powershell
cd C:\TradingScripts\tradelab\.claude\worktrees\research-v2
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
# expect: 91 passed, 1 skipped
```

---

## 6. Files outside the tradelab git repo

| Path | Repo | Backup sidecar |
|---|---|---|
| `C:\TradingScripts\command_center.html` | `C:\TradingScripts` | `command_center.html.bak-2026-04-23-v2` |
| `C:\TradingScripts\launch_dashboard.py` | `C:\TradingScripts` | `launch_dashboard.py.bak-2026-04-23-v2` |

Remote for `C:\TradingScripts` was removed this session (consistent with v1.5 finding). Commits stay local. Backups survive 48h post-merge in case the compressed-cards layout needs rollback.

---

## 7. v2.1 backlog

Items deferred during v2 execution, in rough priority order:

1. **Define the `btn-ghost` CSS class** (or replace usage with `btn btn-secondary` or drop the class). Currently the Refresh Data / New Strategy chip-cluster buttons render as plain `.btn`.
2. **Extract `PREFLIGHT_KEYS` constant** in `command_center.html` — currently the list `['universe', 'cache', 'strategy', 'tdapi']` is duplicated between the HTML chip IDs and the JS loop. If a 5th check is added, both must be kept in sync.
3. **Select-all checkbox wiring** for the pipeline table's `#pipelineSelectAll` input (currently a placeholder with `display:none`).
4. **Compare Selected toast polish** — currently falls back to `alert()` because `showToast` doesn't exist in `command_center.html`. Adding a lightweight toast helper would match the v1.5 job-error UX.
5. **Sparkline fetch load** — `getSparklineRuns` triggers up to 3 extra metrics fetches per unique strategy on first pipeline load. Cached thereafter. If Pipeline grows to 50+ strategies, consider a single batch endpoint `/tradelab/runs/sparkline-batch`.
6. **Feature flag removal** — scheduled for 2026-04-25 (48h post-merge). Unconditionally apply `v2-layout` class and delete the localStorage override block.

---

## 8. Deliberately omitted from v2 (carried from spec §8)

The following were considered and **explicitly out of scope**:

- No "run again with params" quick-action on Pipeline rows.
- No persistent Compare sets (selections are per-session, wiped on reload).
- No engine-side `gate_failures` field — "Why FRAGILE?" is derived client-side from existing metrics.
- No new dependencies (no Chart.js / D3 — sparklines are inline SVG).
- No backend benchmark override pool — only `"SPY"` is accepted; future configurability goes in v2.1+.
- No auth / RBAC (tradelab remains a localhost-only dashboard).

---

## 9. References

- **Spec:** `docs/superpowers/specs/2026-04-23-research-tab-v2-design.md`
- **Plan:** `docs/superpowers/plans/2026-04-23-research-tab-v2.md`
- **Prior summaries:** `RESEARCH_TAB_V1_SUMMARY.md`, `RESEARCH_TAB_V1.5_SUMMARY.md`, `POST_V1.5_STABILIZATION_SUMMARY.md`
- **Protected paths (DO NOT TOUCH):** `src/tradelab/engines/*`, `src/tradelab/canaries/*`, the 4 pre-v1 Command Center tabs, the 10 AlgoTrade safety mechanisms.

### Commit index

tradelab worktree (`research-v2` branch, off master):
```
62fd3af  feat(web): wire /tradelab/compare POST route
a2e9f97  feat(web): add compare module for cross-run report generation
cadc88f  feat(web): include failure_hint in FAILED job dict
b13ae48  feat(web): add failure_hint parser for FAILED job progress logs
ab0b0a5  feat(web): expose /tradelab/preflight GET route
70fd624  test(web): add preflight module tests
d5af2ce  feat(web): add preflight module with 4 status checks
c706c93  docs(plan): research tab v2.0 implementation plan
cb2c5c1  docs(spec): Research Tab v2.0 — research-velocity bundle
```

C:\TradingScripts repo (on master of that repo):
```
9e7e4ef  feat(command-center): compress Live Strategies cards into horizontal strip (v2-layout, feature-flagged)
b84ee74  feat(command-center): add Trend sparkline column to Pipeline
199095b  feat(command-center): add 'Why FRAGILE?' tooltip on verdict pills
f2eb806  feat(command-center): apply prioritization heat to verdict pills
c772c41  feat(command-center): add row checkbox + Compare Selected button
e67f367  feat(launcher): add /tradelab/compare-report static-HTML route
a142f1e  feat(command-center): render failure_hint under FAILED jobs in Job Tracker
2380635  fix(command-center): use #modal-3f-confirm for Start button disable on red preflight
e476501  feat(command-center): integrate preflight into Run confirmation modal
8ef29ed  fix(command-center): harden researchLoadPreflight against XSS via r.label
d55057d  feat(command-center): replace Freshness banner with preflight chip cluster
```

---

## 10. How to resume v2.1

1. Read §4 gotchas and §7 backlog above.
2. If shipping a single v2.1 patch: pick one item from §7, write a spec + plan with `superpowers:writing-plans`, execute via `superpowers:subagent-driven-development`. Don't bundle unrelated items.
3. If v2.1 involves more chip types or another Preflight check: update `preflight.py::compute_preflight`, add to the `PREFLIGHT_KEYS` constant (item 2 in §7 — extract it first), and add the chip `<span>` in the HTML cluster. Tests live in `tests/web/test_preflight.py`.
4. Before any browser-facing change, verify baseline: `pytest tests/web/ tests/cli/test_progress_log.py -q` on master should still show `91 passed, 1 skipped` (assuming v2 is merged).
5. When editing `command_center.html`, re-create a dated backup sidecar before any non-trivial change (`Copy-Item C:\TradingScripts\command_center.html C:\TradingScripts\command_center.html.bak-YYYY-MM-DD`). The v2 sidecar can be deleted once v2.1 ships cleanly.
