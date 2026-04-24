# Option H — Session 2 Complete (CSV Scoring Adapter)

**Date:** 2026-04-24
**Status:** SHIPPED to `master` at `2e2eae0` · Branch `feat/csv-scoring` retained locally for reference
**Previous handoff:** `docs/superpowers/OPTION_H_HANDOFF_2026-04-24.md` — read it first if you don't know what Option H is

**For a future Claude session.** This doc is a complete state dump of Session 2's deliverable, the live-system state of the project, and an actionable plan for Sessions 3 and 4. The objective is that you can pick up Option H without reading the full conversation transcript.

---

## 0. TL;DR

Option H is a 4-session project that pivots tradelab from "Python strategies on a placeholder bot" to "Pine on TradingView is the single source of truth, Python scores via CSV, executes via webhook." Sessions 1 and 2 are complete:

- **Session 1 (DONE 2026-04-24):** FastAPI webhook receiver at `:8878`, ngrok public URL, Alpaca paper integration, immutable card registry. Proven with 4 live TradingView alerts at 13:20–13:23 ET.
- **Session 2 (DONE 2026-04-24):** `tradelab score-from-trades` CLI. Parses TradingView Strategy Tester "List of trades" CSVs, computes DSR + Monte Carlo + verdict, writes a report folder identical in shape to `tradelab run` output, optionally records an audit row.

Sessions 3 (dashboard card UI) and 4 (retire the old bot + Cloudflare Tunnel + runbook) remain. **Estimated remaining effort: ~2.5 days.**

End-state architecture is unchanged from `OPTION_H_HANDOFF_2026-04-24.md` §6 — refer to that diagram.

---

## 1. What Session 2 shipped

### Code (master at `2e2eae0`)

```
src/tradelab/
├── io/
│   ├── __init__.py             — Re-exports parse_tv_trades_csv, ParsedTradesCSV, TVCSVParseError
│   └── tv_csv.py               — Pure parser. No pandas/numpy. Accepts both
│                                  legacy ("Date/Time", "Contracts", "Profit USD",
│                                  "Run-up %", "Drawdown %") AND modern 2025+
│                                  ("Date and time", "Size (qty)", "Net P&L USD",
│                                  "Favorable excursion %", "Adverse excursion %")
│                                  TV column schemas via COLUMN_ALIASES.
├── csv_scoring.py              — Orchestrator. Three public entry points:
│                                    build_backtest_result_from_trades(parsed, ...)
│                                    score_trades(parsed, ...)
│                                    write_report_folder(out, base_name, ...)
├── cli_score.py                — `tradelab score-from-trades` command body
├── cli.py                      — One new registration line at the bottom
└── engines/_diagnostics.py     — Added metrics_from_trades(trades, starting_equity)

tests/
├── io/
│   ├── fixtures/tv_export_amzn_smoke.csv  — 6 closed + 1 open trade
│   └── test_tv_csv.py                     — 11 tests
├── engines/test_metrics_from_trades.py    — 6 tests
├── test_csv_scoring.py                    — 7 tests
└── cli/test_cli_score.py                  — 4 tests
```

**Test totals:** 28 new tests, all green. Full suite: 339 passed, 3 pre-existing failures (verified pre-existing on master before the merge — zero regressions from this work).

### CLI usage (the user-facing surface)

```
tradelab score-from-trades <csv_path>
    --symbol AMZN
    --name viprasol-amzn-v1
    [--timeframe 1H]           # cosmetic, default 1D
    [--starting-equity 100000] # default
    [--mc-simulations 500]     # default
    [--pine-path <path>]       # archives Pine source next to report
    [--audit/--no-audit]       # default --audit
    [--open-dashboard/--no-open-dashboard]  # default --open-dashboard
```

Outputs a folder under `reports/<name>_<YYYY-MM-DD_HHMMSS>/` containing:

