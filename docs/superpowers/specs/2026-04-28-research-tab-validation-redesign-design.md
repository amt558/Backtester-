# Research Tab Validation Redesign — Design Spec (FULL)

**Date:** 2026-04-28
**Status:** **[SUPERSEDED 2026-04-28 same day]** by `2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md`. Reframe surfaced two structural problems (§1 confound + verdict accuracy loop missing) that this FULL spec did not address. CALIBRATED preserves FULL's orthogonal gates (hold-out, multi-dim correlation, relative context, override log) but softens auto-actions to LITE behavior and adds §1 confound panel + canary panel + per-signal hit-rate table. **Do not implement from this doc.**
**Mockup:** `docs/superpowers/mockups/research_tab_redesign_proposal.html` (FULL — superseded)
**Alternative considered:** `docs/superpowers/mockups/research_tab_redesign_proposal_LITE.html` (rejected; would have dropped per-strategy regime bucketing and softened K-S auto-disable to warn-only)

## 0. Final decisions

After reviewing both FULL and LITE mockups, FULL is locked:
- **Per-strategy regime bucketing IS in scope** — regime-fit column on Pipeline, regime-fit tag on Live cards, per-regime PF table in Score modal, "Strategies favored now" stat on regime banner
- **K-S auto-disable on p<0.01 IS in scope** — card status flips to `disabled`, notify(severity=critical) fires
- Statistical-thinness risk on per-regime sample sizes is accepted; mitigation is the calibration banner that watches whether the regime-conditioned verdicts pan out
- False auto-disable risk on K-S is accepted; mitigation is reversibility (status flip via dashboard) + notify includes "manual review needed" link

## 1. Why this exists

The 2026-04-27 gameplan (Slices 1-4) covered hold-out OOS, return correlation, and tracking error. After review, four production-grade gaps remained:

1. **Verdict was one-shot** — no re-evaluation as regimes shift or strategies decay
2. **No regime context** — a "ROBUST" verdict on aggregate history says nothing about whether the strategy works in *current* conditions
3. **Diversification was incomplete** — return correlation alone misses drawdown clustering and entry-time concentration
4. **No feedback loop** — the verdict bar itself was never measured against live outcomes

This spec adds the missing pieces and re-frames the existing gameplan slices so they integrate cleanly. Slice 0 (Robustness Signals modal, shipped 2026-04-27) is preserved as-is.

## 2. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Hold-out OOS is a **gate**, not signal #10 | A failure-mode-distinct signal (untouched data) should not be voted on by 9 in-sample diagnostics |
| D2 | Correlation gate is **multi-dimensional**: return ρ + drawdown ρ + entry-time overlap | Two strategies can have 0.3 return ρ and 0.9 DD ρ — the silent killer of "diversified" books |
| D3 | Regime conditioning is in-scope as a new module + UI surface | Single biggest alpha play; transforms portfolio from "always on" to regime-rotated |
| D4 | Live divergence uses **K-S test + decay slope**, not rolling PF ratio | Statistically grounded; decay sparkline catches dying strategies 3-6mo earlier |
| D5 | Calibration meta-stat is a first-class banner on Research | Closes the loop on the verdict bar itself; without it, mis-calibration is invisible |
| D6 | Verdict carries a **freshness timestamp** | Addresses one-shot flaw; old verdicts get visible decay |
| D7 | Overrides require typed reason, captured per-card | Behavioral guardrail; audit trail for post-mortems |
| D8 | Score modal cells get **relative context** vs your live book | Anchors abstract numbers to your actual track record |

## 3. Architecture overview

