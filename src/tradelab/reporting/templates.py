"""String templates for executive report sections."""

HEADER = """# {strategy_name} — Strategy Review

**Run timestamp:** {timestamp}
**Data window:** {start} → {end}
**Universe:** {universe}
**Report type:** Executive review (observations only)

---
"""

VERDICT = """## Executive verdict

{verdict_line}

---
"""

EDGE_METRICS = """## 1. Edge metrics

| Metric | Value |
|---|---|
| Profit factor | {pf} |
| Sharpe ratio | {sharpe} |
| Deflated Sharpe (DSR) | {dsr} |
| Total return | {total_return}% |
| Annualized return | {annual_return}% |
| Walk-forward efficiency | {wfe} |
| OOS / IS ratio | {oos_is_ratio} |

---
"""

PERFORMANCE_SNAPSHOT = """## 2. Performance snapshot

- Total trades: **{total_trades}**
- Win rate: **{win_rate}%** ({wins} W / {losses} L)
- Average win: **{avg_win_pct}%** · Average loss: **{avg_loss_pct}%**
- Expectancy: **{expectancy}%** per trade
- Max drawdown: **{max_dd}%**
- Average bars held: **{avg_bars_held}**

---
"""

WF_TABLE_HEADER = """## 3. Per-window walk-forward

| Window | Train | Test | IS PF | OOS PF | IS Trades | OOS Trades | OOS WR | OOS DD |
|---|---|---|---|---|---|---|---|---|
"""

WF_TABLE_ROW = "| {i} | {train} | {test} | {is_pf} | {oos_pf} | {is_trades} | {oos_trades} | {oos_wr}% | {oos_dd}% |\n"

WF_TABLE_NONE = "## 3. Per-window walk-forward\n\n*Not run for this strategy (pass --walkforward to enable).*\n\n---\n"

PARAM_IMPORTANCE_HEADER = """## 4. Parameter importance (Optuna)

| Rank | Parameter | Importance |
|---|---|---|
"""

PARAM_IMPORTANCE_ROW = "| {rank} | `{name}` | {importance:.3f} |\n"

PARAM_IMPORTANCE_NONE = "## 4. Parameter importance (Optuna)\n\n*No optimization run (pass --optimize to enable).*\n\n---\n"

ROBUSTNESS_STUB = """## 5. Robustness suite

*Pending Phase 1: MC (3-method × 4-metric), param landscape, entry delay, LOSO.*

Robustness verifies what Optuna cannot: whether the optimized edge survives perturbation.
Optuna finds the best parameter set; robustness tells you whether that best set is real.

---
"""

WHERE_IT_BREAKS_HEADER = """## 6. Where it breaks

"""

OBSERVATIONS_HEADER = """## 7. Observations

"""

FOOTER_HEADER = """---

"""