```
executive_report.md     — same renderer as `tradelab run`
dashboard.html          — best-effort; missing tabs render as 'no data'
backtest_result.json    — pydantic dump for `tradelab compare` parity
tv_trades.csv           — verbatim copy of the imported CSV
strategy.pine           — only if --pine-path was provided
```

### Documented degradations (vs `tradelab run`)

The CSV path cannot run engines that require re-executing the strategy:

- ❌ Optuna (requires re-running with different params)
- ❌ Walk-forward (requires re-running on rolling windows)
- ❌ Param landscape (requires param-space sweep)
- ❌ Entry-delay test (requires +N-bar shift on bar data)
- ❌ Noise injection (requires perturbing bar prices)
- ❌ LOSO (requires per-symbol re-execution; user can approximate by exporting per-symbol CSVs separately and scoring each)
- ❌ Regime breakdown (requires SPY OHLCV; CSV has none)

So the verdict aggregator runs with `compute_verdict(bt, dsr=dsr_p, mc=mc)` only. Maximum of 3 signals, which mathematically caps the achievable verdict at INCONCLUSIVE unless all 3 fire robust.

### Process discipline used

Built via subagent-driven development (`superpowers:subagent-driven-development`). For each of the 6 plan tasks:
1. Implementer subagent (general-purpose, sonnet) — writes failing test first, then implementation, then commits
2. Spec compliance reviewer subagent — independently verifies code matches spec by reading actual files
3. Code quality reviewer subagent (`superpowers:code-reviewer`) — independently reviews against quality concerns
4. Fix loop until both reviewers approve

**Defects caught and fixed by the review loops** (would have shipped to master without):
- 1 Critical: `config_hash=hash_config({})` was constant for every CSV import — defeated audit DB integrity
- 8 Important: silent crash on TV timestamps with seconds; silent truncation of fractional contracts (Pine `percent_of_equity=95` produces fractional shares); precision mismatch with engine's `pct_return`; missing `starting_equity<=0` guard; broad `except Exception` on annualization; `--open` flag inconsistency with `tradelab run`; missing `--mc-simulations` parity flag; dead `classify_dsr` import
- A 9th issue caught by live testing: TradingView's 2025+ Strategy Tester export uses a different column schema than my plan baked in. Fixed via `COLUMN_ALIASES` so parser accepts both.

The plan that drove all of this lives at `docs/superpowers/plans/2026-04-24-csv-scoring-adapter.md`.

---

## 2. End-to-end smoke (real-world results)

Tested against actual TradingView exports of the user's Viprasol v8.2 Pine strategy (1H timeframe, 2014-01 → 2026-04). Pine source archived at `C:\Users\AAASH\Downloads\viprasol_v8_2.pine`.

| Symbol | Trades | PF | DSR | Net P&L | Max DD | Verdict |
|---|---|---|---|---|---|---|
| **AMZN** | 887 | 1.088 | 0.883 | +85% | −45.5% | **FRAGILE** |
| **MU** | 1,319 | 1.418 | 0.997 | +1,240% | −43.7% | **INCONCLUSIVE** |
| **NVDA** | 1,329 | 1.291 | 1.000 | +9,206% | −51.5% | **INCONCLUSIVE** |

**Reading:** strategy works on momentum names (MU, NVDA) and chokes on AMZN's post-2022 mega-cap drift. INCONCLUSIVE is the verdict ceiling on the CSV path (only 3 verdict signals available); both MU and NVDA scored at the ceiling.

A separate `tradelab run viprasol_v83 --robustness --symbols MU,NVDA,SPY` run on the registered Python strategy returned INCONCLUSIVE (5 robust / 2 inconclusive / 1 fragile). The Python strategy is documented in `src/tradelab/strategies/viprasol_v83.py:12-30` as a daily-bar approximation with a different exit model — its results validate that the **strategy family** is mechanically sound (smooth landscape, edge survives noise + entry delay, edge distributes across symbols) but the verdict is not directly comparable to the 1H Pine.

