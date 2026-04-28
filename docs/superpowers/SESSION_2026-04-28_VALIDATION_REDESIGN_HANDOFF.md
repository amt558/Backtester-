# Validation Redesign — Session Handoff (2026-04-28)

**Plan:** `docs/superpowers/plans/2026-04-28-research-tab-validation-redesign-CALIBRATED.md` (2824 lines, 10 slices)
**Spec:** `docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md`
**Memory entry:** `project_validation_redesign_2026-04-28.md` (CALIBRATED v3 locked)

---

## Status snapshot

**Done (4 slices):** -0.5, -1, 0, 0.5
**Remaining (6 slices):** 1a, 1b, 2, 3, 4, 5, 6 + the §1 confound panel (split out)

| Slice | Status | Commits | Notes |
|-------|--------|---------|-------|
| -0.5 Bot `client_order_id` tagging | ✅ | 3 (bot repo) | All Alpaca orders now carry `{strategy}-{symbol}-{ts}` (entry) or `{strategy}-{symbol}-exit-{ts}`. See bot repo, not tradelab. |
| -1 Retrospective calibration | ✅ | 10 in tradelab | `5871dbb`→`d776a81`. Real run on 12mo Alpaca paper data complete. **Statistically thin** — only 25% attribution rate (3 of 12 trades). Re-run in 30 days when natively-tagged trades accumulate. Per-signal hit-rates n=1, can't classify gates yet. Findings: `docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md`. |
| 0 Ledger schema extension | ✅ | 2 in tradelab | `1d52ab7`, `8f0331e`. `runs` table now has `signal_values_json`, `thresholds_json`, `accepted_bool`, `reject_reason`. 5 historical reports backfilled. |
| 0.5 Engine integrity / canary panel | ✅ | 3 in tradelab | `e9ea585`, `b4dbc27`, `09d333e`. **Built per Option A** (reuse existing canaries — see "Plan adaptations" below). 15 new tests. HTML/CSS/JS in **parent repo** uncommitted. |

**Test count after 0.5:** 874 in tradelab repo (subset 345/345 in `tests/canaries`+`tests/web`).

---

## Hand-smoke checklist — ✅ VERIFIED 2026-04-28

Smoke was performed end-to-end. Slice 0.5 works correctly: panel goes red on injected MISMATCH, banner reads "1 MISMATCH — accepts blocked", returns to baseline after row deletion.

**Bug found in original commands:** the `python -c "from tradelab.audit import ..."` and `sqlite3 data/tradelab_history.db ...` snippets are both **cwd-relative**. Running from any directory other than `C:\TradingScripts\tradelab` silently writes/reads a phantom DB at `<cwd>\data\tradelab_history.db` — list_runs() returns the phantom rows, but the dashboard reads the real DB and shows nothing. Updated commands below use absolute paths.

Re-run procedure (cwd-safe):

1. Launch dashboard. From a UTF-8 terminal (or set `$env:PYTHONUTF8="1"` to dodge the cp1252 banner crash from memory `reference_launcher_unicode_banner.md`):
   ```powershell
   $env:PYTHONUTF8 = "1"
   cd C:\TradingScripts
   python launch_dashboard.py
   ```
   Wait for ports 8877 + 8878 to come up, then open `http://localhost:8877` → Research tab.

2. Baseline expected: `rand_canary` MATCH (its INCONCLUSIVE row from 2026-04-19 is in the expected set), `overfit_canary`/`leak_canary`/`survivor_canary` UNKNOWN (no audit rows). Header: `1/4 match · 3 unknown`. Banner not red. Accepts NOT blocked.

3. Inject a fake ROBUST `leak_canary` row (uses absolute db_path — works from any cwd):
   ```powershell
   $py = @'
   from pathlib import Path
   from tradelab.audit import record_run
   record_run("leak_canary", verdict="ROBUST", dsr_probability=0.99,
              db_path=Path(r"C:\TradingScripts\tradelab\data\tradelab_history.db"))
   '@
   $py | python -
   ```
   Reload Research tab. Panel turns red. Header: `1 MISMATCH — accepts blocked`. `leak_canary` cell shows MISMATCH. Any `<button class="accept">` goes to opacity 0.4 + non-clickable.

4. Verify endpoint state directly (optional sanity check):
   ```powershell
   (Invoke-WebRequest -Uri "http://localhost:8877/tradelab/canary-status" -UseBasicParsing).Content | ConvertFrom-Json | Select-Object all_match
   ```
   Should print `all_match : False`.

