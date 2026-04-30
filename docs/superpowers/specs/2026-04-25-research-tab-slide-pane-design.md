# Research Tab — Table + Slide-in Pane Design (Concept E)

**Date:** 2026-04-25
**Author:** Amit + Claude (brainstorm session 2026-04-25)
**Status:** Draft — pending review
**Branch (proposed):** `feat/research-slide-pane`

**Successor to (in spirit, not in code):**
- v1 shipped 2026-04-22 (`5de629b`) — current live state of `command_center.html`
- Option H Session 3a shipped 2026-04-24 (`cb2e1c6`) — added Score / Accept flow, did NOT touch Research tab layout
- v2 "Research Velocity Bundle" (`2026-04-23-research-tab-v2-design.md`) — drafted, not built
- v2.1 engine-truth tooltip (`2026-04-24-research-tab-v2.1-engine-truth-tooltip.md`) — drafted, not built

**Relationship to the unbuilt v2 specs:** they scoped preflight chips, compare-N tearsheets, and engine-truth tooltips. None of those features depend on layout work; they can ship after this spec without conflict. This spec is layout + lifecycle work that v2 deliberately deferred.

**Source design exploration:** `C:\TradingScripts\RESEARCH_TAB_REDESIGN_CONCEPTS.html` — six concepts evaluated; user selected **Concept E (Table + Slide-in Pane)** with the explicit additional requirement of bulk delete for non-performing runs.

---

## 1. Goal

Make the Research Pipeline the single durable source of truth for every backtest attempt — successful, failed, running, queued, or cancelled — and give the user one-click depth-on-demand via a slide-in detail pane plus first-class delete affordances for sweeping out non-performing runs.

In one sentence: **the table is the home page; the pane is the drill-in; deletion is one click.**

---

## 2. Objectives served (from the brainstorm rubric)

