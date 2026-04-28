# LITE-for-Flow-A Shipped — Session Handoff 2026-04-28

**Status:** ✅ Merged to tradelab `master` at `017ec19`. 923/923 tests passing. Hand-smoke surfaced UI/UX issues (TBD details) — punt to next session. Stub-wiring work attempted but interrupted by API error; deferred to next session.

**Companion docs:**
- Spec: `docs/superpowers/specs/2026-04-28-research-tab-lite-flow-a-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-research-tab-lite-flow-a.md`
- Mockup: `docs/superpowers/mockups/research_tab_lite_applied_to_flow_a.html`
- Predecessor handoff: `docs/superpowers/SESSION_2026-04-28_VALIDATION_REDESIGN_HANDOFF.md` (CALIBRATED pause)
- Resumption plan: `docs/superpowers/RESUMPTION_PLAN_2026-04-28.md` (the doc that triggered the LITE reframe)

---

## What was accomplished

### Pipeline — Spec → Plan → Execute → Merge → Smoke

1. **Brainstorm** — reframed CALIBRATED (paused) to LITE-for-Flow-A. Key insight: under Pine→TV→Alpaca, TradingView is source of truth for both backtest and live execution. The §1 confound dissolves entirely.
2. **Spec** authored at `2026-04-28-research-tab-lite-flow-a-design.md` (committed `bc9b9bc`).
3. **Mockup** authored at `research_tab_lite_applied_to_flow_a.html` showing month-2 state with sparse-data fallback (committed `bc9b9bc`).
4. **Plan** authored at `2026-04-28-research-tab-lite-flow-a.md` — 9 tasks, 3 phases, ~4.5 days estimated (committed `90ad96d`).
5. **Subagent-driven execution** — all 9 tasks completed in a single session via implementer + spec compliance + code quality review cycles per task.
6. **Merge** — `--no-ff` to master at `017ec19`, branch `feat/lite-flow-a` deleted. Months-dirty Slice 7a drift preserved unstaged.
7. **Hand-smoke** — backend endpoints verified via curl (all 6 respond correctly). UI smoke surfaced unspecified issues; deferred.

### Backend (tradelab repo, 11 commits + 1 merge on master)

| Commit | Task | Surface |
|---|---|---|
| `3eb51d8` | T1 | `io/returns.py` — `derive_daily_returns` + `write_returns_csv` |
| `175ecb7` | T1 fix | `MalformedTVCSVError` for header validation; `accept_scored` warn-continue test |
| `c985c2c` | T2 | `live/tracking_error.py` — distributional TE/Decay/K-S engine; `GET /tradelab/cards/<id>/tracking-error` |
| `c41b7a7` | T4 | `WalkForwardResult.holdout_result` + `engines/walkforward.py` hold-out backtest + `verdict.py` `hold_out_oos` signal #10 |
| `5420213` | T4 fix | `compute_splits(wf_end=...)` reserves trailing tail from WF range — guarantees hold-out is genuinely untouched |
| `1126a8f` | T5 | `robustness/correlation.py` — pure-Python Pearson; `GET /tradelab/portfolio-health` + `GET /tradelab/correlation/<run_id>` |
| `2e0fa38` | T5 fix | `compute_candidate_vs_cohort(exclude_card_id=...)` — prevents self-correlation polluting max_rho |
| `8395be1` | T6 sub | `GET /tradelab/relative-context/<run_id>` — candidate PF/DSR/DD ranks vs enabled-cards cohort |
| `b9dd80f` | T8 | `regime/banner.py` — `classify_regime` (pure logic) + `fetch_regime` (stub); `GET /tradelab/regime` with NotImplementedError fallback |
| `55c8636` | T8 fix | classify_regime thresholds aligned with spec (VIX<17, vol<0.13, ADX<18); test asserts UNCLEAR strictly |
| `40d116d` | T9 | `calibration/summary.py` — accepted-card outcome aggregator; `GET /tradelab/calibration-summary` with sparse-data fallback at n<3 |
| `017ec19` | merge | `merge: LITE-for-Flow-A research tab — feedback loop on Pine→TV→Alpaca (9 slices)` |

### Frontend (parent repo `C:\TradingScripts`, 7 atomic commits on `main`)

