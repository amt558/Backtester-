# tradelab

A local strategy-discovery instrument: every trading strategy passes through it before real capital is committed.

tradelab is not a backtest engine (that's an internal component), not a live trading system, and not a strategy generator. It converts *"this strategy looks good"* into a defensible, auditable verdict.

## The four questions tradelab answers

1. **Does it have edge?** — PF, Sharpe, DSR-adjusted Sharpe, WFE, OOS/IS ratios
2. **Is the edge real or fragile?** — 6-test robustness suite + verdict aggregator
3. **Where does it break?** — weak windows, weak symbols, cliff params, regime failures
4. **What should I fix?** — observations only (specific mechanical facts; prescriptions are out of scope)

False negatives (missing fragility) cost more than false positives (discarding a winner). Thresholds err toward FRAGILE.

## 60-second quick start

```bash
# 1. Activate venv
source /c/TradingScripts/.venv-vectorbt/Scripts/activate

# 2. Install in dev mode
pip install -e /c/TradingScripts/tradelab

# 3. Set your Twelve Data API key (one-time)
echo "TWELVEDATA_API_KEY=your_key_here" > /c/TradingScripts/tradelab/.env

# 4. Verify install
tradelab doctor

# 5. Run a strategy on a named universe with the full robustness suite
cd /c/TradingScripts/tradelab
tradelab run s2_pocket_pivot --universe magnificent_7 --start 2022-01-01 --robustness
```

Outputs land in `reports/<strategy>_<timestamp>/{executive_report.md, dashboard.html}`. Dashboard auto-opens in your browser.

## Full CLI reference

| Command | Purpose |
|---|---|
| `tradelab doctor` | Self-test: deps, API key, config, strategies, cache, audit DB, canary health |
| `tradelab list` | List registered strategies |
| `tradelab config` | Show active configuration + paths |
| `tradelab universes list` / `show <name>` | Inspect named symbol universes |
| `tradelab run <strategy>` | All-in-one: download → enrich → PIT-check → backtest → report + dashboard |
| `tradelab history list` / `show <id>` / `diff <a> <b>` | Audit-trail queries |
| `tradelab canary-health` | One-page HTML dashboard of canary verdicts |
| `tradelab backtest <strategy>` | Single backtest + QuantStats tearsheet (legacy) |
| `tradelab optimize <strategy>` | Optuna parameter search (legacy) |
| `tradelab wf <strategy>` | Walk-forward validation (legacy) |

### `tradelab run` — primary command

```
tradelab run <strategy> [options]

  --symbols CSV-or-@file     Comma list or @file.txt
  --universe NAME            Named universe from tradelab.yaml (preferred)
  --start YYYY-MM-DD         Default 2020-01-01
  --end YYYY-MM-DD           Default today
  --optimize                 Run Optuna over tunable_params
  --n-trials N               Optuna trials (default 100)
  --walkforward              Walk-forward validation
  --robustness               Full robustness suite (MC + landscape + delay + LOSO + noise)
  --mc-simulations N         MC sims per method (default 500)
  --noise-seeds N            Noise injection seed count (default 50)
  --noise-sigma-bp F         Noise sigma in basis points (default 5.0)
  --loso-trials-per-fold N   Optuna trials per LOSO fold (0 = baseline params)
  --cost-sweep               Re-run at [0, 0.5, 1, 2, 4]x commission
  --allow-yfinance-fallback  Permit yfinance when TWELVEDATA_API_KEY missing
  --no-open-dashboard        Skip auto-opening the HTML dashboard
```

## What ships in a `--robustness` run

Executive markdown report + interactive HTML dashboard with:

- **Performance:** equity curve, drawdown underwater, per-trade P&L scatter
- **Edge metrics:** PF, Sharpe, **DSR (Bailey-López de Prado)**, total/annual return, WFE
- **Robustness suite:**
  1. **Monte Carlo** — 3 resampling methods (shuffle / bootstrap / block-bootstrap) × 4 metrics (MaxDD, max loss streak, time underwater, Ulcer index), 500 sims each
  2. **Param landscape** — 5×5 joint grid on top-2 important params, smoothness ratio, cliff detection
  3. **Entry delay** — `[0, +1, +2]` bar shifts; flags look-ahead leakage
  4. **LOSO** — leave-one-symbol-out; per-fold metrics + dispersion
  5. **Noise injection** — 50 seeds × 5bp ATR-scaled OHLC noise, bar-structure preserving
  6. **Verdict** — rule-based aggregator → `ROBUST` / `INCONCLUSIVE` / `FRAGILE`

Plus, every run is recorded in an append-only SQLite audit trail at `data/tradelab_history.db` with strategy/data/config hashes for forensic reproducibility.

## Twelve Data is authoritative

By default, tradelab refuses to run without `TWELVEDATA_API_KEY` set. Pass `--allow-yfinance-fallback` to opt into yfinance fallback (use sparingly — yfinance has rate limits and occasionally hands back stale data).

The `.env` file at repo root (gitignored) is the canonical place for the key.

## Canaries — tool-health check

Four deliberately-broken strategies that tradelab MUST classify as not-ROBUST. Run monthly:

```bash
tradelab run rand_canary     --universe smoke_5 --robustness
tradelab run leak_canary     --universe smoke_5 --robustness
tradelab run survivor_canary --universe survivor_canary_universe --robustness
tradelab run overfit_canary  --universe big_tech_15 --robustness --optimize
tradelab canary-health
```

If any canary returns `ROBUST`, the tool is broken — halt all real strategy evaluations until root-caused.

## Project layout

```
tradelab/
├── README.md                                  # this file
├── HANDOVER_PREPHASE0_TO_PHASE0.md           # full multi-session handover
├── TRADELAB_MASTER_PLAN.md                   # source-of-truth scope
├── pyproject.toml
├── tradelab.yaml                             # config: paths, strategies, universes, thresholds
├── .env                                      # gitignored — TWELVEDATA_API_KEY
├── data/tradelab_history.db                  # gitignored — append-only audit
├── .cache/ohlcv/1D/*.parquet                 # gitignored — downloaded data cache
├── src/tradelab/
│   ├── cli.py                                # Typer entrypoints
│   ├── cli_run.py / cli_history.py / ...     # subcommand implementations
│   ├── config.py / env.py / determinism.py
│   ├── results.py                            # Pydantic schemas (BacktestResult etc.)
│   ├── registry.py                           # strategy registration
│   ├── data.py                               # legacy CSV loader (untouched)
│   ├── marketdata/                           # downloader + enrich + PIT
│   ├── engines/                              # backtest / optimizer / walk-forward / DSR / cost-sweep
│   ├── strategies/s2_pocket_pivot.py
│   ├── canaries/                             # 4 deliberately-broken strategies
│   ├── synthetic/dial_gauge.py               # locked engine-drift baseline
│   ├── robustness/                           # MC / landscape / delay / LOSO / noise / verdict / suite
│   ├── reporting/                            # executive markdown + tearsheet
│   ├── dashboard/                            # interactive HTML
│   └── audit/                                # SQLite history
├── tests/                                    # 158+ tests
└── reports/                                  # per-run output directories
```

## Status

Production-runnable for any strategy that follows the `Strategy.generate_signals(data, spy_close)` contract. See `HANDOVER_PREPHASE0_TO_PHASE0.md` for full multi-session implementation history (Pre-Phase-0 → Phase 1.1/2/3, four commits, 144+ tests).

## Anti-drift rules

Don't change without consulting `TRADELAB_MASTER_PLAN.md` Part XII:

- Block bootstrap is always on (never gate behind `--deep`)
- Thresholds come from `tradelab.yaml`, not code
- No prescriptive language in the executive report — observations only
- LOSO uses leave-one-out; never random 50/50 split
- Determinism is non-negotiable; every report has an `env_fingerprint` footer
- Canary failures halt all other work
- If it's not in the master plan, don't build it
