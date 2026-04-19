# Authoring strategies for tradelab

Three paths to add a strategy. Pick the one that matches what you have.

| Starting point | Path | Time |
|---|---|---|
| Python pseudocode / written description | **A: SimpleStrategy** | 30–60 min |
| Pine Script (TradingView) | **B: Pine → SimpleStrategy translation** (manual) | 30–60 min |
| Existing Python file with `entry_fn` / `exit_fn` | **C: SimpleStrategy port** (worked example below) | 30 min |

For all three, the recipe is the same: scaffold → fill in entry logic → run.

---

## Recipe (90 seconds)

```bash
# From repo root:
tradelab init-strategy my_breakout --type=simple --description "Channel breakout with vol confirm"
# Edits src/tradelab/strategies/my_breakout.py and registers it in tradelab.yaml.

# Open the generated file, fill in entry_signal(). Save.

tradelab run my_breakout --universe smoke_5 --start 2022-01-01 --robustness
# Verdict + report + dashboard land in reports/my_breakout_<timestamp>/
```

---

## The contract

A `SimpleStrategy` subclass needs three things:

1. **Class attributes**: `name` (string, snake_case), `default_params` (dict),
   optionally `tunable_params` (dict of `{name: (low, high)}` for Optuna),
   `requires_benchmark` (bool — True if your logic uses `RS_21d`).

2. **`entry_signal(row, prev, params, prev2=None) -> bool`**:
   Return True iff this bar is a long entry. Use indicator columns on `row`
   freely. `prev` is yesterday's bar; `prev2` is two bars ago.

3. **`entry_score(row, prev, params, prev2=None) -> float`** (optional):
   Higher score = preferred when more signals fire than position slots.
   Default 1.0 (FIFO).

`default_params` MUST include the engine's exit knobs:
`stop_atr_mult`, `trail_tight_mult`, `trail_wide_mult`, `trail_tighten_atr`.
Put them in once; the engine's trailing-stop logic uses them automatically.

### Indicators available on `row`

The downloader → `enrich_universe` pipeline computes everything below before
your strategy ever sees the data:

| Group | Columns |
|---|---|
| OHLCV | `Open`, `High`, `Low`, `Close`, `Volume` |
| Volatility | `ATR`, `ATR_pct` |
| Momentum | `RSI` |
| Trend MAs | `EMA10`, `EMA21`, `SMA10`, `SMA21`, `SMA50`, `SMA200` |
| Volume | `Vol_MA20`, `Vol_Ratio`, `Vol_OK` |
| Trend gates | `Trend_OK`, `Above50`, `Above200` |
| Patterns | `Pocket_Pivot` |
| Relative strength | `RS_21d` (vs SPY benchmark, 21-bar) |

If you need a column that's not here, compute it inside `entry_signal()`
from `row` / `prev` / `prev2`, or compute it once in `generate_signals()`
override (advanced template).

---

## Path A — Python pseudocode / English description → SimpleStrategy

Example you might describe:

> "Enter long when RSI is below 30, today's close is higher than yesterday's,
> trend is up (SMA10 > SMA21 > SMA50), and volume is at least 1.5x average."

```python
from .simple import SimpleStrategy

class MyOversoldBreakout(SimpleStrategy):
    name = "oversold_breakout"
    requires_benchmark = False
    default_params = {
        "rsi_max": 30.0,
        "vol_mult": 1.5,
        "stop_atr_mult": 1.5, "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,
    }
    tunable_params = {"rsi_max": (15.0, 50.0), "vol_mult": (1.0, 3.0)}

    def entry_signal(self, row, prev, params, prev2=None):
        if prev is None:
            return False
        return (
            row["RSI"] < params["rsi_max"]
            and row["Close"] > prev["Close"]
            and row["Trend_OK"]
            and row["Vol_Ratio"] > params["vol_mult"]
        )
```

That's it. Save, run, get a verdict.

---

## Path B — Pine Script → SimpleStrategy translation