| Commit | Task | Surface |
|---|---|---|
| `6d5b7e10` | T3 | Live-card TE bar / Decay sparkline / K-S badge / REVIEW NEEDED tag in `renderLiveCard()` |
| `8b68fd8a` | T3 fix | Selector fix (`.verdict-pill` insertAdjacent), CSS tokens, null guards, console.warn on fetch fail |
| `927a3a1d` | T4 | Pipeline Hold-out column + Score modal Hold-out gate panel |
| `5aad1337` | T6 | Score modal Portfolio fit gate (with OVERRIDE prompt at max ρ > 0.70) + Relative context section + Pipeline Corr column |
| `92dfdf00` | T7 | Portfolio Health 3-cell panel below Live Strategies |
| `a90b3444` | T8 | Regime banner panel at TOP of Research tab |
| `05258fb7` | T9 | Calibration banner between Regime and Live Strategies |

### What's live in the dashboard now

Top-to-bottom on the Research tab at `http://localhost:8877/`:

1. **Market Regime banner** (T8) — 3 cells (Volatility / Trend / Breadth) showing UNKNOWN today (fetch stubbed)
2. **Verdict Calibration banner** (T9) — n_accepted=4, n_disabled=1, n_te_tripped=0 today
3. **Live Strategies grid** with augmented cards (T3) — TE/Decay/K-S health rows showing "n=0 insufficient" today
4. **Portfolio Health 3-cell panel** (T7) — sparse "—" placeholders today (only 1 enabled card)
5. **Research Pipeline** with Hold-out (T4) + Corr (T6) columns — most rows show "—" (old runs predate hold_out_oos)
6. **Score modal** stack (T4 + T6): Hold-out gate → Diagnostics → Relative context → Portfolio fit → Accept

### Test count

816 baseline → **923 passing** (+107 new tests across T1, T2, T4, T5, T8, T9 — T3/T6/T7 are pure frontend, no Python tests).

---

## The two quick notes from the merge wrap-up

> Once merged, **commit the still-uncommitted Slice 7a / handlers.py drift in a separate cleanup session** as called out in the resumption-plan handoff. Don't bundle it.

> The two intentional stubs (`load_live_returns_for_card` returning `[]`, `fetch_regime` raising NotImplementedError) ship as documented. They light up automatically when you wire real data — not blockers.

Both still apply. Repo state is clean for the LITE-for-Flow-A merge; both follow-ups intentionally deferred.

---

## Issues, concerns, and structural limitations

### Hand-smoke issues (user-observed, details TBD)

User reported "there are a lot of issues" during 2026-04-28 hand-smoke before stopping. **Specific issues NOT captured in this session.** Backend endpoints all returned valid JSON during the curl-based smoke (no 500s, no Traceback). Issues are therefore likely UI-side: rendering, layout, missing wire-ups, console errors that didn't propagate to the dashboard log.

**Next session must start by re-running the hand-smoke and capturing the specific issues the user saw.**

### Backend bug surfaced during smoke

**`audit_reader.get_run_folder()` returns None for runs with `report_card_html_path = NULL` in the runs table.** Many CLI-originated runs (e.g., `tradelab run <strategy> --robustness` without `--report`) have a null report path. This makes:
- `/tradelab/correlation/<run_id>` return `"run not found"` (misleading message)
- `/tradelab/relative-context/<run_id>` return `"run not found"`
- `/tradelab/runs/<run_id>/robustness` return 404 with "no robustness signals" message

For the dashboard's Pipeline view, this surfaces as `—` in the Hold-out and Corr columns. Functionally OK for old runs, but **the error message is wrong** — the run IS in the DB, the report folder just isn't recorded. Should distinguish "run never produced a report folder" from "run not found."

**Affected endpoints:** `/tradelab/correlation/<run>`, `/tradelab/relative-context/<run>`, `/tradelab/runs/<run>/robustness`.

**Fix scope:** small (~5 lines in each endpoint to differentiate the two error cases), or one-shot in `audit_reader.get_run_folder()`.

### Intentional stubs (will light up automatically when wired)

**Stub 1: `tracking_error.load_live_returns_for_card`** returns `[]` always.
- Endpoint correctly reports `status: "insufficient"` for every card today.
- Wire by adding `list_closed_orders(days=90)` to `live/alpaca_client.py` (mirroring the existing `list_open_orders` pattern using `GetOrdersRequest(status=QueryOrderStatus.CLOSED)`), then in `load_live_returns_for_card`: filter by `client_order_id.startswith(f"{card_id}-")`, pair entries with exits per symbol FIFO, compute round-trip `profit_pct` per pair.
- Estimated: ~1-2 hours including tests.
- Stub-wiring was attempted this session via subagent dispatch; the subagent hit an Anthropic API 500 mid-execution. Code was not written. Pick up clean next session.