```
                     ┌─────────────────────────────────────────────────────┐
                     │  command_center.html (port 8877)                    │
                     │   ┌────────────────────────────────────────────┐    │
                     │   │ Research tab                               │    │
                     │   │  ┌─ NEW: Regime banner ───┐                │    │
                     │   │  ┌─ NEW: Calibration banner┐                │    │
                     │   │  ┌─ Live Strategies cards (extended)        │    │
                     │   │  ┌─ NEW: Portfolio Health summary ──┐        │    │
                     │   │  ┌─ Pipeline (extended columns)              │    │
                     │   │  └─ Sig modal (Slice 0, unchanged)           │    │
                     │   │  └─ Score modal (heavily extended)           │    │
                     │   └────────────────────────────────────────────┘    │
                     └────────────────┬────────────────────────────────────┘
                                      │
                ┌─────────────────────┴──────────────────────┐
                ▼                                            ▼
   ┌─ tradelab.web.handlers ─────┐         ┌─ tradelab core (CLI-shared) ────┐
   │  GET  /tradelab/regime      │  NEW    │  tradelab.regime              NEW│
   │  GET  /tradelab/calibration │  NEW    │   classify(bars) → label         │
   │  GET  /tradelab/portfolio-  │         │  tradelab.robustness.holdout    │
   │       health                │  NEW    │   (gate, not signal)             │
   │  GET  /tradelab/correlation │         │  tradelab.robustness.correlation│
   │       /<run_id>             │         │   return + DD + entry-time   EXT │
   │  GET  /tradelab/cards/<id>/ │         │  tradelab.live.divergence    NEW │
   │       divergence            │  NEW    │   K-S + decay slope              │
   │  GET  /tradelab/cards/<id>/ │  NEW    │  tradelab.live.calibration   NEW │
   │       freshness             │         │   accepted-card outcomes loop    │
   └─────────────────────────────┘         └──────────────────────────────────┘
```

## 4. Component-level design

### 4.1 Regime classification — `tradelab.regime`

New module. Three independent classifiers combined into a single regime label.

**Inputs:** daily bars of SPY (or configurable benchmark) over the strategy's backtest window.

**Classifiers:**
- **Volatility:** VIX < 15 = LOW, 15-25 = MID, > 25 = HIGH (configurable)
- **Trend:** SPX above both 50d and 200d MA + ADX > 20 = TRENDING, else RANGING
- **Breadth:** % of S&P 500 above 50d MA — > 60% BROAD, 40-60% MIXED, < 40% NARROW

**Outputs:**
- For backtest: each bar tagged with regime label; per-regime PF/Sharpe/DD computed and persisted in `backtest_result.json::regime_breakdown`
- For live: current regime label cached in `.cache/current_regime.json`, refreshed on each Research tab load (cache TTL 1h)

**Dependencies:** existing `tradelab.data` for bar fetching. No new external deps.

**Error handling:** if benchmark data is missing, classifier returns `UNKNOWN` and per-regime breakdown is suppressed in UI; regime banner shows "regime detection offline."

### 4.2 Hold-out OOS gate — promoted from signal

Backend changes from gameplan (2026-04-27 §Slice 1) preserved. UI changes:

- **Removed:** hold-out as one of 10 cells in Sig modal grid
- **Added:** dedicated `holdout-gate` div at top of Score modal (PASS/FAIL with PF + threshold + sample size)
- **Added:** `Hold-out` column on Pipeline table between `Verdict` and `PF`
- **Added:** annotation in Sig modal explaining the diagnostics shown are gate-conditional

Threshold config in `tradelab.yaml` unchanged (`hold_out_robust_pf: 1.5`, `hold_out_fragile_pf: 1.0`).

### 4.3 Multi-dimensional correlation — `tradelab.robustness.correlation` (extends gameplan §Slice 2)

Three pairwise statistics computed at Score time, persisted at Accept time.

**Persistence (at Accept):** new directory `pine_archive/<card_id>/`:
- `returns.csv` — daily returns (timestamp, return)
- `drawdowns.csv` — daily drawdown depth (timestamp, dd_pct, in_drawdown_bool)
- `entry_times.csv` — every trade entry timestamp + symbol
- `backtest_trades.csv` — every backtest trade (entry_ts, exit_ts, return_pct, regime_label) — **required by Slice 4 K-S test as the baseline distribution**

