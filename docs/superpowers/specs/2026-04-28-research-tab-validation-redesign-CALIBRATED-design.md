# Research Tab Validation Redesign — CALIBRATED Design Spec

**Date:** 2026-04-28
**Status:** Approved by Amit (CALIBRATED v3). Supersedes earlier 2026-04-28 FULL spec same day.
**Mockup:** `docs/superpowers/mockups/research_tab_redesign_proposal_CALIBRATED.html` (authoritative UX reference)
**Mockups rejected:** `research_tab_redesign_proposal.html` (FULL), `research_tab_redesign_proposal_LITE.html` (LITE)
**Recon evidence:** `docs/superpowers/ENGINE_CALIBRATION_RECON_2026-04-23.md`

## 0. Final decisions

After deep review of FULL/LITE mockups against the 2026-04-23 calibration recon evidence, **CALIBRATED v3 is locked.** FULL was approved earlier same day then superseded when reframe surfaced two structural problems that neither FULL nor LITE addressed:

1. **§1 confound:** the deployed bot loads strategies by bare module name (`alpaca_trading_bot.py:25-29`) — it is **not** running `tradelab.strategies.*` code. Every "calibration" stat downstream compares verdicts on tradelab code to live PnL of (possibly) divergent code. FULL/LITE leave this invisible.
2. **Verdict accuracy loop missing:** FULL/LITE emit only 3 thin portfolio-level calibration stats. The recon §7 explicitly asked for per-signal hit-rate evidence — which becomes the basis for `tradelab.yaml` threshold edits, replacing FULL's "tighten 1.5→1.7" guesswork.

CALIBRATED preserves the orthogonal-failure-mode gates from FULL (hold-out, multi-dim correlation), softens the auto-actions to LITE behavior (K-S = REVIEW only, no per-strategy regime fit), and adds three new surfaces: §1 confound panel, engine integrity / canary panel, and per-signal hit-rate table.

**§1 resolution path chosen: (C) retrospective via Alpaca API + bot.log attribution, with code-divergence caveat documented.** Recon §7 estimated 1 session assuming `trades.csv` existed; verification on 2026-04-28 found `trades.csv` does NOT exist on disk (bot `export_trades_csv()` apparently never called) so the retrospective pulls fills from `api.list_orders(status='filled', after=12mo_ago)` instead. Strategy attribution comes from parsing `bot.log` for `Position added: {symbol} ({strategy})` lines and joining on (symbol, time-window). Unmappable fills bucketed as "unattributed" in output. (A) port-and-verify and (B) parallel paper account deferred as later upgrades.

## 1. Why this exists

The 2026-04-27 gameplan covered hold-out OOS, return correlation, tracking error. The 2026-04-28 FULL spec added regime conditioning, multi-dim correlation, K-S divergence, calibration banner. Both are insufficient because:

1. **§1 confound contaminates calibration ground truth.** Recon §1 documented that 2 of 6 deployed strategies (S10, S12) have no tradelab module at all, and the other 4 (S2, S4, S7, S8) load by bare name with no byte-equality verification. Until this resolves, calibration outcome data is comparing wrong things.
2. **Engine integrity is unverified at runtime.** The `tradelab.canary` CLI exists but has no dashboard surface. Silent gauntlet drift would only be detected by losing real money.
3. **The calibration banner is a side-effect, not the centerpiece.** FULL §4.5 emits 3 stats (`te_tripped_pct`, `auto_disabled_pct`, `pf_gap_median`). None of these tell you which of the 9 signals is predictive. Recon §3 already identified `entry_delay` and `loso` as "quiet killers" — but FULL has no surface that would confirm or refute that hypothesis.
4. **Adding gates to a potentially-miscalibrated engine compounds the problem.** Hold-out tests a different failure mode (data leakage) so it earns its place; multi-dim correlation is independent of engine calibration; but K-S auto-disable + per-strategy regime fit on thin samples are amplified skepticism that should wait for ledger evidence.

CALIBRATED honors the recon §7 ordering: **close the verdict-accuracy loop first; ship gates whose value is independent of calibration; defer auto-actions and thin-sample features until evidence justifies them.**

