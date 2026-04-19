# Canary Suite — Reference Document

Four deliberately-broken strategies that tradelab must correctly flag as fragile.

## The four canaries

| Canary | Failure mode | Expected verdict |
|---|---|---|
| RandCanary | Absence of edge | FRAGILE |
| OverfitCanary | Parameter overfitting | FRAGILE (after Optuna) |
| LeakCanary | Look-ahead bias | FRAGILE (entry-delay collapse) |
| SurvivorCanary | Survivorship bias | MARGINAL / FRAGILE (LOSO spread) |

## Files

- `src/tradelab/canaries/*.py`
- `scripts/run_canaries.py`
- `tests/canaries/test_canary_properties.py`

## Monthly usage

```python
from tradelab.marketdata import download_symbols
from scripts.run_canaries import run_canary_health_check

symbols = ["CSCO", "NVDA", "AVGO", "MU", "MSFT", "META", "AMZN", "AMD", "LLY"]
data = download_symbols(symbols)
spy = download_symbols(["SPY"])["SPY"]["Close"]

report = run_canary_health_check(data, spy_close=spy)
print(report.summary())
if not report.all_ok:
    raise SystemExit("Canary anomaly — halt strategy evaluation.")
```

## Anti-drift rules

1. Never "fix" a canary to improve its numbers — broken on purpose
2. Never register canaries in production strategy registry
3. Never tune tunable_params (OverfitCanary's Optuna run is the exception)
4. Tighten expected bands only after multiple stable observations
