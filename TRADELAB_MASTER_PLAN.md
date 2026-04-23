# tradelab MASTER PLAN — 50-hour build to validated discovery platform

**Version:** 1.0
**Created:** April 19, 2026
**Owner:** Amit
**Purpose:** Single source of truth for the full tradelab build. Handed to every new session/agent to prevent scope drift. Read the entire file before executing.

---

## Part I — How to use this document

1. **Every session starts** by reading this file end to end, then running the **Session Kickoff Protocol** (Part XIV).
2. **Every session ends** by writing a handover per the **Session Handover Protocol** (Part XIII) and updating the **Phase Status Table** (Part II).
3. **If the user asks for a change** that modifies scope, update this file explicitly before building. Do not let plans diverge from this document.
4. **If a spec is ambiguous**, ask the user — do not guess. Match terse, direct tone.
5. **If a deferred item is requested mid-session**, refuse per anti-drift rules (Part XII). Note it for the next phase.

This document supersedes `ROADMAP.md` and `SESSION3_KICKOFF-final.md`. Those files are historical reference only.

---

## Part II — What tradelab is and why

tradelab is Amit's **universal discovery instrument** — the CLI tool through which every future trading strategy passes before real capital is committed. It is not a backtest engine (that's an internal component), not a live trading system (that's Alpaca/IBKR), and not a strategy generator. It is a **discipline multiplier**: it converts "this strategy looks good" into a defensible, auditable verdict.

### The four questions tradelab answers

For any strategy input:

1. **Does it have edge?** — PF, Sharpe, DSR-adjusted Sharpe, WFE, OOS/IS ratios
2. **Is the edge real or fragile?** — 5-test robustness suite + regime gap diagnostic
3. **Where does it break?** — weak windows, weak symbols, cliff params, regime failures, underpowered folds
4. **What should I fix?** — *observations only* in Phase 1-4 (mechanical facts). Prescriptions deferred to Phase 6 `tradelab diagnose`.

### Why false negatives dominate false positives

tradelab gates real capital. Missing fragility is expensive (blown trade); falsely flagging a good strategy is cheap (you discard a winner). All thresholds err toward flagging fragility. All ambiguous cases go to WARN, not PASS.

### Phase Status Table (update at each session end)

| Phase | Hours | Status | Notes |
|---|---|---|---|
| Pre-0 (foundation) | 5 | [ ] Not started | Task 0.0 is hard prereq for everything |
| 0 (recalibration) | 2 | [ ] Not started | |
| 1 (Session 3 core + audit) | 7 | [ ] Not started | Core robustness + audit trail |
| 2 (HTML + noise injection) | 4 | [ ] Not started | |
| 3 (UX polish) | 3 | [ ] Not started | |
| 4 (ground truth, upgraded) | 10 | [ ] Not started | 3 ports now, not 2 |
| 5 (research ports) | 6-10 | [ ] Not started | Open-ended |
| 6 (deep diagnostics) | 4-6 | [ ] Not started | Build only when triggered |
| **Critical path total** | **31** | | Phases Pre-0 through 4 |
| **Full build total** | **~50** | | Including Phase 5 |

---

## Part III — Pre-Phase-0 Foundation (~5 hours) — NEW

This entire section did not exist in the original ROADMAP. It was added after recognizing tradelab is a universal tool, not a one-off for three strategies. **Do not skip any task in this section.** Every downstream phase depends on these four tasks being complete and verified.

### Task 0.0 — Fix walk-forward leakage bug (~1-2 hours)

**The bug:** In the current walk-forward engine, positions open at end of test window are force-closed at the *data boundary* rather than the *test window boundary*. This allows positions entered near the end of a test window to "look ahead" into what would have been train data in the next fold, inflating OOS metrics by ~3× for strategies with holds of 1-5 days.

**Fix requirements:**

1. Locate the force-close logic in `src/tradelab/engines/walk_forward.py` (or wherever WF is implemented).
2. Replace data-boundary close with test-window-boundary close: any position still open when `bar_index > test_window_end` must close at the open of the bar immediately following `test_window_end`, using that bar's open price, and must be attributed to the current fold's OOS metrics.
3. Positions that would have extended into the next train window are terminated early — this is correct behavior and models the real constraint that no trader has forward info.

**Regression test (mandatory):**

Write `tests/engines/test_wf_leakage.py`. The test:

- Constructs a deterministic price series with a known "cliff" pattern: price falls 10% on the first bar of every new WF fold boundary.
- Runs a strategy with a 5-day hold that deliberately enters 2 bars before every fold boundary.
- Asserts: the OOS P&L on each fold reflects the position being closed at fold boundary (i.e., captures the cliff), not at data boundary (which would avoid the cliff because the backtest would see the next 3 bars).
- Expected OOS return is hand-computed; actual must match within 0.01%.

**Validation gate:** rerun all three locked-strategy WF analyses (S2, CG-TFE v1.5, Viprasol v8.2). OOS metrics will degrade. Document the delta in `reports/wf_bug_fix_impact_YYYY-MM-DD.md`. If any strategy's post-fix OOS PF drops below 1.0, its "locked production" status must be reconsidered before any robustness work begins.

**Critical:** do not proceed to any other task until this test passes and the reports are written. DSR calibration (Task 0.1) depends on uninflated OOS inputs.

### Task 0.0.5 — Canary strategy suite (~2 hours)

**Purpose:** Four deliberately-broken strategies that tradelab must correctly flag as FRAGILE. If tradelab fails to flag any canary, the tool itself is broken and any "ROBUST" verdict it has emitted in the past is suspect. Run monthly as a health check.

**Location:** `src/tradelab/canaries/` directory. Each canary is a self-contained strategy file following the normal tradelab strategy interface.

#### Canary 1 — RAND-CANARY (random entry)

- **Purpose:** tradelab must detect absence of edge
- **Entry logic:** every bar, with probability p=0.02 (tuned to produce ~150-250 trades on typical 2-year 1H universe), enter long. Fixed seed 42 for reproducibility across runs.
- **Exit:** 10-bar fixed hold
- **No stops, no indicators, no filters**
- **Universe:** same 7-symbol Tier 1 universe used elsewhere
- **Required tradelab output to PASS as a canary (i.e., correctly flag):**
  - PF within 1.0 ± 0.15
  - DSR probability < 0.50
  - MC shuffle distribution nearly identical to original (no clustering — regime gap near zero, which for this canary is correct)
  - LOSO: high variance across folds, no generalization
  - **Verdict: FRAGILE**
- **Tool-broken criterion:** if tradelab emits ROBUST or ROBUST-with-caveat on RAND-CANARY, the tool is broken. Halt all strategy evaluation until root-caused.

#### Canary 2 — OVERFIT-CANARY (curve-fit)

- **Purpose:** tradelab must detect parameter overfitting
- **Entry logic:** composite trigger with 5 parameters: `(RSI < rsi_threshold) AND (volume > vol_mult × vol_ma_n_bars) AND (price > ema_n) AND (atr_percent in [atr_low, atr_high])`. Six parameters exposed for optimization.
- **Optimization protocol:** 500 Optuna trials maximizing in-sample Sharpe on a 50-bar IS window. No OOS validation. This is deliberately pathological.
- **Exit:** 5-bar fixed hold
- **Required tradelab output to PASS as a canary:**
  - IS Sharpe > 3 (the overfit looks good in-sample — this is expected)
  - Walk-forward OOS Sharpe < 0.5 (collapses out of sample)
  - DSR probability < 0.50 (because 500 trials, `sr_expected_under_null` inflates heavily)
  - LOSO: catastrophic (PF < 0.5 on most folds)
  - **Verdict: FRAGILE**
- **Tool-broken criterion:** if DSR probability > 0.80 OR verdict is ROBUST/ROBUST-with-caveat, tool is broken.

#### Canary 3 — LEAK-CANARY (look-ahead bias)

- **Purpose:** tradelab must catch look-ahead leakage via entry-delay test and `tradelab validate`
- **Entry logic:** "buy the open of bar T if close of bar T is higher than close of bar T-1" — this peeks at bar T's close at bar T's open, classic same-bar look-ahead.
- **Exit logic:** "sell when current bar's low equals the minimum low of the *next 5 bars*" — blatant forward look.
- **Required tradelab output to PASS as a canary:**
  - IS backtest: PF > 5, Sharpe > 6 (looks amazing — leaks always do)
  - Entry-delay test (Phase 1 Test 3): `pf_ratio(+1)` < 0.3, `pf_ratio(+2)` near zero
  - `tradelab validate` flags same-bar close usage (Phase 1 feature)
  - **Verdict: FRAGILE** with explicit "look-ahead suspected" flag in report card
- **Tool-broken criterion:** if entry-delay degradation at +1 bar is less than 50%, look-ahead detection is broken.

#### Canary 4 — SURVIVOR-CANARY (survivorship bias)

- **Purpose:** tradelab must flag universes curated with hindsight
- **Universe:** 5 post-hoc hand-picked winners from 2023-2025 — NVDA, MSFT, AVGO, AMD, LLY (all massive trend winners over the backtest window)
- **Entry logic:** simple 50/200 EMA golden cross, long-only, all-in on signal, exit on death cross
- **Required tradelab output to PASS as a canary:**
  - IS PF > 2 (naive trend-following works great on hand-picked trenders)
  - LOSO: high fold-to-fold variance; removing any single symbol meaningfully changes the aggregate verdict
  - Per-symbol OOS PF spread > 2.0 (some symbols carry the strategy, others don't)
  - **Verdict: MARGINAL or FRAGILE** with explicit flag that aggregate metrics are dominated by fewer than all universe members
- **Tool-broken criterion:** if LOSO reports low fold-to-fold variance on this universe, the LOSO implementation is pooling where it shouldn't.

**Canary test harness:** `scripts/run_canaries.py` runs all 4 end-to-end and produces a one-page "canary health report." All 4 must pass (tradelab correctly flags each). Any failure halts all other work.

### Task 0.0.75 — Determinism contract (~30 minutes)

**Requirement:** Given identical inputs, tradelab must produce byte-identical report cards across runs.

**Implementation:**

1. **Every seed in the codebase is explicit and documented.** No `np.random.seed()` or `random.seed()` without an associated constant in `configs/seeds.yaml`.
2. **Report card footer prints:**
   - tradelab version (from `__version__`)
   - git commit hash of the engine at runtime
   - SHA-256 hash of the input OHLCV data
   - SHA-256 hash of the active configs (robustness.yaml, strategy params)
   - All seed values used
3. **Report card body is deterministic.** Run the same strategy twice back-to-back — the two markdown outputs must diff to exactly zero bytes (ignoring timestamp line).
4. **Regression test:** `tests/engines/test_determinism.py` runs S2 twice, hashes both report cards, asserts equality.

**Anti-drift rule:** Any session that introduces non-determinism (parallel execution without seeded ordering, time.time() in logic, etc.) must explicitly fix it before session end. Determinism is not optional.

### Task 0.0.9 — Synthetic regression strategy (~45 minutes)

**Purpose:** An engine-drift baseline that does not depend on real market data or any specific live strategy. When Session N updates tradelab and reruns this, output must match Session N-1 exactly.

**Spec:**

1. **Synthetic price series:** deterministic. A designer-chosen function where weekly returns are hand-computable. Suggested: daily OHLCV where `close(t) = 100 * (1.001)^t + 2 * sin(2π * t / 5)` — drift + 5-day oscillation — with O=H=L=C for simplicity.
2. **Strategy:** "Buy Monday open, sell Friday close." No parameters, no optimization.
3. **Closed-form expected outputs** (computed by hand, stored as constants in `tests/synthetic/expected.yaml`):
   - Total trades (computable from date range)
   - Win count, loss count (each week's direction is deterministic from the function)
   - Total return, Sharpe, PF, MaxDD — all computable from the closed-form price series
4. **Regression test:** `tests/synthetic/test_dial_gauge.py` runs the strategy through tradelab's full backtest engine and asserts output metrics match expected values to 6 decimal places.

**Use:** Run before every merge/release. If it ever fails, the engine has drifted — fix the engine before trusting any other output.

**Location:** `src/tradelab/synthetic/` (strategy), `tests/synthetic/` (test + expected values).

---

## Part IV — Phase 0 (Recalibration, ~2 hours)

Original ROADMAP Phase 0 retained, with two reinforcements: DSR unit tests, and dependency on Pre-0 complete.

**Prerequisite:** All Pre-Phase-0 tasks complete and validated. If Task 0.0 (WF bug fix) is not done, DSR numbers are meaningless.

### Task 0.1 — Deflated Sharpe Ratio (~1 hour)

Spec is as in original ROADMAP section "Task 0.1", with these additions:

**Mandatory unit tests in `tests/engines/test_dsr.py`:**

1. **Random-walk returns:** 1000 synthetic iid normal returns with true Sharpe = 0.3, 100 Optuna trials → DSR must return < 0.50.
2. **Strong trend:** deterministic strong-positive return series, 50 Optuna trials → DSR must return > 0.95.
3. **Edge case:** 500 trials on marginal edge (true Sharpe ≈ 1.0, observed 1.2) → DSR must return between 0.50 and 0.95 (inconclusive band).
4. **Formula verification:** hand-compute DSR for a known (SR, γ3, γ4, N) tuple and assert function output matches to 4 decimals.

**Deliverable unchanged:** `reports/dsr_baseline_YYYY-MM-DD.md` with DSR for S2, CG-TFE v1.5, Viprasol v8.2 — but using *post-WF-bug-fix* baselines.

### Task 0.2 — PIT inception-date assertions (~45 minutes)

Spec unchanged from original ROADMAP. Verify each inception date via web search before committing.

### Task 0.3 — Cost sensitivity sweep (~15 minutes)

Spec unchanged from original ROADMAP.

---

## Part V — Phase 1 (Session 3 core + audit trail, ~7 hours)

Original Session 3 scope (5 tests + verdict + report card, ~6 hours) plus 1 hour for audit trail, promoted from Phase 6.

### Session 3 core (6 hours)

Spec authoritative in `SESSION3_KICKOFF-final.md` sections "Execution order" and "Anti-drift rules." The 4 tests to build:

1. **Test 1:** MC 3-methods × 4-metrics (shuffle, bootstrap, block bootstrap) × (MaxDD, max_loss_streak, time_underwater, ulcer_index)
2. **Test 2:** Param landscape (bootstrapped importance ranking + 5×5 joint grid on top-2 params + smoothness ratio + PNG heatmap)
3. **Test 3:** Entry delay (shifts [0, +1, +2], no negative shifts)
4. **Test 4:** LOSO cross-symbol (per-fold own Optuna study — critical, never share studies across folds)
5. **Test 5:** Verdict engine + terminal report card

Deferred from Session 3: noise injection test, HTML tearsheet, color output, progress bars — all move to Phase 2 or 3.

### Phase 1 addition — tradelab history (audit trail, 1 hour)

**Purpose:** Immutable record of every robustness run. When a live strategy degrades in 2027, Amit must be able to answer "what did tradelab say on approval day?" precisely.

**Schema:** SQLite database at `data/tradelab_history.db`. Table `runs` with columns:

- `run_id` (UUID, primary key)
- `timestamp_utc`
- `strategy_name`
- `strategy_version` (git commit or explicit version tag)
- `tradelab_version`
- `tradelab_git_commit`
- `input_data_hash` (SHA-256 of OHLCV inputs)
- `config_hash` (SHA-256 of all active configs)
- `verdict` (ROBUST / ROBUST-with-caveat / MARGINAL / FRAGILE)
- `dsr_probability`
- `report_card_markdown` (full text, blob)
- `report_card_html_path` (filesystem reference)

**CLI surface:**

- `tradelab history list [--strategy NAME] [--since DATE]` — list recent runs
- `tradelab history show RUN_ID` — print the full report card from that run
- `tradelab history diff RUN_ID_A RUN_ID_B` — diff two reports

**Write rule:** every `tradelab robustness` invocation writes one row on completion. Never modify existing rows. Append-only.

**Anti-drift rule:** no "delete old runs" command. No "mark invalid" command. The history is immutable evidence. If data needs to be excluded from a query, filter at query time, never at storage.

---

## Part VI — Phase 2 (HTML + noise injection, ~4 hours)

Original Phase 2 retained. **Must ship within one week of Phase 1 completion** — put a calendar hold now.

| Task | Effort |
|---|---|
| Test 5: Noise injection (ATR-scaled, bar-structure-preserving, 50 seeds) | 1.5 hr |
| HTML tearsheet for robustness suite | 1.0 hr |
| Test correlation map rendered as table in tearsheet | 0.25 hr |
| `typer.launch(path)` auto-open on tearsheet write | 10 min |
| `tradelab open` — shortcut to open most recent tearsheet | 15 min |
| Canary suite HTML tearsheet aggregator (one-page health dashboard) | 1.0 hr — *new* |

**New in Phase 2:** the canary aggregator. A single HTML page showing the 4 canary verdicts and their key metrics, so the monthly canary health check is one click not four command invocations.

---

## Part VII — Phase 3 (UX polish, ~3 hours)

Spec unchanged from original ROADMAP. Batch in one idle evening only after Phase 2 completes.

---

## Part VIII — Phase 4 (Ground truth validation, upgraded, ~10 hours)

Original Phase 4 is 8 hours for 2 strategies (CG-TFE v1.5, Viprasol v8.2). Upgraded to 10 hours: adds one structurally different reference strategy to prove tradelab generalizes beyond Amit's existing long-only mean-reversion designs.

### Task 4.1 — TV ground truth extraction (~2 hours)

Unchanged from original. Extract exact trade-level outputs for CG-TFE v1.5 across all 7 symbols. **Contingency:** if TradingView CSV export is paywalled on Amit's current subscription, fall back to manual extraction of summary stats (trade count, PF, WR, MaxDD, final equity) and skip trade-level CSV diff. Document which mode was used.

### Task 4.2 — CG-TFE v1.5 Python port (~3 hours)

Unchanged from original. Port-time unit tests for bar indexing convention, EMA alignment, session filter.

### Task 4.3 — Regression validation (~1 hour)

Pass criterion upgraded:

- **Per-symbol criterion:** ≥ 6/7 symbols match within: trade count ±2, PF ±0.05, WR ±0.5%, MaxDD ±0.5%
- **Aggregate criterion (NEW):** mean PF delta across all 7 symbols must be < 0.02 (no systematic bias). Catches the failure mode where all symbols drift by exactly the tolerance in the same direction.

Both criteria must pass. If either fails, halt — engine bug, find it, do not proceed.

### Task 4.4 — Viprasol v8.2 port + validation (~1.5 hours)

Unchanged from original.

### Task 4.5 — Third reference strategy port (~2 hours) — NEW

**Purpose:** CG-TFE and Viprasol are both long-only trend/momentum designs in Amit's own style. Porting a structurally different public strategy proves tradelab generalizes.

**Target:** a documented public mean-reversion or breakout reference strategy with published TradingView or academic-paper metrics. Candidates (pick one):

- Connors RSI-2 strategy (documented widely, short-bias variant available)
- Larry Williams' %R reversal (classic short-term counter-trend)
- A published SSRN paper strategy with reproducible rules and reported metrics

**Pass criterion:** same as Task 4.3 — per-symbol + aggregate. Reference metrics can come from the published source; acceptable tolerance ±0.10 PF (looser than native TV port because cross-platform reproduction has more variance).

**Rejection protocol:** if no strategy passes this test at ±0.10 PF, the engine does not generalize — investigate before Phase 5 research ports.

### Task 4.6 — `tradelab compare` command (~30 minutes)

Unchanged from original.

---

## Part IX — Phase 5 (Research strategy ports, ~6-10 hours)

Only after Phase 4 passes all three strategies (CG-TFE + Viprasol + third reference). Each research strategy (DeepVue VCP, 21-EMA Pullback, Episodic Pivot, etc.) gets the full pipeline: backtest → optimize → WF → robustness → report card → history entry. Verdict determines graduation to paper trading.

Priority order unchanged from original ROADMAP.

---

## Part X — Phase 6 (Deep diagnostics, ~4-6 hours, build when triggered)

Unchanged from original. Build only when the specific need hits. Per-trade regime conditioning, `tradelab diagnose` (LLM prescriptions), etc.

**Note:** `tradelab history` (originally in Phase 6) has been promoted to Phase 1. The remaining Phase 6 items stay deferred.

---

## Part XI — Explicitly out of scope (do not build)

| Item | Why not |
|---|---|
| Purged K-Fold | Marginal over walk-forward for 1-5 day hold times |
| CPCV (Combinatorial Purged Cross-Validation) | Massive effort, tiny incremental value for this data structure |
| Web dashboard | Static HTML + `tradelab open` covers 95% |
| Slack/Telegram notifications | Terminal beep + auto-open is enough |
| `--all` batch runs across strategies | Encourages running without attention |
| Native PDF export | Chrome print-to-PDF handles rare share cases |
| AmiBroker anything | Migrated away; do not resurrect AFL, database paths, or AmiBroker-specific infrastructure in any form |

---

## Part XII — Anti-drift rules (MASTER LIST)

**Violation of any rule = immediate rework.** Every session must re-read this list before coding.

1. **Block bootstrap is always on.** Never gate behind `--deep`. `--iterations fast` reduces count but runs all 3 MC methods.
2. **Thresholds come from config, not code.** All PASS/WARN/FAIL thresholds in `configs/robustness.yaml`. Zero magic numbers in Python.
3. **No rules-based prescription in report card.** Section 4 is observations only. If writing "suggest reducing position size" or "consider adding regime filter," stop.
4. **No multiplicity correction math (Bonferroni/Šidák) in output.** Correlation map in Phase 2 instead.
5. **No random 50/50 split for cross-symbol.** LOSO only. If writing `np.random.choice(universe, size=n//2)`, stop.
6. **No OAT (one-at-a-time) parameter sensitivity.** Test 2 is joint 5×5 grid on top-2 params.
7. **No percentage-based param perturbation.** Steps come from param config in absolute units.
8. **Deferred items stay deferred.** If user asks for a deferred item, respond: "Scoped for Phase N. Adding now risks destabilizing current phase. Note for next session?"
9. **Per-fold own Optuna study in LOSO.** Never share studies across folds.
10. **Observations-only must be specific, not vague.** "FAIL on Test 4" is not acceptable; "LOSO FAIL: median OOS PF 0.78, MSFT-removal fold PF 0.41 (catastrophic), AMZN-removal fold PF 0.89" is.
11. **Determinism is non-negotiable.** No unseeded randomness. No `time.time()` in logic paths. Report card diff with prior identical run must be zero bytes (ignoring timestamp).
12. **Canary suite failures halt all other work.** If monthly canary run fails, root-cause before evaluating any strategy.
13. **No AmiBroker references.** Amit migrated away. Do not suggest it, reference AFL, or use AmiBroker-era infrastructure patterns.
14. **Audit trail is append-only.** No delete, no "mark invalid," no in-place edit of `tradelab_history.db` rows.
15. **False negatives cost more than false positives.** Ambiguous verdicts go to WARN, not PASS.
16. **If a task isn't in this plan, don't build it.** The plan is the scope. Extensions require user approval and a plan update.

---

## Part XIII — Session Handover Protocol (end of every session)

At session end, write `HANDOVER_SESSION_N_TO_N+1.md` containing:

1. **What shipped** — checklist from this plan's relevant phase section
2. **What did not ship** — and why (time, blocker, scope decision)
3. **Actual test output observed** — all numbers, for any canary/regression/strategy run
4. **Design decisions made** that were not pre-specified, with reasoning
5. **Known edge cases and gotchas** discovered during the session
6. **Reference baseline for next session** — the specific numbers next session must reproduce before proceeding (e.g., "S2 baseline: 713 trades / PF 0.98 / WR 56.1% — if this fails, stop")
7. **Deferred items moved forward** — any item kicked from this session to next
8. **Phase Status Table updated** — mark this plan's Part II table with completion status
9. **Git commit hash** — the commit representing end-of-session state

Handover file is the *only* communication channel between sessions. If it's not in the handover, the next session doesn't know.

---

## Part XIV — Session Kickoff Protocol (start of every session)

**Every session starts with these checks. No exceptions. No silent skipping.**

### Check 1 — Read the plan

Read this entire file. Read the prior session's handover. Read the handover before that if the current session follows a gap of >1 week.

### Check 2 — Environment sanity

```powershell
cd C:\TradingScripts\tradelab
.venv-vectorbt\Scripts\activate
tradelab --version
git status
git log -5 --oneline
```

Environment must be clean. If uncommitted changes exist from a prior session, understand what they are before overwriting.

### Check 3 — Baseline regression

Run whichever regression tests exist at current phase:

- Synthetic regression strategy (if Pre-0 complete) — must pass
- S2 baseline (713 trades / PF 0.98 / WR 56.1%) — must hold
- Determinism regression (if post-Task 0.0.75) — must pass

If any fail, STOP. Report divergence to user. Do not proceed.

### Check 4 — Canary health (if Pre-0 complete)

If canary suite exists, run it. All 4 must correctly flag as FRAGILE. If any canary unexpectedly passes as ROBUST, tool is broken — halt.

### Check 5 — Phase prerequisite check

Read Phase Status Table in Part II. Confirm prior phases marked complete. If attempting Phase N when Phase N-1 is incomplete, ask user explicitly: "Phase N-1 shows incomplete status. Proceed anyway or complete N-1 first?"

### Check 6 — Scope lock

Re-read Part XII (anti-drift rules). Re-read the current phase's section in this plan. Confirm the session's planned work matches the plan. Do not expand scope without explicit user approval and plan update.

---

## Part XV — Glossary

For any new agent with zero context:

- **DSR** — Deflated Sharpe Ratio (Bailey & López de Prado, 2014). Adjusts observed Sharpe for number of trials tested during optimization. Returns probability in [0, 1] that edge is not from luck.
- **LOSO** — Leave-One-Symbol-Out cross-validation. Train on N-1 symbols, test on held-out symbol, rotate through all N.
- **MC** — Monte Carlo. In this project: three methods (trade-order shuffle, bootstrap resample, block bootstrap).
- **WF / WFE** — Walk-Forward / Walk-Forward Efficiency. Ratio of OOS to IS performance across rolling windows.
- **PF** — Profit Factor. Gross wins ÷ gross losses.
- **PIT** — Point-In-Time. Ensures backtests only use data available at the simulated historical moment; for tradelab specifically refers to preventing backtests of symbols before their inception.
- **Canary** — a deliberately-broken strategy used to test that tradelab correctly flags fragility.
- **Regime gap** — the ratio of block-bootstrap P95 MaxDD to shuffle P95 MaxDD. >0.50 = highly regime-sensitive.
- **Smoothness ratio** — neighborhood fitness mean ÷ peak fitness in the 5×5 param landscape grid.
- **OAT** — One-At-a-Time param sensitivity. Rejected design — use joint grid instead.
- **IS / OOS** — In-Sample / Out-Of-Sample.

---

## Part XVI — Start here

If this is Session N and N+1's kickoff is reading this fresh:

1. Read Parts I through XII in order.
2. Run Session Kickoff Protocol (Part XIV).
3. Read this session's specific phase section in detail.
4. If confused about any spec, ask the user — do not guess.
5. Begin work only after all kickoff checks pass.

The plan is the single source of truth. The plan plus the prior session's handover is the complete context. If information needed is not in either, the user has it — ask.

End of master plan.
