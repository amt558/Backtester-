# Session Log — Validation Suite → Python-Only Lifecycle → Paper Execution Engine

**Date:** 2026-05-31 → 2026-06-01
**Branches:** `tradelab` repo → `feat/research-tab-v3`; root repo (`C:/TradingScripts`, serves `command_center.html`) → `validation-suite`
**Method:** brainstorming → writing-plans → subagent-driven-development (fresh subagent per task + two-stage spec/quality review), TDD throughout.

This log details, in order, every body of work shipped in this session.

---

## 0. Push / remote status (read first)

- **tradelab backend IS pushed** → `origin` = `https://github.com/amt558/Backtester-.git`, branch `feat/research-tab-v3`.
- **Root repo has NO git remote configured** → the `command_center.html` + `launch_dashboard.py` commits (branch `validation-suite`) are committed **locally only** and could **not** be pushed. A remote must be added before that frontend work can be pushed.

---

## 1. Validation Suite (report-only research layer)

**Goal:** backtest a fixed set of validation methods per run and surface them in the Research tab beside QuantStats — **without** touching the robustness verdict.

**Core design rule (enforced):** the suite is a PARALLEL, REPORT-ONLY layer. `ValidationReport` is a *sibling* of `VerdictResult`, never a member; it NEVER calls `compute_verdict`. Rationale: verdict aggregation is asymmetric (any fragile caps at INCONCLUSIVE; ROBUST needs `n_robust ≥ max(3, len(signals)//2)`), so adding signals would silently re-weight locked baselines (Viprasol v8.2, CG-TFE v1.5). An AST test enforces no verdict import.

**Package:** `src/tradelab/validation/` (`suite.py`, `deep.py`, `__init__.py`, `_selftest.py`); tests in `tests/validation/`.

- **Tier 1 (ledger-only, sync):** `win_loss_streak` (Schilling expected-run heuristic), `expectancy_stability` (rolling 20-trade), `pf_by_month` (computed off `trades[]` grouped by `entry_date[:7]` because `monthly_pnl` lacks gross win/loss).
- **Tier 2 (equity/parquet, sync):** `drawdown_stress` (calendar-window equity scan, granularity-agnostic), `volatility_bucketing` (ATR% terciles from the Twelve Data → parquet cache; **never fetches** — cache miss = inconclusive).
- **Tier 3 (engine re-runs, opt-in):** `cost_sensitivity` (formalizes the existing commission sweep — engine has one cost lever, so commission==slippage), `gate_contribution_isolation` (ablates one gate per re-run via a new opt-in `Strategy.ablatable_gates` interface; `s2_pocket_pivot` declares a map; locked baselines untouched), `random_entry_benchmark` (real exits + seeded-random entries, N sims, real-PF percentile vs random — `_RandomEntryWrapper` copies real params so exits match).

**Record shape:** `{name, outcome ∈ robust|inconclusive|fragile, reason, value, detail}` — the number is embedded in `reason` so the existing dashboard regex renders it. `outcome` is **cosmetic only** (panel colour); it never moves a verdict.

**Verified facts that shaped it:** `Trade.entry_date` is date-only even for 1H strategies (no HH:MM anywhere) → **Time-of-Day Analysis is BLOCKED**; `monthly_pnl` lacks gross win/loss; equity-curve granularity is non-uniform (native daily = daily MTM, TV-imports = per-trade) → calendar-window scan; parquet cache at `.cache/ohlcv/<tf>/<SYM>.parquet`, only 1D cached → vol-bucketing inconclusive for intraday.

**Parked (with reasons):** standalone Slippage panel (engine has only a commission lever), Time-of-Day (date-only timestamps).

**Evidence:** 31 validation tests pass; JSON-safe (27/27 real runs serialize with no Infinity/NaN); demonstrated on real s2 + 1H Viprasol runs (random-entry benchmark showed real PF beats 85% of random sims — entry signal adds edge).

---

## 2. Validation Suite integration

