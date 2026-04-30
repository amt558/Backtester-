# Validation Gaps — Game Plan

**Last updated:** 2026-04-27
**Status:** **[SUPERSEDED 2026-04-28]** — see `specs/2026-04-28-research-tab-validation-redesign-design.md` for the new authoritative plan. Slice 0 still shipped; remaining slices reframed and expanded (regime, DD correlation, entry-time, K-S divergence, calibration banner all added).

## Context

After reviewing tradelab's existing 9-signal robustness suite vs gaps that
typically kill production strategies, three categories of additions were
identified. This doc captures the agreed plan, slice boundaries, dependency
order, and where each piece lives in the dashboard.

The premise: tradelab's existing verdict logic (asymmetric, errs toward
FRAGILE) is solid for catching bad strategies pre-deployment. The gaps are
in:
1. **Pre-deployment** — one untouched-data check + portfolio-fit check
2. **In-production** — live-vs-backtest tracking error monitoring

## Locked decisions (do not relitigate)

| Decision | Why |
|---|---|
| **Drop Optimize/Walk-forward/Run buttons from dashboard UI** | User's primary workflow is Pine→Score→Accept; iteration tools fall to CLI |
| **Keep only Robustness (3r) and Full (3f) buttons** | Those are the only two that produce verdicts |
| **Hold-out OOS = verdict signal #10** | Reuses existing verdict aggregation; smallest change |
| **Cross-strategy correlation = separate gate, not signal** | Portfolio-level, not strategy-level; lives between verdict and Accept |
| **Tracking error lives on Overview, not Research** | Production telemetry, not research artifact |
| **Robustness Signals modal uses Option C matrix** | Single matrix component handles 1-row diagnose AND multi-row compare |
| **Receiver hot-reloads cards.json via watchdog** | Already done; no restart needed for status flips |

## Slice 0 — Robustness Signals modal *(SHIPPED 2026-04-27)*

A consistent way to inspect verdict signals from anywhere in the dashboard.

**What shipped:**
- Backend: new `GET /tradelab/runs/<run_id>/robustness` endpoint (`handlers.py`).
  Reads `<report_folder>/robustness_result.json`, returns `{run_id, strategy,
  verdict, signals, dsr_probability}`.
- Frontend modal `#signalsModal` — Option C matrix layout. Categorized
  columns (Edge / Stability / Generalization), importance tier badges
  (critical/high/medium), per-cell tooltip with full reason text.
- Two entry points:
  - **Pipeline → Actions column → Sig button** (per-run drill-down)
  - **Live Strategies card → Sig button** (per-strategy, opens latest run)
- Toggle inside modal: **"Compare across all live strategies"** — fetches
  each live card's latest run signals and renders as multi-row matrix.
- Tests: 319/319 web+io tests still pass.

**Known v1 limitations (acceptable):**
- Signal cell shows first numeric token from reason text via regex (e.g. "1.62",
  "P35", "8%"). If verdict.py's `reason` format changes, regex may need update.
- Cross-strategy compare makes N parallel HTTP requests (one per strategy).
  Fine up to ~20 strategies; if scale grows, add a single
  `/tradelab/cards/robustness-summary` endpoint.

## Slice 1 — Hold-out OOS gate *(NEXT)*

**Goal:** add a 10th verdict signal that runs the strategy on a "locked"
trailing window that no optimization step has ever touched. WFE only proves
the rolling fold worked; hold-out proves no leakage.

**Where the work lives:**
- `tradelab/src/tradelab/engines/walkforward.py` — extend WF result to
  capture the held-out window backtest as a separate field
- `tradelab/src/tradelab/robustness/verdict.py` — add `hold_out_oos` signal
  computation (pf in hold-out vs threshold)
- `tradelab/tradelab.yaml` (`robustness.thresholds`) — add
  `hold_out_robust_pf: 1.5`, `hold_out_fragile_pf: 1.0`
- `command_center.html` — Settings tab gets "Hold-out window (months)" input
- `command_center.html` — `SIG_DEFS` already has `hold_out_oos` slot; once
  backend emits the signal it auto-renders in the modal matrix

**Categorization (already in SIG_DEFS):**
- Category: Generalization
- Importance: **Critical** (any solo-fail can sink verdict)

**Acceptance criteria:**
- A run with `--robustness` or `--full` produces a `hold_out_oos` signal
  in `robustness_result.json::verdict.signals`
- Sig modal renders 10 columns instead of 9
- Settings tab exposes the window-size config; default 6 months
- A strategy that passes the existing 9 but fails hold-out (PF < 1.0
  on untouched window) lands FRAGILE

**Estimated size:** half a day

## Slice 2 — Cross-strategy correlation gate

**Goal:** prevent accepting a card whose returns are highly correlated with
existing live cards. Catches "this is just another viprasol clone" before it
adds redundant capital risk.

**Where the work lives:**
- New module `tradelab/src/tradelab/robustness/correlation.py`
- Reads candidate's daily returns + each existing live card's persisted
  daily returns (need to start saving these at Accept time — see prereq)