**Computed at Score time:**
- Return ρ: Pearson correlation on daily returns
- DD ρ: Pearson correlation on rolling 30d max-drawdown series
- Entry overlap: % of trade entries within 30min of any existing live card's entry

**Gate logic:** Accept blocked if ANY of (return ρ > 0.70, DD ρ > 0.70, entry overlap > 30%). Override requires typed reason.

**Endpoint:** `GET /tradelab/correlation/<scoring_run_id>` returns `{candidate_id, return_max, dd_max, entry_max, pairwise: [...], gate: pass|warn|fail}`.

### 4.4 Live divergence — `tradelab.live.divergence` (replaces gameplan §Slice 3)

Two stats, both computed on rolling 30-trade window:

**K-S divergence:**
- Two-sample Kolmogorov-Smirnov test: live trade returns vs backtest returns at same regime
- Output: `p_value`, `statistic`
- Threshold: `p > 0.10` healthy, `0.01 < p < 0.10` warn, `p < 0.01` fail (auto-disable)

**Decay slope:**
- Compute per-window Sharpe over a rolling 30-trade window: `mean(returns) / std(returns)` for each window step
- Linear regression of those Sharpe values vs window index → `slope` is the per-trade Sharpe drift
- Output: `slope`, `slope_std_error`, `t_statistic`
- Threshold: `slope > -0.005` healthy, `slope < -0.005 AND t < -2` flag as decaying
- If trade rate is < 30 trades / 30 days, fall back to a 10-day calendar window with the same regression

**Storage:** appended to `pine_archive/<card_id>/divergence_log.jsonl` on each fill via receiver hook.

**Auto-actions:** K-S fail → set card status to `disabled`, fire `notify(severity=critical)`. Decay flag → no auto-action, surface in UI only.

**Endpoint:** `GET /tradelab/cards/<id>/divergence` returns latest stats + window history (for sparkline rendering).

### 4.5 Calibration meta-stat — `tradelab.live.calibration`

New module. Computes feedback metrics across last N accepted cards.

**Inputs:** read each accepted card's `divergence_log.jsonl` + verdict at Accept time.

**Stats computed:**
- `te_tripped_pct` = N cards that hit K-S fail or auto-disable within 30d / N total
- `auto_disabled_pct` = N cards auto-disabled within 60d / N total
- `pf_gap_median` = median(live_PF - backtest_PF) across cards with ≥30 trades

**Threshold-action mapping (rendered in UI):**
- If `te_tripped_pct > 0.25` → recommend tightening hold-out PF threshold
- If `pf_gap_median < -0.30` → recommend tightening DSR floor
- If both → recommend tightening both

**Endpoint:** `GET /tradelab/calibration` returns the three stats + recommendation strings.

**Empty state:** if fewer than 5 accepted cards with ≥30d live data, banner shows "Calibration unavailable — need 5+ cards with 30d+ history." No errors raised.

### 4.6 Verdict freshness

No new module — small additions to `audit_reader.py`:
- `last_verdict_at` field on each Live card response = timestamp of most recent Robustness or Full run
- `regime_at_verdict` field = regime label that was current when last verdict ran

UI: card header shows "verdict 14d old" (subtle); turns amber after 30d, red after 60d. Tooltip explains: "regime has shifted since last verdict — re-run robustness."

### 4.7 Score modal — Relative context section

Pure frontend. Reads existing live card metrics from `/tradelab/strategies` endpoint. For each diagnostic in the candidate's verdict, computes:
- Rank of candidate value among live cards (e.g., "#2 of 7")
- Median of live cards
- Worst of live cards

Renders as a small table between Diagnostics and Regime Performance sections.

### 4.8 Override log

Persisted at `pine_archive/<card_id>/overrides.jsonl`. Each entry: `{timestamp, gate_name, override_value, typed_reason, accepted_at}`. Rendered in Score modal Override Log panel for re-views, and on the Live card if any override is in effect.

## 5. Data flow

### Score time (Pipeline → Score modal click)

