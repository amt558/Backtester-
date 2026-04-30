# Research Tab v3 — Handover Doc (2026-04-30, after Task 8)

> **Read this if you are picking up the Research Tab v3 implementation.** This document is the single source of truth for "where we are." It supersedes the prior handoff doc (`RESEARCH_TAB_V3_HANDOFF_2026-04-30.md`, kept on disk for the Tasks 1–6 history). Newer than the plan; trust this over plan-body sketches when they conflict.

---

## TL;DR

- **Plan:** `docs/superpowers/plans/2026-04-30-research-tab-v3.md` (18 tasks)
- **Spec:** `docs/superpowers/specs/2026-04-30-research-tab-v3-design.md`
- **Visual mockups:** `.superpowers/brainstorm/216-1777553249/content/{01,02,03}*.html` (#3 is the assembled reference)
- **Branches (cross-repo):**
  - tradelab repo: `feat/research-tab-v3` at `C:\TradingScripts\tradelab\`
  - parent repo: `feat/research-tab-v3` at `C:\TradingScripts\`
- **Done:** Tasks 0, 1, 2, 3, 4, 5, 6, 7, 8 (9 plan tasks + slice-0). 13 tradelab commits + 3 parent-repo commits.
- **Next up:** Task 9 — Live Cards compact tile rendering (replaces the existing `#researchLiveCards` skeleton block with real v3 tiles using the verdict-history endpoint from Task 2 + `.tile`/`.drift`/`.kpi`/`.activate` styles already in the v3 scope).
- **Blocking concern:** none. Last full `tests/web/` run = **379 passed**. Both working trees clean. Playwright smoke gate passed after Task 8.
- **Don't run pytest via PowerShell** — the prior session hung. Use Bash. (See "Gotcha #1" below.)

---

## Why we stopped at Task 8

User explicitly asked: *"continue stop at task 8 create .md handover file make and through"*. Tasks 7 and 8 together turn the dashboard's Research tab from "v2 cool-dark Inter" into "v3 warm-dark editorial with Fraunces/Geist/JetBrains Mono and the new action bar." That's a coherent visual milestone — anyone opening the dashboard now sees the v3 styling on the Research tab while every other tab is unchanged. Task 9 starts the next milestone (Live Cards), which is bigger and best done in one focused session.

---

## What's done — full commit log

### tradelab repo (`C:\TradingScripts\tradelab\` on `feat/research-tab-v3`)

```
866cb0a test(web): assert action-bar contract for Task 8                       ← Task 8 tests
5e61dd7 test(web): assert research-v3 scope contract (Task 7)                  ← Task 7 tests
b48e157 docs(research-v3): handoff reflects DELETE semantic flip (840fb0f)
840fb0f refactor(web): flip DELETE /tradelab/runs/<id> from soft-archive
        to hard-delete (drops /permanent suffix; idempotent on unknown)         ← Task 5 fixup
5a8b103 docs(research-v3): handoff updated through Task 6
b3c8bcc feat(web): wire 4 Research-v3 routes (qs-metrics, verdict-history,
        accept activate, permanent delete)                                      ← Task 5 (initial)
bb237b8 feat(web): extend approve_strategy.accept_scored with activate flag    ← Task 4
9954d18 docs(research-v3): handoff after Task 3 — state, gotchas, recipe
44f7a81 feat(web): add run_deletion module with atomic delete + JSONL audit    ← Task 3
b07adc7 feat(web): add verdict_history module for drift sparkline               ← Task 2
aec2605 feat(web): add qs_metrics pure-fn module for Research v3 sub-grid       ← Task 1
e0c68a2 docs(research-v3): plan amendments per slice 0 findings                 ← Task 0 amend
2d5d927 docs(research-v3): slice 0 findings — approve_strategy survey + ...     ← Task 0 notes
```

### parent repo (`C:\TradingScripts\` on `feat/research-tab-v3`)

```
a6023a10 feat(command-center): research-v3 action bar — restyle +
         calibration trust + canary icon (Task 8)
4c1906d7 feat(command-center): add research-v3 CSS scope +
         editorial Google Fonts (Task 7)
421b1294 feat(launcher): add /tradelab/runs/<run_id>/tearsheet pass-through    ← Task 6
```

The parent repo's `feat/research-tab-v3` branch was created off `main` after Task 5 to host launcher + `command_center.html` changes. Both branches merge together when v3 ships.

---

## Per-task summaries (Tasks 1–8)

### Task 1 — `qs_metrics.py` + tests (`aec2605`)

- New module `src/tradelab/web/qs_metrics.py` with pure functions: `sharpe`, `sortino`, `cagr`, `max_drawdown`, `monthly_returns_matrix`, `rolling_sharpe`. All take `pd.Series` of daily returns.
- 7 tests passing.
- **Adaptation from plan:** placeholder expected values (e.g. `sharpe ≈ 0.79`) replaced with actual seed-42 outputs. pandas `.resample("M")` switched to `"ME"` (deprecated in 2.2+).

### Task 2 — `verdict_history.py` + tests (`b07adc7`)

- `get_recent_verdicts(strategy_id, n=12, db_path=None) -> list[str]` for the drift sparkline. Returns lowercase verdicts oldest→newest.
- 7 tests passing.
- **Adaptation:** plan guessed schema as `runs(strategy, verdict, scored_at)`. Real schema is `runs(run_id, timestamp_utc, strategy_name, ..., verdict, ...)`. Plan said "lowercase" verdicts but DB stores uppercase (`ROBUST`); helper normalizes on read so FE CSS classes (lowercase) match. Real-DB smoke confirmed `s2_pocket_pivot` → 12 verdicts; `cg_tfe_v15` → 1.

### Task 3 — `run_deletion.py` + tests (`44f7a81`)

- `delete_run_atomic(run_id, db_path=None, log_path=None) -> dict` + `RunNotFound`.
- Atomic-ish flow: lookup → DB delete → folder rmtree → JSONL audit append. Full rollback intentionally out of scope.
- 6 tests passing.
- **Adaptation:** plan assumed `report_dir` column; real schema has `report_card_html_path` (file path OR folder path).

### Task 4 — `accept_scored` activate flag (`bb237b8`)

- Modified `tradelab/src/tradelab/web/approve_strategy.py`. Added `activate: bool = False` param + `ActivationGateFailed` exception + `AlreadyActivated = CardExistsError` alias.
- When `activate=True`: ROBUST verdict gate enforced before any disk side effects; card written with `status="enabled"`; stamped with `activated_at` + `activated_verdict`. Return dict gains `activated_at`.
- 6 new tests; 16 total in `test_approve_strategy.py`.
- **Adaptation per slice-0:** the plan's "create new activation.py" was rejected because `accept_scored` already writes to `cards.json`. Extending `accept_scored` avoids a second write path.

### Task 5 — backend routes in handlers.py (`b3c8bcc` + `840fb0f` flip)

Initial commit (`b3c8bcc`) wired 4 routes:

- **GET `/tradelab/runs/<run_id>/qs-metrics`** — unenveloped sub-grid payload via `qs_metrics` module + 4 audit-DB header numbers (`total_return`, `trades`, `win_rate`, `profit_factor`). 404 when no folder OR no equity curve.
- **GET `/tradelab/strategies/<id>/verdict-history`** — wraps `verdict_history.get_recent_verdicts`. Returns `{"verdicts": [oldest..newest, lowercase]}`. Empty list (200) for unknown strategies, NOT 404.
- **POST `/tradelab/accept`** extended with optional `activate: bool` field. Maps `ActivationGateFailed` → 422; `CardExistsError` → 409 (existing branch). `_validate_accept_payload` type-checks the new field.
- **DELETE `/tradelab/runs/<run_id>/permanent`** (initial design — superseded).

Subsequent commit (`840fb0f`) flipped the delete semantics per user's "make sure we get it right":

- The `/permanent` suffix went away. The existing `DELETE /tradelab/runs/<id>` route (which was soft-archive) is now hard-delete via `delete_run_atomic`.
- Idempotent: unknown id → 204 (preserves prior contract bulk-delete + stale FE state were calibrated against).
- `archive.archive_run` / `is_archived` / `list_archived_run_ids` primitives + `/unarchive` route remain in place for legacy archived rows; the FE Unarchive button (`command_center.html:4341`) is now dead UX going forward and may be cleaned up in Task 14/15.
- `bulk-delete` semantics shift: unknown ids land in `deleted` (not `failed`) since underlying DELETE is idempotent.

9 new tests in initial commit; net **+5 tests after the flip** (3 `/permanent` tests removed; 1 "row preserved" test removed; 2 renames; gained the new "removes row + folder + appends audit" + "idempotent on second call").

### Task 6 — launcher tearsheet pass-through (`421b1294`, parent repo)

- Added `serve_run_tearsheet()` method on `DashboardHandler` in `C:/TradingScripts/launch_dashboard.py` mirroring `serve_compare_report` pattern.
- Routed via `do_GET`: `/tradelab/runs/<id>/tearsheet` → resolves run folder via `audit_reader.resolve_run_folder` → serves `quantstats_tearsheet.html` from that folder with `text/html`.
- 503 if tradelab handlers couldn't be imported at startup; 404 on unknown run / missing folder / missing tearsheet artifact.
- No pytest in parent repo; verified via AST parse + regex sanity tests for the route.

### Task 7 — research-v3 CSS scope + Google Fonts (`4c1906d7` parent + `5e61dd7` tradelab tests)

- Added 3 Google Fonts `<link>`s to `<head>` (Fraunces / Geist / JetBrains Mono).
- Added a new `<style id="research-v3-scope">` block with the warm-dark editorial palette + typography + component styles for the v3 markup that follows in Tasks 8–15.
- All v3 selectors gated on `body.research-v3 #research ...` so they only apply on the Research tab. Other tabs render exactly as before.
- All CSS variables prefixed `--r3-*` to avoid clobbering the dashboard's existing `:root` vars (`--bg`, `--green`, `--red` would otherwise shift on every other tab during cascade — this was the regression I caught in `test_v3_scope_does_not_leak_root_variable_names`).
- `switchTab()` toggles the `body.research-v3` class only when `tabName === 'research'`.
- **Plan-vs-DOM correction:** plan said `#tab-research`; actual ID is `#research`. All 131 selectors corrected before commit. Verified via Playwright smoke that font + palette flip on Research tab and revert on every other tab. Zero console errors.
- 5 new tests in `test_command_center_html.py`.

### Task 8 — action-bar restyle + calibration trust + canary icon (`a6023a10` parent + `866cb0a` tradelab tests)

- Replaced `#preflight-chips` section with v3 `.action-bar` div: 3 buttons (Refresh Data primary / New Strategy / Score New Strategy), divider, 4 preflight chips, divider, calibration trust chip, spacer, canary status icon.
- Plan-vs-DOM corrections (multiple):
  - Plan body wrote `id="refresh-data-btn"` etc. but spec §5.1 explicitly says "preserve existing IDs"; v2 click handlers bind to `preflightRefreshBtn` / `preflightNewStrategyBtn` / `scoreNewStrategyBtn`. **Existing IDs preserved.** CSS classes flip to `.ab-btn` / `.ab-btn.primary`.
  - Plan body wrote `preflight-strategies` (plural). Actual ID is `preflight-strategy` (singular) — singular wins.
  - Plan body's calibration-trust formula referenced fictional `shared_robust` / `total` fields. Real `/tradelab/calibration-summary` returns `n_accepted` / `n_te_tripped_30d` / `n_disabled_60d` / `median_pf_gap`. Trust is now `1 − max(TE-tripped, disabled) / max(1, n_accepted)`; shows `—` when `n_accepted < 3`.
- `researchLoadPreflight` was rewritten to write into the new `.l`/`.v` chip spans instead of clobbering `chip.innerHTML`. Also adds v3 `.ok`/`.warn`/`.fail` classes alongside legacy `.preflight-*` ones.
- `renderCanaryGrid` extended to toggle the new `#canary-status-icon` visibility. Hidden on all-pass; visible with tooltip listing degraded names when any status === `MISMATCH`. UNKNOWN does NOT light the icon (matches the `body.accepts-blocked` safety-gate semantics).
- 5 new tests in `test_command_center_html.py`.
- **Playwright smoke verified:** Research tab shows warm-dark gradient, copper primary button, all 4 chips populate live (Universe smoke_5 (5) / Cache 15.5h / Strategy 12 OK / TD-API key present) with green dots, calibration trust 0.75 in green. Zero console errors.

---

## What's next — Task 9 in detail

### Goal

Replace the existing `#researchLiveCards` skeleton block (around line 1350–1354 in `command_center.html`) with real v3 tiles. The CSS for `.tile`, `.tile-head`, `.tile-name`, `.verdict.{robust,marginal,fragile,inconclusive}`, `.drift`, `.kpis`, `.kpi`, `.activate.{enabled,disabled,live}` is **already shipped** in `<style id="research-v3-scope">` from Task 7 — Task 9 only adds markup + JS, no new CSS.

### Files

| File | Change |
|---|---|
| `C:\TradingScripts\command_center.html` | Replace `#researchLiveCards` markup. Add JS to fetch verdict-history + render tiles. Wire to existing `researchLoadAll` orchestrator. |
| `C:\TradingScripts\tradelab\tests\web\test_command_center_html.py` | Add tests asserting tile structure, drift sparkline classes, verdict-history fetch, activate-button state machine selectors. |

### Concrete next steps

1. **Read the spec §5.2 (Live Cards row)** at `tradelab/docs/superpowers/specs/2026-04-30-research-tab-v3-design.md` lines ~152–230 for the contract.
2. **Read the mockup tile structure** at `.superpowers/brainstorm/216-1777553249/content/01-live-card-tile.html` and the assembled version at `.../03-assembled-research-tab.html` (around the `<div class="tile-grid">` block).
3. **Plan body Task 9** lives at plan lines 1203–~1380. Key contracts:
   - One tile per strategy returned by `/tradelab/cards` (existing endpoint) — uses `cards_view.list_cards_view`'s output shape.
   - Each tile: `tile-head` (name, version, timeframe, verdict pill), `drift` (12-dot sparkline from `GET /tradelab/strategies/<id>/verdict-history`), `kpis` (4-up: PF / DSR / Sharpe / DD), `activate` button. Optional `health-row` for tracking-error bar + KS dot.
   - Tile click expands inline (Task 11). Activate button fires `POST /tradelab/accept` with `activate: true` (Task 10).
4. **Verify the drift sparkline endpoint** before pasting JS. The existing `verdict_history.py` returns `["robust", "fragile", ...]` lowercase strings — the v3 CSS keys off `.dot.robust`, `.dot.fragile`, `.dot.marginal`, `.dot.inconclusive`. Task 9 just maps the array onto 12 `<span class="dot ${verdict}">` elements.
5. **Write the failing tests first** for tile presence, drift markup, activate button. Use static-HTML grep tests (the test_command_center_html.py pattern).
6. **Implement** the markup + JS. Reuse the existing `researchLiveCards` container ID for backwards compat (the existing skeleton uses it; Task 9 just rewrites its children).
7. **Playwright smoke** with the dashboard up. Click Research → verify tiles render with correct verdict color borders, drift dots animate in, KPIs populate with the right numeric coloring (green for >threshold, red for breach).
8. **Commit** once for parent repo (markup+JS) and once for tradelab repo (tests).

### Risks to watch (Task 9)

- **`#researchLiveCards` is a class, not just an ID.** Existing v2 CSS `.research-cards-grid` may still apply on Research tab and conflict with the new `.tile-grid` styling. Strip the class or keep it gated under `body.research-v3`. The v3 scope's `.tile-grid` rule already exists and will apply via the body class.
- **`/tradelab/cards` shape.** Verify which fields the existing endpoint returns vs what the spec assumes. The mockup uses `card.symbol`, `card.verdict`, `card.dsr_probability`, etc. — if any are missing from the live shape, fix that first or downgrade the tile content.
- **Per-strategy verdict-history fetch fan-out.** With ~10 cards, that's 10 parallel fetches on every Research-tab activation. Acceptable for v1; consider batching in a later pass if it's slow on real load.

---

## Remaining tasks (9–18) at a glance

| # | Title | Notes |
|---|---|---|
| 9  | Live Cards compact tile + drift sparkline | **next up** — markup+JS only, CSS already shipped via Task 7 |
| 10 | Activate state machine + cross-tab linkage | POST /tradelab/accept with `activate=true`; cross-tab pulse to Overview tab |
| 11 | Click-to-expand inline + 7-cell summary | Tile expand toggle |
| 12 | QS sub-grid + 3 inline SVG charts | Uses Task 1's `qs-metrics` endpoint |
| 13 | Cross-strategy factor matrix | Column-warn detection at ≥50% non-pass |
| 14 | Pipeline restyle + per-row trash icon | Reuses v2 pipeline JS; CSS already shipped via Task 7 |
| 15 | Pipeline delete affordances | 4 confirm tiers (inline / bulk / typed >10 / live-card escalation). Calls hard-delete from Task 5. |
| 16 | SSE cascading | `run_deleted` and `card_activated` event branches. Backend already broadcasts (Tasks 5/4). |
| 17 | Full UI smoke gate via Playwright MCP | Playwright MCP confirmed working (used heavily in Tasks 7+8) |
| 18 | Class B activation | `alpaca_config.json` `strategies[i].enabled`; takes effect at next bot startup; write-then-rename |

---

## Slice-0 binding decisions (still load-bearing)

These override the plan body where they conflict — see `docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md`:

- **No `activation.py` is created.** Class A activation lives in `approve_strategy.accept_scored` with `activate=True`. (Task 4 done.)
- **No `/tradelab/strategies/<id>/activate` route.** Activation is `POST /tradelab/accept` with `activate=true`. (Task 5 done.)
- **Class B target = `C:/TradingScripts/alpaca_config.json`**, field `strategies[i].enabled`. Bot reads once at startup — no hot-reload. UI must inform user "takes effect at next bot startup." Use write-then-rename for atomicity. (Task 18.)

---

## How to resume — exact recipe

```bash
# 1. Verify state
cd /c/TradingScripts/tradelab
git status                                # should be clean
git branch --show-current                 # should be feat/research-tab-v3
git log --oneline -8                      # top 8 should match commit hashes above

cd /c/TradingScripts
git status                                # should be clean
git branch --show-current                 # should be feat/research-tab-v3
git log --oneline -3

# 2. Sanity-check the test baseline
cd /c/TradingScripts/tradelab
PYTHONPATH=src python -m pytest tests/web/ --tb=no -q -p no:cacheprovider
# Expected: 379 passed (~2 min)

# 3. Re-read the spec + plan + slice-0 amendments
head -30 docs/superpowers/plans/2026-04-30-research-tab-v3.md
cat docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md

# 4. Read THIS handover doc end-to-end
cat docs/superpowers/RESEARCH_TAB_V3_HANDOFF_2026-04-30_AFTER_TASK_8.md

# 5. Start the dashboard if not running (the user runs this themselves)
#    On user's terminal:  python C:\TradingScripts\launch_dashboard.py

# 6. Open Playwright MCP and navigate to http://127.0.0.1:8877/ ; click Research.
#    Confirm: warm-dark, Geist font, action bar populated, calibration trust shows.

# 7. Begin Task 9 with a TDD slice (write static-HTML tests first, then markup, then JS).
```

---

## Gotchas — DO NOT REPEAT

### Gotcha #1: PowerShell + redirected stdout hangs pytest

The earlier session hung for 13+ minutes on `$env:PYTHONPATH = "src"; python -m pytest tests/web/test_qs_metrics.py -v 2>&1`. Same family as `reference_launcher_unicode_banner.md` (cp1252 stdout redirection breaks Python on Windows). The same command via Bash returned in 1 second.

**Rule:** use **Bash** for pytest. PowerShell is fine for one-shot non-Python commands but not for invoking long-running Python with redirected output.

```bash
# Good
PYTHONPATH=src python -m pytest tests/web/test_X.py -v --no-header -p no:cacheprovider 2>&1 | tail -20

# Bad (will hang)
$env:PYTHONPATH = "src"; python -m pytest tests/web/test_X.py -v 2>&1
```

### Gotcha #2: The plan body's expected values are placeholders

The plan was written before any test was run. Several test fixtures contain **guessed** expected values. When implementing, run the test, observe the actual output, and update the fixture to the real value with a comment.

### Gotcha #3: The plan's DB schema is also a guess

Real schema is `runs(run_id, timestamp_utc, strategy_name, strategy_version, ..., verdict, ..., report_card_html_path, ...)`. Always run `PRAGMA table_info(runs)` against the real DB before writing any SQL touching this table.

### Gotcha #4: Verdict casing inversion (DB ↔ FE)

DB stores **UPPERCASE** (`ROBUST`); FE CSS classes are **lowercase** (`.robust`, `.fragile`). Helpers normalize downward.

### Gotcha #5: tradelab audit DB path is cwd-relative

`Path("data") / "tradelab_history.db"` is relative. Test workspaces in `tmp_path` work fine; production callers must invoke from `C:\TradingScripts\tradelab\`. Same applies to `data/deletions.log` (`run_deletion._default_log_path`) — tests must `monkeypatch.chdir(tmp_path)` to avoid polluting the live tradelab data dir, per `feedback_tests_live_conftest_autouse.md` family.

### Gotcha #6: The plan body's element IDs lie

Tasks 8 had **three** plan-vs-DOM mismatches in a single section. The plan was written before reading the actual `command_center.html`. Always grep the live HTML before pasting the plan's selector lists. Per `feedback_plan_grep_verification.md`.

| Plan body said | Reality |
|---|---|
| `#tab-research` | `#research` |
| `#refresh-data-btn` / `#new-strategy-btn` / `#score-new-strategy-btn` | `#preflightRefreshBtn` / `#preflightNewStrategyBtn` / `#scoreNewStrategyBtn` (and the spec ELSEWHERE says "preserve existing IDs") |
| `#preflight-strategies` (plural) | `#preflight-strategy` (singular) |

### Gotcha #7: The plan body's API field names lie

Task 8's plan body referenced `data.shared_robust / data.total` for the calibration-trust formula. Real `/tradelab/calibration-summary` returns `n_accepted / n_te_tripped_30d / n_disabled_60d / median_pf_gap`. Always check the actual response shape (or the Pydantic model in `tradelab/calibration/summary.py`) before pasting the plan's JS.

### Gotcha #8: `researchLoadPreflight` clobbers chip innerHTML

The v2 implementation does `chip.textContent = ''` then appends a single dot + text node — this WIPES any `<span class="l">` / `<span class="v">` structure on each refresh. Task 8 fixed this by writing into the spans instead of replacing innerHTML. Any future task that rewrites chip content needs to use the same pattern (read sub-elements, set text content) rather than clobbering.

### Gotcha #9: CSS variables that share names with `:root` will clobber every other tab

The v3 mockup defines `--bg`, `--green`, `--red`, etc. The dashboard's `:root` defines the same names with different values. If we'd put the v3 vars under `:root`, EVERY tab's colors would shift. The fix: prefix all v3 vars with `--r3-*` and define them under `body.research-v3 { ... }`. The test `test_v3_scope_does_not_leak_root_variable_names` guards this regression.

### Gotcha #10: `--r3-*` vars only resolve when on Research tab

If JS sets a style like `el.style.color = 'var(--r3-green)'` from a context where the body class isn't yet applied, the style resolves to "" (no color) until the body class is set. Task 8's `updateCalibrationTrustChip` only runs while Research is active so this is moot, but future Tasks 9–13 might set v3-color styles from cross-tab handlers — be careful.

---

## DELETE semantics (since this had an in-flight flip)

Final state of `DELETE /tradelab/runs/<id>` after `840fb0f`:

- **Hard-delete** via `run_deletion.delete_run_atomic` (DB row + folder + JSONL audit append).
- **Idempotent** — unknown id returns 204 (matches stale-FE pattern).
- **SSE broadcast** — emits `{type: "run_deleted", run_id, strategy}` on the existing job-stream broadcaster. FE dispatch by `event.type` is Task 16.
- The `/permanent` URL suffix that briefly existed in `b3c8bcc` is **GONE**.
- `archive.archive_run` / `is_archived` / `list_archived_run_ids` + `POST /tradelab/runs/<id>/unarchive` route remain in place. They're functional for any legacy archived rows but no new rows land in `archived_runs` going forward. The FE Unarchive button (`command_center.html:4341`) is dead UX. Tasks 14/15 may clean it up.

---

## Cross-repo branch reconciliation

Both repos have a branch named `feat/research-tab-v3`:

- **tradelab repo** (`C:\TradingScripts\tradelab\`, gitignored from parent) holds all backend slices + tests + docs.
- **parent repo** (`C:\TradingScripts\`) holds `command_center.html` + `launch_dashboard.py` changes.

These branches don't share history; they're two independent feature branches that ship together. When v3 is ready to merge:

1. Both branches must be in a passing state (full tests + Playwright smoke gates).
2. Merge each branch to its respective `main` / `master`.
3. The parent `main` and tradelab `master` must move to compatible heads. There's no automation enforcing this — verify by hand on the merge commit.

---

## Tests baseline at end of Task 8

```
tests/web/  — 379 passed in 124s (Bash)
  + 5 new in test_command_center_html.py for Task 7 (v3 scope contract)
  + 5 new in test_command_center_html.py for Task 8 (action-bar contract)
```

The static-HTML test file (`tests/web/test_command_center_html.py`) reads `command_center.html` from the parent repo — that file's path is resolved via `_find_command_center_html()` which probes a few standard locations.

---

## When in doubt

1. **Trust slice-0 amendments** over the plan body for Tasks 4, 5, 18. Trust this handover over both for what's already on disk.
2. **Read the actual code** before pasting plan-body markup or JS. Plan body has been wrong on selectors, IDs, schema, and API field names. Per `feedback_plan_grep_verification.md`.
3. **Run pytest via Bash, not PowerShell.**
4. **Use Playwright MCP for any UI smoke** — feedback memory `feedback_playwright_smoke.md` requires it; pytest is necessary but not sufficient.
5. **Smoke between slices** per `feedback_live_smoke_before_next_slice.md` — every Task 7+8 commit was preceded by a Playwright check; Task 9 should follow the same pattern.

— end of handover —
