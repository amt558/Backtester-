---
date: 2026-04-30
branch: feat/research-tab-v3
task: 15 — Pipeline delete affordances
status: discovery (slice 0)
supersedes: plan body lines 1819-1968 where they conflict
---

# Task 15 — Discovery & plan amendments

## TL;DR

The plan body sketches "4 confirm tiers + cascading" as if delete UX is greenfield. **Reality: most of it already exists.** A prior task (T12 or earlier) shipped:

- Modal `#researchDeleteConfirm` with type-DELETE gate (count > 5)
- `showDeleteConfirm(runIds)` orchestrator
- `performDelete(runIds)` calling `DELETE /tradelab/runs/<id>` (single) or `POST /tradelab/runs/bulk-delete` (bulk)
- `getSelectedRunIds()` + `updateSelectionButtons()` driving `pipelineCompareBtn` / `pipelineDeleteBtn` visibility
- Per-row trash icon `.action-btn` triggering single-run flow

**T15's actual NEW scope is narrower**: card-aware escalation (Tiers 2 & 4) before delete, plus stale modal copy fix, plus a BE helper to find cards powered by a given set of run_ids.

---

## Plan body vs. real DOM/JS

Per `feedback_plan_grep_verification.md` and Gotcha #20 (pipeline JS contract is fragile), grep before pasting.

| Plan body identifier | Reality | Action |
|---|---|---|
| `#pipeline-tbody` | `#researchPipelineBody` | Use existing |
| `.row-trash[data-action="delete"]` | `.action-btn` (with `title="Delete run"`) | Use existing |
| `.row-cell-actions` | (not present — actions cell has no class) | Layer over existing |
| `#delete-selected` | `#pipelineDeleteBtn` | Use existing |
| `tr.dataset.runId` | TBD — verify what data-* attrs exist on rows | Verify in slice 1 |
| `tr.dataset.strategy` | TBD | Verify in slice 1 |
| `openModal/closeModal` (new vanilla helpers) | `#researchDeleteConfirm` already in place | Extend existing modal, don't add helpers |
| `inline-confirm` cell replacement (Tier 1) | Currently uses MODAL for single-row too | Decision: keep modal for consistency, OR add inline as plan suggests |

---

## Already implemented (do NOT redo)

| Capability | Where | Notes |
|---|---|---|
| Modal `#researchDeleteConfirm` | `command_center.html:1695-1718` | Header, list-of-5 + "and N more", type-DELETE gate when > 5, Cancel/Delete buttons |
| `showDeleteConfirm(runIds)` | `command_center.html:7079-7108` | Opens modal, wires goBtn → performDelete |
| `performDelete(runIds)` | `command_center.html:7110-7148` | Single → `DELETE /tradelab/runs/<id>` (handles 204/404/error), bulk → `POST /tradelab/runs/bulk-delete` |
| `getSelectedRunIds()` | `command_center.html:7153-7157` | Reads `:checked` checkboxes from `#researchPipelineBody` |
| `updateSelectionButtons()` | `command_center.html:7159-7171` | Toggles Compare (>=2) and Delete (>=1) button visibility |
| Per-row `.action-btn` trash icon | (renderPipelineRows) | Already triggers `showDeleteConfirm([runId])` per code at line ~7075 |
| `DELETE /tradelab/runs/<id>` | `handlers.py` (BE) | Hard-delete since `840fb0f` |
| `POST /tradelab/runs/bulk-delete` | `handlers.py` (BE) | Returns `{deleted: [...], failed: [...]}` |

---

## Actually missing — T15's real scope