```
1. Load run metrics from audit DB (existing)
2. Fetch hold-out result from robustness_result.json (gameplan)
3. POST /tradelab/correlation/<run_id> → return + DD + entry-time vs all live cards
4. Read regime_breakdown from backtest_result.json
5. Read live card metrics for relative-context anchoring
6. Render modal sections in order: Hold-out gate → Diagnostics → Relative context → Regime performance → Portfolio fit → Override log
```

### Accept time

```
1. Verify gate passes (hold-out + 3 correlation gates) OR typed override
2. Persist returns.csv, drawdowns.csv, entry_times.csv to pine_archive/<card_id>/
3. Append override log entry if any gate was overridden
4. Existing card-creation flow proceeds (cards.json write, receiver hot-reload)
```

### Live time (per-fill from receiver)

```
1. receiver._log_alert(order_submitted) hook (NEW)
2. Append to pine_archive/<card_id>/fills.jsonl
3. Compute K-S + decay over rolling window
4. Append to divergence_log.jsonl
5. If K-S p < 0.01: set card status disabled, notify(critical)
```

### Research tab load

```
1. Existing freshness banner + Live Strategies + Pipeline (unchanged endpoints)
2. NEW: GET /tradelab/regime → regime banner data
3. NEW: GET /tradelab/calibration → calibration banner data
4. NEW: GET /tradelab/portfolio-health → max corr + DD ρ + entry overlap
5. For each Live card: GET /tradelab/cards/<id>/divergence → sparkline + K-S + TE bar
```

## 6. Error handling

| Failure mode | Behavior |
|---|---|
| Regime classifier missing benchmark data | Banner shows "regime detection offline"; no per-regime PF in modal; pipelines proceed |
| Card has no `pine_archive/<id>/returns.csv` (legacy card) | Correlation panel shows "baseline missing — re-Accept to populate"; Accept gate is bypassed (warn-only) for legacy cards until baseline exists |
| Card has < 30 live trades | TE bar/decay/K-S shown as "warming up — N/30"; no thresholds tripped |
| Calibration has < 5 accepted cards with 30d data | Banner hidden entirely with empty-state message; no errors |
| `divergence_log.jsonl` corrupt | Card surfaces "divergence offline"; auto-disable does NOT trigger; notify(severity=warning) on parse failure |

No silent failures. Any backend error caught at handler level returns `{error: "...", offline: true}` and the UI section renders an "offline" placeholder.

## 7. Testing strategy

Per existing convention (`tests/web/`, `tests/unit/`, `tests/live/`):

| Module | Unit | Integration | Smoke |
|---|---|---|---|
| `regime` | classifier on known regime fixtures | `regime_breakdown` written to backtest_result.json | banner renders on dashboard load |
| `correlation` (extended) | each of 3 metrics on synthetic data | gate blocks Accept; override path works | Score modal Portfolio Fit panel renders |
| `divergence` | K-S + decay slope on synthetic distributions | auto-disable trips on synthetic divergence; notify fires | Live card sparkline renders + K-S badge |
| `calibration` | stats correct on fixture of accepted cards | recommendation strings match thresholds | banner renders or empty-state |
| Hold-out gate UI | n/a | Pipeline column renders; modal shows gate at top | smoke through dashboard click-through |

**Existing autouse fixture** at `tests/live/conftest.py` (notify-path redirect) extended to redirect `pine_archive` to a tmpdir so live tests don't pollute production archives.

**No new dependencies.** scipy already vendored for K-S; Pearson is in numpy.

## 8. Build order — 6 slices, ~6 days

Dependency-ordered. Each slice ends with all tests green and a hand-smoke through the dashboard before next slice begins (see memory: `feedback_live_smoke_before_next_slice`).

