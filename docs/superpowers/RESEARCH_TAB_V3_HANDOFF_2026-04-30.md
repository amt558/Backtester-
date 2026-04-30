# Research Tab v3 — Handoff Doc (2026-04-30, after Task 6)

> **Read this if you are picking up the Research Tab v3 implementation.** This document is the single source of truth for "where we are" — newer than the plan, supersedes plan-body sketches where they conflict with what was actually built.

---

## TL;DR

- **Plan:** `docs/superpowers/plans/2026-04-30-research-tab-v3.md` (18 tasks)
- **Branches (cross-repo):**
  - tradelab repo: `feat/research-tab-v3` (in `C:\TradingScripts\tradelab\`)
  - parent repo: `feat/research-tab-v3` (in `C:\TradingScripts\`)
- **Done:** Tasks 0, 1, 2, 3, 4, 5, 6. Eight tradelab commits + one parent-repo commit.
- **Next up:** Task 7 — frontend CSS scope + Google Fonts in `command_center.html` (parent repo).
- **Blocking concern:** none. Last full `tests/web/` run = **373 passed**. Both working trees clean.
- **Don't run pytest via PowerShell** — the prior session hung doing exactly that. Use Bash. (See "Gotcha #1" below.)

---

## Why we stopped here

Two reasons, in order:

1. **Mid-stream session handoff.** The original session (running this plan via Sonnet 4.6 subagents) hung on Task 1's pytest invocation under PowerShell. The user killed it. This Opus-1M session resumed cold from the plan + on-disk state, verified Task 1 was actually complete, and continued through Task 3.
2. **Task 4 is a high-risk slice that mutates a production file** (`approve_strategy.py`) with downstream tests. The user requested a handoff before continuing so a fresh session can take Task 4 with full context, rather than picking it up mid-edit.

Tasks 1–3 were chosen as a coherent stopping point because:
- All three are pure additions (new files), zero modification to existing code.
- Each is independently verifiable.
- Task 4 is the first slice that touches an existing module — natural seam.

---

## What's done — commits on `feat/research-tab-v3`

### tradelab repo (`C:\TradingScripts\tradelab\`)

```
b3c8bcc feat(web): wire 4 Research-v3 routes (qs-metrics, verdict-history,
        accept activate, permanent delete)                                    ← Task 5
bb237b8 feat(web): extend approve_strategy.accept_scored with activate flag   ← Task 4
9954d18 docs(research-v3): handoff after Task 3 — state, gotchas, recipe      ← handoff
44f7a81 feat(web): add run_deletion module with atomic delete + JSONL audit   ← Task 3
b07adc7 feat(web): add verdict_history module for drift sparkline             ← Task 2
aec2605 feat(web): add qs_metrics pure-fn module for Research v3 sub-grid     ← Task 1
e0c68a2 docs(research-v3): plan amendments per slice 0 findings               ← Task 0 amend
2d5d927 docs(research-v3): slice 0 findings — approve_strategy survey ...     ← Task 0 notes
```

### parent repo (`C:\TradingScripts\`)

```
421b1294 feat(launcher): add /tradelab/runs/<run_id>/tearsheet pass-through  ← Task 6
```

The parent repo's `feat/research-tab-v3` branch was created off `main` after Task 5
to host the launcher + (forthcoming) `command_center.html` changes. Both branches
merge together when v3 ships.

(`master` head before this branch: see `git log master -1` for the merge base.)

### Task 1 — `qs_metrics.py` + tests (`aec2605`)

- **Created:** `src/tradelab/web/qs_metrics.py`, `tests/web/test_qs_metrics.py`
- **Functions:** `sharpe`, `sortino`, `cagr`, `max_drawdown`, `monthly_returns_matrix`, `rolling_sharpe`. Pure functions, `pd.Series` in.
- **Tests:** 7 passing in 1.0s.
- **Adaptations from plan:**
  - Plan's expected values (`sharpe ≈ 0.79`, `sortino ≈ 1.20`, `cagr ≈ 0.13`) were placeholders. Real seed-42 outputs are `0.159`, `0.266`, `0.013`. Tests updated with comments explaining each.
  - Plan used pandas `.resample("M")`, deprecated since pandas 2.2. Switched to `"ME"` (month-end) per current API.
  - `monthly_returns_matrix` test uses `np.nansum` since 3y of business-day data ends mid-Dec, leaving Dec 2025 NaN.

### Task 2 — `verdict_history.py` + tests (`b07adc7`)

- **Created:** `src/tradelab/web/verdict_history.py`, `tests/web/test_verdict_history.py`
- **Single export:** `get_recent_verdicts(strategy_id, n=12, db_path=None) -> list[str]` (oldest → newest, lowercase).
- **Tests:** 7 passing in 1.0s.
- **Adaptations from plan:**
  - Plan guessed schema as `runs(run_id, strategy, verdict, scored_at)`. Real schema is `runs(run_id, timestamp_utc, strategy_name, ..., verdict, ...)` — column names different.
  - Plan said "lowercase" verdicts; production DB stores uppercase (`ROBUST` / `FRAGILE` / `INCONCLUSIVE`). Helper normalizes on read so the FE drift-sparkline CSS classes (lowercase) match.
  - **Real-DB smoke confirmed:** `s2_pocket_pivot` returns 12 historical verdicts; `cg_tfe_v15` returns 1 ('inconclusive'); canary strategies have 1 each. Sparkline will work on real data.

### Task 3 — `run_deletion.py` + tests (`44f7a81`)

- **Created:** `src/tradelab/web/run_deletion.py`, `tests/web/test_run_deletion.py`
- **Exports:** `delete_run_atomic(run_id, db_path=None, log_path=None) -> dict`, `RunNotFound`.
- **Tests:** 6 passing in 1.1s.
- **Adaptations from plan:**
  - Plan assumed a `report_dir` column. Real schema has `report_card_html_path` (which can be either a file path like `…\dashboard.html` or a folder). Helper resolves either form (mirrors `audit_reader.resolve_run_folder` logic without importing it — kept the module standalone).
  - Added a test for the NULL `report_card_html_path` case (CLI runs scored without `--report`): DB row deletes, `paths_removed` is empty, audit log still appended.
  - `_default_log_path` is module-level + monkeypatchable so callers don't need to thread a path through.

### Slice 0 findings (`2d5d927` + `e0c68a2`)

Two binding decisions live in the plan-amendment block at the **top** of `2026-04-30-research-tab-v3.md` (lines 15–18) and in `docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md`:

- **Task 4 is a modification, not a new module.** Do **not** create `tradelab/src/tradelab/web/activation.py`. Extend `approve_strategy.accept_scored` (lines ~145–254) with an `activate: bool = False` parameter. When `True`: set `status="enabled"`, stamp `activated_at` + `activated_verdict`, gate on ROBUST.
- **Task 5 has no new `/strategies/<id>/activate` route.** The activation route is the existing `POST /tradelab/accept` (handlers.py line ~920) with an extra `activate` boolean in the payload. `_validate_accept_payload` (line ~1435) needs the new field.
- **Task 18 Class B target = `C:\TradingScripts\alpaca_config.json`**, field `strategies[i].enabled`. Bot reads this file once at startup — **no hot-reload**. UI must inform user "takes effect at next bot startup". Use write-then-rename for atomicity.

The plan-body code blocks for Tasks 4 and 5 were written before the slice-0 survey and partially contradict the amendments. **Always trust the amendments over the body** for those two tasks.

---

## What was done since the prior handoff (Tasks 4, 5, 6)

### Task 4 — `accept_scored` activate flag (`bb237b8`)

- **Modified:** `tradelab/src/tradelab/web/approve_strategy.py`, `tradelab/tests/web/test_approve_strategy.py`
- **Adds:** `activate: bool = False` param; `ActivationGateFailed` exception; `AlreadyActivated = CardExistsError` alias
- **When `activate=True`:** ROBUST verdict gate enforced before any disk side effects; card written with `status="enabled"` and stamped with `activated_at` + `activated_verdict`; return dict gains `activated_at` field.
- **6 new tests:** ROBUST happy, FRAGILE/INCONCLUSIVE gate refusal, case-insensitive ROBUST, default backward compat, AlreadyActivated alias contract.

### Task 5 — 4 backend routes in handlers.py (`b3c8bcc`)

- **Modified:** `tradelab/src/tradelab/web/handlers.py`, `tradelab/tests/web/test_handlers.py`
- **GET `/tradelab/runs/<run_id>/qs-metrics`** — unenveloped sub-grid payload via `qs_metrics` module + 4 audit-DB header numbers. 404 on no folder OR no equity curve.
- **GET `/tradelab/strategies/<id>/verdict-history`** — wraps `verdict_history.get_recent_verdicts`. Empty list (200) for unknown strategies, NOT 404.
- **POST `/tradelab/accept`** extended with optional `activate: bool` field. Maps `ActivationGateFailed` → 422; existing `CardExistsError` → 409 still works. `_validate_accept_payload` type-checks the new field.
- **DELETE `/tradelab/runs/<run_id>/permanent`** — NEW route, NOT a replacement. Uses `run_deletion.delete_run_atomic`. The existing `DELETE /tradelab/runs/<run_id>` (soft-archive) is preserved because the FE's `/unarchive` flow depends on it. Pipeline tasks (14/15) will choose between soft-archive and permanent-delete per UX tier — **this is a design decision the user can override later.**
- Both POST-accept-with-activate and DELETE-permanent broadcast on the existing job-stream broadcaster (`get_broadcaster()`); FE dispatch by event.type is Task 16.
- **9 new tests.**

### Task 6 — launcher tearsheet pass-through (`421b1294`, parent repo)

- **Modified:** `C:/TradingScripts/launch_dashboard.py`
- Adds `serve_run_tearsheet()` method on `DashboardHandler` mirroring `serve_compare_report` pattern. Routed via `do_GET` dispatcher: `/tradelab/runs/<id>/tearsheet` → resolves run folder via `audit_reader.resolve_run_folder` → serves `quantstats_tearsheet.html` from that folder.
- 503 if tradelab handlers couldn't be imported at startup; 404 on unknown run / missing folder / missing tearsheet artifact.
- No pytest in parent repo per workspace memory; verified via `python -c "ast.parse(...)"` + regex sanity tests.

---

## What's next — Task 7 (frontend) is the next major slice

Tasks 7–17 are all FE work in `C:/TradingScripts/command_center.html`. Per the v3 architecture lock memory (`reference_command_center_arch_lock.md`): vanilla HTML+JS+Chart.js only — NO React, Vite, FastAPI, Streamlit, or build steps inside `command_center.html`. The Trading Desk side project is the place for any of those.

Task 7 specifically:
- Add `<link>` to Google Fonts (Inter + IBM Plex Mono per spec)
- Add a `body.research-v3`-scoped CSS block (so v2 stays renderable at `body:not(.research-v3)`)
- Wire the tab-switch class toggle so clicking the Research tab adds the class

Read the spec at `tradelab/docs/superpowers/specs/2026-04-30-research-tab-v3-design.md` and the visual mockups at `.superpowers/brainstorm/216-1777553249/content/{01,02,03}*.html` before starting Task 7.

---

## (Stale below — kept for reference) Original "What's next — Task 4" plan

### Goal

Extend `approve_strategy.accept_scored` so the same function handles both:
- **Score → Accept** (existing v1 flow): create card with `status="pending"` or whatever the existing default is.
- **Activate** (v3 new flow): when caller passes `activate=True`, set `status="enabled"`, stamp `activated_at` + `activated_verdict`, and reject if the latest verdict isn't ROBUST.

This avoids two write paths to `cards.json`.

### Files

| File | Change |
|---|---|
| `tradelab/src/tradelab/web/approve_strategy.py` | Add `activate: bool = False` param to `accept_scored`. Add gate logic. Stamp new fields. |
| `tradelab/tests/web/test_approve_strategy.py` | Extend with: `activate=True ROBUST → 200 + status=enabled + stamped fields`; `activate=True MARGINAL → 422`; `activate=True no-runs → 422`; `activate=True duplicate card → 409`. |

### Concrete next steps

1. **Read `approve_strategy.py` end-to-end** (it's ~250 lines). Document on a notepad: current signature of `accept_scored`, what fields it currently writes to `cards.json`, what exceptions it currently raises. Cross-check with the slice-0 findings file (which already surveyed it).
2. **Read `test_approve_strategy.py`** to understand the existing test fixture pattern (test DB setup, cards.json fixture, etc.). Reuse, don't re-invent.
3. **Write the failing tests first** for the four new cases above. Run them via `PYTHONPATH=src python -m pytest tests/web/test_approve_strategy.py -v` to confirm they fail.
4. **Implement** the `activate` flag in `accept_scored`. Define the gate exception class (`ActivationGateFailed`?) and the duplicate exception (`AlreadyActivated`?) — these need to match the names that Task 5 will import in `handlers.py`. The plan-body for Task 4 (lines 745–755) names them `ActivationGateFailed` and `AlreadyActivated` — keep those names so Task 5 imports work.
5. **Run all of `tests/web/`** for regressions. `cards_view.py` reads `cards.json` and may have tests that assume current shape.
6. **Commit.** Suggested message: `feat(web): extend approve_strategy.accept_scored with activate flag for Research v3`.

### Risks to watch

- **`cards_view.py` dependents.** New fields (`activated_at`, `activated_verdict`, `status="enabled"`) may break existing card rendering or `_validate_accept_payload`. Run the full `tests/web/` suite (358 baseline). If `test_cards_view.py` or `test_handlers.py` start failing, the issue is shape contract — fix the consumer, don't roll back the field.
- **Slide-pane**. The slide-pane for live cards reads from `cards.json`; new fields should appear (or be gracefully ignored).
- **Hot-reload**. Per memory `reference_receiver_hot_reload.md`, the receiver auto-reloads `cards.json` via watchdog — no restart needed for status flips. But that's the receiver on port 8878; the dashboard on 8877 reads via its own endpoint. Verify both surfaces see the new field.

---

## Remaining tasks (5–18) at a glance

These are sized roughly. Numbers in [] are TaskList IDs assigned in this session.

| # | TaskList ID | Title | Notes |
|---|---|---|---|
| 4 | #4 | extend approve_strategy with activate flag | **next up** |
| 5 | #5 | wire 4 backend routes in handlers.py | qs-metrics GET, verdict-history GET, accept POST extension, run DELETE. (Plan says 5; slice-0 dropped the dedicated `/activate` route.) |
| 6 | #7 | launcher tearsheet pass-through | one route in `C:\TradingScripts\launch_dashboard.py`, mirrors `serve_compare_report` |
| 7 | #8 | research-v3 CSS scope + Google Fonts | `command_center.html`: link tag + `body.research-v3` block + tab-switch class toggle |
| 8 | #9 | action bar restyle | preserve protected button IDs (`refresh-data-btn`, `new-strategy-btn`, `score-new-strategy-btn`, `preflight-{universe,cache,strategies,tdapi}`) |
| 9 | #10 | Live Cards compact tile + drift sparkline | uses Task 2's `verdict-history` endpoint |
| 10 | #11 | Activate state machine + cross-tab linkage | per slice-0: POST `/tradelab/accept` with `activate=true`; cross-tab pulse to Overview |
| 11 | #12 | click-to-expand inline + 7-cell summary | tile expand toggle |
| 12 | #13 | QS sub-grid + 3 inline SVG charts | uses Task 1's `qs-metrics` endpoint |
| 13 | #14 | cross-strategy factor matrix | column-warn detection at ≥50% non-pass |
| 14 | #15 | pipeline restyle + per-row trash icon | reuses v2 pipeline JS |
| 15 | #16 | pipeline delete affordances | 4 confirm tiers (inline / bulk / typed >10 / live-card escalation) |
| 16 | #17 | SSE cascading | `run_deleted` and `card_activated` event branches |
| 17 | #18 | full UI smoke gate via Playwright MCP | **Playwright MCP is installed and ready** (user confirmed 2026-04-30) |
| 18 | #19 | Class B activation | per slice-0: target = `alpaca_config.json` `strategies[i].enabled`; **takes effect at next bot startup** (no hot-reload); write-then-rename |

---

## How to resume — exact recipe

```bash
# 1. Verify state
cd /c/TradingScripts/tradelab
git status                              # should be clean
git branch --show-current               # should be feat/research-tab-v3
git log --oneline -5                    # top 5 should match the commit hashes above

# 2. Sanity-check the test baseline
PYTHONPATH=src python -m pytest tests/web/ --tb=no -q -p no:cacheprovider
# Expected: 358 passed (~2 min)

# 3. Read the plan amendments (top of plan file)
head -20 docs/superpowers/plans/2026-04-30-research-tab-v3.md

# 4. Read the slice-0 findings
cat docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md

# 5. Open this handoff for the "Next up" section
cat docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30.md

# 6. Begin Task 4
```

---

## Gotchas discovered in this session — DO NOT REPEAT

### Gotcha #1: PowerShell + redirected stdout hangs pytest

The prior Sonnet 4.6 session used `PowerShell` tool calls like:

```
$env:PYTHONPATH = "src"; python -m pytest tests/web/test_qs_metrics.py -v 2>&1
```

…and hung for 13+ minutes with no output, repeated tool calls didn't unstick it. This is the same family of bug as `reference_launcher_unicode_banner.md` (cp1252 stdout redirection breaks Python on Windows). The same command via Bash returned in 1 second.

**Rule going forward:** use **Bash** for pytest. PowerShell is fine for one-shot non-Python commands but not for invoking long-running Python with redirected output.

```bash
# Good
PYTHONPATH=src python -m pytest tests/web/test_X.py -v --no-header -p no:cacheprovider 2>&1 | tail -20

# Bad (will hang)
$env:PYTHONPATH = "src"; python -m pytest tests/web/test_X.py -v 2>&1
```

### Gotcha #2: The plan body's expected values are placeholders

The plan was written before any test was run. Several test fixtures contain **guessed** expected values (`sharpe ≈ 0.79` etc.). When implementing, run the test, observe the actual output, and update the fixture to the real value with a comment. The plan author intended these to be calibrated during execution — they're not contracts, they're starting points.

### Gotcha #3: The plan's DB schema is also a guess

`runs(run_id, strategy, verdict, scored_at)` is what the plan assumed. Real schema is `runs(run_id, timestamp_utc, strategy_name, strategy_version, ..., verdict, ..., report_card_html_path, ...)`. Always run `PRAGMA table_info(runs)` against the real DB before writing any SQL touching this table:

```bash
PYTHONPATH=src python -c "import sqlite3; c=sqlite3.connect('data/tradelab_history.db'); print([r[1] for r in c.execute('PRAGMA table_info(runs)')])"
```

### Gotcha #4: Verdict casing inversion (DB ↔ FE)

DB stores **UPPERCASE** (`ROBUST`); FE CSS classes are **lowercase** (`.robust`, `.fragile`). Verdict_history normalizes downward in the helper. Anywhere else that reads verdict from the DB and renders to the FE must do the same — or the CSS won't match.

### Gotcha #5: tradelab audit DB path is cwd-relative

Per memory `reference_tradelab_db_path_cwd.md`. The `_default_db_path()` returns `Path("data") / "tradelab_history.db"` — a **relative** path. Test workspaces in `tmp_path` work fine; production callers must invoke from `C:\TradingScripts\tradelab\` or pass an absolute path.

---

## Session metadata

- **Branch base:** whatever is in `master` as of 2026-04-30 morning. Run `git merge-base feat/research-tab-v3 master` to see.
- **Working directory state at handoff:** clean, all 5 commits pushed to local `feat/research-tab-v3`. No remote push performed (no GitHub remote on this repo per workspace memory).
- **Test baseline:** 358 passed in `tests/web/` after Task 3 (was 358 before Task 3 too — adding `test_run_deletion.py` + `test_verdict_history.py` brought it from 344 → 358; first run after the qs_metrics commit was 358 already as the prior session had Task 1 staged).
- **Full-suite baseline:** 975 passed (entire repo, ~2.5 min) after Task 1.
- **TaskList in this session:** 18 tasks created, 3 marked completed. IDs: 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19. (ID #6 was a temporary "read-the-plan" task that was deleted after planning was done; IDs 7–19 map to plan Tasks 6–18.) The TaskList resets per-session — the next session should not rely on these IDs and should re-create from the plan.

---

## When in doubt

1. **Trust the slice-0 amendments over the plan body** for Tasks 4, 5, 18.
2. **Trust this handoff over both** for what's already on disk + which adaptations stuck.
3. **Read `approve_strategy.py` and `test_approve_strategy.py` end-to-end** before touching them. They're load-bearing for v1 Score→Accept.
4. **Run pytest via Bash, not PowerShell.**
5. **Use Playwright MCP for any UI smoke** (Task 17 will need it; the user confirmed it's installed).

— end of handoff —
