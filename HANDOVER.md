# Handover packet — April 17, 2026 → tomorrow

**Purpose:** Resume the tradelab build without losing context. If Claude has no memory of our session, this document plus the code is everything needed to pick up exactly where we stopped.

---

## Session 1 status: 95% complete, awaiting verification

**What's built and on disk:**
- Full tradelab package skeleton at `C:\TradingScripts\tradelab\`
- All Session 1 files present (pyproject.toml, tradelab.yaml, src/tradelab/*, etc.)
- Folder structure is correct (single level, not double-nested — fixed April 17)
- Dependencies installed in `.venv-vectorbt`: typer, rich, pydantic, pyyaml, quantstats, jinja2

**What's NOT yet done (tomorrow's first task):**
- Install tradelab itself as editable package
- Run the 3 verification commands
- Confirm smoke-test tearsheet renders correctly

---

## Tomorrow's first 15 minutes — the exact commands

Open PowerShell. Run these in sequence:

```powershell
# 1. Activate the venv
cd C:\TradingScripts
.venv-vectorbt\Scripts\activate

# 2. Install tradelab in editable mode
pip install -e .\tradelab

# 3. Verify the CLI is wired up correctly
tradelab version
# Expected output: tradelab 0.1.0

tradelab list
# Expected: table showing s2_pocket_pivot with status "ported"

tradelab config --test-reports
# Expected: shows config table, then generates a smoke-test HTML report