**Stub 2: `regime.banner.fetch_regime`** raises `NotImplementedError`.
- Endpoint stub-fallback returns UNKNOWN values for all fields. Banner shows UNKNOWN cells today.
- Wire by:
  - Pull SPY 250 daily bars via `StockHistoricalDataClient.get_stock_bars(...)` (pattern exists in `live/receiver.py:199-222`).
  - Compute 50/200 MAs (mean of last 50 / 200 closes), Wilder's ADX (need to write the helper — pandas may help if available).
  - Pull VIX bars; alpaca-py may not support `^VIX` directly — fall back to a hardcoded VIX value (e.g. 18.0) if so.
  - Breadth: alpaca-py likely doesn't expose S&P 500 universe — hardcode at 60.0 with TODO.
- Estimated: ~2-3 hours including ADX implementation and tests.

### Structural limitations — what won't populate until external conditions are met

| Surface | What blocks it from rendering real data | When it lights up |
|---|---|---|
| **Live card TE / Decay / K-S** | Stub 1 (above) + 30+ closed pairs per card | Stub 1 wired AND card has accumulated ~30 closed round-trips |
| **Regime banner** | Stub 2 (above) | Stub 2 wired |
| **Portfolio Health panel** | Need ≥2 enabled cards with persisted returns.csv | When user enables a 2nd Pine card |
| **Score modal Portfolio fit** | Need ≥1 enabled cohort card to compare against | Same as above |
| **Score modal Relative context** | Cohort metrics need verdict.json with PF/DSR/DD; T6 implementer adapted to read PF/DD via audit DB. Today only 1 enabled card → cohort_size=0 → "cohort sparse" message renders correctly. | When ≥3 enabled cards have completed verdicts (sparse-class transitions to populated) |
| **Pipeline Hold-out column** | Run's `robustness_result.json` must contain a `hold_out_oos` signal — only generated by runs scored AFTER T4 shipped | When user re-runs `tradelab run <strategy> --robustness --report` for any existing strategy |
| **Pipeline Corr column** | Run must have a non-null `report_card_html_path` AND a `tv_trades.csv` in that folder | When run is from Score modal flow (auto-frozen). CLI runs without `--report` are silently "—" in this column |
| **Calibration banner** | n_accepted ≥ 3 in last 90d | Today n=4, banner DOES render real numbers |

### Code quality follow-ups (deferred from per-task reviews — none blocking)

From the per-task code-quality reviews:

| ID | Task | Issue | Fix scope |
|---|---|---|---|
| T2 I1 | T2 | (resolved during T2 itself) commit scope creep — T2 commit had bundled Slice 7a hunks; split via working-tree surgery | already fixed |
| T2 I2 | T2 | (resolved) `_decay_series` length contract violation for n<11 | already fixed via padding |
| T2 M1 | T2 | PF undefined for all-winning live distribution returns same `te=None` as bad data — UX gotcha | tiny |
| T2 M2 | T2 | `_decay_series` placeholder of 1.0 for undefined PF is silently lossy | tiny |
| T4 I-1 | T4 | Pipeline column N+1 fetch (per-row HTTP) | medium — add bulk endpoint or client-side concurrency cap |
| T4 I-2 | T4 | PF regex extracts the first number from `reason` text — fragile to f-string edits in verdict.py | small — add structured `details: dict` to VerdictSignal, or `holdout_pf` field |
| T4 I-3 | T4 | Silent hold-out failures collapse to "—" (no UX distinction between "not run", "skipped", "failed") | small — add `holdout_status: Literal["ok", "skipped_too_short", "skipped_disabled", "failed"]` |
| T4 M-2 | T4 | Audit DB N+1 lookups (per card) — fine at <30 cards | medium — add `get_run_metrics_bulk(run_ids)` |
| T5 M1 | T5 | Endpoint imports lazy-inside-handler; codebase mixes patterns | trivial |
| T5 M2 | T5 | `_enabled_card_ids()` helper duplicated across T5/T6/T7/T9 endpoints | small — extract once |
| T5 M3 | T5 | Error message context generic ("compute failed: ...") | trivial |
| T5 M4 | T5 | Cohort-DSR source asymmetry: candidate from `robustness_result.json`, cohort from `verdict.json` — drift risk | medium — pick one source |
| T6 I1 | T6 | FRAGILE confirm + OVERRIDE prompt sequencing — UX could be confusing if both fire | small — consolidate prompts |
| T6 I2 | T6 | Accept-button race window can fire duplicate `/tradelab/correlation` fetch | small — track in-flight Promise |
| T6 M1 | T6 | Endpoint complexity (relative-context inline `_rank_stat`) — extract for unit tests | small |

None of these block use of the system today. They're cleanup items for a future polish pass.

### Repo hygiene follow-ups