**Real reports retained on disk** for inspection:
- `reports/viprasol-amzn-v1_2026-04-24_151323/`
- `reports/viprasol-mu-v1_2026-04-24_151840/`
- `reports/viprasol-nvda-v1_2026-04-24_152129/`
- `reports/viprasol_v83_2026-04-24_152612/` (full robustness, code-path)

---

## 3. What's wired vs what isn't (live system state)

### ✅ Wired and working

| Component | Path | Notes |
|---|---|---|
| Webhook receiver | `src/tradelab/live/receiver.py` on `:8878` | FastAPI; `GET /health`, `POST /webhook`. Validates secret, looks up card, routes to Alpaca. |
| Card registry | `live/cards.json` (gitignored runtime data) | 3 test cards (`test-amzn-v1`, `test-amzn-disabled`, `smoke-test-v1`) — DELETE before going to real production. |
| Alpaca client | `src/tradelab/live/alpaca_client.py` | Reads creds from `C:/TradingScripts/alpaca_config.json`. Paper trading. |
| Alert log | `live/alerts.jsonl` | Append-only audit of every webhook event (accepted + rejected). |
| ngrok tunnel | Ephemeral free-tier URL | Per-session — Windows reboot = new URL. Cloudflare Tunnel migration is a Session 4 task. |
| `tradelab` web dashboard | `C:\TradingScripts\command_center.html` on `:8877` | 5 tabs: overview, calendar, performance, settings, **research**. Research tab is at v2.0 (preflight chips, failure hints, compare-N-runs, FRAGILE tooltips, sparklines). |
| `tradelab score-from-trades` CLI | `src/tradelab/cli_score.py` | Session 2 deliverable. Works end-to-end. Verified live on Viprasol v8.2 across 3 symbols. |
| Audit DB | `data/tradelab_history.db` | Row appended per scoring run. Session 2 fix made `config_hash` actually distinguish CSV imports (encodes symbol + timeframe + starting_equity + n_trades). |
| Verdict engine | `src/tradelab/robustness/verdict.py` | Untouched in Session 2 — full thresholds in `tradelab.yaml` under `robustness.thresholds`. |
| Existing engines | `engines/backtest.py`, `engines/dsr.py`, `engines/optimizer.py`, `engines/walkforward.py`, `robustness/*.py`, `dashboard/builder.py`, `reporting/executive.py` | Unchanged. |

### ❌ Not yet wired (the Session 3 + 4 gap)

| Missing piece | What's needed | Where the backend already exists |
|---|---|---|
| Dashboard CSV paste UI | `<textarea>` for CSV paste + filename hint | — (Session 3 frontend) |
| Dashboard Pine source paste UI | `<textarea>` for Pine source | — (Session 3 frontend) |
| Accept button | `POST /tradelab/approve-strategy` handler | `csv_scoring.score_trades` + `csv_scoring.write_report_folder` already do everything; the backend handler just needs to be a thin wrapper |
| Pine archive folder | `pine_archive/{card_id}/strategy.pine + tv_trades.csv + verdict.json` | `write_report_folder` already takes `pine_source` and `csv_text`; just needs renamed/moved into a card-archive layout |
| Card-registry UI | List/edit/delete cards in dashboard Live Strategies panel | Backend `live/cards.py::CardRegistry` already exposes load/get/save (read `src/tradelab/live/cards.py`); frontend `renderLiveCard(...)` exists in `command_center.html` and currently displays placeholder strategies — needs to source from `cards.json` instead |
| Two-step Delete + Flatten flow | "Disable + Flatten + Delete" combo button with type-the-name confirm | Alpaca client has position close API; needs UI |
| Auto-versioning | `viprasol-amzn` → `viprasol-amzn-v1`, `-v2` on reuse | — (Session 3 logic) |
| File-watch / reload endpoint | `POST /internal/reload` on receiver to hot-pick new cards from `cards.json` after dashboard writes | Receiver currently loads cards once at startup; needs reload trigger |
| Cloudflare Tunnel | Replace ephemeral ngrok URL with stable Cloudflare named tunnel | Session 4 |
| Old-bot retirement | Delete `alpaca_trading_bot.py` + `FINAL STRATEGYIE/` + `launcher.py` + simplify `alpaca_config.json` | Session 4 |
| Runbook | "How Amit adds a new strategy end-to-end" doc | Session 4 |