5. Clean up the injected row (uses absolute path):
   ```powershell
   $py = @'
   import sqlite3
   conn = sqlite3.connect(r"C:\TradingScripts\tradelab\data\tradelab_history.db")
   conn.execute("DELETE FROM runs WHERE strategy_name='leak_canary' AND verdict='ROBUST'")
   conn.commit()
   '@
   $py | python -
   ```
   Reload. Back to baseline.

6. **If you previously ran the buggy commands**, also clean up the phantom DB: `Remove-Item C:\Users\AAASH\data\tradelab_history.db -Force` (and `Remove-Item C:\Users\AAASH\data` if empty).

---

## Critical context for the next session

### 1. Plan adaptations made (don't re-debate)

**Slice 0.5 was rebuilt as Option A** because the plan-as-written had 5 selector mismatches against current code:

- Plan said `tradelab.canary` (singular). **Reality: `tradelab.canaries` (plural)** — already exists at `src/tradelab/canaries/__init__.py`.
- Plan invented 4 hypothetical canaries (`canary_perfect_robust`, `canary_obvious_fragile`, etc.). **Reality: 4 existing canaries are `rand_canary`/`overfit_canary`/`leak_canary`/`survivor_canary`**. `EXPECTED_VERDICT` already defined in `src/tradelab/cli_canary.py:24-34`.
- Plan's `_run_one_canary` hook was unimplementable — there's no `tradelab.canary.run_canary` function. **Reality: query latest verdict from audit DB via `list_runs(strategy=name, limit=1, db_path=db)`** (status check, not re-run).
- Plan's test fixture `http_client` doesn't exist. **Reality: tests call `handlers.handle_get(...)` directly** (see `tests/web/test_handlers.py:12-26` for pattern).
- Plan's `if self.path == "/tradelab/canary-status":` (BaseHTTPRequestHandler-style) is wrong. **Reality: `handle_get_with_status(path_with_query)` is a free function**; route added to its `if/elif` chain before the 404 fallback.

**Lesson:** Per the user's memory `feedback_plan_grep_verification.md`, every selector/signature/enum in the plan MUST be grepped against current code before pasting into the implementer's brief. Slices 1a, 1b, 2, 3, 4, 5, 6 likely have similar drift — verify before dispatching.

### 2. command_center.html lives in the PARENT repo

