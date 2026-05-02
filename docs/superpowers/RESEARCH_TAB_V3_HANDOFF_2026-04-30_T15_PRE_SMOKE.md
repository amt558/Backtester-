# Research Tab v3 — Handover Doc (2026-04-30, mid-Task-15, pre-smoke)

> **Read this if you are picking up Task 15 (pipeline delete affordances).** Slices 1-4 are implemented and unit-tested. Slice 5 (live-BE smoke + commits) is pending. **Nothing is committed yet** — both repos have uncommitted edits that constitute the entire T15 deliverable. This doc is the resume recipe.
>
> Supersedes for Task 15: the parent doc `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md` and the discovery findings at `docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md`. Read both for context before resuming.

---

## TL;DR

- **Plan:** `docs/superpowers/plans/2026-04-30-research-tab-v3.md` Task 15 (lines 1819-1968) — but **plan body is heavily misaligned with current code**. Use the discovery doc + this handover instead.
- **Discovery doc (slice 0 equivalent):** `docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md`
- **Branches (cross-repo):**
  - tradelab: `feat/research-tab-v3` at `C:\TradingScripts\tradelab\` — HEAD `f79e70f` (the prior handover commit). **Slices 1-4 work is UNCOMMITTED.**
  - parent: `feat/research-tab-v3` at `C:\TradingScripts\` — HEAD `ce9332e7` (T14 chrome). **Slice 3-4 FE work is UNCOMMITTED.**
- **Done in this session:** P0 #1 smoke gate cleared (T12/T13/T14 verified live); T15 slices 1-4 (BE helper + new endpoint + FE cascade-aware modal + stale-copy fix).
- **Next up:** Slice 5 — live-BE smoke after dashboard restart, then commit per repo.
- **Test baseline:** **478 passed** (was 455 after T14; +23 across 3 new test files). Full suite ~2 min via Bash.
- **Don't run pytest via PowerShell.** Use Bash.

---

## What's done in this session

### P0 #1 smoke gate (T12/T13/T14) — CLEARED
After two iterations of finding and killing stale dashboard processes, the new BE routes served correctly and Playwright MCP verified all three tasks against real data. Full evidence in the parent handover's new "Smoke results 2026-04-30" section (added during this session). Three findings folded into T15 scope: orphan card→run pointers, expanded-tile Factors-tab placeholder, matrix `fm-` class prefix.

### Task 15 — Slices 1 to 4 (UNCOMMITTED)

#### Slice 1 — BE helper `cards_powered_by_runs`
- **New file:** `src/tradelab/web/run_cascade.py` (~50 lines)
- **New tests:** `tests/web/test_run_cascade.py` (9 tests)
- Pure function: takes `Iterable[str]` of run_ids and `Iterable[dict]` of cards, returns `[{card_id, base_name, scoring_run_id, status}]` for each card whose `scoring_run_id` is in the set. Defensive on missing `scoring_run_id` (smoke/test cards skipped). Returns only the 4 link fields (no leak of `secret`, `quantity`, etc).
- **API design note:** initial draft took an envelope `{groups: [...]}`; refactored mid-slice to flat `Iterable[dict]` after discovering `group_by_base_name` derives base_name from card_id (not from the stored field). Caller should pass `CardRegistry.all_hydrated().values()`.

#### Slice 2 — BE endpoint `POST /tradelab/runs/preview-delete`
- **Modified:** `src/tradelab/web/handlers.py:902` (+23 lines, in `handle_post_with_status`, after the bulk-delete handler at line 901)
- **New tests:** `tests/web/test_runs_preview_delete.py` (7 tests)
- Read-only. Body `{run_ids: [...]}`, returns bare `{cascade: [{card_id, base_name, scoring_run_id, status}]}` (NOT `_ok()`-wrapped — matches sibling `/tradelab/runs/bulk-delete` convention). Validates `run_ids` is a list (400 if missing/wrong type). Handles missing `cards.json` → empty cascade (200, not 5xx).
- Calls `CardRegistry(cards_path).all_hydrated().values()` then `run_cascade.cards_powered_by_runs`.

#### Slice 3 — FE cascade-aware modal
- **Modified:** `command_center.html` (~+83 lines net)
- **New tests:** added 5 to `tests/web/test_command_center_html.py` (T15 group)
- Modal markup at line 1695 gained `#deleteConfirmCascade` (hidden) + `#deleteConfirmDisableGo` button (hidden by default).
- `showDeleteConfirm` is now **async**: preflights `POST /tradelab/runs/preview-delete`, renders cascade list with each card's `base_name (card_id, status)` when non-empty, reveals Disable+Delete button. Type-DELETE gate now disables BOTH the regular Delete button AND the Disable+Delete button until "DELETE" is typed (count > 5 case).
- New helper `disableAndDelete(runIds, cascade)`: PATCHes each `card_id` to `{status:"disabled"}`, toasts on per-card failures (don't block delete), then calls `performDelete(runIds)`.
- Preflight failure (BE down / network blip) falls through gracefully to no-cascade flow with a console warn — better to allow delete than block on a preflight error.

#### Slice 4 — stale modal copy fix
- **Modified:** same `command_center.html` modal markup
- **New tests:** added 2 to `tests/web/test_command_center_html.py`
- Removed: "The audit DB record is preserved (filtered out of default queries — restorable from the archived_runs table by a developer if needed)." (Stale soft-archive copy from before commit `840fb0f`.)
- Added: "This permanently removes the audit row, deletes the report folder from disk, and appends an entry to `data/deletions.log`. Cannot be undone."

### Test baseline movement (this session)

| After             | tests/web/ total |
|-------------------|-----------------:|
| T14 (handover)    |              455 |
| T15 Slice 1       |              464 |
| T15 Slice 2       |              471 |
| T15 Slices 3 + 4  |          **478** |

All green; zero regressions.

---

## Uncommitted work — full file list

### tradelab repo (`C:\TradingScripts\tradelab\`)

```
modified:
  docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md  (+37 lines  — smoke results section + reverted false P1)
  src/tradelab/web/handlers.py                                          (+23 lines  — preview-delete route)
  tests/web/test_command_center_html.py                                 (+135 lines — 7 T15 static-HTML tests)

new:
  docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md     (slice 0 / discovery)
  src/tradelab/web/run_cascade.py                                       (BE helper)
  tests/web/test_run_cascade.py                                         (9 unit tests)
  tests/web/test_runs_preview_delete.py                                 (7 handler tests)
```

### parent repo (`C:\TradingScripts\`)

```
modified:
  command_center.html  (+83 lines — modal markup, showDeleteConfirm async + cascade, disableAndDelete helper)

untracked (NOT part of T15, can be ignored):
  ngrok_daemon.log
  receiver_daemon.log
```

---

## Slice 5 — exact recipe to finish T15

### 1. Restart the dashboard (user runs)

Kill whatever's on port 8877 + relaunch fresh. The route `/tradelab/runs/preview-delete` is in handlers.py on disk but won't be served until the running process re-imports the module.

```powershell
Get-NetTCPConnection -LocalPort 8877 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep -Seconds 1
$env:PYTHONUTF8="1"
Start-Process powershell -ArgumentList '-NoExit','-Command','python C:\TradingScripts\launch_dashboard.py' -WindowStyle Normal
```

**Watch out for:** the gotcha pattern from this session — second launcher attempt while old one still owns port 8877 results in the new process running but only serving stale code. Verify via curl below before opening the browser.

### 2. BE probe (cheap)

```bash
# Should return 200 with {"cascade": []}
curl -s -X POST http://127.0.0.1:8877/tradelab/runs/preview-delete \
  -H "Content-Type: application/json" -d '{"run_ids":[]}'

# Should return 200 with {"cascade": []} (run not in any card)
curl -s -X POST http://127.0.0.1:8877/tradelab/runs/preview-delete \
  -H "Content-Type: application/json" -d '{"run_ids":["does-not-exist"]}'

# Should return 400 with {"error": "missing run_ids field", ...}
curl -s -X POST http://127.0.0.1:8877/tradelab/runs/preview-delete \
  -H "Content-Type: application/json" -d '{}'
```

If all three return their expected shape (NOT `{"error": "not found"}`), proceed.

### 3. Find a card-tied run for the cascade smoke

```bash
# Walk live cards, extract scoring_run_id values, match against audit DB runs.
curl -s http://127.0.0.1:8877/tradelab/cards | python -c "
import sys, json
d = json.load(sys.stdin)
groups = (d.get('data') or {}).get('groups') or []
for g in groups:
    for c in g.get('cards', []):
        srid = c.get('scoring_run_id')
        if srid:
            print(f\"{c.get('card_id')} → run {srid} (status={c.get('status')})\")
"
```

Pick any run_id from that output — that's a candidate for triggering the Tier 2 modal (single-row cascade) or include in a multi-select for Tier 4.

### 4. Playwright smoke (observe-only — no real deletes)

Memory `feedback_demo_first_workflow.md` and the cost of being wrong (real cards/runs) — **cancel out of every modal**, do not click the destructive buttons.

```text
Navigate http://127.0.0.1:8877/command_center.html → Research tab.

Smoke A — modal copy + preflight (any row):
  - Click trash icon on any pipeline row.
  - Verify modal title says "Delete 1 run(s)?".
  - Verify modal description says "This permanently removes the audit row,
    deletes the report folder from disk, and appends an entry to
    data/deletions.log. Cannot be undone." NOT the old "audit DB record is
    preserved" copy.
  - Network panel should show POST /tradelab/runs/preview-delete fired.
  - Cancel.

Smoke B — Tier 2 (single, cascade present):
  - Click trash on the row whose run_id matches a card's scoring_run_id
    (from step 3 above).
  - Cascade box appears: orange-bordered, lists "<base_name> (<card_id>, <status>)".
  - "Disable card + delete" button (orange) appears between Cancel and Delete.
  - Cancel — do NOT click "Disable card + delete" or "Delete".

Smoke C — Tier 4 (bulk including a card-tied run):
  - Multi-select 3+ pipeline rows, including the card-tied one from step 3.
  - Click "Delete Selected (N)".
  - Cascade box shows the affected card(s).
  - Cancel.

Smoke D — type-DELETE gate (count > 5):
  - Multi-select 6+ rows.
  - Both Delete AND Disable+Delete buttons should be disabled until input
    value === "DELETE". Type, watch them enable. Clear, watch them disable.
  - Cancel.
```

If any smoke fails, fix and re-smoke before commit. Do NOT click through the destructive paths during smoke.

### 5. Commits — separate per repo

Per established pattern (T12-T14 each shipped as separate parent + tradelab commits on the same branch):

```bash
# tradelab repo first (BE + tests)
cd /c/TradingScripts/tradelab
git add src/tradelab/web/run_cascade.py \
        src/tradelab/web/handlers.py \
        tests/web/test_run_cascade.py \
        tests/web/test_runs_preview_delete.py \
        tests/web/test_command_center_html.py \
        docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md \
        docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md
git commit -m "feat(web): /tradelab/runs/preview-delete + cascade helper + Task 15 contract tests"

# parent repo second (FE)
cd /c/TradingScripts
git add command_center.html
git commit -m "feat(command-center): cascade-aware delete modal — Tier 2/4 escalation + stale-copy fix (Task 15)"
```

DO NOT commit `ngrok_daemon.log` or `receiver_daemon.log` from the parent repo — they're runtime artifacts (already gitignored if the gitignore is up-to-date).

After committing, write a follow-up handover doc `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_T15.md` (or merge T15 into the parent handover) with the new test baseline (~478 → it stays ~478, no new tests in slice 5) and any smoke deltas.

---

## Findings worth carrying forward

### Plan-vs-DOM mismatches found in T15 (per `feedback_plan_grep_verification.md`)

The plan body sketched T15 as if delete UX were greenfield. Reality: ~70% of T15 was already shipped in earlier tasks. New mismatches:

| Plan body said | Reality | Action taken |
|---|---|---|
| `#pipeline-tbody` | `#researchPipelineBody` | Used existing |
| `.row-trash[data-action="delete"]` | `.action-btn` (with `title="Delete run"`) | Used existing |
| `.row-cell-actions` | (no such class) | N/A |
| `#delete-selected` | `#pipelineDeleteBtn` | Used existing |
| `openModal/closeModal` (new vanilla helpers) | `#researchDeleteConfirm` modal already in place | Extended existing |
| `inline-confirm` cell replacement (Tier 1) | Modal-based today | KEPT modal for consistency (deferred inline to v3.5) |
| `POST /tradelab/cards/<base_name>/disable` | Doesn't exist; `PATCH /tradelab/cards/<card_id>` does | Used PATCH with `{status:"disabled"}` |
| `cards.some(c => c.id === strategy)` | Cards envelope is nested `{groups:[{base_name, cards:[...]}]}` | New BE helper handles walking |
| `summary.run_count` (runs-summary endpoint) | No such endpoint; not needed for cascade detection | Skipped (Tier 2 trigger is "card has scoring_run_id == this run", simpler) |

The handover update from this session also pinned a NEW gotcha: bulk-delete leniency on unknown ids LOOKS like a bug but is intentional per `tests/web/test_runs_bulk_delete.py:59-81` (idempotent contract). Don't re-file as P1.

### Architectural decisions

- **`run_cascade.py` is a new module, not part of `run_deletion.py`** (Task 5's existing module). Reason: cascade detection is read-only / preview logic, while run_deletion is mutation. Single-responsibility boundary.
- **Endpoint returns bare JSON, not `_ok()`-wrapped.** Matches sibling `/tradelab/runs/bulk-delete` convention. The `_ok()` wrap is only used by GET handlers in the cards/strategies space.
- **`disableAndDelete` does NOT block on per-card PATCH failures.** Toasts a "N/M failed" warning then proceeds with delete. Reason: the user explicitly chose the destructive path; a network blip on the disable shouldn't trap them in modal limbo with a half-committed action.
- **Preflight failure falls through to no-cascade flow** (instead of blocking the delete). Reason: BE down / not-yet-deployed / 404 on `/preview-delete` shouldn't prevent the user from deleting runs. Worst case: user gets the existing pre-T15 experience.

### What did NOT change

- `performDelete(runIds)` — unchanged. Still handles single (DELETE) and bulk (POST /tradelab/runs/bulk-delete).
- Per-row trash icon (`actionsCell` rendering) — unchanged. Still triggers `confirmDeleteRun(runId)` → `showDeleteConfirm([runId])`.
- `#pipelineDeleteBtn` wiring — unchanged. Still calls `showDeleteConfirm(getSelectedRunIds())`.
- DELETE handler in handlers.py — unchanged. Still hard-delete since `840fb0f`.
- bulk-delete handler — unchanged. Still idempotent on unknown ids.
- All other Research-tab features (Live Cards, factor matrix, QS sub-grid, drift sparklines, action buttons, etc.) — unchanged.

### Open questions (all resolved during this session)

- Q1 Tier 1 inline vs modal → KEPT modal (consistency, deferred inline to v3.5).
- Q2 `disable` endpoint → CONFIRMED uses existing `PATCH /tradelab/cards/<card_id>` with `{"status":"disabled"}`.
- Q3 SSE cascade → DEFERRED to T16 (already on the plan).
- Q4 bulk-delete leniency → CONFIRMED intentional; no fix needed.

---

## How to resume (cold-start)

```bash
# 1. State check
cd /c/TradingScripts/tradelab
git status                            # should show the modified + untracked files listed above
git branch --show-current             # feat/research-tab-v3
git log --oneline -3                  # top should be f79e70f

cd /c/TradingScripts
git status                            # M command_center.html (+ daemon logs)
git branch --show-current             # feat/research-tab-v3
git log --oneline -3                  # top should be ce9332e7

# 2. Test baseline check
cd /c/TradingScripts/tradelab
python -m pytest tests/web/ --tb=no -q -p no:cacheprovider
# Expected: 478 passed (~2 min)

# Targeted re-runs:
python -m pytest tests/web/test_run_cascade.py -v             # 9 passed (~0.1s)
python -m pytest tests/web/test_runs_preview_delete.py -v     # 7 passed (~0.1s)
python -m pytest tests/web/test_command_center_html.py -k task15 -v   # 7 passed (~0.1s)

# 3. Read the discovery doc + this handover
cat docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md
cat docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_T15_PRE_SMOKE.md   # this file

# 4. Restart dashboard + smoke (Slice 5 recipe above)

# 5. Commit per repo (commands above)

# 6. Write follow-up handover (or merge into parent handover)
```

---

## Things that could go wrong during Slice 5

1. **Dashboard restart leaves old PID alive on 8877.** Symptom: `/tradelab/runs/preview-delete` returns 404 from JSON envelope despite the route being on disk. Fix: re-run the kill+restart one-liner; verify PID via `Get-NetTCPConnection -LocalPort 8877 -State Listen`. This bit us TWICE this session.
2. **No card has a `scoring_run_id` matching any current run.** Symptom: cascade is always empty in smoke. The smoke turned up `s2_pocket_pivot`'s card pointing at deleted run `fe4757a3-…` (orphan). If only orphan card→run pointers exist, you can't smoke Smoke B/C. Workaround: temporarily inject a card via `cards.json` editing OR call `showDeleteConfirm` with a forged run_id via `browser_evaluate` (synthetic check).
3. **`fetchJSON` swallows non-2xx silently** (Gotcha #16 from prior handover). The new `showDeleteConfirm` checks `Array.isArray(resp && resp.cascade)` defensively. If preflight returns `{error: "..."}` the cascade falls through to empty — correct degradation.
4. **PATCH /tradelab/cards/<id>** requires the card to exist. If the user clicks Disable+Delete on a cascade including an already-deleted card_id (race), the PATCH 404s and gets toasted. Delete still proceeds.
5. **Async `showDeleteConfirm` callers don't await.** `confirmDeleteRun(runId)` and the `pipelineDeleteBtn` click handler both call without `await`. That's fine for fire-and-forget UI invocation — the function will populate the modal asynchronously.

---

## Reference

- Parent handover (T12-T14 + smoke): `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md`
- Discovery / slice 0: `docs/superpowers/notes/2026-04-30-research-v3-task15-discovery.md`
- Plan body (USE WITH CAUTION — heavily stale): `docs/superpowers/plans/2026-04-30-research-tab-v3.md` lines 1819-1968
- Memory references that applied:
  - `feedback_plan_grep_verification.md` — every plan identifier was wrong; verified all before writing
  - `feedback_dependency_order.md` — sliced BE → BE → FE → FE in dependency order
  - `feedback_act_on_recommendations.md` — picked Tier 1 modal / SSE deferral / etc. without re-prompting
  - `feedback_live_smoke_before_next_slice.md` — gating Slice 5 on smoke for exactly this reason
  - `feedback_demo_first_workflow.md` — smoke is observe-only; no real disables/deletes
  - `reference_command_center_arch_lock.md` — vanilla HTML+JS only; no React/builds (followed)
  - `superpowers:test-driven-development` — RED → GREEN → REFACTOR cycle for both BE slices and FE static tests

— end of handover —
