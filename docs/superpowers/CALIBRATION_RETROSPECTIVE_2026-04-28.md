# Slice -1 Calibration Retrospective Findings — 2026-04-28

**Run:** `python -m tradelab retrospective-calibration --paper` against the real Alpaca paper account, last 12 months of fills, joined to `C:/TradingScripts/alpaca_bot.log` for strategy attribution and `tradelab/reports/` for predicted verdicts.

**Output:** `reports/calibration_retrospective_2026-04-28.json`

**§1 caveat:** outputs compare tradelab verdicts to live PnL of (possibly) different code per recon §1 — deployed bot loads strategies by bare module name, not as `tradelab.strategies.*`. Slice -0.5 (committed earlier today) tags `client_order_id` going forward; this retrospective relies on bot.log parsing for the historical 12mo window.

---

## Headline

**Verdict: insufficient attributed sample.** The feedback loop is mechanically working but cannot yet produce decisive evidence about the verdict engine's predictive power. Recommended decision: **continue building Slice 0 onward** (orthogonal-coverage gates that don't depend on calibration evidence), while natively-tagged trades accumulate.

Per the plan's decision gate (Task -1.7 Step 6), this matches the "Insufficient attributed sample (attribution_pct < 50%)" branch — not "engine has signal" or "engine is noise."

---

## Headline numbers

| Metric | Value |
|---|---|
| Round-trip trades pulled from Alpaca (last 12mo) | **12** |
| Trades attributed to a strategy via bot.log | 3 (25%) |
| Trades unattributed (no matching `Position added` line within 24h) | 9 (75%) |
| Distinct attributed strategies | 2 (S2_PocketPivot, S12_MomentumAcceleration) |
| Distinct deployed strategies per `alpaca_config.json` | 6 (S2, S4, S7, S8, S10, S12) |
| Tradelab reports on disk (2026-04-27 re-runs) | 5 (S2 ×3, S4 ×2) |
| Per-signal hit rate samples ≥ 3 | **0** |

The 12-trade window is too thin to drive threshold tuning. Two of six deployed strategies (S2, S12) showed any activity in the bot log; four (S4, S7, S8, S10) had **zero** Position added entries in the current 24KB log file. Either:
- Bot.log has rotated/been truncated and only contains recent activity
- Those strategies have not generated entries in the time the current log covers
- Or the bot's logging format has drifted in ways the regex doesn't catch

The next retrospective (post Slice -0.5 native tagging) should not depend on log parsing at all and will reveal whether the lack of attribution was a logging artefact or genuinely thin trading.

---

## Per-strategy live outcomes

| Strategy | Trades | Total PnL | Live PF | Fragile signals from latest report |
|---|---:|---:|---:|---|
| S2_PocketPivot | 2 | +$462.02 | ∞ (no losses) | `wfe`, `loso` |
| S12_MomentumAcceleration | 1 | -$745.92 | 0.0 | — (not in tradelab.yaml; never scored) |
| unattributed | 9 | -$95.97 | 0.13 | n/a |

### Verdict-vs-reality observations

**S2_PocketPivot** is the only strategy with both attributed live trades AND a tradelab report. The latest report (2026-04-27) shows S2 as **ROBUST** overall but with `wfe` and `loso` still firing as fragile signals. S2's live performance over those 2 trades was profitable — fragile-signal fires did not predict loss in this micro-sample. n=1 per signal, so this is **insufficient sample**, not evidence the gates are noisy.

This is also a **verdict drift** datapoint: recon §5 (2026-04-21) reported S2 as FRAGILE with 4 fragile signals (`baseline_pf`, `dsr`, `noise_injection`, `wfe`). The 2026-04-27 re-run shows S2 as ROBUST with only 2 fragile signals (`wfe`, `loso`). Either the strategy materially improved or the gauntlet was re-run on a different data window. Worth investigating before Slice 0.

**S12_MomentumAcceleration** is the §1 confound made concrete. The bot trades S12 with $25k/25% allocation, but `tradelab.yaml` has no entry for it — the verdict engine has never scored this code. The single trade we attributed to S12 was a $745.92 loss. We cannot grade this loss against any prediction. This is exactly the case the §1 confound panel (CALIBRATED v3) needs to surface on the dashboard.

**Unattributed bucket** (9 trades, -$96 net, PF 0.13) is dominated by losses. We cannot say which strategies these came from. Some are likely S4/S7/S8 (deployed and tradelab-scored), some likely S10 (deployed but not in tradelab.yaml). The mixed-loss profile is consistent with the recon §5 finding that "the engine thinks the deployed portfolio is a disaster" — 4 of 4 deployed strategies that had reports scored FRAGILE — but we can't confirm from this thin sample.

