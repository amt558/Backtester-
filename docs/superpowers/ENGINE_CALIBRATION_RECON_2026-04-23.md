# Engine Calibration Recon — 2026-04-23 (autonomous session)

**Scope:** Read-only reconnaissance ahead of a decision on whether to freeze dashboard work and calibrate the verdict engine. Seven tasks completed solo. Nothing in the repo was modified. Credentials you pasted in chat were **not** written into this file — see §0.

---

## 0. Credential handling (read this first)

- **Twelve Data key you resent today is the same pre-exposed value** flagged in the last handoff (`02d795…327bc8b`). It has **not** been rotated. Until you rotate it on twelvedata.com it remains burned.
- **New Alpaca key + secret you pasted** is now in this session's transcript. If any transcript storage/sync is active, treat that key as exposed and rotate again. I did **not** read `alpaca_config.json`'s credential fields — only the `strategies[]` array needed for §5.
- I did not touch `alpaca_config.json`, `.env`, or any secret-bearing file.

---

## 1. Deployed-strategy count & tradelab divergence

**Answer to the question that started this session:** the live paper account is **not empty**. 6 strategies are actively enabled on the paper account. This changes the premise of the prior brainstorm — a live-vs-backtest divergence check is testable.

**Deployed (from `C:/TradingScripts/alpaca_config.json`):**

| Role | Name | Module | Allocation |
|---|---|---|---|
| core_alpha | S4_InsideDayBreakout | `s4_inside_day_breakout` | $25,000 / 25% |
| core_alpha | S12_MomentumAcceleration | `s12_momentum_acceleration` | $25,000 / 25% |
| core_diversifier | S7_RDZMomentum | `s7_rdz_momentum` | $20,000 / 20% |
| stabilizer | S8_BullishOutsideDay | `s8_bullish_outside_day` | $15,000 / 15% |
| satellite | S2_PocketPivot | `s2_pocket_pivot` | $10,000 / 10% |
| satellite | S10_RSNewHighs | `s10_rs_new_highs` | $5,000 / 5% |

**Disabled with removal reasons** (pre-tradelab vetting):
- S1_52Week_Breakout — "Sharpe 1.19 worst. Return/DD 3.6x inefficient."
- S3_GapUpMomentum — "MC 5th percentile -18.7%. Negative tail risk."
- S5_PowerTrendPullback — "-76.6% bear loss. Catastrophic tail risk."

**Critical structural finding: the live bot is not running tradelab code.** The `module` field in `alpaca_config.json` is a bare name (`s4_inside_day_breakout`), not `tradelab.strategies.s4_inside_day_breakout`. `C:/TradingScripts/alpaca_trading_bot.py:25-29` imports from `alpaca_trade_api` and loads strategies by flat module name — meaning there is a **separate copy of strategy code** deployed, vetted through a **separate pipeline**. Tradelab's verdict engine has never been applied to the live strategies.

**S10 and S12 don't exist in `tradelab.yaml` at all** — the live bot runs two strategies tradelab has never heard of.

**Implication for the calibration plan:** a true engine-validity test needs one of:
- (A) Port each live bot strategy INTO tradelab (so the engine sees the deployed code)
- (B) Stand up a **separate paper account** that trades only what tradelab approves, run in parallel for 30 days, compare — the existing paper account is the wrong harness because it runs code the engine never scored
- (C) Weaker alternative: compare the tradelab-report verdicts on S4/S7/S8/S2 (which exist in both) against the live bot's forward returns, accepting that the code isn't identical

See §7 for the experiment design that uses (B).

---

## 2. Verdict thresholds (current values)

Source: `tradelab.yaml:38-56` (authoritative) and `src/tradelab/robustness/verdict.py:57-85` (code fallback). They match exactly.

| Gate | Robust ≥ | Fragile ≤ | Notes |
|---|---|---|---|
| `baseline_pf` (profit factor) | 1.50 | 1.10 | Band 1.10–1.50 → inconclusive |
| `dsr` (deflated Sharpe prob) | 0.95 | 0.50 | Band 0.50–0.95 → inconclusive |
| `mc_dd_fragile_percentile` | — | 10.0 | Observed DD in bottom-10% of shuffle sims |
| `smoothness_robust` / `fragile` | 0.15 | 0.40 | Param-landscape std/best ratio |
| `entry_delay_fragile` | — | 0.50 | PF drop ≥50% at +1 bar → fragile |
| `loso_fragile_spread` | — | 1.00 | PF spread across symbols |
| `wfe_robust` / `fragile` | 0.75 | 0.50 | OOS/IS ratio |
| `noise_pf_drop_p5_fragile` | 0.10 | 0.40 | p5 noisy PF drop |
| `regime_spread_fragile` | 0.70 | 0.40 | Worst-regime PF / best-regime PF |
| `regime_spread_hard_fragile` | — | 0.20 | **Hard override → FRAGILE regardless** |
| `regime_min_trades_pct` / `_abs` | 10% / 5 | — | Sample-size guard |