### ⚠️ Known limitations to watch out for

- **Pine ↔ Python drift on Viprasol v8.3:** the registered Python strategy is a daily-bar approximation with a different exit model. Code-path robustness suite produces verdicts that aren't directly comparable to the 1H Pine CSV path. For real strategy decisions, trust the CSV path.
- **CSV path verdict ceiling is INCONCLUSIVE.** Only 3 verdict signals (baseline_pf, dsr, mc_max_dd) are available without bar data. Mathematically can't score ROBUST without all 3 firing robust simultaneously.
- **`regime_spread` signal is misleading on momentum strategies.** The Viprasol code-path run reported `regime_spread: robust` but the explanation showed `bull=78% of trades` — strategy's RS+EMA filters by construction avoid bear regimes, so we don't actually know how the strategy performs in a bear; we just know it doesn't fire much. Worth surfacing in the card UI in Session 3.
- **`shares` truncation rounded, not floored:** Pine's `percent_of_equity=95` produces fractional contracts in the CSV (e.g., 4740). Parser uses `int(round(...))`. For ~4000+ contracts this rounds within ±0.5 — invisible. For very small share counts (crypto perpetuals at 0.5 BTC) the banker's rounding could surprise. Equities-only: non-issue today.
- **TV CSV column schema may change again.** Parser handles both legacy and 2025+ schemas via `COLUMN_ALIASES` in `src/tradelab/io/tv_csv.py:17-30`. If TradingView renames more columns, add the new name to the relevant tuple.

---

## 4. Sessions 3 and 4 — actionable plan

### Session 3 — Dashboard card UI (~2 days)

**Goal:** the user pastes CSV + Pine → clicks Accept → gets a card → flips it ON → live trades. All in the existing `:8877` dashboard.

**Pre-flight (~30 min):** Re-read `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md` to understand the current Research tab v2.0 layout, JS architecture (state in `researchState`, event delegation, `renderLiveCard`), and the backend handler patterns in `src/tradelab/web/handlers.py`.

**Tasks** (suggested decomposition; refine via `superpowers:writing-plans` before executing):

1. **Backend: new-strategy approval endpoint** (~3h)
   - `POST /tradelab/approve-strategy` body: `{ csv_text, pine_source, base_name, symbol, timeframe }`
   - Handler reads CSV → calls `csv_scoring.score_trades` → calls `csv_scoring.write_report_folder` with audit on
   - Then writes a card entry to `tradelab/live/cards.json` (status: disabled by default — user toggles ON manually)
   - Auto-versioning: if `base_name` exists, append `-v{n+1}`
   - Returns `{ card_id, verdict, report_folder, scoring_run_id }` for the frontend
   - File: extend `src/tradelab/web/new_strategy.py` (already exists for the existing "create strategy" flow) or create `src/tradelab/web/approve_strategy.py`
   - Tests: `tests/web/test_approve_strategy.py` (mock cards.json, assert versioning, assert verdict pass-through)

2. **Frontend: Research-tab Accept widget** (~3h)
   - Add a "Score & Approve" panel to the Research tab
   - Two textareas: CSV paste, Pine source paste
   - Symbol input + base-name input + timeframe dropdown
   - "Score" button → calls `POST /tradelab/approve-strategy` → shows verdict inline (re-use the FRAGILE/ROBUST color logic from existing `verdictHeatClass()`)
   - "Accept" button (only enabled after a successful score) → confirms verdict → flips card to disabled state in registry
   - Edit `command_center.html` only — keep with v2.0 conventions

