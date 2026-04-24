# Mechanical Readiness Audit — 2026-04-24

**Scope:** Can the plumbing support a real Pine-Script-converted strategy arriving tomorrow?
**Premise:** Current deployed strategies (S2/S4/S7/S8/S10/S12) are placeholders. Real production strategies will be developed in Pine Script on TradingView and replace them. This audit asks whether the mechanical path from "new strategy idea" → "tradelab-scored" → "dashboard-displayed" → "live-traded on Alpaca" works end to end today.

---

## TL;DR

**Tradelab engine + dashboard plumbing: ~90% healthy.** All 13 audited endpoints return correctly. All 12 registered strategies import. Doctor passes. Frontend↔backend routes align with no orphans.

**The P0 gap is architectural, not buggy:** the live bot (`alpaca_trading_bot.py`) loads strategies from a separate folder (`C:/TradingScripts/FINAL STRATEGYIE/`) using a different interface than tradelab's `tradelab.strategies.*`. When a real strategy arrives, it must be ported **twice** — once for tradelab (scoring), once for the bot (execution) — and the two copies must be kept in sync as the Pine source evolves. This is the main thing to fix before real strategies land.

Two P1 bugs: (a) dashboard's `run --robustness` job submit defaults to no universe (5/11 historical jobs failed on "No symbols provided"), (b) dashboard submits `wf` with `--universe` flag that the CLI doesn't accept (1/11 failure).

---

## 1. Feature-by-feature status matrix

Verified against running dashboard on `http://localhost:8877`. Endpoints probed with live HTTP; UI interactions marked "needs browser smoke."

### Overview tab

| Feature | Endpoint | Status | Notes |
|---|---|---|---|
| Portfolio KPIs (value, P&L, cash, buying power) | `GET /api/v2/account` | ✅ GREEN | Returns cash $99,729.93, account ACTIVE |
| Positions table | `GET /api/v2/positions` | ✅ GREEN | Returns `[]` (no open positions, expected) |
| Orders table | `GET /api/v2/orders` | ✅ GREEN | Returns 8.7KB of recent orders |
| Drawdown KPI | `GET /api/v2/account/portfolio/history` | 🟡 YELLOW | Endpoint exists; needs browser smoke to confirm calendar chart renders |
| Strategy cards (6x) | Static + `GET /config` | ✅ GREEN | Toggle bug **FIXED today** (commit `e0a127b`) |
| Strategy toggle (on/off) | `POST /config` | ✅ GREEN | Verified via served HTML inspection |
| Flatten individual | `DELETE /api/v2/positions/{symbol}` + `POST /config` | 🟡 YELLOW | Works per code inspection; needs browser smoke |
| Emergency Flatten All | `DELETE /api/v2/orders` + `DELETE /api/v2/positions?cancel_orders=true` | 🟡 YELLOW | Same |
| Circuit breaker bar | `GET /config` (daily_loss_limit) | 🟡 YELLOW | Endpoint works; visual needs smoke |
| Market context (SPY) | `GET /api/v2/stocks/SPY/bars` | 🟡 YELLOW | Endpoint maps correctly |

### Calendar / Performance / Settings tabs

| Feature | Status | Notes |
|---|---|---|
| Calendar P&L master grid | 🟡 YELLOW | Source data endpoint works; needs browser smoke |
| Strategy Performance comparison table | ✅ GREEN | Static data, no backend |
| Settings > Save API keys | ✅ GREEN | Localstorage only (intentional) |
| Settings > Export/download config | ✅ GREEN | Uses `GET /config` |

### Research tab

