# tradelab — Context Briefing for Claude

> Share this file with Claude (Desktop, Code, or API) so it can advise on
> tradelab work without needing to re-derive the project's conventions. The
> rules here are non-negotiable; many exist because of specific incidents.

---

## 1. What tradelab is

A local strategy-discovery CLI and launcher that gates real-capital
deployment. Every trading strategy passes through its validation gauntlet
(baseline PF, Deflated Sharpe Ratio, Monte Carlo resampling, noise
injection, entry-delay, LOSO, walk-forward, regime-concentration) before
being considered trustworthy.

**Core philosophy: err toward FRAGILE.** Missing a real fragility (false
negative) costs more than discarding a winner (false positive). Thresholds
are deliberately strict. Never propose changes that dilute this bias.

---

## 2. Location

| Path | Purpose |
|------|---------|
| `C:\TradingScripts\tradelab\` | Repo root |
| `C:\TradingScripts\.venv-vectorbt\` | Python 3.12 venv (name is legacy; vectorbt was removed) |
| `C:\TradingScripts\tradelab\tradelab.yaml` | Active config |
| `C:\TradingScripts\tradelab\.cache\ohlcv\1D\*.parquet` | Authoritative data cache |
| `C:\TradingScripts\tradelab\.cache\optuna_studies.db` | Optuna study persistence |
| `C:\TradingScripts\tradelab\.cache\launcher-state.json` | Launcher state (active strategy/universe/toggles) |
| `C:\TradingScripts\tradelab\.cache\yaml_backups\` | Auto-backups of tradelab.yaml before each write |
| `C:\TradingScripts\tradelab\reports\` | All run artifacts (index.html, overview.html, per-run dashboards) |
| `C:\TradingScripts\tradelab\data\tradelab_history.db` | Audit DB of all runs |
| `C:\TradingScripts\tradelab\tradelab-launch.bat` | Double-clickable launcher entry point |

---

## 3. Data pipeline — **Twelve Data ONLY; CSV concept is dead**

- **Authoritative source**: `tradelab.marketdata.download_symbols()` → Twelve
  Data API → parquet cache at `.cache/ohlcv/1D/`.
- `TWELVEDATA_API_KEY` env var required; user is on the paid tier.
- **Do NOT propose, reference, or fall back to CSV paths.** The old
  `tradelab.data` module still exists but is DEPRECATED — never suggest it.
- **Do NOT reference AmiBroker_Data, `*_1min.csv`, or `paths.data_dir`** in
  new code or advice. The yaml no longer sets `data_dir`.
- Launcher shows data freshness in the banner; toggle `rb` enables a
  startup prompt that offers to refresh via Twelve Data if cache is stale
  (>24h by default).

---

## 4. Registered strategies (12 total)

| Name | Status | Concept |
|------|--------|---------|
| `s2_pocket_pivot` | ported | Chris Kacher pocket pivot with trend alignment + RS filter + ATR trail |
| `s4_inside_day_breakout` | ported | Inside day → breakout above prior high on 1.2×+ volume |
| `s7_rdz_momentum` | ported | RSI z-score mean reversion on trending stocks |
| `s8_bullish_outside_day` | ported | Engulfing candle in uptrend on 1.5×+ volume |
| `qullamaggie_ep` | ported | Qullamaggie Episodic Pivot — ported from DeepVue research |
| `viprasol_v83` | ported | Viprasol v8.3 composite-score entry |
| `cg_tfe_v15` | scaffold | CG-TFE v1.5 — placeholder modules, NOT a real strategy |
| `frog` | registered | User-created test strategy (scaffold from `ns`) |
| `rand_canary` | canary | Random entries — DSR must flag fragile (tool-health anchor) |
| `overfit_canary` | canary | 6-param pathological — Optuna+WF must show IS/OOS decay |
| `leak_canary` | canary | Look-ahead bias — entry-delay test must collapse it |
| `survivor_canary` | canary | Curated winners — LOSO must reveal per-symbol spread |

**Canaries are deliberately broken.** If any returns ROBUST, tool trust is
compromised. **NEVER delete or "fix" their numbers.** The `doctor` command
includes a canary-health check.

---

## 5. CLI commands (what `tradelab <cmd>` does)

| Command | Purpose |
|---------|---------|
| `tradelab run <strategy>` | Full pipeline: download → backtest → dashboard → audit. Flags: `--optimize`, `--walkforward`, `--robustness`, `--cost-sweep`, `--full` (all), `--universe <name>` |
| `tradelab backtest <strategy>` | Baseline backtest (no optimize/WF/robustness) |
| `tradelab optimize <strategy>` | Optuna tuning on `tunable_params`; persists to `.cache/optuna_studies.db` |
| `tradelab wf <strategy>` | Walk-forward with per-window Optuna |
| `tradelab compare <run_folders...>` | Cross-run comparison (QuantStats multi-strategy + SPY overlay + regime breakdown) |
| `tradelab gate-check --symbols X --gates Y` | Pearson correlation between indicator gates; flags redundant combinations |
| `tradelab overview` | Portfolio overview HTML — one row per registered strategy with latest run |
| `tradelab rebuild-index` | Regenerate `reports/index.html` from audit DB |
| `tradelab doctor` | Env/config/strategy health check |
| `tradelab list` | Show registered strategies |
| `tradelab screen <strategy>` | Per-symbol backtest for strategy-screening |
| `tradelab history` | Query audit DB |

---

## 6. The launcher (`tradelab-launch.bat`)

Double-click opens a PowerShell menu with these sections:

### HOME — quick views
- `t` — open latest tearsheet for active strategy (robustness > dashboard > quantstats)
- `ts` — open quantstats tearsheet specifically
- `o` — build + open portfolio overview
- `r` — recent runs picker (open any prior dashboard)
- `c` — compare last 2 runs of active strategy

### STRATEGY — create/edit
- `ns` — new strategy (scaffold + editor + validate: import + runtime smoke on smoke_5 + register)
- `ne` — edit active strategy (re-validates on save-close)
- `nc` — clone strategy (source + params → new name + class)
- `nd` — delete strategy (archives source to `_archive/`, optional audit cleanup; REFUSES canaries)
- `pp` — promote latest run's params to yaml defaults (with diff preview)
- `s` / `u` — change active strategy / universe (persists)

### RUN — compute
- `1` — quick optimize (20 trials, no tearsheet)
- `2` — quick walk-forward (10 trials/window)
- `3` — run + dashboard (baseline, ~1-2 min)
- `3r` — run + robustness suite (~3-5 min)
- `3f` — run `--full` (optuna + wf + cost + robustness, ~10 min; confirm prompt)

### HEALTH
- `d` — re-run doctor
- `!` — canary suite (must NOT return ROBUST)
- `g` — gate-check indicator correlations

### DATA
- `rf` — refresh active universe via Twelve Data
- `rb` — toggle startup-refresh prompt (default ON)
- `rp` — toggle pre-run-refresh prompt (default OFF)

### EXTERNAL
- `#` — launch AlgoTrade Command Center (Alpaca-connected, `Launch_Dashboard.bat` → port 8877)