1. **Card-aware escalation BEFORE delete.** Today, `performDelete` fires `DELETE` blindly. If a run is the `scoring_run_id` of a live card, deleting it orphans the card (verified in smoke: s2_pocket_pivot's card already points at deleted run `fe4757a3-…`). T15 should detect and surface this PRE-delete:
   - **Tier 2 (single, has live card):** "This run is the basis for live card X. Disable card + delete? / Delete anyway?"
   - **Tier 4 (bulk, includes runs that power cards):** Danger modal listing affected cards with cascade preview.
   - Tier 1 (single, no card) and Tier 3 (bulk, no cards) keep current flow.

2. **Stale modal copy.** `command_center.html:1702-1706` reads:
   > "The report folder will be removed from disk. The audit DB record is preserved (filtered out of default queries — restorable from the archived_runs table by a developer if needed)."
   
   This describes the OLD soft-archive semantics. Since `840fb0f` flipped DELETE to hard-delete, the audit row IS removed too. Update copy to reflect reality.

3. **No BE helper to find cards by run_id.** Grep returns nothing for `cards_powered_by_run` / `find_cards.*run` / `cards_for_run`. The handler already walks `card.scoring_run_id` inline at `handlers.py:548, 612, 615` (filtering self-correlation in verdict-history). Extract a shared helper in `cards` module: `cards_powered_by_runs(run_ids: set[str]) -> list[CardLink]`.

4. **Cards envelope shape (verified live):** `{error: ..., data: {groups: [{base_name, cards: [...]}], total_cards, total_enabled}}`. Each card has `card_id`, sometimes `scoring_run_id` (only Pine-script approval cards do — smoke test cards don't). Defensive walking required.

5. **Orphan-card detection (bonus).** Smoke turned up s2_pocket_pivot pointing at a deleted run. As part of T15's BE helper, also detect orphans (`scoring_run_id` not in audit DB) — surface them in a dimmed/warning state in the matrix or live cards. Deferred sub-task; not blocking T15 launch.

---

## Non-issue (initially looked like a bug, confirmed intentional)

**Bulk-delete leniency on unknown ids is BY DESIGN.** Initial probe showed `{"deleted": ["__nonexistent__"]}` for a fake run_id. Looked like a bug at first, but `tests/web/test_runs_bulk_delete.py:59-81` (`test_bulk_delete_unknown_id_treated_as_success_idempotent`) documents the rationale: "prior soft-archive contract returned 404 → failed, but with stale FE state that produced spurious 'run not found' errors on resources the user already knew were gone." Hard-delete + idempotency is the intentional v3 contract. **Not a T15 issue, not a P1.** Lesson: grep tests before filing bugs (per `feedback_plan_grep_verification.md`).

---

## Proposed slice plan (amended from plan body)

### Slice 1 — BE: card-by-runs helper
- Add `tradelab.web.cards.cards_powered_by_runs(run_ids: set[str], cards_data: dict) -> list[dict]` returning `[{card_id, base_name, scoring_run_id}]` for each card whose `scoring_run_id` is in `run_ids`.
- Pure function (takes already-fetched cards data); easy to unit test.
- Add 4-5 unit tests: empty input, no matches, single match, multiple matches across groups, defensive on missing `scoring_run_id`.

### Slice 2 — BE: delete-preview endpoint
- New route: `POST /tradelab/runs/preview-delete` body `{run_ids: [...]}` → `{cascade: [{card_id, base_name, scoring_run_id, status}], orphan: [run_ids not in audit DB]}`.
- Pure read-only — no mutation. Used by FE to decide which tier modal to show.
- Add 4 handler tests.

### Slice 3 — FE: tiered escalation
- Refactor `showDeleteConfirm(runIds)` to first fetch `/tradelab/runs/preview-delete`.
- If cascade is empty → existing flow (Tier 1 / Tier 3).
- If cascade non-empty + 1 run → Tier 2 modal (escalation w/ "Disable card + delete" option).
- If cascade non-empty + bulk → Tier 4 modal (danger w/ affected card list).
- Add 8-10 static-HTML tests pinning new modal markup + handlers.

### Slice 4 — FE: fix stale modal copy
- One-line replacement of the audit-DB-preservation paragraph with hard-delete reality.
- Update or add 1 static-HTML test pinning the new copy.

### Slice 5 — Live-BE smoke + commit
- Restart dashboard.
- Playwright smoke: select a row whose run is NOT a card basis → Tier 1 modal (existing). Select s2_pocket_pivot's run (or similar card-tied run) → Tier 2 escalation modal. Multi-select → Tier 3 / Tier 4 based on cascade.
- Commit each repo separately per established pattern.

---

## Open questions for user

1. **Tier 1 inline vs modal:** Plan body says inline confirm in cell. Current code uses modal for single-row too. Cost of changing to inline: minor; benefit: faster UX. **Recommendation: KEEP modal for now (consistency), defer inline to v3.5**. Override if you want inline.

2. **`disable-and-delete` action in Tier 2:** Plan body proposes a "Disable card + Delete" button. **CONFIRMED 2026-04-30:** `POST /tradelab/cards/<base_name>/disable` does NOT exist, but `PATCH /tradelab/cards/<card_id>` with `{"status": "disabled"}` does (handlers.py:1147-1162, validation at 1314-1336). Tier 2 should PATCH each affected card_id → disabled, then DELETE the run. The BE helper must return `card_id` (not just `base_name`) so the FE can PATCH the right resource.

3. **SSE cascade broadcast (Task 16's job):** Plan comment in `performDelete` says "// SSE will cascade tile/matrix updates (Task 16)". For T15, after delete we currently call `refreshPipeline()` but don't refresh matrix or live cards. **Decision: leave matrix/cards stale-until-refresh for T15; let T16 fix this with SSE.** Otherwise scope creep.

4. **Bulk-delete leniency:** File separately as P1 in handover, or wait for user to decide?

---

## References

- Plan body: `docs/superpowers/plans/2026-04-30-research-tab-v3.md` lines 1819-1968 (use this doc when they conflict)
- Handover: `RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_14.md` Task 15 preview section
- Memory: `feedback_plan_grep_verification.md`, `feedback_dependency_order.md`, `reference_command_center_arch_lock.md` (vanilla HTML+JS only)
- Gotchas applied: #20 (don't rename pipeline IDs), #16 (fetchJSON returns body even on 404), #19 (signal name set)