**Aggregation rule** (`verdict.py:297-316`):
- 2+ fragile signals, **or** 1 fragile + 0 robust → **FRAGILE**
- 0 fragile **and** ≥ max(3, n_signals/2) robust → **ROBUST**
- Otherwise → **INCONCLUSIVE**
- `regime_spread_hard` signal alone → hard-forces **FRAGILE** regardless

**Observation:** "1 fragile + 0 robust → FRAGILE" is very strict. A strategy that fires 1 fragile and 4 inconclusive lands in FRAGILE even though 4 of 5 signals are agnostic. This is intentional per the anti-drift comment (false negatives cost more than false positives), but it is the single biggest lever driving FRAGILE verdicts.

---

## 3. Kill-rate per gate (from the 5 tradelab reports with full robustness suites)

Reports audited: `cg_tfe_v15_2026-04-19`, `s4_inside_day_breakout_2026-04-19`, `s7_rdz_momentum_2026-04-19`, `s8_bullish_outside_day_2026-04-19`, `s2_pocket_pivot_2026-04-21_152734`.

| Gate | # fragile fires / 5 strategies | Strategies that failed it |
|---|---|---|
| `baseline_pf` | 3 | S2 (0.78), S4 (1.05), S7 (0.57) |
| `dsr` | 2 | S2 (0.001), S7 (0.148) |
| `mc_max_dd` | 1 | CG-TFE |
| `param_landscape` | 0 | — |
| `entry_delay` | 3 | S4 (66%), S8 (61%), S2 (40.5%) — wait, S2 was 40.5% which is <50%, so this is actually 2. Let me recount from the reports: S4 66% fragile, S8 61% fragile; CG-TFE 36% inconclusive; S7 12% inconclusive; S2 40.5% inconclusive → **2 fires** |
| `loso` | 2 | S4 (spread 3.42), S8 (spread 4.39) |
| `noise_injection` | 1 | S2 (57%) |
| `wfe` | 1 | S2 (0.00) |
| `regime_spread` / `_hard` | 0 | Gate not triggered in any of the 5 reports (regime_breakdown may have been absent) |

**Recount of entry_delay:** S4 66% fragile, S8 61% fragile → **2 fires, not 3**.

**Corrected kill-rate table:**

| Gate | Fragile fires | Strategies |
|---|---|---|
| `baseline_pf` | 3 | S2, S4, S7 |
| `dsr` | 2 | S2, S7 |
| `entry_delay` | 2 | S4, S8 |
| `loso` | 2 | S4, S8 |
| `mc_max_dd` | 1 | CG-TFE |
| `noise_injection` | 1 | S2 |
| `wfe` | 1 | S2 |

**Interpretation:**
- `baseline_pf` < 1.1 is the most common disqualifier — but the strategies that fail it (S2 PF 0.78, S7 PF 0.57) are clearly losers and should be killed. Not a calibration problem.
- **`entry_delay` and `loso` are the quiet killers.** Both fire on S4 and S8, two strategies that are currently deployed live. If your goal is to reconcile "engine says FRAGILE vs. live bot happily trading them," these are the gates to examine first.
- `loso` threshold at 1.0 is lenient in absolute terms (PF spread of 1.0 is large), but S4's spread of 3.42 and S8's 4.39 are genuinely huge — the strategy's edge is concentrated in a minority of symbols. This is a real finding, not an overcautious gate.
- `entry_delay` threshold at 0.50 (50% PF drop at +1 bar) is aggressive. S4 drops 66%, S8 drops 61% — both fail decisively. But CG-TFE drops 36% and passes, S2 drops 40.5% and passes. The band 40–50% is where calibration matters.

---

## 4. CG-TFE post-mortem — memory vs. reality

Your `project_cg_tfe_killed.md` memory says: *"Pullback-to-demand (Order Block) strategy shelved 2026-04-21; OOS PF 1.09 vs 1.3 threshold."*

**What the actual report says** (`reports/cg_tfe_v15_2026-04-19_181306/executive_report.md`):
- Aggregate verdict: **INCONCLUSIVE**, not FRAGILE
- PF: **1.152**, not 1.09
- No walk-forward was run for CG-TFE (section 3: "Not run for this strategy")
- Signals: 1 fragile (mc_max_dd), 2 robust (loso, noise_injection), 4 inconclusive
- By the aggregation rule, 1 fragile + 2 robust → INCONCLUSIVE ✓ (correct)
- Data window 2020-01-01 → 2024-06-30 — this is the longest-horizon run available