### UTIL
- `4/5/6` — rebuild index / open optuna-dashboard tab / open index tab
- `k` — kill optuna-dashboard on :8080
- `i` — install Desktop shortcut
- `z` — cleanup orphan run folders
- `x` — custom tradelab command

### META
- `h` — help glossary (full key reference)
- `q` — quit

---

## 7. Verdict system

Every `--robustness` or `--full` run emits **ROBUST / MARGINAL / FRAGILE /
INCONCLUSIVE**. Signals contributing:

| Signal | Flags fragile when |
|--------|--------------------|
| `baseline_pf` | PF < 1.1 |
| `dsr` | Deflated Sharpe prob < 0.50 |
| `mc_max_dd` | Observed DD in bottom 10% of shuffle sims |
| `param_landscape` | Fitness drops sharply near optimum (cliff) |
| `entry_delay` | PF collapses if signals shift ±1–2 bars |
| `loso` | Per-symbol PF spread > 1.0 (edge concentrated) |
| `noise_injection` | PF drops > 40% at p5 noisy run |
| `wfe` | OOS_PF / IS_PF < 0.50 |
| `regime_spread` | Worst-regime PF / best-regime PF < 0.40 |

**Aggregation rule**: 2+ fragile → FRAGILE. 1 fragile with 0 robust →
FRAGILE. All-robust → ROBUST. Otherwise INCONCLUSIVE.

**Regime hard-gate override**: if `regime_spread < 0.20` (edge is
regime-specific), verdict is forced FRAGILE regardless of other signals.
This closes the loophole where a bull-only strategy could score ROBUST.

**Regime sample-size guard**: each regime needs at least
`max(5 trades, 10% of total trades)` to contribute to the spread ratio.
Prevents noisy tiny-sample regimes from firing false signals.

Thresholds live in `tradelab.yaml → robustness.thresholds`.

---

## 8. Things to NEVER propose

These are ruled out by prior decisions — don't suggest them:

- **vectorbt** — was evaluated in April 2026, dropped. Semantic drift vs tradelab's portfolio logic made it net-negative. Not a dep.
- **CSV loaders / AmiBroker_Data / `tradelab.data`** — deprecated. Twelve Data parquet cache is the only data path. Do not propose fallbacks.
- **Pre-filters on historical windows** (e.g. "run strategy only on Minervini-passing symbols") — introduces survivorship bias at the universe level. Was ripped out. Minervini-style filters are OK for live scanning (point-in-time), NEVER for backtest trimming.
- **Purged K-Fold / CPCV / Bonferroni corrections** — ruled out per TRADELAB_MASTER_PLAN.md.
- **Smoothing the verdict** (e.g. continuous robustness score replacing ROBUST/FRAGILE labels) — dilutes the FRAGILE bias. If discussed, can be ADDITIVE but never replace the buckets.
- **Auto-generation of strategy code by LLM** — interpretation/narration OK, generation violates the "err toward FRAGILE" research discipline.
- **Grid search as primary optimizer** — Optuna TPE is the choice. Grid search over 10k+ combos amplifies overfitting.