3. **Backend: card-list endpoint** (~1h)
   - `GET /tradelab/cards` → returns serialized `cards.json` content
   - File: `src/tradelab/web/handlers.py` (add a handler) + thin wrapper around `src/tradelab/live/cards.py::CardRegistry.list()`
   - Tests: `tests/web/test_cards_endpoint.py`

4. **Frontend: Live Strategies panel sourced from cards.json** (~2h)
   - Currently `renderLiveCard()` shows placeholder strategies from `alpaca_config.json`. Switch to fetching `/tradelab/cards`.
   - Each card row shows: card_id, symbol, status (ON/OFF), live position from Alpaca, recent trades count, link to verdict report
   - ON/OFF toggle calls `PUT /tradelab/cards/{id}` (also new — see Task 5)

5. **Backend: card toggle + delete + flatten** (~3h)
   - `PUT /tradelab/cards/{id}` body: `{ enabled: bool }` → updates registry
   - `DELETE /tradelab/cards/{id}` with require-name-confirm header — refuses if status is ON or has open positions
   - `POST /tradelab/cards/{id}/flatten` — closes all Alpaca positions for that card
   - "Disable + Flatten + Delete" combo: frontend orchestrates these 3 calls
   - Tests: `tests/web/test_card_lifecycle.py`

6. **Receiver: hot-reload cards.json** (~1h)
   - Add `POST /internal/reload` endpoint to `src/tradelab/live/receiver.py`
   - Dashboard calls it after every cards.json mutation (or use file-watch, but explicit reload is simpler)
   - Update `cards.py::CardRegistry` to expose a `reload()` method if not already

7. **Polish + smoke** (~2h)
   - End-to-end manual test: paste Viprasol CSV → score → accept → toggle ON → fire a smoke alert from TV → verify Alpaca fill
   - Clean up the 3 test cards from `cards.json` once a real card exists

**Done definition:** Amit can paste a Viprasol v8.2 AMZN CSV into the dashboard → see verdict → click Accept → see a card appear in Live Strategies → flip it ON → TV alert fires → Alpaca fills. Without leaving the dashboard.

### Session 4 — Retire old bot + cleanup (~half day)

**Tasks** (unchanged from `OPTION_H_HANDOFF_2026-04-24.md` §5):

1. Delete `C:/TradingScripts/alpaca_trading_bot.py`
2. Delete `C:/TradingScripts/FINAL STRATEGYIE/` folder
3. Simplify `alpaca_config.json` — remove `strategies[]` array (cards replace it)
4. Delete `C:/TradingScripts/launcher.py` and `C:/TradingScripts/run_dashboard.bat`
5. Update `Launch_Dashboard.bat` to also start the webhook receiver
6. Migrate ngrok → Cloudflare Tunnel (named tunnel, free, stable URL)
7. Wrap receiver as Windows service (via `nssm` or `pywin32`) for reboot survival
8. Write the runbook: "How Amit adds a new strategy end-to-end" (~2h doc)
9. Nightly reconciliation job: compare Alpaca fills vs expected-trades from receiver alert log

**Open after Session 4:** real-world soak. Run a real strategy on real money (paper) for 30+ days, then evaluate verdict-vs-reality calibration.

---

## 5. Resume instructions for the next Claude session

### If you're picking up Session 3

```bash
cd C:\TradingScripts\tradelab

# 1. Verify state
git status                      # should be clean
git log --oneline -3            # HEAD should be 2e2eae0 or later
git branch                      # should be on master; feat/csv-scoring may still exist locally

# 2. Confirm Session 1 services are running (if not, restart per OPTION_H_HANDOFF_2026-04-24.md §9)
Get-NetTCPConnection -LocalPort 8878 -State Listen -ErrorAction SilentlyContinue   # receiver
Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue   # ngrok
Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue   # dashboard

# 3. Test the Session 2 deliverable still works
PYTHONPATH=src; PYTHONIOENCODING=utf-8
python -m tradelab.cli score-from-trades tests/io/fixtures/tv_export_amzn_smoke.csv `
    --symbol AMZN --name smoke-v1 --no-open-dashboard --no-audit