| Slice | What | Where | Depends on | Size |
|---|---|---|---|---|
| **1a** | Hold-out **gate** (not signal #10): backend signal + Score modal top section + Pipeline column | `walkforward.py`, `verdict.py`, `command_center.html` | nothing | 0.5d |
| **1b** | Relative context section in Score modal | `command_center.html` only | live card endpoint (exists) | 0.5d |
| **2** | Multi-dim correlation gate: return + DD + entry-time, all three persisted at Accept | new `correlation.py`, `pine_archive/` writer, Score modal Portfolio Fit panel, Pipeline Corr column | gameplan slice 2 prereq (persist returns) | 1.5d |
| **3** | Regime detection: classifier + per-regime PF in backtest + banner + per-regime table in modal + regime-fit column on Pipeline | new `regime.py`, `audit_reader.py`, command_center.html | benchmark data wiring | 2d |
| **4** | Live divergence: K-S + decay sparkline + auto-disable, replaces planned tracking-error work | new `divergence.py`, receiver hook, Live card UI extensions | requires per-card backtest baseline (slice 2 persists this) | 1.5d |
| **5** | Calibration meta-stat banner + verdict freshness | new `calibration.py`, Research tab banner | requires N=5 cards with slice-4 data (gates banner naturally) | 0.5d |

Slices 4 and 5 effectively run after Slice 3 because regime context is needed to make K-S "compare against backtest at same regime" meaningful.

Slices 1a, 1b, 2 are independent of regime work and could be shipped first if you want value before Slice 3 lands.

## 9. Out of scope (explicit)

| Item | Why not |
|---|---|
| PnL attribution (decompose live PnL by directional / timing / vol-capture) | Heavy math, "understanding" not "deciding" use case |
| Capacity / friction sensitivity charts | At retail size this is a sanity check; revisit beyond ~$2M AUM |
| Synthetic-series bootstrap for overfit detection | Would replace Monte Carlo signal; backend-only change, not a UI redesign item — separate spec |
| Always-visible Robustness panel (Slice 0 alternative) | Sig-modal-on-demand is correct UX; revisit if open count exceeds ~20/day |
| Compare-N-runs view | Already in v1.5 backlog (RESEARCH_TAB_V1_SUMMARY §5.5); not validation-related |
| Optuna study views | Amit explicitly declined; orthogonal |
| Multi-tenant / auth / LAN exposure | Single-user localhost-only is locked |

## 10. Cross-cutting decisions

- **Settings centralization:** all new policy values (regime VIX cutoffs, correlation thresholds, K-S p-value cutoffs, decay slope threshold) live in `tradelab.yaml::robustness` and `tradelab.yaml::live` blocks. Settings tab on Research surfaces them with friendly labels.
- **No backwards-compat shims:** signal name changes in `verdict.py` propagate freely; tests + Sig modal regex catch drift.
- **Notify hooks:** auto-disable on K-S fail uses existing `notify.notify()` with `severity=critical`. No new channel work.
- **No new dependencies:** numpy + scipy already vendored.
- **Single PID, single port, single HTML file:** locked per V1 architecture.

## 11. Risk register

| Risk | Mitigation |
|---|---|
| Regime classifier disagrees with intuition (e.g., classifies as TRENDING during a chop) | Configurable thresholds in `tradelab.yaml`; UI shows the underlying values (VIX, ADX) so user can cross-check |
| Pearson correlation on small samples is noisy | Require ≥60 trading days of overlap before computing; below threshold show "insufficient overlap" |
| K-S test fires false positives during regime transitions | Compare live vs backtest **at same regime label**, not aggregate |
| Calibration banner thresholds become stale | All thresholds in yaml, reviewed quarterly via the banner's own "tighten" recommendation |
| Auto-disable mistriggers and kills a valid card | `disabled` is reversible (status flip via Live card); notify includes "manual review needed" link |

## 12. Definition of done

- All 6 slices' tests pass (unit + integration + live)
- Hand-smoke through dashboard demonstrates: regime banner, calibration banner, all 3 correlation cells, K-S + decay on a Live card, Score modal hold-out gate at top
- `GAMEPLAN_validation_gaps.md` is marked `[SUPERSEDED — see 2026-04-28 spec]`
- New memory entry pointing at this spec
- Mockup file remains as visual reference

---

**Next:** writing-plans skill produces the implementation plan from this spec, slice-by-slice.