**Three possibilities for the discrepancy:**
1. A later re-run (post-2026-04-19) produced different numbers and wasn't saved to `reports/`. No such file exists in `reports/` as of today.
2. "OOS PF 1.09" refers to a walk-forward window that wasn't run here.
3. Memory is simply wrong. The "1.3 threshold" also doesn't match anything in `tradelab.yaml` — the real `pf_robust` is 1.5 and `pf_fragile` is 1.1.

**Recommendation:** update or delete the CG-TFE memory. The strategy scored INCONCLUSIVE per the last run we have on disk — it was not engine-killed at PF 1.09. If you manually shelved it for reasons outside the engine, record those reasons; if you re-ran it and got different numbers, we need to find or regenerate the newer report. The CG-TFE v1.5 strategy file still exists at `src/tradelab/strategies/cg_tfe_v15.py` (status `scaffold`, description "3 modules still placeholders").

---

## 5. Engine verdicts on currently-deployed strategies

This is the most consequential finding of the session. Every deployed strategy that has a tradelab report scored FRAGILE.

| Deployed name | Module | Tradelab report | Engine verdict | Fragile signals | Robust signals |
|---|---|---|---|---|---|
| S4_InsideDayBreakout | s4_inside_day_breakout | 2026-04-19_165800 | **FRAGILE** | baseline_pf (1.05), entry_delay (66%), loso (3.42) | param_landscape |
| S7_RDZMomentum | s7_rdz_momentum | 2026-04-19_170449 | **FRAGILE** | baseline_pf (0.57), dsr (0.148) | mc_max_dd |
| S8_BullishOutsideDay | s8_bullish_outside_day | 2026-04-19_174716 | **FRAGILE** | entry_delay (61%), loso (4.39) | baseline_pf (2.35), param_landscape |
| S2_PocketPivot | s2_pocket_pivot | 2026-04-21_152734 | **FRAGILE** | baseline_pf (0.78), dsr (0.001), noise_injection (57%), wfe (0.00) | mc_max_dd, loso |
| S10_RSNewHighs | s10_rs_new_highs | *none* | — | — | — |
| S12_MomentumAcceleration | s12_momentum_acceleration | *none* | — | — | — |

**Two readings of this, both true:**

1. **The engine thinks the deployed portfolio is a disaster.** 4 of 4 testable deployed strategies failed the verdict. S2 and S7 have negative expectancy on their tradelab data windows. S4 barely breaks even (PF 1.05).

2. **The engine and the bot are looking at different things.** The data windows in tradelab reports (2022-2024, 2024-2026) differ per strategy. The bot may be running a different universe, different params, different entry/exit logic. Without the calibration experiment in §7, we don't know whether the engine is **right** or **miscalibrated**.

**This is the core question.** Either:
- The engine is right and the deployed portfolio is underperforming its historical pattern — expect future P&L to disappoint.
- The engine is wrong and is systematically killing live-viable strategies — a direct P&L leak every time you shelve something on FRAGILE.

You cannot know which is true without the experiment. This is the strongest argument I found today for the "stop building dashboard, calibrate engine" pivot.

---

## 6. Toggle bug on command_center strategy cards

**Symptom:** Clicking the on/off toggle at the top-right of any strategy card produces the alert *"Could not save to alpaca_config.json — is the launcher running?"* — even though the launcher is running.

**Root cause:** HTTP method mismatch between frontend and backend.
- Frontend (`command_center.html:1002-1006`) sends `PUT /config` with the new `disabled_strategies` array.
- Backend (`launch_dashboard.py:107-116`) implements `do_GET` and `do_POST` only — there is no `do_PUT`. Python's `BaseHTTPRequestHandler` returns **501 Not Implemented** for unimplemented methods.
- Frontend catches the non-2xx response and displays a misleading "launcher not running" error.

**Same bug fires on flatten-with-disable path** (`command_center.html:1063-1068`) — also uses `PUT /config`. If you've ever clicked Flatten and checked "also disable," the disable write silently failed.

**Two fix options:**

- **A) Change frontend to POST.** One-line edit at `command_center.html:1003`: `method: 'PUT'` → `method: 'POST'`. Same change at line 1065 for the flatten path. Matches the existing `do_POST` → `write_config()` route. **Recommended** — smaller blast radius, no backend change.
- **B) Add `do_PUT` to `launch_dashboard.py`.** Mirror the existing `do_POST` body. Slightly more code but preserves REST semantics (PUT for updates is more idiomatic than POST).

**I did not apply either fix** — per the handoff protocol, `command_center.html` already has 2 uncommitted XSS fixes awaiting your review. Adding a third uncommitted change muddles the commit strategy you laid out. Approve one of A/B and I'll make the change.

**Also worth fixing alongside:** the error message on line 1012 is diagnostically useless. It should include the HTTP status so future bugs like this surface faster — e.g. `alert('Failed to save: HTTP ${res.status}')`.

---

## 7. Calibration experiment design (for your approval before we touch code)