| # | Objective | Resolution |
|---|---|---|
| OBJ 01 | Single source of truth | ✅ Pipeline rows cover all statuses; Active Jobs panel removed |
| OBJ 02 | Survives page reload | ✅ Failed and queued runs persist to audit DB at job start |
| OBJ 03 | Status legible at a glance | ⚠ Pill-only (acceptable trade-off; Concept E doesn't claim spatial status) |
| OBJ 04 | Action without dropdowns | ✅ Letter-buttons replace `Run ▾`; numerics `(1)/(3r)/(3f)` dropped |
| OBJ 05 | Delete is first-class | ✅ Three paths: per-row trash, pane button, bulk-delete with confirm |
| OBJ 06 | Live ↔ Research continuity | ❌ Deferred — Live cards stay as a separate strip; resolving this is full Concept D / Item #1 work |

---

## 3. Non-goals (explicitly deferred)

These were considered and pushed out of scope for this spec to keep the implementation in the ~5-6 day budget:

- **Equity sparkline in the slide-in pane.** Defer to v2.5; pane shows numeric history only.
- **Embedded `dashboard.html` iframe in the pane.** Click-through opens the existing modal as today — no architectural change to dashboard viewing.
- **Promote-to-Live button** (Item #1, Python → live card bridge). Separate work track; pane will leave room for the button but not implement it.
- **Per-strategy SSE routing.** Frontend refreshes on tab focus + on any global SSE event. Good enough for single-user dashboard.
- **Soft-archive / undo-delete.** User explicitly said "get rid of" — going hard delete. Revisit only if data-loss complaints arise.
- **Compare-N-runs visual changes.** Existing checkbox column stays; Compare CLI is unchanged. We add a Delete-N button alongside the (already-deferred) Compare button, not a redesigned Compare flow.
- **Card list UI / receiver hot-reload / toggle ON-OFF buttons** (parked Session 3b items, unrelated to research workflow).
- **Resolution of OBJ 06** (Live cards merged into one rail). Full IDE concept; out of scope here.

---

## 4. User experience

### 4.1 Tab landing

```
┌─ Research tab ────────────────────────────────────────────────┐
│ [Refresh Data] [New Strategy]      Freshness: green · 4h     │
│                                                               │
│ Live Strategies (6)  ◀── unchanged from today                 │
│ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐                                  │
│ │S2│ │S4│ │S7│ │S8│ │S10│ │S12│                                │
│ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘                                  │
│                                                               │
│ Research Pipeline                                             │
│ [strategy ▾] [status ▾] [date ▾] [Reset]      52 · 2 running │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ ☐ Status  Strategy  Verdict  PF  WR  ...  Actions       │   │
│ │ ☐ ▶47%    S2_v3     —        —   —       [Cancel]       │   │
│ │ ☐ QUEUED  S4_test   —        —   —       [Cancel]       │   │
│ │ ☐ DONE    S2        STRONG   1.82 0.62   [D Q Op WF R Rb F 🗑]│
│ │ ☐ FAILED  S7_exp    —        —   —       [stderr Re-run 🗑]  │
│ │ ...                                                       │   │
│ └─────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

The Active Jobs section that previously sat between the Live cards and the Pipeline is **gone**. Running and queued runs are pinned to the top of the Pipeline with status pills + thin in-row progress bars.

### 4.2 Row click → slide-in pane

Click any row body (not on an action button) → a 360px detail pane slides in from the right of the viewport. The table reflows to fit remaining width: columns hide in this priority order until it fits — `Trend` (sparkline) → `Trades` → `WR` → `DD` → `DSR` → `Date`. The `☐ / Status / Strategy / Verdict / PF / Actions` columns always stay visible.

```
┌─ Research tab (with pane open) ─────────────────────┐ ┌────────────────┐
│ Live cards strip (unchanged)                        │ │ × S2          │
│                                                     │ │   STRONG · LIVE│
│ Pipeline (compressed: only Status/Strategy/Verdict/ │ │                │
│   PF/Actions columns visible)                       │ │ Latest run · 2h│
│                                                     │ │   PF 1.82      │
│ ┌────────────────────────────────────────────┐      │ │   WR 0.62      │
│ │ ☐ ▶47% S2_v3 — — [Cancel]                  │      │ │   DD 11.3%     │
│ │ ☐ DONE S2 ◀ STRONG 1.82 [D Q Op WF R Rb F 🗑]│ ◀selected │ DSR 0.42  │
│ │ ☐ DONE S4 MOD 1.31 [...]                   │      │ │   87 trades    │
│ │ ☐ FAILED S7_exp [stderr Re-run 🗑]         │      │ │                │
│ │ ...                                        │      │ │ Last 5 runs:   │
│ └────────────────────────────────────────────┘      │ │  DONE Run 2h   │
│                                                     │ │  DONE WF 1d    │
│                                                     │ │  DONE Rb 2d    │
│                                                     │ │  DONE Full 4d  │
│                                                     │ │  FAIL Run 6d   │
│                                                     │ │                │
│                                                     │ │ [D] [Q] [🗑Del]│
│                                                     │ │ New run:       │
│                                                     │ │ [Op WF R Rb F] │
└─────────────────────────────────────────────────────┘ └────────────────┘
```

**Pane closes on:** × button, click anywhere on table backdrop, ESC keypress.

**URL hash sync:** opening the pane sets `#tab=research&strategy=S2`. F5 reload restores the open pane on the same strategy.

### 4.3 Status column — five states

| Pill | Color | Action set in row |
|---|---|---|
| `RUNNING` + progress bar | blue (animated) | Cancel |
| `QUEUED` | purple | Cancel |
| `DONE` + verdict pill | green | D Q Op WF R Rb F 🗑 |
| `FAILED` | red | stderr Re-run 🗑 |
| `CANCELLED` | grey | Re-run 🗑 |

`stderr` opens a small modal (or expands inline) with the captured `error_tail` from the audit DB.

### 4.4 Delete affordances — the "get rid of non-performing tests" feature

Three paths to delete, designed for different scales:

**A. Single-row delete** — click 🗑 in the Actions column → confirm modal:
> Delete this run? **S2 · Run · 2h ago**
> Folder: `tradelab/reports/s2_2026_04_25_140311/`
> [Cancel] [Delete]

**B. Pane delete** — open the pane on a strategy, click "🗑 Delete this run" in the action bar → same confirm as A but operates on the row that opened the pane.

**C. Bulk delete (the sweep flow)** — the existing per-row checkbox column already exists for "Compare Selected." We add a second button next to it: **"Delete (N) selected"** in red. Workflow for non-performer cleanup:

1. Filter Verdict = `WEAK` or `FAILED`
2. Click the header checkbox to select all visible
3. Click "Delete (N) selected"
4. Confirm modal lists the first 5 folders + count of remainder. **If N > 5, requires typing "DELETE" to confirm.**
5. Backend processes in one bulk request; frontend shows partial-success toast if any failed.

This mirrors the existing FRAGILE type-confirm gate on Score — same proven UX pattern.

### 4.5 Live monitoring without a dedicated panel

Running rows pin to the top of the Pipeline regardless of sort. The header strip shows the live count: `52 runs · 2 running` (clickable to filter to running-only). When a job transitions running → done, the row stays in place with its pill changing color; it does not jump positions.

---

## 5. Data model

### 5.1 Audit DB schema migration

Current `runs` table has columns roughly: `run_id, strategy, verdict, pf, wr, dd, dsr, trades, completed_at, ...`.

**Add two columns:**

```sql
ALTER TABLE runs ADD COLUMN status TEXT NOT NULL DEFAULT 'done';
ALTER TABLE runs ADD COLUMN error_tail TEXT;
ALTER TABLE runs ADD COLUMN started_at TEXT;  -- nullable; populated for queued/running
```

**Migration:** historical rows get `status='done'` (the default). Idempotent — wrap in `PRAGMA user_version` check that bumps from version N to N+1.

**Status enum (validated at write-time, not enforced by DB):**
- `queued` — row inserted at submit, no started_at, no metrics
- `running` — started_at populated, no metrics yet
- `done` — completed_at populated, metrics populated, terminal
- `failed` — completed_at populated, error_tail populated, no metrics, terminal
- `cancelled` — completed_at populated, no metrics, terminal

### 5.2 Job lifecycle write path

| Trigger | DB action |
|---|---|
| User clicks Op/WF/Run/Rb/F (or via launcher CLI) | `INSERT (status='queued', strategy=..., started_at=NULL)` |
| Subprocess actually starts | `UPDATE status='running', started_at=now()` |
| Subprocess exits 0 + writes `backtest_result.json` | `UPDATE status='done', completed_at=now(), pf=..., wr=..., ...` (existing path) |
| Subprocess exits non-zero | `UPDATE status='failed', completed_at=now(), error_tail=<last 4kb of stderr>` |
| User clicks Cancel | `UPDATE status='cancelled', completed_at=now()` + send SIGTERM |
| Server crashes mid-job | On next dashboard startup: orphan `running`/`queued` rows older than 1h → `UPDATE status='cancelled'` (orphan sweep) |

### 5.3 Deletion semantics

**Hard delete only.** No soft-archive flag. Operation:

1. Look up `report_folder` from the run row
2. Recursively delete the folder (`shutil.rmtree`)
3. `DELETE FROM runs WHERE run_id = ?`
4. Both inside a `try/except` — folder deletion failure (e.g., file lock from open `dashboard.html`) returns 409 to client, leaves DB row untouched

Bulk delete is N independent (folder, row) pairs in a loop — partial success is acceptable and reported back per-id.

---

## 6. API surface

### 6.1 New routes (in `tradelab/src/tradelab/web/handlers.py`)

```
DELETE /tradelab/runs/<run_id>
  → 204 No Content       (success: folder + row both removed)
  → 404 Not Found        (run_id unknown)
  → 409 Conflict         (folder removal failed; row preserved)
                         body: {"error": "folder locked", "run_id": "..."}

POST /tradelab/runs/bulk-delete
  body: {"run_ids": ["abc", "def", "ghi"]}
  → 200 OK
    body: {"deleted": ["abc", "def"], "failed": [{"id": "ghi", "reason": "folder locked"}]}

GET /tradelab/strategies/<name>/history?limit=10
  → 200 OK
    body: [
      {"run_id": "...", "kind": "Run", "status": "done", "verdict": "STRONG",
       "pf": 1.82, "completed_at": "2026-04-25T14:03:11Z", "duration_s": 47},
      ...
    ]
```

### 6.2 Modified routes

```
GET /tradelab/runs?status=&strategy=&since=
  Behavior change:
    - default status filter is now "all" (was: only successful runs)
    - response includes new status, error_tail, started_at fields
    - response order: status='running' first, then 'queued', then completed_at desc
```

```
SSE /tradelab/jobs/stream
  Behavior change:
    - emits a job_update event per status transition (queue → run → terminal)
    - frontend updates the matching Pipeline row in place rather than populating a separate jobState Map
    - event payload: {run_id, status, started_at?, completed_at?, error_tail?}
```

### 6.3 Routes that disappear

Nothing removed at the HTTP layer. The `/tradelab/jobs/stream` SSE route stays — its consumer changes.

---

## 7. Frontend changes (`command_center.html`)

### 7.1 Removed

- `<section id="research-job-tracker">` (lines ~693-700) — the entire Active Jobs panel
- The `jobState` Map and its `renderJobTracker()` function (lines ~3347-3402)
- Header count `0 active` etc. — replaced by `52 runs · 2 running` in the Pipeline filter strip

### 7.2 Modified

**Pipeline table markup (lines 728-749):**

- New `<th>Status</th>` column inserted after the existing checkbox column (width:24px at line 733)
- Existing `<th>Run</th>` column (line 743, the `Run ▾` dropdown) **replaced** by `<th>Actions</th>` holding the letter-button strip
- Existing `<th>Trend</th>` column (line 741, sparkline) **kept** but added to the column-hide priority list when pane is open
- Row body click handler (excluding clicks on action buttons / checkbox / sparkline cell) opens slide-in pane
- Running/queued rows pinned-to-top via server-side ordering in `/tradelab/runs`

**Filter strip:**

- "Clear" button (line 724, `id="researchFilterClear"`) **renamed to "Reset filters"** (one-line label fix from item #3D — long-overdue)
- New status dropdown filter added alongside existing strategy/verdict/since filters
- New "Delete (N) selected" button placed alongside existing `id="pipelineCompareBtn"` (line 729). Hidden until ≥1 row checked, red styling. Both Compare and Delete buttons visible simultaneously when ≥2 rows selected

**SSE handler (~line 3422-3454):**

- Rewrite to dispatch `job_update` events to `updatePipelineRow(run_id, payload)` rather than `jobState.jobs.set(...)`
- On reconnect (tab focus), refetch `/tradelab/runs` to pick up updates that fired off-tab

### 7.3 Added

**Slide-in pane component** (~150 LOC HTML + CSS + JS):

- Fixed-position div, anchored right, 360px wide
- Slide-in via CSS `transform: translateX(0)` transition, ~200ms ease
- Click handler registered on Pipeline row body
- Closes on: × button, ESC key, click on table area outside pane
- Hash sync: `window.location.hash = "tab=research&strategy=S2"` on open, parsed on page load
- Content fetched from `GET /tradelab/strategies/<name>/history`
- Last 5 runs rendered as compact rows; clicking one opens the existing dashboard.html / quantstats modal (existing flow)
- "Delete this run" button operates on the run that opened the pane

**Bulk-delete confirm modal:**

- New modal template; reuses the FRAGILE type-confirm pattern from Score
- Lists up to 5 folder paths inline + "and N more"
- Type "DELETE" required if total selected > 5

---

## 8. Edge cases & error handling

| Case | Handling |
|---|---|
| User opens pane on S2; SSE fires for an S2 run completing | Pane refreshes its history list in place from `/tradelab/strategies/S2/history` |
| User clicks Delete on row already deleted by another tab | API returns 404 → toast: "Already deleted, refreshing list" → frontend refetches |
| Folder removal fails (open dashboard.html holds a file lock) | API returns 409 → toast: "Couldn't delete folder. Close any open dashboards for this run and retry." DB row stays |
| Run was queued but server crashed before start | Orphan sweep on next dashboard startup marks it `cancelled` |
| Bulk delete: 3 of 5 succeed | API returns `{deleted: [...], failed: [...]}` → toast: "Deleted 3, 2 failed (file lock)" |
| User closes pane while history fetch is still in-flight | Abort the fetch via AbortController; ignore late response |
| Pane's hash sync conflicts with `#tab=…` from other tabs | Pane only sets `&strategy=…`; reading code is tolerant of param order |
| Compare and Delete buttons both visible at once | Both shown side-by-side when ≥2 selected; both single-action when 1 selected (Compare disabled at N=1) |

---

## 9. Tests

### 9.1 New unit tests (`tests/web/`)

```
test_runs_delete.py
  test_delete_run_removes_folder_and_row
  test_delete_run_404_unknown_id
  test_delete_run_409_when_folder_locked
  test_delete_run_db_row_preserved_when_folder_fails

test_runs_bulk_delete.py
  test_bulk_delete_all_success_returns_full_deleted_list
  test_bulk_delete_partial_returns_both_lists
  test_bulk_delete_empty_request_returns_200_with_empty_lists

test_strategy_history.py
  test_history_returns_last_n_for_strategy
  test_history_includes_running_and_failed_runs
  test_history_404_unknown_strategy

test_runs_status_filter.py
  test_default_returns_all_statuses (regression: was successful-only)
  test_status_filter_running_excludes_done
  test_runs_ordered_running_then_queued_then_completed_desc

test_schema_migration.py
  test_migration_adds_status_column_with_done_default
  test_migration_idempotent_when_run_twice
  test_migration_preserves_existing_metric_values
```

### 9.2 New integration tests

```
test_job_lifecycle_writes_status.py
  test_subprocess_start_writes_running
  test_subprocess_success_writes_done_with_metrics
  test_subprocess_failure_writes_failed_with_error_tail
  test_cancel_writes_cancelled

test_orphan_sweep.py
  test_running_row_older_than_1h_marked_cancelled_on_startup
```

### 9.3 Manual smoke checklist (post-implementation)

- Open Research tab → Active Jobs panel is gone
- Trigger a backtest → row appears with QUEUED then RUNNING then DONE pills
- Click a DONE row → pane slides in showing strategy history
- Click × on pane → table returns to full width
- F5 reload with pane open → pane reopens on same strategy (hash sync)
- Click 🗑 on a row → confirm modal → row disappears + folder gone on disk
- Filter to FAILED → check 3 → click "Delete (3) selected" → confirm → all gone
- Force a folder lock (open dashboard.html in another tab) → click delete → 409 toast, DB row remains
- Cancel a RUNNING job → row becomes CANCELLED, subprocess actually killed

---

## 10. Migration & backward compatibility

- **Schema migration** runs automatically at dashboard startup. Idempotent. Bumps `PRAGMA user_version`.
- **HTML backup:** `command_center.html.bak-2026-04-25` before edits. Pattern matches v1's backup convention.
- **Active Jobs removal is destructive** — no feature flag. Once shipped, the panel is gone. Rollback is a git revert + restore from .bak.
- **No CLI changes** — `tradelab run`, `tradelab optimize`, etc. continue to work identically. The schema migration is invisible to CLI users.

---

## 11. Effort estimate

| Phase | Days |
|---|---|
| Schema migration + status column population on lifecycle events | 1.0 |
| Delete endpoints (single + bulk) + orphan sweep | 1.0 |
| Strategy history endpoint | 0.5 |
| `/tradelab/runs` modifications (status filter, ordering, new fields) | 0.5 |
| Frontend: Active Jobs removal + Status column + action strip | 1.0 |
| Frontend: Slide-in pane (CSS + JS + hash sync) | 1.0 |
| Frontend: Delete affordances + confirm modal | 0.5 |
| Tests (unit + integration) | 0.75 |
| Manual smoke + bug fixes + polish | 0.75 |
| **Total** | **~6 days** |

---

## 12. Open questions for review

1. **Should the bulk-delete confirm gate trigger at N > 5 or N > 10?** Spec says >5; defensible either way.
2. **Should `error_tail` be capped at 4 KB or larger?** 4 KB fits a screenful of Python traceback. Larger uses more DB.
3. **Should the slide-in pane be resizable by the user?** Spec says fixed 360px for v2 — keeps it simple.
4. **Should the Status column be sortable, or always pinned (running > queued > date)?** Spec says always-pinned to prevent running rows scrolling out of view.
5. **Should the orphan sweep threshold be 1h, or driven by a config setting?** Spec says hardcoded 1h.
6. **Should we ship the "Reset filters" rename in this spec or as a separate PR?** Spec bundles it (one-line change).

---

## 13. What this spec does NOT pre-commit

- No commitment to ever building the deferred items in §3 — they each get their own decision later
- No commitment to migrating to a different web framework
- No commitment on Item #1 (Python → live card) — Promote-to-Live is a separate spec
- No commitment on Item #2 (Pine source linter) — separate workstream
- No commitment to merge with v2 / v2.1 unbuilt specs — those can be revisited independently

---

## 14. Files touched (estimated)

```
tradelab/src/tradelab/web/
  handlers.py              CHANGED — 3 new route handlers, 2 modified
  audit_reader.py          CHANGED — query expanded, history function added
  job_lifecycle.py         NEW    — status write path
  schema_migration.py      NEW    — idempotent migration runner
  orphan_sweep.py          NEW    — startup hook

tradelab/src/tradelab/launch_dashboard.py  CHANGED — call orphan_sweep on startup

C:/TradingScripts/command_center.html  CHANGED
  - remove research-job-tracker section
  - remove jobState Map + renderJobTracker
  - add Status column + action strip in Pipeline table
  - add slide-in pane component (HTML + CSS + JS)
  - add bulk-delete button + confirm modal
  - rewire SSE to update Pipeline rows in place
  - rename "Clear" → "Reset filters"

tests/web/
  test_runs_delete.py            NEW
  test_runs_bulk_delete.py       NEW
  test_strategy_history.py       NEW
  test_runs_status_filter.py     NEW
  test_schema_migration.py       NEW
  test_job_lifecycle_writes_status.py  NEW
  test_orphan_sweep.py           NEW
```

---

*End of spec.*