- **`cli_run.py`:** `--validation` (eager in `--full`, tier 1-2) / `--validation-deep` (opt-in tier 3) / `--validation-sims` (default 200); writes `validation.json` in the run folder next to `quantstats_tearsheet.html`.
- **`web/handlers.py`:** `GET /tradelab/runs/{id}/validation` → `{run_id, strategy, suite_version, signals[]}`, 200 + empty for missing.
- **Frontend (`command_center.html`):** dark/green `VAL_DEFS` matrix + `validationModal` reusing the existing `sig-table` machinery + a "Val" button beside "Sig". Verified end-to-end: `run --validation` wrote 5 checks, `--validation-deep` wrote 8, route served all 8.
- **FE safety proof:** the pre-existing V3 FE test failures (Task14/15 TDD against not-yet-built HTML) were identical before/after every frontend edit (71 failed), so additive changes introduced **zero** new failures.

---

## 3. Pine cleanup (Option 2)

User decision: retire Pine/TradingView, Python-only. Purged **Pine sources + TV-import runs only**, kept the converted Python strategies.
- Deleted 9 TV-import run folders (6 via the proper DB-delete handler, 3 filesystem) + `pine_archive/` + the orphaned `virpo-mu-v1` live card.
- **Kept** `viprasol_v83.py` / `cg_tfe_v15.py` + yaml entries, all canaries, the 2 test/smoke fixture cards.
- Flagged the contradiction (these were earlier "locked baselines") before deleting; user chose Option 2 (keep the Python files).

---

## 4. Phase 1 — Python Strategy Import (Method A + auto-discovery C)

Retire the Pine/CSV input; the Command Center auto-discovers Python `Strategy` subclasses and imports a selected one.
- `web/new_strategy.py`: `discover_unregistered_strategies()` (scans `src/tradelab/strategies/`, skips registered), `import_discovered()` (writes the `tradelab.yaml` entry, reusing `_append_strategy_to_yaml`).
- `handlers.py`: `GET /tradelab/strategies/discoverable`, `POST /tradelab/strategies/import` (400/409 guarded; a review-found unhandled-exception path was fixed to 500).
- Frontend: "Score New Strategy (CSV+Pine)" modal → **"Import Strategy"** (discovery dropdown + Import button); **726-line removal** of the CSV/Pine flow (opus review verified zero dangling references, no shared code removed).
- Live check: discovery returns the one unregistered strategy (`simple`).

---

## 5. Phase 2 — Test flow + QuantStats

- **QuantStats was NOT broken** — probed `render_backtest_tearsheet`, produced a 600 KB+ tearsheet on a real run. Added a regression guard (`tests/reporting/test_tearsheet_regression.py`).
- **Post-import "Test" button**: fires the existing `/tradelab/jobs` trigger as `run --full` (allowlisted) → backtest + robustness + validation + QuantStats. Opus review confirmed the runtime contract (the button really launches a job).

---

## 6. Phase 3a — Card Lifecycle (Accept + toggle + Overview card; paper-mode, NO orders)