**Goal:** Test whether the tradelab verdict engine correctly predicts deployed-strategy outcomes. Answer: is a FRAGILE verdict a save or a miss?

**What the experiment must produce:**
- An empirical hit-rate: of N strategies tradelab verdicts, what fraction of FRAGILE ones would have lost money live, and what fraction of ROBUST ones would have won?
- Per-gate attribution: which gates (e.g. `entry_delay`, `loso`) are predictive vs. noisy?

**Design: parallel paper accounts, 30-day window**

- **Paper account A (engine-approved):** trades only strategies with tradelab verdict ROBUST or INCONCLUSIVE. Strategies are the `tradelab.strategies.*` code, not the live bot's copy.
- **Paper account B (engine-rejected):** trades only strategies with verdict FRAGILE (picked from shelved/demoted strategies — CG-TFE, S5_PowerTrendPullback, etc.). Same code path as A.
- **Paper account C (current live bot):** keep running as-is for comparison — this is the "neither tradelab nor new harness" baseline.
- All three on the same universe (big_tech_15 or magnificent_7 per `tradelab.yaml`), same capital ($25k–$50k each — you choose), same commission model.

**What we measure at day 30:**
- PF, Sharpe, max DD per account
- Per-strategy hit: did each live strategy match its predicted verdict direction?
- Gate-level hit rate: for each fragile-fire, did the strategy actually underperform? (yes = gate is predictive; no = gate may be overtuned)

**What "engine was right" means quantitatively:**
- Primary: Account A beats Account B by ≥1 Sharpe point OR ≥20% total return spread at day 30 → engine has signal
- Secondary: FRAGILE gates with <50% hit rate are candidates for recalibration
- Null: accounts within noise of each other → engine is not currently adding value, recalibrate or replace

**Data we need to log** (in addition to what the bot already logs):
- For every trade: which strategy, which gate-verdict was it placed under, entry/exit timestamps
- For every skipped-signal: which gate vetoed it (requires instrumentation in the engine — ~half a day's work)

**Prerequisites before we can start:**
1. A second paper Alpaca account (or a single account with strategy-level tagging already in place — the bot has `positionMap[].strategy`, this may be sufficient)
2. A thin harness that runs `tradelab.strategies.*` modules against live data — **this is the biggest unknown**. Tradelab currently runs backtests, not live execution. Building this live-execution harness is 2-5 days of work on its own.
3. Clarity on capital: are you comfortable putting $50k–$150k of paper capital against this for 30 days? Paper, so no real-money risk, but it ties up attention.

**Honest tradeoff with this experiment:** it's expensive in calendar time (30 days minimum, realistically 60 to gather enough trades) and requires building a live-execution harness tradelab currently lacks. A cheaper proxy would be **retrospective calibration**: take the last 12 months of each deployed strategy's live trades (already logged in `trades.csv`), compare to what tradelab would have predicted from a backtest over the same 12 months. No new harness, no new capital, answer in a day. Weaker signal because you can't isolate the engine's forward-predictive power, but 10x cheaper.

**My recommendation: do the retrospective calibration first** (1 session), then decide whether the forward experiment is worth building. If retrospective shows the engine has zero predictive power on strategies already trading, stop there and recalibrate before building more harness.

---

## 8. What I did NOT do (flagging explicitly)

- Did not touch `command_center.html`, `launch_dashboard.py`, `alpaca_config.json`, or any verdict threshold
- Did not revoke any Alpaca key
- Did not start paper-trading anything
- Did not commit anything
- Did not rotate the Twelve Data key (only you can, at twelvedata.com)

---

## 9. Decisions I need from you to continue

1. **Fix the toggle bug: option A or B** (§6). Option A recommended — one-line change to `command_center.html:1003` and `:1065`.
2. **Update or delete the CG-TFE memory** (§4) — its numbers don't match the report on disk.
3. **Calibration experiment direction:** retrospective first (§7 "honest tradeoff") or go straight to forward parallel-paper? Retrospective is cheaper and strongly recommended as step-1.
4. **If retrospective approved:** I need to read `C:/TradingScripts/trades.csv` (or wherever live trades are logged) and the last N strategy backtests on the same window. Confirm OK to read those files.
5. **Twelve Data key rotation** — still on your plate, I can't do it. Once rotated, the new key should **not** be pasted in-channel; I'll read it from wherever it's stored.
6. **Alpaca key rotation (optional)** — the key you pasted today is now in transcript. If you consider transcripts exposed, rotate again.

---

**End of recon.** Total autonomous work: ~70 minutes of reads, no writes to code or config. Seven tasks (6 planned + toggle-bug investigation) covered. The headline is §5: the engine says every deployed strategy is fragile. That's either the strongest possible argument for recalibration, or the strongest possible argument that the deployed portfolio is about to disappoint. You can't know which without the experiment in §7.