| Feature | Endpoint | Status | Notes |
|---|---|---|---|
| Preflight chips (4) | `GET /tradelab/preflight` | ✅ GREEN | Returns 3 OK + 1 WARN (cache 27.4h old, by design) |
| Refresh Data button | `POST /tradelab/refresh-data` | 🟡 YELLOW | Endpoint mapped; not yet runtime-tested |
| Live Strategies cards (3 recent runs) | `GET /tradelab/runs?strategy=...&limit=3` | ✅ GREEN | 23 runs in audit DB, shape confirmed |
| Pipeline rows (Research table) | `GET /tradelab/runs?limit=50` | ✅ GREEN | 23 runs, verdict/PF/WR/DSR fields present |
| Pipeline filters | `GET /tradelab/runs?strategy=&verdict=&since=` | 🟡 YELLOW | Endpoint works; B1 race bug from V2 audit still open (filter-rapid-change) |
| Run dropdown menu (optimize/wf/run/full) | `POST /tradelab/jobs` | 🔴 RED | **See §2 gap "Job submission CLI-arg drift"** |
| Compare Selected button | `POST /tradelab/compare` | 🟡 YELLOW | Endpoint mapped; needs smoke |
| Compare-report viewer | `GET /tradelab/compare-report?path=...` | ✅ GREEN | Validates path regex, returns 400 for invalid (verified) |
| Report viewer (dashboard.html, quantstats) | `GET /tradelab/reports/{folder}/{file}` | ✅ GREEN | Served `executive_report.md`, `index.html`, `overview.html` all returned 200 |
| Job Tracker panel | `GET /tradelab/jobs` | ✅ GREEN | Returns 11 jobs across done/failed/cancelled states |
| SSE live job stream | `GET /tradelab/jobs/stream` | 🟡 YELLOW | Endpoint exists; needs browser smoke (long-polling can't be HTTP-probed cleanly) |
| Cancel job | `POST /tradelab/jobs/{id}/cancel` | 🟡 YELLOW | Route mapped |
| What-If sliders | `POST /tradelab/whatif` | 🟡 YELLOW | Route mapped |
| What-If save variant | `POST /tradelab/save-variant` | 🟡 YELLOW | Route mapped |
| New Strategy modal | `POST /tradelab/new-strategy` | 🟡 YELLOW | Route mapped; three actions (test/register/discard) |
| Feature flag `v2-layout` / `researchLayoutLegacy` | Frontend CSS class + localStorage | 🟡 YELLOW | Needs browser smoke |

**Legend:** ✅ verified live · 🟡 code-path works but needs a browser click-through to confirm UX · 🔴 broken

---

## 2. P0 gaps — block real-strategy arrival

### P0-1. The strategy-code split (live bot ≠ tradelab)

**Evidence:**
- `alpaca_trading_bot.py:493` sets `strategy_dir = Path(config_path).parent / "FINAL STRATEGYIE"` — bot imports strategies from `C:/TradingScripts/FINAL STRATEGYIE/*.py`
- `tradelab.strategies.*` lives at `C:/TradingScripts/tradelab/src/tradelab/strategies/*.py`
- Both directories contain `s2_pocket_pivot.py`, `s4_inside_day_breakout.py`, etc. — **different files, different interfaces**
- Bot-side S4: 214 lines, self-contained pandas script with hardcoded data dir
- Tradelab-side S4: 99 lines, uses the tradelab framework, and the file itself says *"Note vs source: the source's exit had a Below-SMA21 break test instead of the engine's Below-SMA50. Behavior will be close but not identical"*
- `alpaca_config.json` has S10 and S12 (enabled, 25%+5% allocation) that have NO tradelab-side counterpart — meaning tradelab has never scored them
- The old recon doc §1 flagged this; now confirmed in code

**Impact for Pine-Script flow:**
Every new real strategy requires two separate Python ports — one for tradelab (framework conventions, class-based, data-abstracted), one for the bot (pandas script, hardcoded pathing). Every time the Pine source changes, both ports must be updated. Drift is inevitable.

**Fix options (ordered by ambition):**

- **(a) Keep two copies, add a sync check.** Lowest effort. Add a CI test that diffs signature/parameters between bot-side and tradelab-side. Still two maintenance surfaces; just prevents silent drift. ~2h.
- **(b) Make the bot load from `tradelab.strategies.*`.** Rewrite `alpaca_trading_bot.py` to call into the tradelab framework for signal generation; bot keeps only execution + position management. Delete `FINAL STRATEGYIE/`. Single source of truth. ~1–2 days. **Recommended.**
- **(c) Full rewrite of the bot as a `tradelab live` command.** Makes tradelab the whole backend and the bot a thin CLI of it. ~1 week.

### P0-2. No defined Pine-Script ingestion pipeline

**Evidence:** No pine→python tooling in the repo, no template/scaffold for "here's how a Pine strategy becomes a tradelab strategy." The `tradelab init-strategy` CLI command exists (scaffolds a new strategy from a template) but doesn't address translation from Pine.

**Impact:** When the first real Pine strategy is ready, there's no runbook for converting it. The user ends up hand-translating under time pressure without a standard template.

**Fix options:**

- **(a) Manual translation runbook.** Document the steps: (1) scaffold via `tradelab init-strategy`, (2) paste Pine logic as comments, (3) port indicator math, (4) run `tradelab backtest` for sanity, (5) run `tradelab run --robustness` for full scoring. ~3h to write up.
- **(b) Pine→Python semi-automatic converter.** Evaluate tools (Pynescript, LLM-assisted). Would cut per-strategy porting from ~1 day to ~2 hours but adds tool-maintenance overhead.
- **(c) Webhook bridge skip-tradelab path.** Pine emits TradingView alerts → webhook endpoint → Alpaca order. Tradelab is bypassed; no verdict scoring. Fast but throws away the engine's value prop for Pine strategies.

**Decision needed:** Pick (a), (b), or (c) — this shapes the next 3 weeks of work more than any other decision.

---

## 3. P1 gaps — real bugs, not blockers

### P1-1. Job submission defaults are broken

**Evidence:** Of 11 historical job submissions:
- 6 failed (all "CLI arg error")
- 4 done (exit 0)
- 1 cancelled

Of the 6 failed:
- 5× `run --robustness`: `error_tail = "No symbols provided. Use --symbols, --universe, or --symbols @file.txt."` — dashboard submits argv without `--universe` or `--symbols`.
- 1× `wf`: `error_tail = "No such option: --universe"` — dashboard submits `--universe smoke_5` to a command that doesn't accept that flag.

**Impact:** Any user who clicks Run → "Full" on a strategy card hits this unless they've pre-selected a universe. Silent failure from the UI (job appears failed in tracker). This will bite every new-user onboarding session.

**Fix:** Update `tradelab.web.jobs._post_job()` to (a) default `--universe smoke_5` (or whatever `launcher-state.json` says is active) when none specified for `run`/`run --robustness`, and (b) NOT pass `--universe` when command is `wf` (since `wf` doesn't accept it — or add `wf --universe` to the CLI). ~1h.

### P1-2. `alpaca_config.json` strategies diverge from tradelab.yaml

**Evidence:** `alpaca_config.json` has 10 strategies (6 enabled, 3 disabled, S1 disabled). `tradelab.yaml` has 12 registered. S10 and S12 are in the bot but not in tradelab. No sync file, no validation.

**Impact:** Dashboard's Research tab and Live Strategies card can show the same strategy name with different data, or silently miss strategies. If user renames one, the other doesn't track.

**Fix:** Make `tradelab.yaml` the single source of truth; derive the bot's enabled list from it plus an `alpaca_config.json` override of capital_allocation/role/max_positions (metadata the bot needs but tradelab doesn't). ~3h once P0-1 is done (they're related).

### P1-3. `renderPipelineRows` orphan-fetch race (from V2 audit B1)

**Evidence:** Filter-change rapid-click can leave stuck "…" in metric cells. Already documented.

**Impact:** Low — cosmetic, self-heals on next page load.

**Fix:** AbortController in `renderPipelineRows`. ~1h. Already scoped in V2 audit.

---

## 4. P2 gaps — polish, defer

From the V2 audit doc (already on disk):

- **B2:** sparkline cache never invalidated (~30min fix)
- **B4:** inline `onclick` style inconsistency (~1h)
- **B6:** SVG string concat in `renderSparkline` — defense-in-depth (~1h)
- **B9:** static-test regex blind to nested template composition (~1h test-file update)

And from this audit:

- `launcher.py` + `run_dashboard.bat` on :8000 is stale — different server than the :8877 production one. Delete both to prevent double-launch confusion. ~5min.
- Several tradelab strategy files exist on disk but aren't registered in `tradelab.yaml` (`cg_tfe_v15`, `frog`, `qullamaggie_ep`, `viprasol_v83`, `simple`) — actually they ARE registered (saw in `tradelab list`). False alarm; `tradelab.yaml` lookup via the tool showed grep-truncation. Closed.

---

## 5. What's NOT broken (reassurance)

- Tradelab doctor: **all 8 critical checks pass** (python, deps, config, strategies, cache, audit_db, canaries).
- All 12 strategies import correctly.
- Audit DB has 23 runs; latest ran 2026-04-23, yesterday.
- Preflight correctly flags only real issues (cache 27.4h stale).
- Every frontend endpoint in the feature matrix maps to a real backend handler; zero orphans.
- Dashboard HTML served matches the just-landed XSS + toggle fixes (verified at runtime).
- Alpaca proxy authenticated with new key rotated today; live account returns ACTIVE.

---

## 6. Recommended sequence

Given the "strategies are placeholders" framing, the order that matters:

**Tier 1 — before real strategies arrive (MUST):**
1. **Decide the P0-2 Pine-ingestion path.** Pick (a), (b), or (c) from §2. This is 1 conversation, 0 code. But it shapes everything below.
2. **Fix P0-1 strategy-code split** (option (b) recommended: bot loads from `tradelab.strategies.*`). ~1–2 days. Do this before porting the first real strategy — otherwise every real strategy has two copies from day one.
3. **Fix P1-1 job-submit defaults.** ~1h. Small and worth it — prevents "why does Run always fail?" churn.

**Tier 2 — makes dashboard more robust (SHOULD):**
4. Fix P1-3 filter-race.
5. Fix P2 polish items from V2 audit.
6. Ship v2.1 engine-truth tooltip (spec ready, ~3h).

**Tier 3 — after Tier 1 is done, the real fun (WANT):**
7. Write the Pine→Python translation runbook per P0-2 decision.
8. Port the first real Pine strategy end-to-end as a canary — validates the whole pipeline.

---

## 7. What I did NOT do in this audit

- Did not click through the UI in a real browser. 🟡-status features need your 5-minute eyeball pass: Calendar tab render, modal flows (Compare, Run --Full, New Strategy, What-If), feature flag toggle, SSE job updates.
- Did not test `POST /tradelab/whatif` / `POST /tradelab/save-variant` / `POST /tradelab/new-strategy` with real payloads (destructive paths — require intent).
- Did not touch code. This is pure diagnosis.
- Did not make memory updates or commits.

---

**End of audit.** Total time: ~40 minutes of reads + endpoint probes. The actionable P0s reduce to two decisions (Pine path + bot-tradelab unification strategy) and one short fix (job defaults). Everything else is polish.
