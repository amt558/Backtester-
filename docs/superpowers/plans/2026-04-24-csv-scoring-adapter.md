# CSV Scoring Adapter (Option H, Session 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tradelab score-from-trades` CLI command that ingests a TradingView Strategy Tester "List of trades" CSV, runs DSR + Monte Carlo + verdict aggregation, and produces a report folder identical in shape to what `tradelab run` writes today.

**Architecture:** Pure-function CSV parser → orchestrator that builds a synthetic `BacktestResult` from trade rows → reuses the existing verdict engine, executive-report renderer, dashboard builder, and audit DB writer. No new strategy plug-ins, no marketdata calls — the CSV is the source of truth.

**Tech Stack:** Python 3.13, pandas, pydantic v2, typer, pytest. All new code under `src/tradelab/`. All tests under `tests/`.

**Pre-flight:**
- Tree is clean as of `8a9a342`. Recommended: create a feature branch (`git switch -c feat/csv-scoring`) before Task 1 so the work is reviewable separately from Session 1's `feat/live` material.
- Set `PYTHONPATH=src` and `PYTHONIOENCODING=utf-8` in your shell for every test run (Windows console + tradelab convention).

---

## File structure

| Path | Responsibility |
|---|---|
| Create: `src/tradelab/io/__init__.py` | Marker for new I/O subpackage |
| Create: `src/tradelab/io/tv_csv.py` | Pure parser: TradingView CSV bytes → `list[Trade]` + window dates |
| Create: `src/tradelab/io/__init__.py` exports | re-export `parse_tv_trades_csv` |
| Modify: `src/tradelab/engines/_diagnostics.py` | Add `metrics_from_trades(trades, starting_equity)` helper |
| Create: `src/tradelab/csv_scoring.py` | Orchestrator: trades → `BacktestResult` → DSR + MC + verdict → report dir + audit row |
| Create: `src/tradelab/cli_score.py` | Typer command function for `score-from-trades` |
| Modify: `src/tradelab/cli.py` (after line 456) | Register the new command alongside the existing `from .cli_X import …` block |
| Create: `tests/io/__init__.py` | (empty) |
| Create: `tests/io/test_tv_csv.py` | Parser unit tests + edge cases |
| Create: `tests/io/fixtures/tv_export_amzn_smoke.csv` | 6-trade canonical TV CSV (long-only) |
| Create: `tests/engines/test_metrics_from_trades.py` | Trade-list → metrics helper tests |
| Create: `tests/test_csv_scoring.py` | Orchestrator unit tests (uses real verdict engine) |
| Create: `tests/cli/test_cli_score.py` | End-to-end Typer CliRunner test that produces a real report folder under `tmp_path` |

Why these splits:
- `io/tv_csv.py` is pure parsing — no I/O, no engine knowledge — so it stays trivially testable.
- `engines/_diagnostics.py` already houses post-backtest helpers (`compute_regime_breakdown`, `compute_monthly_pnl`); `metrics_from_trades` belongs there.
- `csv_scoring.py` is the only module that reaches into verdict + reporting + audit. Keep the orchestration in one file so future degradation modes (e.g., multi-CSV LOSO in Session 3) are easy to add in one place.

---

## Reference: TradingView "List of trades" CSV

