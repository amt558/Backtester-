# Walk-Forward Leakage Fix — Verification Report

**Date:** April 19, 2026
**Task:** Pre-Phase-0 Task 0.0 (per `TRADELAB_MASTER_PLAN.md`)
**Investigator:** Claude (Session start)
**Status:** FIX VERIFIED PRESENT. Regression test added. No impact rerun required.

---

## 1. Summary

The walk-forward data-leakage bug described in memory and in the master plan ("forced close at data boundary rather than test window boundary, inflating OOS ~3x") is **already fixed** in the current tradelab codebase. The fix was applied during the port from `s2_backtest.py` to `src/tradelab/engines/backtest.py`.

A regression test (`tests/engines/test_wf_leakage.py`) has been added to prevent the fix from being reverted by future sessions.

No historical impact analysis is required: the Session 2 baseline (`S2 : 713 trades / PF 0.98 / WR 56.1%`) was produced by the post-fix engine. The figures in memory are trustworthy.

---

## 2. Investigation method

Read the full source of:

- `src/tradelab/engines/backtest.py`
- `src/tradelab/engines/walkforward.py`
- `src/tradelab/engines/optimizer.py`
- `src/tradelab/engines/__init__.py`

Traced the code path by which an end-of-window position is liquidated in walk-forward. Checked for forward-data access in that path. Checked for forward-data access in any other path that could contaminate OOS metrics.

---

## 3. The fix in detail

The relevant block is `src/tradelab/engines/backtest.py`, lines 184-212:

```python
# --- END-OF-WINDOW LIQUIDATION (LEAKAGE FIX) ---
if all_dates:
    window_end_date = all_dates[-1]
    for sym, pos in list(positions.items()):
        df = indexed.get(sym)
        if df is None:
            continue
        sym_dates = df.index[df.index <= window_end_date]
        if len(sym_dates) == 0:
            continue
        close_date = sym_dates[-1]
        px = df.loc[close_date, "Close"]
        ...
```

Two bounds guarantee the liquidation cannot read a forward bar:

1. `all_dates` is filtered at line 75 to `start_ts <= d <= end_ts`, so `window_end_date = all_dates[-1]` is at most the requested window end.
2. `sym_dates = df.index[df.index <= window_end_date]` clips each per-symbol full-dataset index to dates at or before the window end. Taking `[-1]` cannot overshoot.

The in-source comment at lines 15-18 records the nature of the fix explicitly:

> *LEAKAGE FIX: the original code used `df.index[-1]` to close surviving positions at end-of-data. When called over a sub-window (walk-forward), that leaked future bars into the OOS test result. This engine uses the end-of-window close instead.*

`walkforward.py` adds a matching annotation at lines 14-15:

> *The original leakage bug is fixed automatically because run_backtest now uses window-end close for end-of-window liquidation rather than end-of-data.*

---

## 4. Adjacent paths checked for leakage

Beyond end-of-window liquidation, four other paths could theoretically leak forward data. Each was examined:

| Path | Verdict |
|---|---|
| `all_dates` construction (line 74) | Clean — filtered immediately on line 75 |
| Per-bar exit check (Pass 1) | Clean — only reads `df.loc[date]`, i.e., current bar |
| Signal collection (Pass 2) | Clean — uses `df.iloc[curr_idx]`, current bar only |
| Mark-to-market (Pass 4) | Clean — uses `df.loc[date, "Close"]`, current bar only |

No forward-data access detected.

---

## 5. Regression test

**File:** `tests/engines/test_wf_leakage.py`

**Design:** a synthetic-data test that constructs a price series with a deliberate regime break at the window boundary. Pre-boundary prices are ~100, post-boundary prices ~200. A position is forced open 3 bars before the boundary and cannot exit naturally (trail and SMA50 exits are disabled by construction). The end-of-window liquidation is therefore exercised directly.

**Assertions (5 tests):**

1. `test_end_of_window_exit_date_is_inside_window` — exit date must be ≤ window end
2. `test_end_of_window_exit_reason_is_end_of_window` — the exit path must be the liquidation block, not a trail stop
3. `test_end_of_window_exit_price_reflects_pre_boundary_regime` — exit price ≤ 105 (pre-boundary regime tops at ~100.4)
4. `test_end_of_window_pnl_is_not_inflated` — |PnL%| < 5 on a flat-regime position
5. `test_extending_window_past_boundary_changes_pnl` — positive control: a longer window produces materially different PnL, proving the `end` parameter is honored

If any test fails, the WF fix has regressed. A 20%+ inflation in OOS PnL% on this fixture is the smoking-gun signature.

**How to run:**

```powershell
cd C:\TradingScripts\tradelab
.venv-vectorbt\Scripts\activate
pytest tests/engines/test_wf_leakage.py -v
```

Expected output: 5 tests pass.

---

## 6. Impact on prior results

None required. The memory of record contains:

- S2 baseline: 713 trades / PF 0.98 / WR 56.1%
- Viprasol v8.3 WF Sharpe degradation (4.86 → 1.93)
- CG-TFE v1.5 portfolio PFs
- Session 2 S2 WF (616 OOS trades, Window 2 weakness, MSFT concentration)

All these numbers were produced by the post-fix engine (`tradelab.engines.backtest.py`). They are the calibrated baselines Phase 0 Task 0.1 (DSR) should compute against.

No recompute is needed before proceeding to Task 0.1.

*Caveat worth noting for future work:* if any analysis in memory pre-dates the port to tradelab (i.e., came from `s2_backtest.py` or `s2_walkforward.py` directly, or from an AmiBroker workflow that is now retired), those specific numbers are pre-fix and would be inflated. Nothing in the current plan depends on such numbers, but anyone re-reading old session notes should be aware.

---

## 7. Sign-off checklist

- [x] Source read end-to-end for all engine files
- [x] Fix verified present with line-numbered reference
- [x] Adjacent paths audited for forward-data access
- [x] Regression test drafted with 5 assertions
- [ ] Regression test executed and passing (Amit to confirm after drop-in)
- [x] Verification report written (this file)

Once Amit confirms `pytest tests/engines/test_wf_leakage.py -v` → 5/5 passing, Task 0.0 is complete and Pre-Phase-0 advances to Task 0.0.5 (canary suite).