There's no auto-translator (Pine has its own runtime semantics around
`security()`, `bgcolor()`, `strategy.entry()`, etc.). But the entry logic
maps cleanly. Translation table:

| Pine | tradelab equivalent |
|---|---|
| `ta.rsi(close, 14)` | `row["RSI"]`  *(already 14-period)* |
| `ta.sma(close, 50)` | `row["SMA50"]` |
| `ta.ema(close, 21)` | `row["EMA21"]` |
| `ta.atr(14)` | `row["ATR"]` |
| `volume > ta.sma(volume, 20) * 1.5` | `row["Vol_Ratio"] > 1.5` |
| `close > close[1]` | `row["Close"] > prev["Close"]` |
| `low[1] < low[2] and high[1] < high[2]` | `prev["Low"] > prev2["Low"] and prev["High"] < prev2["High"]` (inside day) |
| `strategy.entry("Long", strategy.long, when=cond)` | `def entry_signal(...) → return cond` |
| `strategy.exit("X", stop=...)` | use engine default trail or set `stop_atr_mult` |
| `input.float(1.5, "RSI Mult")` | `default_params["rsi_mult"] = 1.5` |

Send me your Pine `strategy.entry()` and `strategy.exit()` blocks and I'll
do the translation.

---

## Path C — Existing Python `entry_fn` / `exit_fn` → SimpleStrategy port

This is the pattern in `/c/TradingScripts/FINAL STRATEGYIE/`. The translation
is:

```python
# Original:
def entry_fn(r, prev, prev2, sym, df, idx):
    if r['ATR_pct'] > 8: return None
    if not r['Trend_OK']: return None
    if prev.get('Inside_Day') and r['Close'] > prev['High'] and r['Vol_Ratio'] > 1.2:
        return {'sym': sym, 'price': r['Close'], 'stop': prev['Low'] - 0.5*r['ATR'],
                'score': r['RS_21d'] + r['Vol_Ratio']}
    return None
```

```python
# Ported:
class S4InsideDayBreakout(SimpleStrategy):
    name = "s4_inside_day_breakout"
    default_params = {"stop_atr_mult": 1.5, ...}

    def entry_signal(self, row, prev, params, prev2=None):
        if prev is None or prev2 is None: return False
        if row["ATR_pct"] > 8: return False
        if not row["Trend_OK"]: return False
        prev_inside = prev["High"] < prev2["High"] and prev["Low"] > prev2["Low"]
        if not prev_inside: return False
        if row["Close"] <= prev["High"]: return False
        if row["Vol_Ratio"] <= 1.2: return False
        return True

    def entry_score(self, row, prev, params, prev2=None):
        return float(row["RS_21d"] + row["Vol_Ratio"])
```

See `src/tradelab/strategies/s4_inside_day_breakout.py` for the full ported
example.

---

## Advanced — when SimpleStrategy isn't enough

Use `tradelab init-strategy my_strat --type=advanced` if you need:
- Vectorised signal computation (faster than per-bar Python loop)
- Custom indicators that need a full DataFrame pass
- Per-symbol indicator pre-computation

The advanced template gives you the full `Strategy.generate_signals(data, spy_close)`
contract. You build the `buy_signal` / `entry_stop` / `entry_score` columns
directly. See `src/tradelab/strategies/s2_pocket_pivot.py` for the reference.

---

## Once your strategy is registered

```bash
tradelab list                                           # confirm it's there
tradelab doctor                                          # confirm import works

tradelab run my_strat --universe smoke_5 --start 2022-01-01
tradelab run my_strat --universe magnificent_7 --start 2020-01-01 --robustness
tradelab run my_strat --universe semis --start 2020-01-01 --full   # the works

tradelab history list --strategy my_strat                # all your runs
tradelab history diff <run_a_short_id> <run_b_short_id>  # compare two
```

If your strategy is fragile, tradelab will say so. If it's robust, tradelab
will tell you which signals back that up. False negatives cost more than
false positives — the tool errs toward FRAGILE.