`C:\TradingScripts\command_center.html` is the canonical dashboard HTML. NOT `tradelab/src/tradelab/web/command_center.html` (doesn't exist). The plan's path was wrong. Slice 0.5's HTML/CSS/JS additions are in the parent repo and **uncommitted** (the parent repo also has a 1000+ line pre-existing dirty diff in this file from prior work — handle it separately whenever you commit the parent repo).

The tradelab-side guard rail: `tests/web/test_command_center_html.py` has 5 static-contract tests that read the parent-repo HTML and assert on markup/CSS/JS. Drift on either side breaks pytest.

### 3. Slice 7a's handlers.py changes are STILL deliberately uncommitted

Memory says Slice 7a (daily digest) shipped 2026-04-27 but is uncommitted by design. Among the 20 dirty files: `src/tradelab/web/handlers.py` carries Slice 7a additions including `probe_receiver_status()`, `/tradelab/runs/{id}/robustness`, `/tradelab/live/digest/preview`, `/tradelab/live/digest/state`, `handle_digest_*_get()`, capital/max_positions validation.

**During Slice 0.5 the implementer accidentally bundled this into a commit** via `git add src/tradelab/web/handlers.py`. Surgically split via `git reset --soft HEAD~2` + selective re-staging. **Final state: handlers.py is back to dirty with Slice 7a only.**

For all future slices that touch handlers.py:
- **NEVER `git add src/tradelab/web/handlers.py` whole** — it sweeps Slice 7a in.
- Use `git add -p` to interactively pick canary/new-route hunks only, OR
- Use the controller-driven approach from this session: backup combined → reset to baseline → Edit only the new lines → stage → commit → restore combined.

### 4. §1 confound is concrete, not hypothetical

S10_VolumeBreakout and S12_MomentumAcceleration **lost $745 in production** but have **no tradelab module**. The engine has never scored them. Open question for the user (deferred):

- **(A)** Port them into `tradelab.strategies.*` so they enter the verdict-accuracy loop.
- **(B)** Accept they live outside the loop. Their losses don't validate or invalidate the gauntlet.
- **(C)** Investigate why bot.log appeared truncated (S4/S7/S8/S10 had zero `Position added` entries despite being deployed).

User has not picked yet. The retrospective doc surfaces this; revisit after the next 30-day re-run.

### 5. S2 verdict drifted between recon and reports

Recon doc (2026-04-21) said S2 was FRAGILE with 4 fragile signals. Current `s2_pocket_pivot/.../robustness_result.json` (2026-04-27) says ROBUST with only `wfe`+`loso` fragile. Either strategies were re-run with different data or thresholds shifted. **Future verdict-accuracy work needs to compare against a frozen snapshot, not "current report"** — the freezing is what Slice 0's `runs` table extension enables.

---

## Next slice: 1a (Hold-out as Gate)

**Plan section:** lines 1563-1786 of `docs/superpowers/plans/2026-04-28-research-tab-validation-redesign-CALIBRATED.md`.

**Pre-dispatch checklist** (do these BEFORE briefing the implementer subagent):

1. Read the slice's plan text in full.
2. **Grep every selector/import/function-name in the plan against current code.** Treat the plan as a draft, not a spec.
3. If you find drift, decide on adaptation BEFORE briefing the implementer (see "Plan adaptations" pattern above).
4. Brief the implementer with full task text + verified codebase facts inline. **Don't let them re-read the plan** — give them the corrected spec directly.
5. Mandate TDD, specify model (standard/Sonnet for multi-file integration; Haiku only for trivial/mechanical), specify commit hygiene (`git add` specific paths, NEVER `-A`, NEVER stage handlers.py whole).
6. After implementer reports, dispatch spec-compliance reviewer (Haiku is fine), then code-quality reviewer (Haiku).
7. Mark task complete only after both reviews approve.

---

## Open questions for the user

1. **Slice 1a now or later?** Last user input was "continue task" but Slice 0.5 hasn't been smoked. Ask before dispatching 1a.
2. **§1 confound (A/B/C)?** Deferred — surface again after next retrospective re-run (30 days).
3. **Commit Slice 0.5 frontend in parent repo?** HTML/CSS/JS sits dirty alongside 1000-line pre-existing diff. User's call.
4. **Commit pollution avoidance going forward?** `git add -p` discipline OR controller-driven surgical staging — pick a default.

---

## Files / commits to know

**Slice 0.5 commits (clean):**
- `e9ea585` feat(canaries): runtime integrity check
- `b4dbc27` feat(web): GET /tradelab/canary-status endpoint
- `09d333e` test(web): canary panel + accept-block static contracts

**Slice 0 commits:**
- `1d52ab7` feat(audit): extend runs table
- `8f0331e` feat(audit): backfill_runs_table.py

**Slice -1 commits:** `5871dbb` → `d776a81` (10 commits incl. fixes for bot.log parsing, Alpaca SDK migration, robustness shape, BOM handling).

**Slice 0.5 new files:**
- `src/tradelab/canaries/runtime.py` (101 lines)
- `tests/canaries/test_runtime.py` (132 lines, 6 tests)
- `tests/web/test_canary_status_endpoint.py` (83 lines, 4 tests)
- `tests/web/test_command_center_html.py` (extended +78 lines, 5 new tests)
- `src/tradelab/web/handlers.py` (1 import + 7-line route in `handle_get_with_status`)

**Parent-repo (uncommitted) Slice 0.5 changes:**
- `C:\TradingScripts\command_center.html` — canary panel section (~line 1051), `loadCanaryStatus()`/`renderCanaryGrid()` JS (~line 3739+), `body.accepts-blocked` CSS rule (~line 379-380), `loadCanaryStatus()` wired into `researchLoadAll` Promise.all.

---

## Quick-start for the next Claude session

```
1. Read this doc.
2. Read docs/superpowers/plans/2026-04-28-research-tab-validation-redesign-CALIBRATED.md lines 1563-1786 (Slice 1a).
3. Confirm with user: hand-smoke Slice 0.5 first, or skip and dispatch 1a?
4. If dispatching 1a: grep every selector in the slice's plan text against current code BEFORE briefing the implementer.
5. Use the Slice 0.5 implementer brief in the prior session as a template — full task text inline, verified codebase facts, TDD mandate, commit hygiene.
6. After implementer + 2 reviewers: mark task complete, surface status, ask user before dispatching 1b.
```

Memory entries that affect this work: `project_validation_redesign_2026-04-28.md`, `feedback_plan_grep_verification.md`, `feedback_live_smoke_before_next_slice.md`, `project_tradelab_slice_7a_complete.md`, `reference_robustness_result_shape.md`, `reference_alpaca_trade_history_source.md`.