# 4. Open the smoke-test report in Chrome
start C:\TradingScripts\tradelab\reports\smoke_test_tearsheet.html
```

**If all four commands succeed and the HTML shows a full QuantStats tearsheet** (equity curve, monthly heatmap, drawdown chart), Session 1 is verified.

---

## What could go wrong during verification

### Issue 1: `tradelab: command not found`
Most likely cause: venv not activated. Re-run `.venv-vectorbt\Scripts\activate` and confirm the green `(.venv-vectorbt)` prefix appears.

### Issue 2: `ModuleNotFoundError: No module named 'tradelab'`
Most likely cause: `pip install -e` didn't complete. Re-run step 2 and watch for "Successfully installed tradelab-0.1.0" message.

### Issue 3: `FileNotFoundError: tradelab.yaml not found`
Most likely cause: running command from wrong folder. The CLI walks up from cwd looking for tradelab.yaml. Either:
- `cd C:\TradingScripts\tradelab` before running, OR
- Set environment variable: `$env:TRADELAB_CONFIG="C:\TradingScripts\tradelab\tradelab.yaml"`

### Issue 4: QuantStats import error during `--test-reports`
Most likely cause: quantstats didn't install cleanly. Run `pip show quantstats` to confirm, then `pip install --upgrade quantstats` if needed.

### Issue 5: Smoke-test report generates but looks broken
Possible cause: matplotlib/seaborn backend issue. QuantStats uses matplotlib under the hood. Check the HTML in Chrome — if charts are missing, report back.

---

## Then we move to Session 2 (~60 min)

**Goal:** Port the real strategy + backtest logic into the tradelab package.

**Files to port (sources already in `C:\TradingScripts\`):**
- `s2_port.py` → `tradelab/strategies/s2_pocket_pivot.py` (generate_signals method body)
- `s2_backtest.py` → `tradelab/engines/backtest.py` (the backtest() function)
- `s2_optuna.py` → `tradelab/engines/optimizer.py` (Optuna study logic)
- `s2_walkforward.py` → `tradelab/engines/walkforward.py` (**WITH THE LEAKAGE BUG FIXED** — see below)

**Commands that should work after Session 2:**
- `tradelab backtest s2_pocket_pivot` → runs baseline, outputs QuantStats tearsheet
- `tradelab optimize s2_pocket_pivot --trials 50` → Optuna run + tearsheet of best params
- `tradelab wf s2_pocket_pivot` → walk-forward with WFE ratio, proper leakage-free splits

**Validation target:** reproduce today's results:
- Baseline: 713 trades, PF 0.98, WR 56.1%
- Optuna best (trial #11/50): 917 trades, PF 1.45, WR 75.2%

If Session 2 produces those numbers, the port is successful. If numbers differ significantly, we have a regression to hunt.

---

## The walk-forward leakage bug — critical fix for Session 2

**What the bug does:** In `s2_walkforward.py`, positions that haven't exited by the end of the test window are NOT force-closed at the window boundary. Instead, they're allowed to run until the end of all data (April 2026). This leaks future information into the test result.

**Evidence it's real:** Window 3 alone shows +560% OOS with top 3 trades (LITE +862%, MULL +709%, PARR +200%) all exiting on "End of Data" April 2026, despite that test window ending June 2025.

**Impact:** Aggregate WF result showed +858.9% — probably closer to +30% when fixed. Bug inflates results ~3x.

**The fix for Session 2:**
```python
# In the walk-forward loop, after running backtest on test window:
# BEFORE computing test_metrics, force-close any positions whose
# exit_date > test_window_end. Set their exit_date = test_window_end
# and exit_price = close price on that date. Recompute PnL.
```

Do NOT skip this fix. Any OOS metric produced without it is misleading.

---

## Session 3 scope (~60 min, after Session 2)

**Goal:** Implement the 5-test robustness suite in `tradelab/engines/robustness.py`.

Methodology borrowed from `marketcalls/vectorbt-backtesting-skills`:

1. **Monte Carlo trade shuffle** — randomize order of 1000 trade outcomes, measure max drawdown distribution
2. **Noise injection** — add Gaussian noise (σ=0.05%) to OHLC, re-run backtest, compare PF before/after
3. **Parameter sensitivity** — perturb each parameter ±10%, measure fitness variance
4. **Entry/exit delay** — shift signal timing by [-2, -1, 0, 1, 2] bars, measure degradation
5. **Cross-symbol validation** — optimize on random half of universe, test on other half

**Important:** Do not copy marketcalls code directly. Implement methodology using their README as specification. This avoids inheriting any bugs in their implementation and avoids licensing questions.

**Verdict logic:** Strategy is "robust" if:
- Noise injection: PF drops < 20%
- Param sensitivity: top 3 params show < 30% fitness variance
- Entry delay ±1 bar: PF stays above 1.2
- Cross-symbol: OOS PF within 40% of IS PF

---

## Key context that might get lost without this document

### About the user (Amit)
- Based in Washington DC
- Trades through Interactive Brokers (TWS port 7496)
- Data provider: Twelve Data paid plan (144 req/min, unlimited daily)
- Primary dev environment: Cursor/VS Code + PowerShell
- Team: solo for now, team joining "later" (no firm timeline)
- Removed AmiBroker from stack today — do not suggest it

### About the codebase
- Existing working modules at `C:\TradingScripts\` (s2_port.py, s2_backtest.py, s2_optuna.py, s2_walkforward.py)
- Twelve Data CSVs at `C:\TradingScripts\AmiBroker_Data\` (folder name is legacy, data is Twelve Data)
- Three CSV formats in that folder — data loader must be format-aware
- 126 symbols available including SPY (needed as benchmark)
- DeepVue MCP infrastructure at `C:\TradingScripts\deepvue_mcp\` (data_loader.py has format detection logic we can reuse)

### About the strategies
- **S2 Pocket Pivot**: validated, will be first port. Entry at signal-bar close, 25% position, max 5 concurrent, ATR trailing stop.
- **CG-TFE v1.5**: investigated today, has NO real Python source. The AFL file is scaffold only. Do not attempt to run it. Reported PF numbers (5.14, 2.84, 2.48) cannot be reproduced without the actual source code.
- **Viprasol v8.2**: mentioned in memory as "locked production version" but we haven't touched it today. May come up in future sessions.

### About VectorBT Pro (decision deferred)
- $20/month Annual Saver (personal use only)
- Purchase via Ko-fi: https://ko-fi.com/s/88d8ca176c
- Email olegpolakow@vectorbt.pro with GitHub username after payment
- Manual repo access grant, pip install via PAT
- Decision: wait until after Session 3 of tradelab, then try 1 month
- Amit's GitHub exists but unused (option to enable 2FA + generate PAT when ready)

### About today's honest findings
- Today's walk-forward showed +858% OOS — this was FALSE, caused by leakage bug
- Realistic expected result after bug fix: ~+30-300% range, much lower than the inflated number
- Edge in S2 lives in EXITS (trail_tight_mult, 65% of parameter importance), not entries
- This is useful for future strategy design: stop obsessing over entry signals, focus on exit management

---

## File inventory — what's at C:\TradingScripts\tradelab\

```
C:\TradingScripts\tradelab\
├── .gitignore                          # git-ready
├── README.md                           # package docs
├── pyproject.toml                      # pip config, registers tradelab CLI
├── tradelab.yaml                       # central config (paths, defaults, registry)
├── reports\
│   └── .gitkeep                        # placeholder, HTML outputs land here
└── src\tradelab\
    ├── __init__.py                     # version 0.1.0
    ├── cli.py                          # Typer commands (list/config implemented, rest stubbed)
    ├── config.py                       # Pydantic YAML loader
    ├── registry.py                     # dynamic strategy import from config
    ├── results.py                      # BacktestResult, OptunaResult, WalkForwardResult, RobustnessResult
    ├── engines\
    │   └── __init__.py                 # placeholder (Session 2 fills)
    ├── reporting\
    │   ├── __init__.py
    │   └── tearsheet.py                # QuantStats integration + smoke-test generator
    └── strategies\
        ├── __init__.py                 # exports Strategy base class
        ├── base.py                     # Strategy ABC
        └── s2_pocket_pivot.py          # stub (Session 2 ports real logic)
```

---

## If tomorrow's Claude has zero memory of today

Read these in order to reconstruct context:

1. This file (`HANDOVER.md`) — you're reading it
2. `README.md` in the tradelab folder — product overview
3. `tradelab.yaml` — config and strategy registry
4. `src/tradelab/cli.py` — understand the CLI shape
5. `src/tradelab/results.py` — understand the data shapes

Then proceed to the "Tomorrow's first 15 minutes" section above.

If verification succeeds, ask Amit if he wants to proceed to Session 2 (port S2 strategy) or take a different direction.

---

## Sign-off

Session 1 build quality: **solid foundation, not yet verified end-to-end.**
Blocking issues: **none known.**
Risks for tomorrow: **low** — just a pip install and 3 CLI invocations.

End of handover packet.
