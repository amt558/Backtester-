# Research Tab — LITE applied to Flow A — Design

**Date:** 2026-04-28
**Status:** Approved for plan-writing
**Visual reference:** `docs/superpowers/mockups/research_tab_lite_applied_to_flow_a.html`
**Supersedes:** `docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md` (paused; see RESUMPTION_PLAN_2026-04-28.md for why)
**Predecessor (gameplan):** `docs/superpowers/GAMEPLAN_validation_gaps.md` — sliced differently here but same gates

---

## 1. Context

The CALIBRATED redesign was paused on 2026-04-28 after Slice -1's retrospective surfaced foundational issues: §1 confound concrete (S10/S12 have no tradelab module), per-signal calibration data months away (n=1), S2 verdict drift, and endemic plan-vs-code drift. CALIBRATED's verdict-accuracy feedback loop was premised on validating tradelab's Python implementation against its live PnL — a premise that doesn't hold while strategies are placeholders.

This redesign reframes around **Flow A** (Pine→TradingView→Alpaca) as the production architecture, per `TRADELAB_MANUAL.html`. Under Flow A, TradingView is the source of truth for both backtest and live execution: the same Pine script generates the backtest CSV (uploaded at Score time) and fires the live alerts (routed via webhook → receiver → Alpaca). There is no Python equivalent to drift from Pine; the §1 confound dissolves entirely.

The target picture is `research_tab_redesign_proposal_LITE.html`, applied to this Flow A reality. The frozen `pine_archive/<card_id>/tv_trades.csv` becomes the canonical backtest baseline. Tracking error becomes a distributional comparison (live trade returns vs backtest trade returns), not a per-bar fill match — eliminating the "Pine→Python predicted-fills exporter" prereq that bloated the original gameplan's Slice 3.

## 2. Scope

### In scope

| Element | Surface |
|---|---|
| Market Regime banner (Vol / Trend / Breadth) | Top of Research tab |
| Verdict Calibration banner (3 stats) | Below regime banner; aggregates over accepted-card history |
| Live Strategies cards augmented | TE bar, Decay sparkline, K-S p-value badge, REVIEW NEEDED / REVIEW URGENT tags |
| Portfolio Health summary (3 cells) | Below Live Strategies |
| Research Pipeline gains Hold-out gate column | New leftmost-after-Verdict column |
| Research Pipeline gains Corr column | New column between DD and Trades |
| Score Modal — Hold-out gate panel | At top of modal body |
| Score Modal — Relative context section | Between Diagnostics and Portfolio fit |
| Score Modal — Portfolio fit gate (with Accept blocker) | Hard gate: ρ > 0.70 disables Accept; OVERRIDE prompt mirrors FRAGILE confirm |

### Out of scope (deferred or dropped)

- **Per-strategy regime fit** (regime-fit tag on Live cards, regime-fit column on Pipeline, Regime Performance table in Score modal) — LITE explicitly drops; statistical risk on thin per-bucket samples
- **K-S auto-disable** — LITE rule: REVIEW only, manual disable
- **"Strategies favored now" regime stat** — depends on per-strategy bucketing
- **§1 confound panel, canary integrity panel, per-signal hit-rate table** — CALIBRATED-only; do not apply under Flow A
- **Pine→Python equivalence work** — irrelevant under TV-only architecture
- **Settings tab risk-limits centralization** — thresholds live in `tradelab.yaml` for now
- **Per-fill backtest replay / `predicted_fills.jsonl` per timestamp** — distributional TE eliminates the need

## 3. Architecture

### 3.1 New backend modules