**Slice 7a + scratch drift in tradelab repo:**
- ~20 modified files unstaged on master post-merge. Includes `src/tradelab/web/handlers.py` (~206 line drift with the digest endpoints, capital/max_positions card fields, robustness endpoint, probe_receiver_status helper), plus various Slice 7a test files.
- Per the resumption-plan handoff: schedule a dedicated cleanup session. Do NOT bundle into next slice's commit.
- Stash with `git stash push -u -m "<reason>"` if you need to checkout a clean tree for any reason.

**Months-dirty `command_center.html` in parent repo:**
- ~1300+ lines of unstaged work covering signals modal extensions, pipeline table changes, panic banner, etc. Pre-existing pre-LITE.
- Same handling: dedicated cleanup session, partial-staging discipline.

### Sub-skill / process notes for next session

- Hand-smoke after each significant frontend change (per `feedback_live_smoke_before_next_slice` memory). The dashboard log doesn't surface JS console errors — must use browser devtools.
- Pre-flight grep before pasting plan code (per `feedback_plan_grep_verification` memory). The T3 implementer pasted my plan's selectors verbatim — `.research-card-verdict, .verdict-row` didn't exist in current markup, REVIEW tag never rendered until the fix-up commit. Same lesson hit again on T8 thresholds (test-locked-the-impl, not the spec).
- CSS token discipline: do not introduce `--accent`, `--text-faint`, `--text-dim`, `--border-2`, `--panel-2`, `--gate` — the dashboard's `:root` defines `--green`, `--red`, `--amber`, `--text`, `--text2`, `--text3`, `--border`, `--cyan`, `--card`, `--blue`, plus `--*-bg` and `--*-border` companions. Document this in the next implementation plan as a plan-wide convention.
- Subagent-driven development with two-stage review caught real bugs that the implementer self-review missed (T3 selector mismatch, T8 threshold drift, T4 hold-out window overlap). Worth keeping the discipline.

---

## Next session pickup

1. **Re-run hand-smoke and capture specific UI issues.** This is the gating step. Open `http://localhost:8877/` in a browser, click Research tab, devtools console open, walk through:
   - 3 banners at top render?
   - Live cards have new health rows + look right?
   - Pipeline shows new columns?
   - Score modal opens cleanly with all 4 panels stacked correctly?
   - Any console errors?
2. **Fix the surfaced issues.** Most likely candidates: CSS layout, missing wire-ups (e.g., a callback never calls a render function), data shape drift between endpoint response and frontend reader.
3. **Decide on stub-wiring (T2 + T8).** Either schedule for after the UI fixes, or interleave. Stub 1 (load_live_returns_for_card) had a subagent dispatch start this session; the implementer hit an API 500 — clean re-dispatch will work.
4. **Audit follow-up items above** — pick which (if any) to bundle into the next session vs defer further.
5. **Optional:** schedule a dedicated `command_center.html` + `handlers.py` cleanup session to commit the months-dirty drift in coherent chunks. Untangle Slice 7a from pre-Slice-7a; commit each in a separate logical batch.

---

## Files referenced

**Specs / plans / mockups:**
- `tradelab/docs/superpowers/specs/2026-04-28-research-tab-lite-flow-a-design.md`
- `tradelab/docs/superpowers/plans/2026-04-28-research-tab-lite-flow-a.md`
- `tradelab/docs/superpowers/mockups/research_tab_lite_applied_to_flow_a.html`

**Predecessor docs (still relevant for context):**
- `tradelab/docs/superpowers/SESSION_2026-04-28_VALIDATION_REDESIGN_HANDOFF.md` — CALIBRATED pause
- `tradelab/docs/superpowers/RESUMPTION_PLAN_2026-04-28.md` — the doc that triggered the LITE reframe
- `tradelab/docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md` — Slice -1 findings
- `tradelab/docs/superpowers/GAMEPLAN_validation_gaps.md` — original 4-slice gameplan (superseded)

**Memory entries that affect this work:**
- `project_validation_redesign_2026-04-28.md` (updated this session: PAUSED → SHIPPED)
- `feedback_plan_grep_verification.md`
- `feedback_live_smoke_before_next_slice.md`
- `reference_robustness_result_shape.md`
- `reference_alpaca_trade_history_source.md`
- `reference_powershell_utf8_bom.md`
- `reference_launcher_unicode_banner.md`
- `reference_tradelab_db_path_cwd.md`
- `project_tradelab_placeholder_strategies.md`

**Architecture manual:**
- `C:\TradingScripts\TRADELAB_MANUAL.html` — Flow A workflow (Section 5)