---

## 9. Recent session additions (April 2026)

- DeepVue MCP indicator library absorbed into `tradelab.indicators.deepvue` (ATR%, ADR%, Sigma Spike, RMV, RS, Weinstein, VCP, Minervini, Pocket Pivot, etc.)
- `tradelab gate-check` command (Pearson correlation between indicator gates)
- Qullamaggie Episodic Pivot ported as a first-class strategy
- Regime-conditional performance (bull/chop/bear by SPY state at entry) with three-tier verdict (soft / hard / insufficient-data)
- Expected-return distribution emitted from Monte Carlo (annualized p5/p50/p95 on tearsheet + index/overview)
- Monthly P&L attribution in the Trades tab
- Launcher menu reorganized into HOME / STRATEGY / RUN / HEALTH / UTIL / DATA / EXTERNAL / META with full `h` help glossary
- Strategy authoring lifecycle: `ns` (new) / `ne` (edit) / `nc` (clone) / `nd` (delete/archive) / `pp` (promote params)
- Two-stage strategy validation: import check AND runtime smoke test on smoke_5
- YAML auto-backup to `.cache/yaml_backups/` before any write (last 10 retained)
- Data-freshness banner + `rf/rb/rp` refresh toggles (parquet cache only)
- AlgoTrade Command Center integration via `#` key (Alpaca on :8877)
- Launcher state persistence (active strategy/universe/toggles survive restarts)
- Regression detection after each run (PF drop ≥10%, MaxDD worse ≥25%, or verdict degradation → explicit warning)
- **Unified dark theme (CC-matched palette)** across every HTML surface: index, overview, per-run dashboard, compare, robustness tearsheet, QuantStats tearsheet (via CSS override), screener. Single source of truth in `src/tradelab/dashboard/_theme.py` (exports `THEME_CSS` + `apply_plotly_theme(fig)`). No theme toggle. Palette: `--bg #0f1117`, `--bg-panel #1e2028`, `--accent #22c55e`, `--win #22c55e`, `--loss #ef4444`, `--warn #eab308`, Inter font.

---

## 10. Work-in-progress — Unified web dashboard (NOT YET STARTED)

**Status**: Scoped, approved in principle, awaiting explicit go-ahead for Day 1. User is a full-time active trader with three monitors running multiple strategies; web dashboard will live on monitor 3 while trading happens on 1–2.

**Goal**: Single bookmarkable URL (`localhost:8500`) replacing the scattered `reports/*.html` workflow. Sidebar nav across Runs / Strategies / Compare / Optuna / Settings. Launch triggered via new launcher key `w`.

**Tech stack (decided)**: FastAPI + Jinja2 + HTMX for partial updates + SSE for live run progress. Reuses existing `THEME_CSS` from `dashboard/_theme.py` — no new styling work. Background task runner hooks into existing `progress_cb` in engines.

**Open question (must answer before Day 1)**: LAN access for tablet/phone (`0.0.0.0` + firewall rule) vs localhost-only (`127.0.0.1`, just this machine).

**Day-by-day plan (~5 days)**:

| Day | Deliverable |
|-----|-------------|
| 1 | FastAPI skeleton. Routes: `/`, `/runs`, `/strategies`, `/compare`, `/optuna`, `/settings`. Jinja2 templates. Serve `reports/` as static. Reuse `THEME_CSS`. Sidebar nav. `tradelab serve` CLI cmd. |
| 2 | `/runs` view. Live table from `reports/*/backtest_result.json`. Filters (strategy, verdict, date, min trades) persisted in URL. Sparklines. 30s auto-refresh. |
| 3 | `/runs/<id>` drill-down. Embeds existing `dashboard.html` in iframe. Native panels above (quick stats, verdict pill, param block, "rerun with tweaks" button). |
| 4 | Trigger-a-run form. Strategy dropdown + param overrides. SSE stream for live progress. Background task runner. |
| 5 | `/compare` multi-select → one-click compare report. `/optuna` study tables + best-trial params. Polish. Launcher `w` key. |

**What it won't do**: generate alpha, replace the launcher, replace `tradelab` CLI commands. Pure UX layer over existing outputs.

**Anti-scope-creep**: this is FastAPI-only. No React, no Next.js, no build step, no PWA. If I drift toward any of those, stop me.

**Resume point for a fresh Claude Code session**:
1. Read this file + `MEMORY.md` + `project_tradelab.md`.
2. Ask user: LAN or localhost-only?
3. Start Day 1: create `src/tradelab/web/` package (`app.py`, `templates/`, `static/`), wire `tradelab serve` via CLI.
4. Confirm Day 1 deliverable visible at `localhost:8500` before proceeding to Day 2.

---

## 11. When in doubt

- Read `TRADELAB_MASTER_PLAN.md` in repo root before proposing design changes — it's the source of truth for scope and anti-drift rules.
- Check `tradelab-launch.ps1` for the current launcher behavior.
- `tradelab doctor` tells you if the environment is sane.
- If a feature sounds useful but conflicts with "err toward FRAGILE," the philosophy wins.