---

## Per-signal seed hit rates

```
loso: fires=1, accepted=1, failed=0, hr=n/a, read=insufficient sample
wfe:  fires=1, accepted=1, failed=0, hr=n/a, read=insufficient sample
```

Neither signal has enough data points to classify as predictive/questionable/noisy. **This will remain the case until either** (a) more strategies have attributed live trades, or (b) the same strategies accumulate more trades over time.

The recon §3 "quiet killers" hypothesis (`entry_delay` and `loso` are the gates that matter most for reconciling engine vs deployed-bot reality) cannot be confirmed or refuted from this run. `entry_delay` did not fire as fragile in the 2026-04-27 S2 report — it shows as `inconclusive` ("PF drop 17% at +1 bar"), down from 40.5% in the recon-era report. This may indicate S2 has stabilized or that the test was re-run with different data.

---

## Top issues surfaced (not in the plan)

1. **Bot.log appears to have rotated or been truncated.** Only 3 of 12 fills could be attributed via `Position added` pattern matching. Future calibration runs should not depend on log archaeology — Slice -0.5's `client_order_id` tagging is the correct long-term fix and is already shipped.

2. **Robustness report shape did not match plan assumption.** The plan and initial implementation assumed `signals` was a top-level dict with `{name: {verdict: "FRAGILE"}}`. Real shape is `verdict.signals` as a list of `{name, outcome, reason}` with **lowercase** `outcome` strings. Fixed mid-run (commit `8e553f4`); both shapes now supported via `extract_fragile_signal_names`. Plan should be updated to reflect real shape.

3. **CamelCase ↔ snake_case naming mismatch** between bot (`S2_PocketPivot`) and tradelab (`s2_pocket_pivot`) was not anticipated by the plan. Bridge added (commit `384f29f`) via `normalize_strategy_name`. Memory-worthy gotcha.

4. **Two deployed strategies (S10, S12) have NO tradelab module.** This is the §1 confound made unambiguous. The retrospective bucketed S12's $745.92 loss as attributed-but-unscoreable. The CALIBRATED dashboard's §1 panel should flag these explicitly so they cannot be silently included in calibration averages.

5. **S2 verdict drift between recon (2026-04-21) and current reports (2026-04-27).** Recon-era report had 4 fragile signals; current has 2. Either strategies were re-run on different data, or thresholds shifted. Audit before any Slice 6 calibration banner is shipped.

---

## Recommendation

**Continue with Slice 0.** The retrospective is mechanically working — schema is in place, attribution logic exists, signal extraction handles real report shape. What's missing is **data**, which only time + Slice -0.5's tagging will solve.

Slices 0, 0.5, 1a, 1b, 2 are independent of calibration evidence and should ship next per the build order. By the time Slice 3 (per-signal hit-rate panel UI) is being implemented, ~30 days of natively-tagged trades will be available for a second retrospective run that should show >80% attribution.

**Re-run schedule:** schedule a second retrospective for 2026-05-28 (30 days post Slice -0.5). If attribution_pct ≥ 50% at that point, hit-rate seeding becomes meaningful.

**§1 escalation:** S10 and S12 having no tradelab module is a structural gap that limits calibration regardless of attribution quality. Either port them into tradelab.strategies.* (recon §1 path A) or accept they are permanently outside the verdict-accuracy loop.

---

## Commits this slice produced

- `5871dbb` feat(calibration): package skeleton (Slice -1 Task 1.A)
- `d882ee1` feat(calibration): Alpaca fetcher + buy/sell pairer (Slice -1 Task 1.B)
- `c4047fa` feat(calibration): bot.log Position added parser + attribution (Slice -1 Task 1.C)
- `2c94339` feat(calibration): retrospective orchestrator (Slice -1 Task 2)
- `c2f2e7c` feat(calibration): re-export public API in __init__ (Slice -1 Task 2)
- `019d43c` feat(cli): retrospective-calibration subcommand (Slice -1 Task 3)
- `a5246fe` fix(cli): handle nested alpaca config shape + UTF-8 BOM
- `1a5ef41` refactor(cli): use alpaca-py via adapter (no deprecated SDK)
- `384f29f` feat(calibration): normalize CamelCase bot names to snake_case
- `8e553f4` fix(calibration): handle real robustness_result.json shape

Tests: 17 calibration + 6 cli = 23 new tests, all passing. 20 prior modified files from Slice 7a left untouched throughout.
