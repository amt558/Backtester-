# Resumption Plan — Validation Redesign (paused 2026-04-28)

**Companion to:** `SESSION_2026-04-28_VALIDATION_REDESIGN_HANDOFF.md` (status snapshot)
**Recommendation:** **Go back to the design phase before writing any more code.**

---

## TL;DR

Slice 0.5 shipped clean and was verified end-to-end. Stop here. The CALIBRATED plan's foundation shifted under us mid-execution — the retrospective surfaced findings the plan didn't anticipate. Resume by re-reading the design alternatives, deciding the §1 confound, picking a scope that's actually evidence-grounded, and re-authoring the plan with selectors verified against current code.

---

## Why a design revisit is the right move

The CALIBRATED plan was locked **before** Slice -1 ran. Slice -1's findings invalidated three of the plan's assumptions:

1. **§1 confound is concrete, not theoretical.** S10_RSNewHighs and S12_MomentumAccel **lost $745 in production** but **have no `tradelab.strategies.*` module**. The engine has never scored them and cannot, regardless of how much data accumulates. Slices that depend on the verdict-accuracy loop (1b, 2, 3, 6) are missing data for ~20% of live strategies — by structure, not by sampling.

2. **Per-signal calibration data is months away.** Attribution rate was 25% (3 of 12 trades) and per-signal hit-rate n=1. CALIBRATED v3 plans a hit-rate UI (Slice 3) and a verdict-accuracy banner (Slice 6) that need n>>1 per signal to show anything meaningful. Building those now ships UI for an empty data flow.

3. **The verdict-comparison baseline isn't stable.** S2 was FRAGILE in the 2026-04-21 recon and ROBUST in 2026-04-27 reports — same strategy, different verdict, no rerun documented. Verdict-accuracy work needs a **frozen snapshot** (which Slice 0's runs-table extension now enables) but the historical comparison data was never frozen.

Plus a chronic execution-side issue:

4. **Plan-vs-code drift is endemic.** Slice 0.5 had 5 selector mismatches against current code; the parallel grep agent found 4 in Slice 1a before dispatch. Plans 1b–6 were authored at the same time and likely have similar drift. Catching drift mid-slice has cost real time twice now.

These aren't "tweaks for the next slice." They're foundational. The honest move is to revisit design.

---

## What's locked vs. what's open

### Locked (don't relitigate)
- Slice 0.5 backend (audit-DB query → `/tradelab/canary-status` → MATCH/MISMATCH/UNKNOWN panel + accept-block) is correct. Tests + smoke prove it. Keep it.
- Slice 0 ledger extension (`signal_values_json`, `thresholds_json`, `accepted_bool`, `reject_reason`) is the right schema. Keep it.
- Slice -1's retrospective code is the right structure. **The findings** are what changes our path, not the code.
- Slice -0.5 (`client_order_id` tagging in the bot) is on a one-way ratchet — every new fill from now forward tags itself for future attribution. Keep it.

### Open for design re-evaluation
- Whether the LITE / proposal / CALIBRATED design is still the right picture given new evidence.
- Whether the 6 remaining slices (1a, 1b, 2, 3, 4, 5, 6) are the right next 6 — or whether a smaller, evidence-grounded subset is more honest.
- §1 confound resolution (A / B / C) — see below.
- Frontend commit hygiene: parent-repo `command_center.html` is months-dirty. Cleaning it is its own focused session, not a sub-task of any slice.

---

## Design-phase re-read (next session: ~30 min reading)

Re-read these in order:

1. `docs/superpowers/GAMEPLAN_validation_gaps.md` — the **original** 4-slice plan (Sig modal → Hold-out OOS → Correlation gate → Tracking error / Portfolio panel). Smaller, scoped to gaps that don't depend on calibration data. Status header marks it superseded; ignore that — it's the simpler shape worth comparing back to.
2. `docs/superpowers/mockups/research_tab_redesign_proposal.html` — the original proposal (likely matches the 4-slice gameplan).
3. `docs/superpowers/mockups/research_tab_redesign_proposal_LITE.html` — the trimmed alternative. **Important:** LITE was on the table earlier 2026-04-28; CALIBRATED was chosen later same day. With calibration data delayed, LITE's premise (caution + minimal infrastructure) may have been right.
4. `docs/superpowers/mockups/research_tab_redesign_proposal_CALIBRATED.html` — what was chosen. The full 10-slice plan layered on this.
5. `docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md` — the findings that changed the picture.
6. Memory entry `project_validation_redesign_2026-04-28.md` — current locked state.

---

## §1 confound — must be decided before Slice 1b or beyond

S10_RSNewHighs and S12_MomentumAccel lost $745 in production. They have **no tradelab module**. Three options were surfaced; user has not picked:

- **(A) Port them into `tradelab.strategies.*`.** They enter the verdict-accuracy loop. Cost: ~1-2 days of strategy implementation each, plus calibration. Benefit: closed-loop validation across the live portfolio.
- **(B) Accept they live outside the loop.** Verdict-accuracy claims apply only to S2/S4/S7/S8 (and future Pine→tradelab strategies). S10/S12's losses don't validate or invalidate the gauntlet. Cost: zero. Benefit: honesty about scope. Risk: ~20% of live strategies invisible to the validation system forever.
- **(C) Investigate `bot.log` truncation first.** S4/S7/S8/S10 had **zero** "Position added" lines despite being deployed. If the log was truncated, attribution rate could be much higher than 25% — which would change the calibration timeline. Cost: ~half a day debugging the bot's logging. Benefit: might unblock the calibration loop without porting strategies.

**Recommendation:** **(C) first, then re-decide A vs B.** If the log was truncated, we have more data than we thought and the calibration timeline shrinks. If it wasn't, we know we're stuck at n=1 and (B) becomes the honest answer for now.

---

## Concrete agenda — first hour of next session

1. **Read the 6 docs above** (~30 min).
2. **Run the §1.C investigation** (~30 min): grep `bot.log` size history, check rotation config, verify the "Position added" pattern is what's actually emitted on entry, see if older log files exist that the retrospective didn't pick up.
3. **Decide §1 A/B/C explicitly** based on what (2) finds.
4. **Re-author scope.** Pick one of:
   - (i) Adopt LITE as the near-term plan; CALIBRATED becomes the horizon target after 30-day data accumulates.
   - (ii) Trim CALIBRATED to non-calibration-dependent slices only (likely: Slice 1a hold-out gate, Slice 4 regime banner if independent, Slice 5 K-S review if independent — defer 1b/2/3/6).
   - (iii) Pause the entire redesign for 30 days and re-run the retrospective when natively-tagged trades have accumulated. Use the time on §1.A (porting S10/S12) so the next retrospective is complete.
5. **Re-author the plan file** for whatever scope is chosen. Mandatory: every selector / signature / enum is grepped against current code at write-time, not at dispatch-time. The drift cost is paid once during planning, not N times during execution.

---

## Operational state (don't lose track of this)

| Surface | State | What to do |
|---------|-------|------------|
| tradelab repo | HEAD `09d333e` (Slice 0.5 final). 874 tests pass. | Nothing — clean. |
| tradelab repo dirty (~20 M files) | Slice 7a `handlers.py` deliberately uncommitted, plus assorted scratch. | Continue the existing pattern; don't `git add` whole files in subsequent slices. |
| Parent repo (`C:\TradingScripts`) | `command_center.html` has 36 hunks dirty (Slice 0.5 panel + months of pre-existing changes). 80+ untracked files including `alpaca_bot.log`, reports, downloaders, `.docx`/`.pdf`. | Schedule a **dedicated cleanup session**. Do not bundle into any slice's commit. |
| Phantom DB | Cleaned up 2026-04-28 (was at `C:\Users\AAASH\data\tradelab_history.db`, created by buggy cwd-relative smoke command). | Already gone. |
| Bot repo | `client_order_id` tagging shipped (Slice -0.5). Every new fill carries strategy attribution natively. | Nothing — running. |
| Daily digest | Slice 7a, on Task Scheduler at 16:30 ET. | Nothing — running. |

---

## What "in the right direction" looks like

The redesign isn't failing. It's growing up. The retrospective found real foundational issues that should change the plan — that's the system working. The wrong move would be to keep dispatching slices on a plan whose assumptions changed.

The right move:
1. Re-read the design alternatives with new evidence.
2. Decide §1 explicitly.
3. Pick a scope you can defend as evidence-grounded.
4. Re-author the plan with selectors verified up-front.
5. Resume execution.

That's a fresh-session task, not a tail-end-of-tired-session task.

---

**Files referenced:**
- `docs/superpowers/GAMEPLAN_validation_gaps.md`
- `docs/superpowers/mockups/research_tab_redesign_proposal.html`
- `docs/superpowers/mockups/research_tab_redesign_proposal_LITE.html`
- `docs/superpowers/mockups/research_tab_redesign_proposal_CALIBRATED.html`
- `docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md`
- `docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md`
- `docs/superpowers/plans/2026-04-28-research-tab-validation-redesign-CALIBRATED.md`
- `docs/superpowers/SESSION_2026-04-28_VALIDATION_REDESIGN_HANDOFF.md` (status snapshot, smoke checklist)

**Memory entries that affect this work:**
`project_validation_redesign_2026-04-28.md`, `feedback_plan_grep_verification.md`, `feedback_live_smoke_before_next_slice.md`, `project_tradelab_slice_7a_complete.md`, `reference_robustness_result_shape.md`, `reference_alpaca_trade_history_source.md`, `reference_launcher_unicode_banner.md`.