| Module | Purpose | Reads | Returns |
|---|---|---|---|
| `tradelab.live.tracking_error` | Per-card TE / Decay / K-S | `pine_archive/<card_id>/tv_trades.csv` + Alpaca fills filtered by `client_order_id` for card | `{te, decay_series, ks_p, n_live_trades, status}` |
| `tradelab.regime.banner` | Current market regime read | alpaca-py: VIX, SPX vs 50/200 MA, breadth (% S&P 500 above 50d MA) | `{vol, trend, breadth, last_shift_date}` |
| `tradelab.calibration.summary` | Aggregate over accepted-card outcomes | `live/cards.json` + tracking_error per card | `{n_accepted, n_te_tripped_30d, n_disabled_60d, median_pf_gap}` |
| `tradelab.robustness.correlation` | Pairwise correlations | `pine_archive/<card_id>/returns.csv` for each enabled card | `{pairs: [{a, b, return_rho, dd_rho, entry_overlap}], max_return_rho, max_dd_rho, max_entry_overlap}` |

### 3.2 Extensions to existing modules

| Module | Change |
|---|---|
| `tradelab.engines.walkforward` | Compute backtest on a hold-out trailing window (separate from WF folds); add result field |
| `tradelab.robustness.verdict` | Add `hold_out_oos` signal (10th) using new WF result; threshold from `tradelab.yaml` |
| Score-flow handler (writes pine_archive on Accept) | Additionally derive daily-returns from tv_trades.csv and write `pine_archive/<card_id>/returns.csv` |

### 3.3 New persisted artifacts

| Path | When written | Format |
|---|---|---|
| `pine_archive/<card_id>/returns.csv` | At Accept time, plus a backfill script for existing cards | `date,return_pct` daily series derived from tv_trades.csv |

No other new persistence. TE/Decay/K-S are computed on demand; calibration banner aggregates on demand; regime banner pulls from alpaca-py on demand. All cacheable in memory at endpoint level if needed.

### 3.4 New dashboard endpoints (port 8877)

| Endpoint | Returns |
|---|---|
| `GET /tradelab/cards/<id>/tracking-error` | `tracking_error` shape above |
| `GET /tradelab/regime` | `regime` shape above |
| `GET /tradelab/calibration-summary` | `calibration_summary` shape above |
| `GET /tradelab/portfolio-health` | `correlation` shape above (over enabled cards only) |
| `GET /tradelab/correlation/<scoring_run_id>` | Candidate-vs-enabled-cards correlation for Score modal Portfolio fit gate |

All endpoints follow existing tradelab-prefix pattern in `dashboard/handlers.py`.

### 3.5 Frontend touch points