- `web/approve_strategy.py`: **`accept_python_run`** — a Python-compatible accept (no `strategy.pine`/`pine_archive`), **advisory** gating (activating a non-ROBUST verdict requires `confirm_non_robust=True`, else `ActivationGateFailed`), creates a card stamped `source:"python"`, `mode:"paper"`, `strategy`, `verdict`, `symbol`, `timeframe`. (Opus verified the advisory gate is bypass-proof and there's no order code.)
- `handlers.py`: `POST /tradelab/strategies/accept` (400/422-gate/404/409). Verified live (400/422/200).
- **Toggle:** Python cards enable/disable through the existing `POST /tradelab/cards/bulk-toggle` (`CardRegistry.set_status`) — no new endpoint needed.
- **Frontend:** "Accept" button on a run with a verdict; 422 → "accept anyway" confirm → re-POST with `confirm_non_robust`; Overview source-label guarded for Python cards. Opus verified **all 3 runtime fetch contracts** (`/runs/{id}/folder`, static `backtest_result.json`, the accept POST).

---

## 7. Phase 4 — Paper Execution Engine (`src/tradelab/live/strategy_runner.py`)

A paper-locked **desired-state reconciler**: each cadence, run the strategy, compute the desired position from the latest bar, reconcile against the live Alpaca position.

**Confirmed decisions:** sizing from a card-level `allocation_usd`; **exits authored in the Python strategy** (`buy_signal` → long, `sell_signal` → flat, neither → hold — the engine never invents an exit); safety = the existing **$5k daily-loss + kill-switch**; cadence from the strategy's `timeframe`.

- **Decision core:** `desired_position`, `size_qty` (floor(alloc/price)), `safety_block_reason`.
- **`reconcile_card`:** idempotent buy-to-open / sell-to-close, injected `submit_fn`, deterministic `client_order_id`.
- **`run_once`:** reconciles enabled/python/paper cards, safety-gated; one bad card never stops others.
- **`_real_deps` + `run_tick` + `start()/stop()` daemon**, registered (try/except-guarded) in `launch_dashboard.py`; `allocation_usd` card field + Overview `$` input (via the existing `PATCH /tradelab/cards/{id}`).

**Safety — proven by two adversarial opus reviews:**
- A review **caught a fail-OPEN bug**: a *missing* `paper_trading` key defaulted to allow → would have fired orders. Fixed to **fail-closed** (`is not True`) + unreadable-P&L blocks entries + regression tests.
- The daemon review verified: tests **never** touch Alpaca (poison-pill); **no dep failure can cause a buy/sell** (all deps inside the per-card try; `get_positions` failure ≠ empty, so no double-buy); **no duplicate-order spam** (position-state idempotency + broker `client_order_id` dedup); `stop()` prompt; double-start guarded; launch registration guarded.

**Operational state:**
- The daemon **auto-starts** with the dashboard but trades **only** enabled `source:"python" mode:"paper"` cards with `allocation_usd` set — currently **nothing is eligible**, so it won't trade until a card is enabled + funded.
- **Paper-locked by construction:** the engine refuses ALL orders unless `alpaca_config.json alpaca.paper_trading == True`. Setting it `false` **stops** the engine (does NOT go live). Real-money go-live is a deliberate future addition (out of scope).

**Known follow-ups (not safety bugs):** `_get_price` reads the 1D cache regardless of timeframe (intraday sizing may be off); `_bar_bucket` treats only `…D` as daily; bar-close timing is simple-periodic (safe because reconcile is idempotent).

---

## 8. Specs & plans written (in `docs/superpowers/`)

- `specs/2026-05-31-python-only-strategy-lifecycle-design.md`
- `specs/2026-05-31-phase4-paper-execution-engine-design.md`
- `plans/2026-05-31-python-strategy-import.md` (Phase 1)
- `plans/2026-05-31-python-strategy-test-and-quantstats.md` (Phase 2)
- `plans/2026-05-31-phase3a-card-lifecycle.md`
- `plans/2026-05-31-phase4-paper-execution-engine.md`

## 9. Test status

- `tests/validation/` 31 · `tests/live/` 320 · `tests/web/` (excluding the 71 pre-existing V3 Task14/15 failures) all green · `tests/reporting/` 2 · frozen `tests/robustness/test_verdict.py` unchanged.
- The **71 pre-existing `test_command_center_html.py` failures** are in-flight V3 Task14/15 TDD (HTML features not built by this session); verified identical count before/after every change — this session introduced none.

## 10. The end-to-end lifecycle now available

Author a Python `Strategy` in `src/tradelab/strategies/` → **Import** (Command Center discovers it) → **Test** (`run --full`: backtest + robustness + validation + QuantStats) → **Accept** (advisory confirm if not ROBUST) → set **`$` allocation** + **enable** the Overview card → the **paper daemon** auto-reconciles it and places **paper** Alpaca orders on the strategy's `buy_signal`/`sell_signal`.
