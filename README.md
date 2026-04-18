# tradelab

Local quant research platform for systematic trading strategies.

## What it does

- **Backtest** any registered strategy on your Twelve Data universe
- **Optimize** parameters via Optuna with configurable fitness
- **Walk-forward** validate with leakage-free splits
- **Robustness test** via Monte Carlo shuffle, noise injection, parameter sensitivity, entry/exit delay, and cross-symbol holdout
- **Report** everything as QuantStats HTML tearsheets saved to disk

## Stack

- Python 3.12+
- VectorBT (free edition) as the backtest engine
- Optuna for parameter search
- QuantStats for tearsheets
- Typer for CLI

## Quick start

```powershell
cd C:\TradingScripts
.venv-vectorbt\Scripts\activate
pip install -e ./tradelab
tradelab --help
tradelab list
tradelab backtest s2_pocket_pivot
```

Reports are written to `C:\TradingScripts\tradelab\reports\`.

## Commands

| Command | What it does |
|---|---|
| `tradelab list` | List registered strategies |
| `tradelab config` | Show active configuration |
| `tradelab backtest <strategy>` | Run single backtest + HTML tearsheet |
| `tradelab optimize <strategy>` | Optuna parameter search + tearsheet |
| `tradelab wf <strategy>` | Walk-forward validation + tearsheet |
| `tradelab robustness <strategy>` | 5-test robustness suite + tearsheet |
| `tradelab full-test <strategy>` | Everything in one pass |
| `tradelab compare <s1> <s2>` | Side-by-side comparison |

## Project layout

```
tradelab/
├── pyproject.toml
├── README.md
├── tradelab.yaml              # config: data paths, strategy registry, defaults
├── src/tradelab/
│   ├── cli.py                 # typer commands
│   ├── config.py              # yaml loader
│   ├── results.py             # BacktestResult, OptunaResult, etc.
│   ├── registry.py            # strategy registration
│   ├── data.py                # Twelve Data CSV loader (3 format-aware)
│   ├── engines/
│   │   ├── backtest.py        # core backtest engine
│   │   ├── optimizer.py       # Optuna integration
│   │   ├── walkforward.py     # proper walk-forward (leakage-free)
│   │   └── robustness.py      # 5 robustness tests
│   ├── strategies/
│   │   ├── base.py            # Strategy base class
│   │   └── s2_pocket_pivot.py # first registered strategy
│   └── reporting/
│       ├── tearsheet.py       # QuantStats HTML generation
│       └── templates/         # optional custom templates
└── reports/                   # generated HTML files land here
```

## Status

This is Session 1 of the build. Only the foundation is in place. The strategy engines are ported in Session 2, robustness suite in Session 3.