Single file: `command_center.html` (lives in parent repo `C:\TradingScripts\`, not tradelab repo).

- New Research tab DOM sections: regime banner, calibration banner, portfolio health (insert in mockup order)
- Live Strategies card template: add three new health-rows (TE / Decay / K-S) and the REVIEW NEEDED / REVIEW URGENT tags
- Pipeline table: add Hold-out and Corr column cells
- Score modal: add hold-out gate panel at top, relative context section, portfolio fit gate panel; disable Accept button on max ρ > 0.70 unless OVERRIDE prompt resolves

No new modal. The K-S "REVIEW NEEDED" notify uses existing `notify.notify(severity="warning", ...)` infrastructure.

## 4. Data flow

| UI element | Data source | Compute |
|---|---|---|
| Regime banner cells | `GET /tradelab/regime` → alpaca-py | Look up VIX, SPX MA cross, ADX, % above 50d |
| Calibration banner stats | `GET /tradelab/calibration-summary` | Iterate `cards.json`, per accepted card check first-30d TE crossings |
| Live card PF/WR/DD/DSR | Existing — latest `verdict.json` per card | Already shipped |
| Live card TE bar (5 cells) | `GET /tradelab/cards/<id>/tracking-error` | Color buckets from `te` ratio: ≥0.80 green, 0.60–0.80 amber, <0.60 red |
| Live card Decay sparkline | Same endpoint, `decay_series` | 11-point smoothed rolling PF over last 30 trades |
| Live card K-S badge | Same endpoint, `ks_p` | Two-sample K-S on (live trade returns) vs (backtest trade returns); badge p<0.05 amber, p<0.01 red |
| REVIEW NEEDED / URGENT tag | Derived from K-S badge severity | NEEDED on amber, URGENT on red |
| Portfolio Health 3 cells | `GET /tradelab/portfolio-health` | Take max of return_rho, dd_rho, entry_overlap across pairs |
| Pipeline Hold-out cell | New `hold_out_oos` signal in run's `robustness_result.json` | Existing verdict-signals reader |
| Pipeline Corr cell | Per-run from a small lookup against current enabled cards | Same correlation engine, point-vs-cohort variant |
| Score modal Hold-out panel | `verdict.signals[name=hold_out_oos]` | New verdict signal #10 |
| Score modal Relative context | `cards.json` + each card's `verdict.json` | Compute rank/median/worst across enabled cards |
| Score modal Portfolio fit | `GET /tradelab/correlation/<scoring_run_id>` | Same correlation engine; Accept-button gate at ρ > 0.70 |

## 5. Implementation sequencing

10 slices, 3 phases, total ~4.5 days. Each slice is independently shippable; phases group by dependency.

### Phase 1 — Feedback loop (~2 days, critical path)

| # | Slice | Effort | Depends on |
|---|---|---|---|
| S1 | Returns persistence at Accept (write `pine_archive/<card_id>/returns.csv` from tv_trades.csv) + backfill script for existing cards | ~half day | Existing Score→Accept flow |
| S2 | `tradelab.live.tracking_error` module + `GET /tradelab/cards/<id>/tracking-error` endpoint | ~half day | S1 (uses returns.csv); Slice -0.5 client_order_id tagging (already shipped) |
| S3 | Live card UI: TE bar / Decay sparkline / K-S badge / REVIEW NEEDED tag in `command_center.html` | ~half day | S2 |
| S4 | Hold-out OOS gate: extend WF engine, add `hold_out_oos` to verdict, render in Pipeline column + Score modal panel | ~half day | Independent — can run parallel with S1-S3 |

### Phase 2 — Portfolio surfaces (~1.5 days)

| # | Slice | Effort | Depends on |
|---|---|---|---|
| S5 | `tradelab.robustness.correlation` module (return ρ + DD ρ + entry-time overlap) + `GET /tradelab/correlation/<scoring_run_id>` + `GET /tradelab/portfolio-health` endpoints | ~half day | S1 (returns.csv per card) |
| S6 | Score modal Portfolio fit gate panel + Accept-button blocker on max ρ > 0.70 + OVERRIDE confirm prompt | ~half day | S5 |
| S7 | Pipeline Corr column | bundled w/ S6 | S5 |
| S8 | Portfolio Health 3-cell panel on Research tab | ~half day | S5 |

### Phase 3 — Context & meta (~1 day)

| # | Slice | Effort | Depends on |
|---|---|---|---|
| S9 | Regime banner: `tradelab.regime.banner` module + `GET /tradelab/regime` + UI panel | ~half day | Independent |
| S10 | Calibration banner: `tradelab.calibration.summary` module + `GET /tradelab/calibration-summary` + UI panel | ~half day | S2 (tracking_error per card); displays sparse for first ~30d |

### Build order (locked by dependency)

```
S1 ──┬─► S2 ──► S3                S4 (parallel from start)
     │
     └─► S5 ──┬─► S6 + S7
              │
              └─► S8

S9 (independent)        S10 (after S2)
```

**Hand-smoke gate between phases:** per `feedback_live_smoke_before_next_slice` memory, smoke through the live system between slices on the dashboard, fix bugs mid-smoke not next session.

## 6. Spec-level defaults (locked)

| Decision | Default | Source |
|---|---|---|
| TE rolling window | last 30 trades | Original gameplan |
| TE bar color buckets (5 cells, fill from left) | ≥0.80 green-full · 0.60–0.80 amber (3 cells) · <0.60 red (1 cell) | Original gameplan + LITE mockup |
| Decay sparkline | last 30 trades, 11-point smoothed | LITE mockup |
| K-S threshold | p < 0.05 amber (REVIEW NEEDED) · p < 0.01 red (REVIEW URGENT) | LITE mockup |
| K-S notify severity | warning (NEVER critical in LITE) | LITE explicit rule |
| Hold-out window | 6 months (configurable in `tradelab.yaml`) | Original gameplan |
| Hold-out PF thresholds | `hold_out_robust_pf: 1.50`, `hold_out_fragile_pf: 1.00` | Original gameplan |
| Correlation gate | ρ > 0.70 hard fail (with OVERRIDE) · 0.50–0.70 amber · <0.50 ok | Original gameplan |
| Insufficient-sample threshold | n < 30 trades shows `n=N insufficient` badge instead of value | Honest sparse-data behavior |
| Regime data source | alpaca-py | Avoid new dependency |
| Calibration banner window | last 90 days | LITE mockup |

## 7. Non-goals

- This is **not** a verdict-accuracy validation system. Under Flow A, "verdict accuracy" reduces to "is the gauntlet's research-time PF a good predictor of live-time PF" — answered by the calibration banner directly, not by per-signal hit-rate calibration.
- This is **not** a strategy authoring or porting tool. Strategies are authored in Pine on TradingView. tradelab scores their CSV exports.
- This is **not** infrastructure for placeholder-strategy validation. Placeholders run through the same code path; they just have no live fills to populate TE/Decay/K-S until enabled in paper.
- This design does **not** assume tradelab.strategies.* matches anything live. Pine is the source of truth.

## 8. Risks and open questions

### Risks

1. **alpaca-py for breadth data may not have S&P 500 universe.** If breadth (% above 50d) requires a separate market-data feed, S9 grows by ~half a day. Verify during plan-writing.
2. **Distributional K-S vs paired K-S.** Distributional comparison is correct here (live PnL distribution vs backtest PnL distribution). If a future user wants paired comparison (live trade i vs backtest trade i at same timestamp), that's a different test and needs predicted-fill snapshots — out of scope here.
3. **`pine_archive` may not be on the receiver's filesystem.** S2 reads tv_trades.csv on the dashboard side, not the receiver. If pine_archive is dashboard-local (per current convention), no issue. Verify during plan-writing.
4. **Backfill script for existing cards.** S1 must derive returns.csv from already-frozen tv_trades.csv for any cards accepted before this slice. Should be deterministic — the CSV doesn't change.
5. **Parent-repo `command_center.html` is months-dirty.** Frontend slices (S3, S6, S7, S8, S9 panel, S10 panel) all touch this file. Continue current pattern of partial-staging commits per `project_validation_redesign_2026-04-28` memory; do not bundle parent-repo cleanup into any slice.

### Open questions (resolve during plan-writing, not now)

- Exact field names in tracking-error JSON response (e.g. `te` vs `te_ratio`, `decay_series` shape: array of floats vs `{x, y}` pairs). Plan should grep existing endpoint conventions for naming.
- Whether the 11-point decay sparkline is downsampled from raw rolling-PF series or computed natively at 11 points. Either works; pick the simpler.
- Whether OVERRIDE confirm at Accept reuses the existing FRAGILE confirm prompt or creates a parallel one. Plan should grep `command_center.html` to see what's there.
- Whether S10 calibration banner should hide entirely below n=3 or render with `insufficient sample` placeholder. Mockup chooses placeholder; plan should follow.

## 9. References

- **Mockup:** `docs/superpowers/mockups/research_tab_lite_applied_to_flow_a.html`
- **Predecessor mockups:** `research_tab_redesign_proposal.html` (FULL, rejected), `research_tab_redesign_proposal_LITE.html` (target picture), `research_tab_redesign_proposal_CALIBRATED.html` (paused)
- **Architecture manual:** `C:\TradingScripts\TRADELAB_MANUAL.html` — Flow A (section 5)
- **Original gameplan:** `docs/superpowers/GAMEPLAN_validation_gaps.md` — defaults pulled from here
- **Why CALIBRATED was paused:** `docs/superpowers/RESUMPTION_PLAN_2026-04-28.md`
- **Retrospective findings:** `docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md`
- **Memory:** `feedback_plan_grep_verification` (grep selectors before plan dispatch), `feedback_live_smoke_before_next_slice`, `reference_robustness_result_shape`, `reference_alpaca_trade_history_source`, `project_validation_redesign_2026-04-28`