- Computes pairwise Pearson correlation
- Returns `{candidate_id, max_correlation, pairwise: {card_id: r}, gate: "pass"|"warn"|"fail"}`
- New endpoint `GET /tradelab/correlation/<scoring_run_id>` (called by Score modal after verdict)
- Score modal gets a new **"Portfolio Fit"** panel between verdict panel
  and Accept button, listing each pairwise correlation with color coding
- Hard gate: Accept button disabled if `max_correlation > 0.70` unless
  user types `OVERRIDE` in a confirm prompt (mirrors the FRAGILE confirm)

**Prereq:** at Accept time, persist the candidate's daily-returns series to
`pine_archive/<card_id>/returns.csv`. Without this, slice 2 has no data to
correlate against.

**Acceptance criteria:**
- Score modal renders Portfolio Fit panel for any new candidate
- `accepted-card-with-known-correlation` test fixture proves the gate
  blocks Accept and the override path works

**Estimated size:** 1 day

## Slice 3 — Live-vs-backtest tracking error monitor

**Goal:** detect strategy drift in production within ~30 trades, not 6 months.

**Where the work lives:**
- New module `tradelab/src/tradelab/live/tracking_error.py`
- Hooks into receiver's `_log_alert` on `order_submitted` events to capture
  every fill (price, qty, timestamp)
- For each card, maintain rolling 30-trade window of (live_pnl, backtest_pnl_at_same_timestamp)
- Backtest comparison data: pre-computed per-bar signals from the strategy's
  Pine — saved at Accept into `pine_archive/<card_id>/predicted_fills.jsonl`
- Compute live PF / backtest PF ratio over the window
- Threshold actions:
  - ≥ 0.80 → green health badge
  - 0.60–0.80 → amber; show on Live Card with tooltip
  - < 0.60 → red; auto-set card status to `disabled` AND notify (uses
    existing notify infrastructure)
- New endpoint `GET /tradelab/cards/<id>/tracking-error` returns rolling
  window data
- Overview Live Card badge shown next to the verdict pill

**Prereq:** Pine→Python predicted-fill exporter (or accept that we can only
compare directional signals, not exact fills, for Pine-authored strategies)

**Acceptance criteria:**
- Card with 30+ logged fills shows a tracking error badge on Overview
- Synthetic divergence test fixture trips the auto-disable path
- Auto-disable emits a notify with severity=critical

**Estimated size:** 2-3 days

## Slice 4 — Portfolio Validation panel

**Goal:** at-a-glance "is my portfolio diversified?" view on the Research tab.

**Where the work lives:**
- Reuses slice-2 correlation engine
- New panel on Research tab between **Live Strategies** and **Research
  Pipeline** sections
- Renders correlation matrix heatmap of all live cards (NxN cells, color by
  correlation strength)
- Diagonal = 1.0; off-diagonal red if > 0.70, amber 0.50–0.70, green < 0.50
- Click any cell to see returns overlay chart for those two strategies

**Prereq:** slice 2 (correlation engine + persisted returns per card)

**Acceptance criteria:**
- Panel renders for any portfolio with ≥ 2 enabled cards
- Cells color-coded; hover shows numeric value
- Empty state when fewer than 2 enabled cards

**Estimated size:** 1 day

## Build order (locked, by dependency)

```
Slice 0 (Sig modal) ──────────────────────────────── DONE 2026-04-27
        │
        ▼
Slice 1 (Hold-out OOS) ─── verdict signal #10
        │
        ▼
Slice 2 (Correlation gate) ─── Score modal panel + persist returns
        │                       │
        │                       └─► prereq for Slice 3 backtest baseline
        │                       └─► prereq for Slice 4 heatmap
        ▼
Slice 3 (Tracking error)        Slice 4 (Portfolio panel)
   live telemetry                  research-tab heatmap
```

Slices 3 and 4 can run in parallel after Slice 2 lands.

## Cross-cutting decisions

- **Settings centralization:** all global validation policies (hold-out
  window size, correlation threshold, tracking error thresholds) live in
  Settings → Risk Limits. Keeps daily-loss-limit company.
- **No backwards compat shims:** when a signal name or threshold key changes
  in `verdict.py`, just change it. Tests + the Sig modal regex will catch
  drift.
- **Modal reuse:** Slice 1 doesn't add a new modal — `hold_out_oos` slots
  into existing `SIG_DEFS` and renders automatically. Slice 4 is a new
  research-page panel, not a modal.
- **Notify hooks:** Slice 3 auto-disable triggers existing `notify.notify()`
  with severity=critical. No new channel work.

## What we explicitly chose NOT to build (yet)

- **"Always-visible Robustness panel above Pipeline"** — superseded by
  Slice 0's modal-on-demand. If we open the modal 20+ times/day, revisit.
- **Per-signal magnitude bars (Option B from mockup)** — modal currently
  shows pill-with-value cells. Adding spectrum bars requires backend to
  emit `value` + `thresholds` per signal, not just the reason text. Future
  enhancement if cell density becomes insufficient.
- **Public `/tradelab/cards/robustness-summary` aggregate endpoint** —
  current per-strategy parallel fetch in modal compare-toggle is fine up to
  ~20 strategies. Build the aggregate only if scale demands.