## 2. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| C1 | **§1 confound panel at top of Research tab** | The deployed-vs-scored mismatch must be unavoidable on every page load |
| C2 | **§1 path (C) retrospective on `trades.csv`** as Slice -1 | Recon §7 step-1; cheapest signal; doesn't block other slices |
| C3 | **Engine Integrity / Canary panel** with Accept-block on canary mismatch | Silent gauntlet drift currently invisible; canary CLI exists, just needs runtime surface |
| C4 | **Verdict ledger schema extension** on existing `runs` table | Per-signal hit-rate is impossible without this; existing `data/tradelab_history.db::runs` already has `verdict, dsr_probability` — extend with `signal_values_json, thresholds_json, accepted_bool, reject_reason` |
| C5 | **Per-signal hit-rate table** in Verdict Accuracy Loop banner | The actual feedback loop; displays "fragile fires / accepted despite / failed in prod / hit rate" per signal |
| C6 | **Hit-rate tags inline on Score modal diagnostic cells** | Bring the evidence to the decision point |
| C7 | Hold-out as **gate** (not signal #10) — preserved from FULL | A failure-mode-distinct test should not be voted on by 9 in-sample signals |
| C8 | **Multi-dim correlation** (return + DD + entry-time) — preserved from FULL | Independent of §1; computed from live trade timestamps + PnL |
| C9 | Relative context section in Score modal — preserved from FULL | Anchors abstract numbers to live track record |
| C10 | Override log + verdict freshness — preserved from FULL | Audit trail; old verdicts get visible decay |
| C11 | **Regime banner only — NO per-strategy regime fit** (LITE behavior) | Per-bucket samples on 2y backtests are 9-42 trades; tagging POOR/STRONG off such samples is statistical theatre. Defer to ledger evidence |
| C12 | **K-S divergence shown but REVIEW-only — NO auto-disable** (LITE behavior) | K-S on 30 trades is noisy AND backtest baseline may be from divergent code under §1; auto-disable is unsafe under either uncertainty |
| C13 | Decay sparkline on Live cards — preserved from FULL | Display-only signal; no auto-action |
| C14 | All hit-rate cells carry §1 caveat pill until resolved | Honest about contamination rather than hiding it |

## 3. Architecture overview

```
                     ┌─────────────────────────────────────────────────────┐
                     │  command_center.html (port 8877)                    │
                     │   ┌────────────────────────────────────────────┐    │
                     │   │ Research tab                               │    │
                     │   │  ┌─ NEW: §1 Confound panel (TOP)──┐       │    │
                     │   │  ┌─ NEW: Engine Integrity / Canary┐       │    │
                     │   │  ┌─ Regime banner (banner only)             │    │
                     │   │  ┌─ NEW: Verdict Accuracy Loop banner─┐    │    │
                     │   │  │   + per-signal hit-rate table        │    │
                     │   │  ┌─ Live Strategies cards (extended)        │    │
                     │   │  ┌─ Portfolio Health (multi-dim corr)        │    │
                     │   │  ┌─ Pipeline (hold-out gate + corr cols)    │    │
                     │   │  └─ Score modal (extended w/ hit-rate tags) │    │
                     │   └────────────────────────────────────────────┘    │
                     └────────────────┬────────────────────────────────────┘
                                      │
                ┌─────────────────────┴──────────────────────┐
                ▼                                            ▼
   ┌─ tradelab.web.handlers ─────┐         ┌─ tradelab core (CLI-shared) ──────┐
   │  GET /tradelab/code-match   │  NEW    │  tradelab.audit.history (EXTEND) │
   │  GET /tradelab/canary-status│  NEW    │   runs table: + signal_values_json│
   │  GET /tradelab/calibration  │  EXT    │                + thresholds_json  │
   │  GET /tradelab/hit-rate     │  NEW    │                + accepted_bool    │
   │  GET /tradelab/regime       │  NEW    │                + reject_reason    │
   │  GET /tradelab/portfolio-   │         │  tradelab.calibration.code_match  NEW│
   │      health                 │  NEW    │   (deployed-vs-scored compare)    │
   │  GET /tradelab/correlation/ │  NEW    │  tradelab.calibration.retrospective NEW│
   │      <run_id>               │         │   (Slice -1: trades.csv → hit rate)│
   │  GET /tradelab/cards/<id>/  │  NEW    │  tradelab.calibration.hit_rate    NEW│
   │      divergence             │         │   (per-signal predictive power)   │
   │                             │         │  tradelab.canary.runtime          NEW│
   │                             │         │   (canary verdicts → status)      │
   │                             │         │  tradelab.regime                  NEW│
   │                             │         │   (banner-only classifier)        │
   │                             │         │  tradelab.robustness.holdout      EXT│
   │                             │         │  tradelab.robustness.correlation  EXT│
   │                             │         │  tradelab.live.divergence         NEW│
   │                             │         │   (K-S + decay, REVIEW-only)      │
   └─────────────────────────────┘         └──────────────────────────────────┘
```

**Module changes vs FULL spec:**
- **NEW:** `tradelab.calibration.code_match`, `tradelab.calibration.retrospective`, `tradelab.calibration.hit_rate`, `tradelab.canary.runtime`
- **MODIFIED:** `tradelab.regime` (banner only — no per-strategy bucketing); `tradelab.live.divergence` (REVIEW only — no auto-disable)
- **EXTENDED:** `tradelab.audit.history` (4 new columns on `runs` table)
- **PRESERVED FROM FULL:** `tradelab.robustness.holdout`, `tradelab.robustness.correlation`

## 4. Component-level design

### 4.1 §1 Confound panel — `tradelab.calibration.code_match`

New module. Runs on every Research tab load; results cached for 5min.

**Inputs:**
- `C:/TradingScripts/alpaca_config.json::strategies[]` — deployed module names + allocations
- `tradelab.yaml::strategies` keys — what tradelab knows about
- For each deployed module that has a tradelab counterpart: hash of source file at deployed location vs hash at `tradelab/src/tradelab/strategies/<name>.py`

**Output:** for each deployed strategy:
- `live_module_name`, `allocation_pct`
- `tradelab_module_name` or `null`
- `last_scored_verdict` + `last_scored_at` from runs table (if any)
- `code_match_status`: `MATCHED` (hashes byte-equal) | `DIVERGENT` (both files exist but hashes differ) | `MISSING` (no tradelab module)

**Endpoint:** `GET /tradelab/code-match` returns the table above + summary counts.

**UI:** topmost panel on Research tab. Big visible row per deployed strategy. Resolution paths (A/B/C) shown inline with currently chosen path highlighted (C per C2).

**Error handling:** if `alpaca_config.json` missing or unreadable, panel renders "config not found — confound check offline" without raising. Other panels proceed.

### 4.2 Engine Integrity / Canary panel — `tradelab.canary.runtime`

New module. Reuses existing `tradelab.canary` CLI logic (per `tests/cli/test_cli_canary.py`).

**Inputs:** 4 canary strategies with known expected verdicts:
- `canary_perfect_robust` — expected ROBUST
- `canary_obvious_fragile` — expected FRAGILE
- `canary_inconclusive` — expected INCONCLUSIVE
- `canary_data_leak` — expected FRAGILE (hold-out fail; new in CALIBRATED, requires Slice 1a)

**Behavior:** runs canaries on a daily cron AND on every dashboard load (cached 5min). If any canary's actual verdict ≠ expected verdict, panel goes red, **all Score modal Accept buttons are disabled across the dashboard**, and a critical notify fires.

**Endpoint:** `GET /tradelab/canary-status` returns `{canaries: [...], all_match: bool, last_run_at: timestamp}`.

**Storage:** `data/canary_history.jsonl` (append-only).

**Error handling:** if any canary fails to run (data fetch failure, etc.), treat as `UNKNOWN` not as `MISMATCH` — don't block Accepts on infrastructure errors. Notify with severity=warning.

### 4.3 Verdict ledger schema extension — `tradelab.audit.history` (EXTEND)

The existing `data/tradelab_history.db::runs` table (per `src/tradelab/audit/history.py:33-50`) already has `run_id, timestamp_utc, strategy_name, verdict, dsr_probability, report_card_*`. **Extend with 4 columns; do not create a new table.**

```sql
ALTER TABLE runs ADD COLUMN signal_values_json TEXT;
ALTER TABLE runs ADD COLUMN thresholds_json TEXT;
ALTER TABLE runs ADD COLUMN accepted_bool INTEGER;
ALTER TABLE runs ADD COLUMN reject_reason TEXT;
```

- `signal_values_json` — full 9-signal vector at evaluation time (e.g. `{"baseline_pf": 1.62, "dsr": 0.83, "entry_delay": 0.34, ...}`)
- `thresholds_json` — active thresholds at evaluation time (snapshot of `tradelab.yaml::robustness.thresholds`)
- `accepted_bool` — 1 if user accepted the card to Live, 0 if rejected, NULL if no decision yet
- `reject_reason` — free text from Reject modal; NULL if accepted

**Backfill:** one-time script reads each `reports/<run>/robustness_result.json` + `cards.json` history to populate retroactively. Acceptable to leave older runs with NULL for the 4 new columns if the source files don't exist.

**Migration:** runs at module import via `_SCHEMA` in `history.py` — `CREATE TABLE IF NOT EXISTS` already handles new installs; add `ALTER TABLE` checks for existing DBs.

**Tests:** unit test verifies migration runs idempotently on existing DB; integration test verifies new fields populated on a fresh run.

### 4.4 Slice -1 retrospective calibration — `tradelab.calibration.retrospective`

New module. Implements recon §7 step-1, **adapted for missing `trades.csv`** (verified 2026-04-28).

**Inputs:**
- Alpaca API via existing `alpaca_config.json` credentials — call `api.list_orders(status='filled', after=ISO12mo_ago, limit=500, direction='desc')`
- `bot.log` (path resolved from `alpaca_trading_bot.py:79 log_file` property) — parse `Position added: {symbol} ({strategy})` lines for strategy attribution
- For each strategy with a tradelab module + a recent backtest report: predicted verdict from `reports/.../robustness_result.json`
- Acknowledgment: predictions are on tradelab code; trades are from deployed code (§1 caveat in output)

**Processing:**
1. Pull all filled orders from Alpaca for last 12 months (paginated)
2. Parse `bot.log` for `Position added: {symbol} ({strategy})` lines → build `(symbol, ts) → strategy` index
3. Match each Alpaca fill to a strategy via nearest-time `Position added` for same symbol within ±2h window
4. Unmappable fills (no log line within window) bucketed as `"unattributed"` with explicit count
5. For each attributed strategy, compute live PF, live Sharpe, live max DD over the 12mo window
6. Compare to predicted verdict (ROBUST → expected to win; FRAGILE → expected to lose)
7. Per-signal: when signal said FRAGILE on a strategy that was deployed anyway, did it lose money? (initial seed for `hit_rate.py`)
8. Output: JSON report + console summary; **does not write to runs table** (retrospective is one-shot, not part of the live ledger)

**Output:** `reports/calibration_retrospective_<date>.json` with per-strategy + per-signal hit-rate seed values, plus `attribution_quality: {attributed_count, unattributed_count, attribution_pct}`, all flagged with `code_divergence_caveat: true`.

**Estimated:** 1.5 days (vs recon's 1-session estimate; trades.csv missing forces Alpaca API + log-parser).

### 4.4a Slice -0.5 bot client_order_id tagging — `alpaca_trading_bot.py` patch

Tiny prerequisite to ensure future retrospectives have native attribution.

**Files modified:**
- `alpaca_trading_bot.py:166-202` (`submit_order` method) — add `client_order_id` kwarg
- `alpaca_trading_bot.py:850` (entry path) — pass `client_order_id=f"{strategy}-{symbol}-{int(time.time())}"`
- `alpaca_trading_bot.py:900` (stop-loss exit path) — pass `client_order_id=f"{strategy}-{symbol}-exit-{int(time.time())}"`

**Effect:** every Alpaca order from this point forward carries strategy attribution in the broker's record. Future calibration runs can skip log parsing entirely.

**Doesn't help historical fills** — those already lack the tag. Slice -1's log-file fallback is needed for the 12mo retrospective regardless.

**Estimated:** 0.5 day including testing.

### 4.5 Per-signal hit rate — `tradelab.calibration.hit_rate`

New module. Reads extended `runs` table + outcome data; computes per-signal predictive power.

**Inputs:**
- `runs` table rows where `accepted_bool=1` AND `timestamp_utc < now - 30d` (need ≥30d outcome window)
- For each accepted card: live PnL outcome from `pine_archive/<card_id>/fills.jsonl` or `trades.csv` join
- "Failed in prod" definition: live PF < 1.0 over the outcome window OR card was auto-disabled OR card was manually disabled with reject_reason matching `(fail|broken|decay|loss)`

**Computed per signal:**
- `fragile_fires_90d`: count of runs where this signal was FRAGILE in the last 90d
- `accepted_despite`: of those, how many had `accepted_bool=1` (override path)
- `failed_in_prod`: of those accepted, how many failed
- `hit_rate` = `failed_in_prod / accepted_despite` (NULL if `accepted_despite < 3` — flagged as "insufficient sample")
- `read`: text classification (`predictive` ≥50% with n≥3 / `questionable` 25-50% with n≥3 / `noisy` <25% with n≥3 / `insufficient sample` n<3)

**Endpoint:** `GET /tradelab/hit-rate` returns per-signal table.

**Score modal integration:** each diagnostic cell renders a hit-rate tag inline (ratio + colored if questionable/noisy). Hover for full breakdown.

**Empty state:** if total `accepted_bool=1` runs < 5, banner shows "hit-rate unavailable — need 5+ accepted cards with 30d+ history."

**§1 caveat:** every hit-rate value carries a CAVEAT pill until §1 confound resolves. Display value but visually flag as conditional.

### 4.6 Regime classification — `tradelab.regime` (banner only — LITE behavior)

Same classifier as FULL spec §4.1 (volatility / trend / breadth → regime label) but **no per-strategy bucketing**:
- No `regime_breakdown` field on backtest_result.json
- No regime-fit column on Pipeline
- No regime-fit tag on Live cards
- No "Strategies favored now" cell on regime banner
- No Regime Performance table in Score modal

**Endpoint:** `GET /tradelab/regime` returns just current regime label + sub-classifier values.

**Upgrade path:** once Slice 5 ledger has ≥6 months of regime-tagged outcome data, evaluate adding per-strategy bucketing in a future spec amendment.

### 4.7 Live divergence — `tradelab.live.divergence` (REVIEW-only — LITE behavior)

Same K-S test + decay slope as FULL spec §4.4 BUT:
- K-S `p < 0.01` → set `review_status: urgent` on card; render REVIEW URGENT badge; notify with `severity=warning`
- **NO auto-disable.** Card status remains user-controlled.
- Decay flag → render sparkline; no notify; no status change.

**Endpoint:** unchanged from FULL spec — `GET /tradelab/cards/<id>/divergence`.

**Upgrade path:** once Slice 5 ledger shows K-S correlates with real failure (>70% predictive over 30+ samples), upgrade to auto-disable in a future spec amendment.

### 4.8 Hold-out, multi-dim correlation, relative context, override log, verdict freshness, decay

**Unchanged from FULL spec** §§ 4.2 (hold-out gate), 4.3 (multi-dim correlation), 4.7 (relative context), 4.8 (override log), 4.6 (verdict freshness). Decay sparkline preserved as display-only health signal on Live cards.

## 5. Data flow

### Research tab load

```
1. GET /tradelab/code-match → §1 confound panel
2. GET /tradelab/canary-status → engine integrity panel; if any mismatch, set
   global "accepts_blocked: true" flag in dashboard state
3. GET /tradelab/regime → regime banner (banner only)
4. GET /tradelab/calibration + GET /tradelab/hit-rate → verdict accuracy loop banner
5. Existing freshness banner + Live Strategies cards
6. GET /tradelab/portfolio-health → multi-dim corr summary
7. Existing Pipeline (extended w/ hold-out gate + corr columns)
8. For each Live card: GET /tradelab/cards/<id>/divergence → sparkline + K-S
```

### Score time (Pipeline → Score modal click)

Same as FULL spec §5 BUT:
- Score modal diagnostic cells fetch hit-rate tags from cached `/tradelab/hit-rate` response
- If `accepts_blocked: true` (canary mismatch), Accept button is disabled with tooltip "Engine canary mismatch — investigate before accepting"

### Accept time

Same as FULL spec §5 BUT:
- Writes new row to extended `runs` table with full signal vector + thresholds + `accepted_bool=1`
- If gate overridden, reject_reason captured (becomes "override reason" in this case)

### Live time (per-fill from receiver)

Same as FULL spec §5 BUT:
- K-S `p < 0.01` does NOT auto-flip card status; sets `review_status: urgent` only
- Existing notify path with severity=warning instead of severity=critical

### Reject time (NEW path)

```
1. User clicks Reject in Score modal → modal prompts for reject_reason
2. Writes runs row with accepted_bool=0 + reject_reason populated
3. No card creation; no archive persist
```

### Slice -1 retrospective (one-shot)

```
1. CLI: tradelab retrospective-calibration --window 12m
2. Reads trades.csv + reports/ + tradelab.yaml
3. Computes per-strategy + per-signal seed hit rates
4. Writes reports/calibration_retrospective_<date>.json
5. Console summary; flags §1 caveat
```

## 6. Error handling

| Failure mode | Behavior |
|---|---|
| `alpaca_config.json` missing | §1 panel shows "confound check offline"; other panels proceed |
| Canary run errors out (data fetch fail) | Mark as UNKNOWN (not MISMATCH); notify warning; do not block Accepts |
| `runs` table migration partial | Log error; CALIBRATED features that need new columns show "ledger extension incomplete" empty state |
| `pine_archive/<id>/fills.jsonl` missing for an accepted card | hit-rate counts that card as "outcome unknown"; doesn't fail the panel |
| Alpaca API call fails or rate-limited | Slice -1 retrospective fails with explicit error; suggests retry with backoff; doesn't block other slices |
| `bot.log` missing or unparseable | Slice -1 proceeds; all fills bucketed as `"unattributed"`; output flags attribution_pct=0 |
| K-S baseline missing (legacy card) | Card surfaces "warming up — needs baseline"; no REVIEW badge |
| < 5 accepted cards with 30d outcome data | Hit-rate panel hidden with empty-state message |
| `regime classifier` benchmark data missing | Banner shows "regime detection offline"; pipelines proceed |

**No silent failures.** Backend errors return `{error, offline: true}`; UI renders explicit "offline" placeholders. Canary mismatch is the **only** condition that blocks Accepts globally.

## 7. Testing strategy

| Module | Unit | Integration | Smoke |
|---|---|---|---|
| `code_match` | hash compare on synthetic file pair | endpoint returns table for fixture `alpaca_config.json` | §1 panel renders with mock 6 strategies |
| `canary.runtime` | each canary returns expected verdict on fixture | mismatch path disables Accept globally | banner renders green/red on dashboard load |
| `audit.history` extension | migration idempotent on existing + new DB | new run row populates 4 new columns | n/a |
| `retrospective` | per-signal hit-rate on synthetic trade fixture | end-to-end on `trades.csv` fixture | CLI output matches snapshot |
| `hit_rate` | rate computation correct for known fixtures | reads runs + outcome data; renders table | hit-rate tags appear in Score modal |
| `regime` (banner only) | classifier on known regime fixtures | banner data flow | banner renders 3 cells |
| `divergence` (REVIEW-only) | K-S + decay on synthetic distributions | REVIEW status set; no auto-disable | Live card REVIEW badge appears |
| Hold-out gate | per FULL spec | per FULL spec | per FULL spec |
| Multi-dim correlation | per FULL spec | per FULL spec | per FULL spec |
| Relative context | n/a | per FULL spec | per FULL spec |

**Existing autouse fixture** at `tests/live/conftest.py` extended to redirect `pine_archive` AND `data/canary_history.jsonl` to tmpdir.

**No new dependencies.** scipy + numpy already vendored; sqlite3 stdlib.

**Hand-smoke between slices** per `feedback_live_smoke_before_next_slice` memory.

## 8. Build order — 10 slices, ~8 days + §1 fix

Dependency-ordered. Each slice ends with all tests green AND a hand-smoke through the dashboard before the next slice begins.

| Slice | What | Depends on | Size |
|---|---|---|---|
| **-0.5** | Patch `alpaca_trading_bot.py` to tag `client_order_id` w/ strategy on every submit | nothing | 0.5 day |
| **-1** | §1 retrospective calibration via Alpaca API + bot.log attribution (path C) | -0.5 (clean tagging from now) | 1.5 days |
| **0** | Ledger schema extension on `runs` table + backfill script | nothing | 0.5 day |
| **0.5** | Engine Integrity / Canary panel + Accept-block on mismatch | nothing (canary CLI exists) | 0.5 day |
| **1a** | Hold-out as gate (FULL §4.2 preserved) | nothing | 0.5 day |
| **1b** | Relative Context section in Score modal | nothing (frontend only) | 0.5 day |
| **2** | Multi-dim correlation gate + `pine_archive/<id>/` writers | nothing | 1.5 days |
| **3** | Per-signal hit-rate panel + Score modal hit-rate tags | Slice -1 + Slice 0 | 1 day |
| **4** | Regime banner (banner only, LITE behavior) | nothing | 1 day |
| **5** | Live divergence (K-S + decay, REVIEW-only) | Slice 2 (`backtest_trades.csv` baseline) | 1 day |
| **6** | Verdict Accuracy Loop banner (calibration stats + hit-rate panel together) | Slices -1 + 0 + 3 | 1 day |

**Independent slice groups (can be parallelized in the same day if scope allows):**
- {Slice -1, 1a, 1b, 4} — independent of each other
- Slice 2 unlocks Slice 5
- Slice 0 unlocks Slice 3 unlocks Slice 6
- Slice 0.5 fully independent

**Recommended sequence (single-track):** -0.5 → -1 → 0 → 0.5 → 1a → 1b → 2 → 3 → 4 → 5 → 6.

## 9. Out of scope (explicit)

| Item | Why deferred |
|---|---|
| Per-strategy regime fit (regime-fit column / tag / table) | Per-bucket samples ~9-42 trades; ship after Slice 6 ledger evidence validates |
| K-S auto-disable | Ship REVIEW-only first; upgrade after Slice 6 evidence shows >70% predictive |
| §1 path (A) port-and-verify | Path (C) retrospective chosen as step-1; (A) considered as later upgrade |
| §1 path (B) parallel paper account | 30-day soak too slow as step-1; revisit if (C) shows insufficient signal |
| PnL attribution panel | Heavy math, "understanding" not "deciding" use case |
| Capacity / friction sensitivity | Retail size, sanity check; revisit beyond ~$2M AUM |
| Synthetic-series bootstrap | Backend signal-only change; separate spec |
| Always-visible Robustness panel | Sig-modal-on-demand is correct UX |
| Compare-N-runs view | Already in v1.5 backlog |
| Multi-tenant / auth / LAN exposure | Single-user localhost-only locked |

## 10. Cross-cutting decisions

- **Settings centralization:** all new policy values (canary expected verdicts, hit-rate thresholds, regime VIX cutoffs, K-S p-value cutoffs) live in `tradelab.yaml::calibration`, `tradelab.yaml::canary`, `tradelab.yaml::regime`, and `tradelab.yaml::live` blocks
- **No backwards-compat shims:** signal name changes propagate; tests + Sig modal regex catch drift
- **No new dependencies:** numpy + scipy + sqlite3 already vendored
- **Single PID, single port, single HTML file architecture:** locked
- **§1 caveat propagation:** every cell that derives from verdict-vs-outcome calibration carries a CAVEAT pill until `code_match_status=MATCHED` for all deployed strategies

## 11. Risk register

| Risk | Mitigation |
|---|---|
| §1 retrospective on `trades.csv` shows engine has zero predictive power | Explicit deliverable; if true, halt remaining slices and recalibrate before adding more gates. Slice -1 IS the answer to "should we keep building this stack" |
| Canary panel false-fires due to data fetch errors | Distinguish UNKNOWN from MISMATCH; only MISMATCH blocks Accepts |
| Hit-rate panel statistically thin (<5 accepted cards) | Empty state with explicit message; banner hidden until n≥5 |
| Hit-rate inverts later as more data arrives | Display absolute counts alongside percentage; user can judge |
| Pearson correlation on small samples noisy | Require ≥60 trading days overlap before computing |
| §1 caveat fatigue (user starts ignoring CAVEAT pills) | Caveats disappear automatically once `code_match_status=MATCHED`; not user-dismissable |
| Retrospective Slice -1 produces ambiguous result | Deliverable includes explicit go/no-go on whether engine has signal; ambiguous = recommend (A) port-and-verify next |

## 12. Definition of done

- All 10 slices' tests pass (unit + integration + live)
- Hand-smoke through dashboard demonstrates: §1 confound panel populated for 6 deployed strategies; canary panel green; verdict accuracy loop banner with hit-rate table; hold-out gate at top of Score modal; hit-rate tags inline on diagnostic cells
- Slice -1 retrospective output committed to `reports/calibration_retrospective_<date>.json`
- `runs` table contains ≥10 entries with all 4 new columns populated (proves the ledger works end-to-end)
- 2026-04-28 FULL spec marked SUPERSEDED with one-line pointer to this doc
- Memory entry updated to point at this spec
- CALIBRATED mockup remains as visual reference

---

**Next:** writing-plans skill produces the implementation plan from this spec, slice-by-slice.