User exports via TV Strategy Tester → "List of trades" tab → "Export" button. The file is plain UTF-8 CSV with one header row. Column names current as of TV 2026 (verify against the user's actual export — case and exact spacing matter):

```
Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,Drawdown USD,Drawdown %
```

Pairing rule: each completed trade has **two rows** sharing one `Trade #` — an entry row (`Type` ∈ {"Entry long","Entry short"}) and an exit row (`Type` ∈ {"Exit long","Exit short"}). Exit row carries `Profit USD`, `Profit %`, run-up, drawdown. Open trades have only an entry row → drop them.

Date format from TV: `2024-03-04 14:30` (no seconds, no timezone). Treat as naive timestamps — TV exports in chart timezone.

---

### Task 1: TV CSV parser (pure function)

**Files:**
- Create: `src/tradelab/io/__init__.py`
- Create: `src/tradelab/io/tv_csv.py`
- Create: `tests/io/__init__.py`
- Create: `tests/io/test_tv_csv.py`
- Create: `tests/io/fixtures/tv_export_amzn_smoke.csv`

- [ ] **Step 1: Create the test fixture**

Write `tests/io/fixtures/tv_export_amzn_smoke.csv` with this exact content (6 closed trades, one open trade we expect to be dropped):

```csv
Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,Drawdown USD,Drawdown %
1,Entry long,Long,2024-01-08 09:30,150.00,10,,,,,,,,
1,Exit long,Exit,2024-01-12 09:30,156.00,10,60.00,4.00,60.00,0.06,80.00,5.33,-20.00,-1.33
2,Entry long,Long,2024-01-22 09:30,158.00,10,,,,,,,,
2,Exit long,Exit,2024-01-24 09:30,154.00,10,-40.00,-2.53,20.00,0.02,10.00,0.63,-50.00,-3.16
3,Entry long,Long,2024-02-05 09:30,160.00,10,,,,,,,,
3,Exit long,Exit,2024-02-09 09:30,170.00,10,100.00,6.25,120.00,0.12,120.00,7.50,-15.00,-0.94
4,Entry long,Long,2024-02-20 09:30,172.00,10,,,,,,,,
4,Exit long,Exit,2024-02-22 09:30,168.00,10,-40.00,-2.33,80.00,0.08,5.00,0.29,-60.00,-3.49
5,Entry long,Long,2024-03-04 09:30,175.00,10,,,,,,,,
5,Exit long,Exit,2024-03-08 09:30,182.00,10,70.00,4.00,150.00,0.15,90.00,5.14,-10.00,-0.57
6,Entry long,Long,2024-03-18 09:30,180.00,10,,,,,,,,
6,Exit long,Exit,2024-03-22 09:30,189.00,10,90.00,5.00,240.00,0.24,110.00,6.11,-5.00,-0.28
7,Entry long,Long,2024-04-01 09:30,190.00,10,,,,,,,,
```

Trade 7 is intentionally open (no exit row).

- [ ] **Step 2: Write the parser test**

Create `tests/io/test_tv_csv.py`:

```python
"""TradingView 'List of trades' CSV parser tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.io.tv_csv import (
    ParsedTradesCSV,
    TVCSVParseError,
    parse_tv_trades_csv,
)


FIXTURE = Path(__file__).parent / "fixtures" / "tv_export_amzn_smoke.csv"


def test_parses_six_closed_trades_and_drops_open_trade():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    assert isinstance(parsed, ParsedTradesCSV)
    assert len(parsed.trades) == 6  # trade #7 is open and must be dropped


def test_window_dates_span_first_entry_to_last_exit():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    assert parsed.start_date == "2024-01-08"
    assert parsed.end_date == "2024-03-22"


def test_first_trade_round_trip_preserves_prices_pnl_and_pct():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    t = parsed.trades[0]
    assert t.ticker == "AMZN"
    assert t.entry_date == "2024-01-08"
    assert t.exit_date == "2024-01-12"
    assert t.entry_price == 150.00
    assert t.exit_price == 156.00
    assert t.shares == 10
    assert t.pnl == 60.00
    assert t.pnl_pct == 4.00
    assert t.exit_reason == "Exit"          # from Signal column on exit row
    assert t.mfe_pct == 5.33
    assert t.mae_pct == -1.33
    assert t.bars_held == 4                 # calendar days between entry/exit


def test_short_trade_pnl_uses_csv_value_not_recomputed():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry short,Short,2024-05-01 09:30,100.00,5,,,,,,,,\n"
        "1,Exit short,Cover,2024-05-03 09:30,95.00,5,25.00,5.00,25.00,0.03,30.00,6.00,-2.00,-0.40\n"
    )
    parsed = parse_tv_trades_csv(csv, symbol="MU")
    t = parsed.trades[0]
    # Short profit: entry 100 → exit 95 → +5 per share × 5 shares = 25 (matches CSV).
    assert t.pnl == 25.00
    assert t.exit_reason == "Cover"


def test_missing_required_column_raises():
    bad = "Foo,Bar\n1,2\n"
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(bad, symbol="AMZN")
    assert "missing column" in str(exc.value).lower()


def test_empty_csv_raises():
    with pytest.raises(TVCSVParseError):
        parse_tv_trades_csv("", symbol="AMZN")


def test_no_closed_trades_raises():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-01-01 09:30,100,10,,,,,,,,\n"
    )
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(csv, symbol="AMZN")
    assert "no closed trades" in str(exc.value).lower()
```

- [ ] **Step 3: Run the test to confirm it fails**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/io/test_tv_csv.py -v
```

Expected: ImportError / collection error — `tradelab.io.tv_csv` does not yet exist.

- [ ] **Step 4: Implement the parser**

Create `src/tradelab/io/__init__.py`:

```python
"""I/O adapters: parse external file formats into tradelab's domain types."""
from .tv_csv import ParsedTradesCSV, TVCSVParseError, parse_tv_trades_csv

__all__ = ["ParsedTradesCSV", "TVCSVParseError", "parse_tv_trades_csv"]
```

Create `src/tradelab/io/tv_csv.py`:

```python
"""TradingView Strategy Tester 'List of trades' CSV parser.

Pure: reads CSV text, returns domain objects, no I/O. The orchestrator
(csv_scoring.py) is responsible for reading bytes off disk and feeding them
in. Keep this module free of pandas / numpy so it stays cheap to test.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from ..results import Trade


REQUIRED_COLUMNS = {
    "Trade #", "Type", "Signal", "Date/Time", "Price USD", "Contracts",
    "Profit USD", "Profit %", "Run-up %", "Drawdown %",
}


class TVCSVParseError(ValueError):
    """Raised when the CSV is unreadable, malformed, or contains no closed trades."""


@dataclass(frozen=True)
class ParsedTradesCSV:
    trades: list[Trade]
    start_date: str  # ISO YYYY-MM-DD of earliest entry
    end_date: str    # ISO YYYY-MM-DD of latest exit


def _date_only(stamp: str) -> str:
    """Convert TV's 'YYYY-MM-DD HH:MM' to 'YYYY-MM-DD'."""
    try:
        return datetime.strptime(stamp.strip(), "%Y-%m-%d %H:%M").strftime("%Y-%m-%d")
    except ValueError:
        # Some TV exports drop the time when the bar is daily.
        return datetime.strptime(stamp.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")


def _bars_between(entry: str, exit_: str) -> int:
    a = datetime.strptime(entry, "%Y-%m-%d")
    b = datetime.strptime(exit_, "%Y-%m-%d")
    return max(int((b - a).days), 0)


def _f(row: dict, key: str, default: float = 0.0) -> float:
    v = (row.get(key) or "").strip()
    if not v:
        return default
    return float(v)


def parse_tv_trades_csv(csv_text: str, *, symbol: str) -> ParsedTradesCSV:
    if not csv_text or not csv_text.strip():
        raise TVCSVParseError("CSV is empty")

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise TVCSVParseError("CSV has no header row")

    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise TVCSVParseError(f"missing column(s): {sorted(missing)}")

    rows_by_trade: dict[str, list[dict]] = {}
    for row in reader:
        tnum = (row.get("Trade #") or "").strip()
        if not tnum:
            continue
        rows_by_trade.setdefault(tnum, []).append(row)

    trades: list[Trade] = []
    for tnum in sorted(rows_by_trade.keys(), key=lambda s: int(s)):
        rows = rows_by_trade[tnum]
        entry = next((r for r in rows if r["Type"].startswith("Entry")), None)
        exit_ = next((r for r in rows if r["Type"].startswith("Exit")), None)
        if entry is None or exit_ is None:
            # Open trade — drop silently.
            continue

        entry_date = _date_only(entry["Date/Time"])
        exit_date = _date_only(exit_["Date/Time"])
        trades.append(Trade(
            ticker=symbol,
            entry_date=entry_date,
            exit_date=exit_date,
            entry_price=_f(entry, "Price USD"),
            exit_price=_f(exit_, "Price USD"),
            shares=int(_f(entry, "Contracts")),
            pnl=_f(exit_, "Profit USD"),
            pnl_pct=_f(exit_, "Profit %"),
            bars_held=_bars_between(entry_date, exit_date),
            exit_reason=(exit_.get("Signal") or "tv_csv").strip() or "tv_csv",
            mae_pct=_f(exit_, "Drawdown %"),
            mfe_pct=_f(exit_, "Run-up %"),
        ))

    if not trades:
        raise TVCSVParseError("no closed trades found in CSV")

    return ParsedTradesCSV(
        trades=trades,
        start_date=min(t.entry_date for t in trades),
        end_date=max(t.exit_date for t in trades),
    )
```

- [ ] **Step 5: Run tests until green**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/io/test_tv_csv.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tradelab/io/ tests/io/
git commit -m "feat(io): TradingView CSV parser for Strategy Tester exports"
```

---

### Task 2: Trade-list → BacktestMetrics helper

**Files:**
- Modify: `src/tradelab/engines/_diagnostics.py` (append a new function at the bottom)
- Create: `tests/engines/test_metrics_from_trades.py`

- [ ] **Step 1: Write the failing test**

Create `tests/engines/test_metrics_from_trades.py`:

```python
"""metrics_from_trades — derive BacktestMetrics from an arbitrary trade list."""
from __future__ import annotations

from tradelab.engines._diagnostics import metrics_from_trades
from tradelab.results import Trade


def _t(pnl: float, pnl_pct: float, bars: int = 3,
       entry: str = "2024-01-01", exit_: str = "2024-01-04") -> Trade:
    # Round-trip-friendly synthetic trade.
    return Trade(
        ticker="X", entry_date=entry, exit_date=exit_,
        entry_price=100.0, exit_price=100.0 + pnl_pct, shares=1,
        pnl=pnl, pnl_pct=pnl_pct, bars_held=bars, exit_reason="t",
    )


def test_empty_trades_returns_zero_metrics():
    m = metrics_from_trades([], starting_equity=100_000.0)
    assert m.total_trades == 0
    assert m.profit_factor == 0.0
    assert m.win_rate == 0.0
    assert m.final_equity == 100_000.0


def test_basic_metrics_three_wins_two_losses():
    trades = [
        _t(100.0, 1.0), _t(-50.0, -0.5), _t(200.0, 2.0),
        _t(-100.0, -1.0), _t(150.0, 1.5),
    ]
    m = metrics_from_trades(trades, starting_equity=10_000.0)
    assert m.total_trades == 5
    assert m.wins == 3
    assert m.losses == 2
    assert m.win_rate == 60.0
    assert m.gross_profit == 450.0
    assert m.gross_loss == 150.0
    assert m.profit_factor == 3.0
    assert m.net_pnl == 300.0
    assert m.final_equity == 10_300.0
    assert round(m.pct_return, 4) == 3.0


def test_max_drawdown_is_negative_percent_of_peak():
    # Two wins lift equity to 10_300, then a loss takes it to 10_000 (~-2.91%).
    trades = [_t(200.0, 2.0), _t(100.0, 1.0), _t(-300.0, -3.0)]
    m = metrics_from_trades(trades, starting_equity=10_000.0)
    assert m.max_drawdown_pct < 0
    assert round(m.max_drawdown_pct, 2) == round(-300.0 / 10_300.0 * 100, 2)


def test_avg_bars_held_is_mean_of_bar_counts():
    trades = [_t(10, 0.1, bars=2), _t(10, 0.1, bars=4), _t(10, 0.1, bars=6)]
    m = metrics_from_trades(trades, starting_equity=100_000.0)
    assert m.avg_bars_held == 4.0
```

- [ ] **Step 2: Run to confirm it fails**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/engines/test_metrics_from_trades.py -v
```

Expected: ImportError — `metrics_from_trades` does not exist.

- [ ] **Step 3: Implement the helper**

Append to `src/tradelab/engines/_diagnostics.py`:

```python
def metrics_from_trades(trades: list, starting_equity: float = 100_000.0):
    """Derive BacktestMetrics from a list of Trade objects.

    Used by csv_scoring.py to score externally-computed trade lists (e.g.,
    TradingView Pine Strategy Tester exports). Equity is built by sequencing
    trade pnls in their list order; max_drawdown is computed against running
    peak equity. Sharpe is intentionally left at 0.0 here — daily-bar Sharpe
    requires the bar-level equity curve, which the orchestrator constructs
    separately and writes to BacktestResult.equity_curve. Downstream DSR
    consumes that curve, not this helper.
    """
    from ..results import BacktestMetrics

    if not trades:
        return BacktestMetrics(final_equity=starting_equity)

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gp = float(sum(t.pnl for t in wins))
    gl = float(abs(sum(t.pnl for t in losses)))
    if gl > 0:
        pf = gp / gl
    elif gp > 0:
        pf = 10.0  # cap matches engines/backtest.py convention
    else:
        pf = 0.0

    net = float(sum(t.pnl for t in trades))
    final_equity = starting_equity + net

    # Peak-to-trough drawdown on running equity.
    eq = starting_equity
    peak = starting_equity
    max_dd_pct = 0.0
    for t in trades:
        eq += t.pnl
        if eq > peak:
            peak = eq
        if peak > 0:
            dd_pct = (eq - peak) / peak * 100.0
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct

    avg_win_pct = float(sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0.0
    avg_loss_pct = float(sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0.0
    avg_bars = float(sum(t.bars_held for t in trades) / len(trades))

    return BacktestMetrics(
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(trades) * 100, 2),
        profit_factor=round(min(pf, 10.0), 3),
        gross_profit=round(gp, 2),
        gross_loss=round(gl, 2),
        net_pnl=round(net, 2),
        pct_return=round(net / starting_equity * 100, 4),
        annual_return=0.0,           # filled by orchestrator using window dates
        final_equity=round(final_equity, 2),
        avg_win_pct=round(avg_win_pct, 3),
        avg_loss_pct=round(avg_loss_pct, 3),
        avg_bars_held=round(avg_bars, 2),
        max_drawdown_pct=round(max_dd_pct, 3),
        sharpe_ratio=0.0,             # filled by orchestrator from equity_curve
    )
```

- [ ] **Step 4: Run tests until green**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/engines/test_metrics_from_trades.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/engines/_diagnostics.py tests/engines/test_metrics_from_trades.py
git commit -m "feat(engines): add metrics_from_trades helper for external trade lists"
```

---

### Task 3: CSV → BacktestResult orchestrator (no I/O yet)

**Files:**
- Create: `src/tradelab/csv_scoring.py`
- Create: `tests/test_csv_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_csv_scoring.py`:

```python
"""csv_scoring orchestrator tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.csv_scoring import build_backtest_result_from_trades, score_trades
from tradelab.io.tv_csv import parse_tv_trades_csv


FIXTURE = Path(__file__).parent / "io" / "fixtures" / "tv_export_amzn_smoke.csv"


@pytest.fixture
def parsed_amzn():
    return parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")


def test_build_backtest_result_populates_window_and_strategy_name(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn,
        strategy_name="viprasol-amzn-v1",
        symbol="AMZN",
        timeframe="1H",
        starting_equity=100_000.0,
    )
    assert bt.strategy == "viprasol-amzn-v1"
    assert bt.symbol == "AMZN"
    assert bt.timeframe == "1H"
    assert bt.start_date == "2024-01-08"
    assert bt.end_date == "2024-03-22"
    assert len(bt.trades) == 6
    assert bt.metrics.total_trades == 6


def test_build_backtest_result_emits_equity_curve_per_trade(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    # One equity point per closed trade, dated by exit_date, equity is cumulative.
    assert len(bt.equity_curve) == 6
    assert bt.equity_curve[0] == {"date": "2024-01-12", "equity": 100_060.0}
    assert bt.equity_curve[-1]["equity"] == round(100_000.0 + 240.0, 2)


def test_build_backtest_result_fills_annual_return_from_window(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    # 73-day window, +0.24% net → annualized roughly 1.2% (cross-check arithmetic only).
    assert bt.metrics.annual_return > 0
    assert bt.metrics.annual_return < 5.0  # sanity bound


def test_build_backtest_result_includes_monthly_pnl(parsed_amzn):
    bt = build_backtest_result_from_trades(
        parsed_amzn, strategy_name="x", symbol="AMZN", starting_equity=100_000.0,
    )
    months = {row["month"] for row in bt.monthly_pnl}
    assert months == {"2024-01", "2024-02", "2024-03"}


def test_score_trades_returns_verdict_and_dsr(parsed_amzn):
    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    assert out.verdict.verdict in {"ROBUST", "INCONCLUSIVE", "FRAGILE"}
    # 6 trades is too few for a meaningful DSR — should be NaN-handled, not crash.
    assert out.dsr_probability is None or 0.0 <= out.dsr_probability <= 1.0
    assert out.backtest_result.metrics.total_trades == 6
    assert out.monte_carlo is not None
    assert out.monte_carlo.n_trades == 6
```

- [ ] **Step 2: Run to confirm it fails**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/test_csv_scoring.py -v
```

Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement the orchestrator**

Create `src/tradelab/csv_scoring.py`:

```python
"""Orchestrator: CSV-derived trades → verdict + report folder + audit row.

The single entry point that callers (CLI, dashboard backend) use:

    parsed = parse_tv_trades_csv(csv_text, symbol="AMZN")
    out = score_trades(parsed, strategy_name="viprasol-amzn-v1", symbol="AMZN")
    folder = write_report_folder(out, base_name="viprasol-amzn-v1",
                                 pine_source=None, csv_text=csv_text)

Degraded relative to `tradelab run`:
  - no Optuna / WF / param landscape / entry delay / noise / LOSO
  - DSR uses n_trials=1
  - dashboard.html still renders, but several tabs will be empty
  - regime breakdown empty (no SPY data)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .engines._diagnostics import compute_monthly_pnl, metrics_from_trades
from .engines.dsr import classify_dsr, deflated_sharpe_ratio
from .io.tv_csv import ParsedTradesCSV
from .results import BacktestResult
from .robustness.monte_carlo import MonteCarloResult, run_monte_carlo
from .robustness.verdict import VerdictResult, compute_verdict


@dataclass
class CSVScoringOutput:
    backtest_result: BacktestResult
    dsr_probability: Optional[float]
    monte_carlo: Optional[MonteCarloResult]
    verdict: VerdictResult


def build_backtest_result_from_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
) -> BacktestResult:
    metrics = metrics_from_trades(parsed.trades, starting_equity=starting_equity)

    # Equity curve, one point per trade exit (good enough for QuantStats /
    # DSR resampling — shorter than a daily-bar curve but sufficient).
    equity = starting_equity
    curve: list[dict] = []
    for t in parsed.trades:
        equity += t.pnl
        curve.append({"date": t.exit_date, "equity": round(equity, 2)})

    # Annualize using calendar days in the window.
    try:
        d0 = datetime.strptime(parsed.start_date, "%Y-%m-%d")
        d1 = datetime.strptime(parsed.end_date, "%Y-%m-%d")
        days = max((d1 - d0).days, 1)
        if metrics.final_equity > 0 and starting_equity > 0:
            growth = metrics.final_equity / starting_equity
            ann = (growth ** (365.0 / days) - 1.0) * 100.0
            metrics = metrics.model_copy(update={"annual_return": round(ann, 3)})
    except Exception:
        pass

    monthly = compute_monthly_pnl(parsed.trades)

    return BacktestResult(
        strategy=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        params={},
        metrics=metrics,
        trades=list(parsed.trades),
        equity_curve=curve,
        regime_breakdown={},
        monthly_pnl=monthly,
    )


def score_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
    mc_simulations: int = 500,
) -> CSVScoringOutput:
    bt = build_backtest_result_from_trades(
        parsed, strategy_name=strategy_name, symbol=symbol,
        timeframe=timeframe, starting_equity=starting_equity,
    )

    # DSR on the trade-exit equity curve. Returns NaN for very short series.
    dsr_p: Optional[float] = None
    returns = bt.daily_returns()
    if returns is not None and len(returns) >= 2:
        p = deflated_sharpe_ratio(returns.values, n_trials=1)
        if not math.isnan(p):
            dsr_p = float(p)

    # MC: shuffles trade pnls; needs trades but no bar data.
    mc = None
    if bt.trades:
        try:
            mc = run_monte_carlo(bt, n_simulations=mc_simulations,
                                 starting_equity=starting_equity)
        except Exception:
            mc = None

    verdict = compute_verdict(bt, dsr=dsr_p, mc=mc)

    return CSVScoringOutput(
        backtest_result=bt,
        dsr_probability=dsr_p,
        monte_carlo=mc,
        verdict=verdict,
    )
```

- [ ] **Step 4: Run tests until green**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/test_csv_scoring.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/csv_scoring.py tests/test_csv_scoring.py
git commit -m "feat(csv_scoring): orchestrate trades→verdict (DSR + MC + aggregation)"
```

---

### Task 4: Report folder writer + audit DB integration

**Files:**
- Modify: `src/tradelab/csv_scoring.py` (add `write_report_folder` and `_record_audit`)
- Modify: `tests/test_csv_scoring.py` (add report-folder + audit tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_csv_scoring.py`:

```python
import json

from tradelab.audit import list_runs


def test_write_report_folder_creates_executive_dashboard_and_json(parsed_amzn, tmp_path):
    from tradelab.csv_scoring import score_trades, write_report_folder

    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    folder = write_report_folder(
        out,
        base_name="viprasol-amzn-v1",
        out_root=tmp_path,
        pine_source="// dummy pine\nstrategy('x')",
        csv_text="dummy,csv\n",
        record_audit=False,
    )

    assert folder.exists() and folder.is_dir()
    assert folder.name.startswith("viprasol-amzn-v1_")
    assert (folder / "executive_report.md").exists()
    assert (folder / "dashboard.html").exists()
    assert (folder / "backtest_result.json").exists()
    assert (folder / "tv_trades.csv").exists()
    assert (folder / "strategy.pine").exists()

    # Round-trip the JSON to confirm BacktestResult survives pydantic dump+load.
    data = json.loads((folder / "backtest_result.json").read_text(encoding="utf-8"))
    assert data["strategy"] == "viprasol-amzn-v1"
    assert data["symbol"] == "AMZN"
    assert len(data["trades"]) == 6


def test_write_report_folder_records_audit_row_when_enabled(parsed_amzn, tmp_path):
    from tradelab.csv_scoring import score_trades, write_report_folder

    db_path = tmp_path / "history.db"
    out = score_trades(parsed_amzn, strategy_name="x", symbol="AMZN")
    write_report_folder(
        out,
        base_name="viprasol-amzn-v1",
        out_root=tmp_path,
        pine_source=None,
        csv_text="x\n",
        record_audit=True,
        db_path=db_path,
    )

    rows = list_runs(strategy="viprasol-amzn-v1", db_path=db_path)
    assert len(rows) == 1
    assert rows[0].verdict in {"ROBUST", "INCONCLUSIVE", "FRAGILE"}
    assert rows[0].report_card_html_path is not None
```

- [ ] **Step 2: Run to confirm they fail**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/test_csv_scoring.py -v
```

Expected: 2 collection / attribute errors for the new tests.

- [ ] **Step 3: Implement `write_report_folder`**

Append to `src/tradelab/csv_scoring.py`:

```python
from .audit import record_run as _audit_record_run
from .audit.history import DEFAULT_DB_PATH as _DEFAULT_DB_PATH
from .dashboard import build_dashboard
from .determinism import hash_config
from .reporting import generate_executive_report


def _safe_dashboard(out: CSVScoringOutput, out_dir: Path) -> Optional[Path]:
    """Build dashboard.html. Tolerate failures so the rest of the report survives."""
    try:
        return build_dashboard(
            out.backtest_result,
            optuna_result=None, wf_result=None,
            universe=None,
            out_dir=out_dir,
            robustness_result=None,
        )
    except Exception:
        return None


def write_report_folder(
    out: CSVScoringOutput,
    *,
    base_name: str,
    out_root: Path = Path("reports"),
    pine_source: Optional[str] = None,
    csv_text: Optional[str] = None,
    record_audit: bool = True,
    db_path: Path = _DEFAULT_DB_PATH,
) -> Path:
    """Persist a full report folder under <out_root>/<base_name>_<timestamp>/.

    Files written:
      executive_report.md       — same renderer as `tradelab run`
      dashboard.html            — best-effort; missing tabs render as 'no data'
      backtest_result.json      — pydantic dump for `tradelab compare` parity
      tv_trades.csv             — verbatim copy of the imported CSV
      strategy.pine             — Pine source if caller provided one

    Audit row is written when record_audit=True (default).
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = Path(out_root) / f"{base_name}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)

    # Override strategy name in the BacktestResult so the report header uses
    # the user-supplied base name rather than whatever was passed to score_trades.
    bt = out.backtest_result.model_copy(update={"strategy": base_name})

    report_path = generate_executive_report(
        bt, optuna_result=None, wf_result=None,
        universe=None, out_dir=folder, robustness_result=None,
    )

    dashboard_path = _safe_dashboard(
        CSVScoringOutput(
            backtest_result=bt,
            dsr_probability=out.dsr_probability,
            monte_carlo=out.monte_carlo,
            verdict=out.verdict,
        ),
        folder,
    )

    (folder / "backtest_result.json").write_text(
        bt.model_dump_json(indent=2), encoding="utf-8",
    )

    if csv_text is not None:
        (folder / "tv_trades.csv").write_text(csv_text, encoding="utf-8")
    if pine_source is not None:
        (folder / "strategy.pine").write_text(pine_source, encoding="utf-8")

    if record_audit:
        _audit_record_run(
            strategy_name=base_name,
            verdict=out.verdict.verdict,
            dsr_probability=out.dsr_probability,
            input_data_hash=None,            # no OHLCV; CSV is the source
            config_hash=hash_config({}),
            report_card_markdown=report_path.read_text(encoding="utf-8"),
            report_card_html_path=str(dashboard_path) if dashboard_path else None,
            db_path=db_path,
        )

    return folder
```

- [ ] **Step 4: Run tests until green**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/test_csv_scoring.py -v
```

Expected: 7 passed (5 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/csv_scoring.py tests/test_csv_scoring.py
git commit -m "feat(csv_scoring): write report folder + audit DB row from CSV scoring"
```

---

### Task 5: CLI command `score-from-trades`

**Files:**
- Create: `src/tradelab/cli_score.py`
- Modify: `src/tradelab/cli.py` (one new line in the `from .cli_X import …` block at the bottom)
- Create: `tests/cli/test_cli_score.py`

- [ ] **Step 1: Write the failing CLI test**

Create `tests/cli/test_cli_score.py`:

```python
"""End-to-end CliRunner test for `tradelab score-from-trades`."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tradelab.cli import app


FIXTURE = Path(__file__).parent.parent / "io" / "fixtures" / "tv_export_amzn_smoke.csv"


def test_score_from_trades_produces_report_folder(tmp_path, monkeypatch):
    # Run the CLI from a clean cwd so reports/ lands under tmp_path.
    monkeypatch.chdir(tmp_path)
    csv_dst = tmp_path / "amzn.csv"
    shutil.copy(FIXTURE, csv_dst)

    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", str(csv_dst),
        "--symbol", "AMZN",
        "--name", "viprasol-amzn-v1",
        "--no-open",
        "--no-audit",
    ])
    assert result.exit_code == 0, result.output

    reports_dir = tmp_path / "reports"
    folders = [p for p in reports_dir.iterdir() if p.is_dir()
               and p.name.startswith("viprasol-amzn-v1_")]
    assert len(folders) == 1
    folder = folders[0]
    assert (folder / "executive_report.md").exists()
    assert (folder / "backtest_result.json").exists()
    assert (folder / "tv_trades.csv").exists()


def test_score_from_trades_missing_csv_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", "no-such-file.csv",
        "--symbol", "AMZN", "--name", "x",
        "--no-open", "--no-audit",
    ])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "no such" in result.output.lower()


def test_score_from_trades_bad_csv_reports_parse_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, [
        "score-from-trades", str(bad),
        "--symbol", "AMZN", "--name", "x",
        "--no-open", "--no-audit",
    ])
    assert result.exit_code != 0
    assert "missing column" in result.output.lower()
```

- [ ] **Step 2: Run to confirm it fails**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/cli/test_cli_score.py -v
```

Expected: command not registered → "No such command 'score-from-trades'".

- [ ] **Step 3: Implement the CLI module**

Create `src/tradelab/cli_score.py`:

```python
"""`tradelab score-from-trades` — score an externally produced trade list."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .csv_scoring import score_trades, write_report_folder
from .io.tv_csv import TVCSVParseError, parse_tv_trades_csv


console = Console()


def score_from_trades(
    csv_path: Path = typer.Argument(..., help="Path to a TradingView 'List of trades' CSV."),
    symbol: str = typer.Option(..., "--symbol", help="Ticker the CSV represents (e.g., AMZN)."),
    name: str = typer.Option(..., "--name", help="Card base name (e.g., 'viprasol-amzn-v1'). "
                                                  "Used for the report folder + audit row."),
    timeframe: str = typer.Option("1D", "--timeframe",
                                   help="Bar timeframe of the source Pine strategy (cosmetic)."),
    starting_equity: float = typer.Option(100_000.0, "--starting-equity",
                                           help="Equity baseline for percent / DD calculations."),
    pine_path: str = typer.Option("", "--pine-path",
                                    help="Optional path to the Pine source to archive next to the report."),
    audit: bool = typer.Option(True, "--audit/--no-audit",
                                help="Write a row to the audit DB."),
    open_dashboard: bool = typer.Option(True, "--open/--no-open",
                                         help="Auto-open dashboard.html when finished."),
):
    """Score a TradingView Strategy Tester CSV and emit a report folder."""
    if not csv_path.exists():
        console.print(f"[red]CSV not found:[/red] {csv_path}")
        raise typer.Exit(2)

    csv_text = csv_path.read_text(encoding="utf-8-sig")  # tolerate BOM

    try:
        parsed = parse_tv_trades_csv(csv_text, symbol=symbol)
    except TVCSVParseError as e:
        console.print(f"[red]CSV parse error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"[dim]Parsed {len(parsed.trades)} closed trades "
                  f"({parsed.start_date} → {parsed.end_date}).[/dim]")

    out = score_trades(
        parsed, strategy_name=name, symbol=symbol,
        timeframe=timeframe, starting_equity=starting_equity,
    )

    pine_source = None
    if pine_path:
        p = Path(pine_path)
        if p.exists():
            pine_source = p.read_text(encoding="utf-8")
        else:
            console.print(f"[yellow]Pine source not found, continuing without:[/yellow] {p}")

    folder = write_report_folder(
        out, base_name=name, pine_source=pine_source,
        csv_text=csv_text, record_audit=audit,
    )

    v = out.verdict
    color = {"ROBUST": "green", "INCONCLUSIVE": "yellow", "FRAGILE": "red"}.get(v.verdict, "white")
    console.print(f"\n[bold]Verdict:[/bold] [{color}]{v.verdict}[/{color}]  "
                  f"({sum(1 for s in v.signals if s.outcome=='robust')} robust / "
                  f"{sum(1 for s in v.signals if s.outcome=='inconclusive')} inconclusive / "
                  f"{sum(1 for s in v.signals if s.outcome=='fragile')} fragile)")
    console.print(f"Report:    [cyan]{folder / 'executive_report.md'}[/cyan]")
    console.print(f"Dashboard: [cyan]{folder / 'dashboard.html'}[/cyan]")

    if open_dashboard:
        try:
            typer.launch(str(folder / "dashboard.html"))
        except Exception:
            pass
```

- [ ] **Step 4: Register the command in `src/tradelab/cli.py`**

Add this line in the registration block at the bottom of `cli.py`, immediately after the `from .cli_gate_check import …` line (currently line 456):

```python
from .cli_score import score_from_trades as _score_cmd; app.command(name="score-from-trades")(_score_cmd)
```

- [ ] **Step 5: Run CLI tests until green**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest tests/cli/test_cli_score.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Spot-check the live command in a real shell**

```
cd C:\TradingScripts\tradelab
PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m tradelab.cli score-from-trades \
    tests/io/fixtures/tv_export_amzn_smoke.csv \
    --symbol AMZN --name smoke-v1 --no-open --no-audit
```

Expected: prints "Verdict: …" and writes a folder under `reports/smoke-v1_*`. Open `executive_report.md` to eyeball the rendered output. Delete the smoke folder afterward.

- [ ] **Step 7: Commit**

```bash
git add src/tradelab/cli_score.py src/tradelab/cli.py tests/cli/test_cli_score.py
git commit -m "feat(cli): add score-from-trades command for TradingView CSV imports"
```

---

### Task 6: Full-suite regression check

- [ ] **Step 1: Run the entire test suite**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 pytest -q
```

Expected: all green. New tests (~14) included; no existing tests regressed.

- [ ] **Step 2: If `tradelab list` / `tradelab --help` runs are part of CI smoke, verify them**

```
PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m tradelab.cli --help | grep score-from-trades
```

Expected: the new command appears in the help listing.

- [ ] **Step 3: If everything's clean, push the branch (do not auto-merge to master)**

Hand control back to Amit for review and merge.

---

## What Session 2 deliberately does NOT do

These are deferred to later sessions per the handoff (`OPTION_H_HANDOFF_2026-04-24.md` §5):

- **Dashboard textarea / paste UI.** Session 3.
- **Card registry write + Accept button.** Session 3.
- **Card-archive (`pine_archive/{card_id}/`) layout.** Session 3 — Session 2 produces a free-form `reports/<name>_<ts>/` folder; Session 3's `/tradelab/approve-strategy` handler can move/copy into the canonical card layout.
- **Multi-CSV LOSO.** Session 3+ — needs the dashboard to manage a per-symbol CSV bundle.
- **Optuna / WF / param-landscape / entry-delay / noise injection.** Permanently out of scope for the CSV path (those need code-driven re-execution; degradations were explicitly accepted).

## Self-review notes

Spec coverage cross-check against the handoff §5 task list:

| Spec item | Plan task |
|---|---|
| New CLI command with `--symbol`, `--name`, etc. | Task 5 |
| TV CSV parser (Trade# pairing) | Task 1 |
| Normalize to internal trade-record schema | Task 1 (writes `Trade` directly) + Task 2/3 (builds `BacktestResult`) |
| Feed to verdict engine — DSR, MC, verdict aggregation | Task 3 (`score_trades`) |
| (LOSO with per-symbol CSVs) | **Deferred** — single-CSV path only; multi-CSV is Session 3 work |
| (Regime spread) | Empty by design — no SPY data in CSV path |
| Write a `run_record` into audit DB | Task 4 (`record_audit=True` branch) |
| Store CSV + synthetic dashboard.html + executive_report.md under `reports/{name}_{ts}/` | Task 4 (`write_report_folder`) |

No placeholders. Type names cross-checked against `src/tradelab/results.py`, `src/tradelab/audit/history.py`, `src/tradelab/robustness/verdict.py`, `src/tradelab/robustness/monte_carlo.py`, `src/tradelab/reporting/executive.py`, `src/tradelab/dashboard/builder.py`, `src/tradelab/cli.py`. Function signatures verified against current head (`8a9a342`).