# Expect: "Verdict: ..." line + a folder under reports/smoke-v1_*/
# Then: rm -rf reports/smoke-v1_*

# 4. Start brainstorming Session 3
# - Read this doc end-to-end
# - Read docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md (current dashboard architecture)
# - Read src/tradelab/web/handlers.py (handler patterns to follow)
# - Read src/tradelab/live/cards.py (registry API to wrap)
# - Read src/tradelab/csv_scoring.py (the orchestrator the new endpoint will call)
# - Use superpowers:brainstorming to scope the work, then superpowers:writing-plans to draft a plan
# - Execute the plan via superpowers:subagent-driven-development (this worked well for Session 2)
```

### If you're picking up Session 4 (after Session 3 lands)

Refer to `OPTION_H_HANDOFF_2026-04-24.md` §5 — Session 4 task list is unchanged.

### Required reading before either

- This doc (you're in it)
- `docs/superpowers/OPTION_H_HANDOFF_2026-04-24.md` — original Option H rationale, workflow design, architecture diagram
- `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md` — current dashboard JS architecture, state model, event delegation patterns
- `docs/superpowers/plans/2026-04-24-csv-scoring-adapter.md` — Session 2 plan (useful template for Session 3 plan)
- The user's auto-memory at `C:/Users/AAASH/.claude/projects/C--Users-AAASH/memory/MEMORY.md` — particularly:
  - `project_option_h_workflow_design.md` — Amit's immutable-card workflow
  - `project_tradelab_placeholder_strategies.md` — S2/S4/S7/S8/S10/S12 are scaffolding
  - `feedback_plan_grep_verification.md` — verify plan selectors against current code first
  - `feedback_web_over_hotkeys.md` — Amit prefers web UI over hotkeys (Session 3 is exactly this preference)
  - `reference_alpaca_config_location.md` — creds in JSON, not env

---

## 6. Open questions / pending decisions

Same set as `OPTION_H_HANDOFF_2026-04-24.md` §10, plus one new:

1. **Cloudflare Tunnel migration** — still deferred to Session 4 start. ~20 min. Stable URL so TV alerts don't break on ngrok restart.
2. **Gitignore policy for `tradelab/live/`** — runtime data (`cards.json`, `alerts.jsonl`) contains secrets. Decide at next commit time.
3. **Receiver as Windows service** — Session 4 task. `nssm` is the simplest option.
4. **Retry / reconciliation on missed alerts** — Session 4+ task. Nightly job compares Alpaca fills to expected-trades from alerts.jsonl.
5. **NEW: Pine→Python port hardening** — the Viprasol v8.3 daily-bar Python proxy is too divergent from the 1H Pine to give comparable robustness verdicts. Either tighten the Python port (rewrite exits to match Pine) or formally deprecate the Python path for any strategy where a Pine version exists. Recommendation: deprecate; the Pine is the SOT per Option H.

---

## 7. Retired ideas (don't revisit)

Same set as `OPTION_H_HANDOFF_2026-04-24.md` §11. Plus:

- **Per-symbol parsers / multi-format CSV adapter (e.g., the Python-backtest CSVs in Downloads).** Considered during Session 2; rejected. Option H workflow is TV-only as the source of truth. The old Python-backtest CSVs (`v17c_AMZN_45m_L_trades.csv` etc. in Amit's Downloads) are historical artifacts; if old strategies need to be re-scored, re-backtest them in TV first.

---

## 8. Reproducibility footer

```
tradelab:   master @ 2e2eae0
session 2 branch (retained):  feat/csv-scoring @ 2e2eae0  (12 commits ahead of pre-session master 8a9a342)
python:     3.13.13
pytest:     9.0.3 — 339 passed (28 new), 3 pre-existing failures (zero regressions)
generated:  2026-04-24
```

**End of Session 2 handoff.**
