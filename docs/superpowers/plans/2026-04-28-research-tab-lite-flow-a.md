# Research Tab — LITE for Flow A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LITE research-tab feedback loop applied to Flow A — TE / Decay / K-S per live card, Hold-out OOS gate, multi-dimensional correlation gate at Accept, Portfolio Health, Regime banner, Calibration banner.

**Architecture:** Distributional tracking error against frozen `pine_archive/<card_id>/tv_trades.csv` baselines (no Pine→Python predicted-fills exporter needed). New backend modules in `tradelab.io`, `tradelab.live.tracking_error`, `tradelab.regime.banner`, `tradelab.calibration.summary`, `tradelab.robustness.correlation`. New `GET /tradelab/...` endpoints on the dashboard's `web/handlers.py` (pure `http.server` regex routing). Frontend additions in `C:\TradingScripts\command_center.html` (single-file inline JS).

**Tech Stack:** Python 3.11+, pydantic v2, scipy.stats (K-S), numpy, alpaca-py (regime), pytest, vanilla JS + inline CSS in `command_center.html`.

**Spec:** `docs/superpowers/specs/2026-04-28-research-tab-lite-flow-a-design.md`
**Mockup:** `docs/superpowers/mockups/research_tab_lite_applied_to_flow_a.html`

---

## Plan-wide conventions

**Working directory:** All `git` and `pytest` commands run from `C:\TradingScripts\tradelab` unless explicitly stated otherwise. Frontend commits run from the parent repo `C:\TradingScripts`.

**Pre-flight grep before each task:** Per `feedback_plan_grep_verification` memory, re-verify named selectors at execution time. If a selector this plan names has moved or been renamed since 2026-04-28, fix the plan task in place before implementing.

**Partial-staging commits only:** Per the resumption-plan memory, never `git add -A` and never `git add <whole-file>` for files with unrelated dirty hunks (especially `command_center.html`). Always `git add -p` or `git add <specific-files-changed-by-this-task>`.

**Endpoint envelope:** All new endpoints in `web/handlers.py` follow the existing pattern — return `_ok(data)` (200) or `_err(msg)` (400/404/500). Body shape: `{"error": null, "data": ...}` on success, `{"error": "msg", "data": null}` on error.

**Notify severity for K-S:** WARNING never CRITICAL. LITE rule.

**Smoke gate between tasks:** Per `feedback_live_smoke_before_next_slice` memory, after each task's pytest passes, run a manual smoke through the dashboard before moving to the next task. If a bug surfaces, fix it before continuing — not next session.

---

## Task 1: Returns persistence at Accept (S1)

**Files:**
- Create: `tradelab/src/tradelab/io/returns.py`
- Create: `tradelab/tests/io/test_returns.py`
- Modify: `tradelab/src/tradelab/web/approve_strategy.py:138-234` (function `accept_scored`)
- Create: `tradelab/scripts/backfill_returns.py`
- Create: `tradelab/tests/scripts/test_backfill_returns.py`

- [ ] **Step 1.1: Pre-flight grep**

```bash
grep -n "def accept_scored" tradelab/src/tradelab/web/approve_strategy.py
grep -n "tv_trades.csv" tradelab/src/tradelab/web/approve_strategy.py
grep -n "from .io.tv_csv" tradelab/src/tradelab/web/approve_strategy.py tradelab/src/tradelab/web/handlers.py
```
Expected: `accept_scored` defined ~line 138; `tv_trades.csv` referenced when copying to `archive_dir`; `tv_csv` reader used in `web/`. If any moved, update task selectors.

- [ ] **Step 1.2: Write the failing test for returns derivation**

Create `tradelab/tests/io/test_returns.py`:

```python
"""Test daily-returns derivation from tv_trades.csv."""
from __future__ import annotations
from pathlib import Path
import csv
import pytest
from tradelab.io.returns import derive_daily_returns, write_returns_csv


def _write_tv_trades(tmp_path: Path) -> Path:
    """Two trades on 2026-01-05 (one win, one loss), one on 2026-01-06."""
    p = tmp_path / "tv_trades.csv"
    p.write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30:00,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00:00,103.00,10,30.00,3.00\n"
        "2,Entry long,enter,2026-01-05 13:00:00,105.00,10,,\n"
        "2,Exit long,exit,2026-01-05 14:30:00,103.00,10,-20.00,-1.90\n"
        "3,Entry long,enter,2026-01-06 09:30:00,107.00,5,,\n"
        "3,Exit long,exit,2026-01-06 15:00:00,112.00,5,25.00,4.67\n",
        encoding="utf-8",
    )
    return p


def test_derive_daily_returns_groups_by_exit_date(tmp_path: Path) -> None:
    csv_path = _write_tv_trades(tmp_path)
    rows = derive_daily_returns(csv_path)
    # Two distinct trade-exit dates → two daily rows.
    assert len(rows) == 2
    by_date = {r["date"]: r for r in rows}
    # 2026-01-05 net return: trade 1 (+3.00%) + trade 2 (-1.90%) = +1.10%.
    assert by_date["2026-01-05"]["return_pct"] == pytest.approx(1.10, abs=0.001)
    # 2026-01-06: single trade +4.67%.
    assert by_date["2026-01-06"]["return_pct"] == pytest.approx(4.67, abs=0.001)


def test_derive_daily_returns_handles_alt_column_names(tmp_path: Path) -> None:
    """tv_csv supports both 'Profit USD' and 'Net P&L USD', etc."""
    p = tmp_path / "tv_trades.csv"
    p.write_text(
        "Trade #,Type,Signal,Date and time,Price USD,Size (qty),Net P&L USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30:00,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    rows = derive_daily_returns(p)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["return_pct"] == pytest.approx(3.00, abs=0.001)


def test_write_returns_csv_emits_two_columns(tmp_path: Path) -> None:
    out = tmp_path / "returns.csv"
    write_returns_csv(out, [
        {"date": "2026-01-05", "return_pct": 1.10},
        {"date": "2026-01-06", "return_pct": 4.67},
    ])
    text = out.read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    assert reader.fieldnames == ["date", "return_pct"]
    assert rows == [
        {"date": "2026-01-05", "return_pct": "1.10"},
        {"date": "2026-01-06", "return_pct": "4.67"},
    ]


def test_derive_returns_empty_csv_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "tv_trades.csv"
    p.write_text("Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n", encoding="utf-8")
    assert derive_daily_returns(p) == []
```

- [ ] **Step 1.3: Run test to verify it fails**

```bash
pytest tradelab/tests/io/test_returns.py -v
```
Expected: ImportError / ModuleNotFoundError on `tradelab.io.returns`.

- [ ] **Step 1.4: Implement `tradelab/src/tradelab/io/returns.py`**

```python
"""Derive daily-returns series from tv_trades.csv exports.

Used at Accept time (and via backfill script) to persist a per-card
returns series at pine_archive/<card_id>/returns.csv, which feeds the
correlation engine and tracking-error engine.

Returns are aggregated by trade-EXIT date. Multi-trade days net out.
"""
from __future__ import annotations
from pathlib import Path
import csv
from typing import Iterable
from .tv_csv import read_tv_csv  # existing reader handles column variants


def derive_daily_returns(tv_trades_csv: Path) -> list[dict]:
    """Return [{date: 'YYYY-MM-DD', return_pct: float}, ...] sorted by date.

    Groups exits by date; sums their `Profit %` values per day.
    Entries (no profit value) are ignored.
    """
    trades = read_tv_csv(tv_trades_csv)
    by_date: dict[str, float] = {}
    for t in trades:
        # tv_csv normalizes to a `Trade` model with exit_date, profit_pct.
        # Skip rows with no exit (open trades) or no profit value.
        exit_date = t.exit_date
        profit_pct = t.profit_pct
        if exit_date is None or profit_pct is None:
            continue
        key = exit_date.strftime("%Y-%m-%d")
        by_date[key] = by_date.get(key, 0.0) + float(profit_pct)
    return [{"date": d, "return_pct": round(by_date[d], 4)} for d in sorted(by_date)]


def write_returns_csv(out_path: Path, rows: Iterable[dict]) -> None:
    """Write [{date, return_pct}] rows as 2-column CSV with header."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "return_pct"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "date": row["date"],
                "return_pct": f"{float(row['return_pct']):.2f}",
            })
```

**Note:** The exact attribute names on `Trade` (`exit_date`, `profit_pct`) must match `tradelab.io.tv_csv`. Verify with: `grep -n "class Trade\|exit_date\|profit_pct" tradelab/src/tradelab/io/tv_csv.py` before running. If they differ (e.g., `exit_dt`, `profit_percent`), adjust the implementation to use the actual names.

- [ ] **Step 1.5: Run test to verify it passes**

```bash
pytest tradelab/tests/io/test_returns.py -v
```
Expected: 4 passed.

- [ ] **Step 1.6: Wire returns.csv write into `accept_scored`**

In `tradelab/src/tradelab/web/approve_strategy.py`, locate the block that copies `tv_trades.csv` into `archive_dir` (around line 187-189 per pre-flight grep). Immediately AFTER the `if csv_src.exists(): _shutil.copy2(csv_src, archive_dir / "tv_trades.csv")` line, add:

```python
        # S1: persist daily-returns series for correlation + tracking-error engines
        if csv_src.exists():
            from ..io.returns import derive_daily_returns, write_returns_csv
            try:
                returns_rows = derive_daily_returns(archive_dir / "tv_trades.csv")
                write_returns_csv(archive_dir / "returns.csv", returns_rows)
            except Exception as e:
                # Don't block Accept on returns-derivation failure;
                # backfill script can re-derive later.
                _log.warning("returns.csv derivation failed for %s: %s", card_id, e)
```

Verify the surrounding indentation matches the existing function (likely 8 spaces if inside a try-block, 4 if at function-body level). Match the existing style.

- [ ] **Step 1.7: Add integration test for accept_scored returns write**

Append to `tradelab/tests/io/test_returns.py` (or in `tradelab/tests/web/test_approve_strategy.py` if that's where accept_scored tests live — grep first):

```python
def test_accept_scored_writes_returns_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling accept_scored with a tv_trades.csv in the report folder
    writes a returns.csv next to it in pine_archive."""
    # This is an integration test — set up a minimal report folder + scoring run.
    # Use the existing accept_scored test fixtures if any; otherwise
    # mock around accept_scored's other writes (cards.json, alerts) and assert
    # only on the returns.csv side-effect.
    # NOTE: detail this by grepping existing tests/web/test_approve_strategy.py first;
    # match its fixture style.
    pytest.skip("Implement using existing accept_scored fixtures")
```

If `tests/web/test_approve_strategy.py` exists (grep to check), inline the test there using its existing fixtures. The test asserts that after `accept_scored(...)`, `pine_archive/<card_id>/returns.csv` exists with at least 1 row.

- [ ] **Step 1.8: Run all tests to confirm no regression**

```bash
pytest tradelab/tests/ -x
```
Expected: all passing (816+ from prior baseline). New tests added in step 1.2 + 1.7 also pass.

- [ ] **Step 1.9: Implement backfill script**

Create `tradelab/scripts/backfill_returns.py`:

```python
"""One-time backfill: derive returns.csv for every existing pine_archive card.

Idempotent — skips cards that already have returns.csv unless --force is passed.

Usage:
    python -m tradelab.scripts.backfill_returns                    # dry run
    python -m tradelab.scripts.backfill_returns --apply            # write
    python -m tradelab.scripts.backfill_returns --apply --force    # overwrite existing
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from tradelab.io.returns import derive_daily_returns, write_returns_csv


def find_archive_root() -> Path:
    """pine_archive is at <repo_root>/pine_archive. Resolve from this script's location."""
    here = Path(__file__).resolve()
    # tradelab/scripts/backfill_returns.py → repo root is parents[2]
    return here.parents[2] / "pine_archive"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    parser.add_argument("--force", action="store_true", help="overwrite existing returns.csv")
    parser.add_argument("--archive-root", type=Path, default=None, help="override pine_archive path")
    args = parser.parse_args(argv)

    archive_root = args.archive_root or find_archive_root()
    if not archive_root.exists():
        print(f"ERROR: pine_archive not found at {archive_root}", file=sys.stderr)
        return 1

    n_processed = 0
    n_written = 0
    n_skipped = 0
    n_failed = 0
    for card_dir in sorted(archive_root.iterdir()):
        if not card_dir.is_dir():
            continue
        tv_csv = card_dir / "tv_trades.csv"
        returns_csv = card_dir / "returns.csv"
        if not tv_csv.exists():
            continue
        n_processed += 1
        if returns_csv.exists() and not args.force:
            n_skipped += 1
            continue
        try:
            rows = derive_daily_returns(tv_csv)
            if not rows:
                print(f"  skip {card_dir.name}: no usable trades")
                n_skipped += 1
                continue
            if args.apply:
                write_returns_csv(returns_csv, rows)
                print(f"  wrote {card_dir.name}: {len(rows)} days")
                n_written += 1
            else:
                print(f"  would write {card_dir.name}: {len(rows)} days")
        except Exception as e:
            print(f"  ERROR {card_dir.name}: {e}", file=sys.stderr)
            n_failed += 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] processed={n_processed} written={n_written} skipped={n_skipped} failed={n_failed}")
    return 0 if n_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 1.10: Add backfill test**

Create `tradelab/tests/scripts/test_backfill_returns.py`:

```python
"""Test the backfill script's dry-run, apply, and skip-existing behavior."""
from __future__ import annotations
from pathlib import Path
import pytest
from tradelab.scripts import backfill_returns


def _make_card(archive_root: Path, card_id: str, with_existing_returns: bool = False) -> Path:
    """Set up a card_dir with tv_trades.csv and optionally returns.csv."""
    card = archive_root / card_id
    card.mkdir(parents=True, exist_ok=True)
    (card / "tv_trades.csv").write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30:00,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    if with_existing_returns:
        (card / "returns.csv").write_text("date,return_pct\n2026-01-05,99.99\n", encoding="utf-8")
    return card


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _make_card(tmp_path, "alpha-v1")
    rc = backfill_returns.main(["--archive-root", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "alpha-v1" / "returns.csv").exists()
    out = capsys.readouterr().out
    assert "would write" in out


def test_apply_writes_returns(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1")
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply"])
    assert rc == 0
    assert (tmp_path / "alpha-v1" / "returns.csv").exists()


def test_apply_skips_existing_without_force(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1", with_existing_returns=True)
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply"])
    assert rc == 0
    # File should still contain the sentinel value (99.99), unchanged.
    assert "99.99" in (tmp_path / "alpha-v1" / "returns.csv").read_text(encoding="utf-8")


def test_apply_force_overwrites(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1", with_existing_returns=True)
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply", "--force"])
    assert rc == 0
    text = (tmp_path / "alpha-v1" / "returns.csv").read_text(encoding="utf-8")
    assert "99.99" not in text
    assert "3.00" in text
```

- [ ] **Step 1.11: Run all tests**

```bash
pytest tradelab/tests/io/test_returns.py tradelab/tests/scripts/test_backfill_returns.py -v
pytest tradelab/tests/ -x
```
Expected: new tests pass; no regressions.

- [ ] **Step 1.12: Smoke — run backfill in dry-run, then apply**

```bash
python -m tradelab.scripts.backfill_returns
# Inspect output. If it lists existing cards correctly, run --apply:
python -m tradelab.scripts.backfill_returns --apply
ls pine_archive/*/returns.csv
```
Expected: at least 1 returns.csv created (the dogfooded card from yesterday).

- [ ] **Step 1.13: Commit**

```bash
git add tradelab/src/tradelab/io/returns.py \
        tradelab/tests/io/test_returns.py \
        tradelab/scripts/backfill_returns.py \
        tradelab/tests/scripts/test_backfill_returns.py \
        tradelab/src/tradelab/web/approve_strategy.py
git commit -m "feat(io): persist returns.csv at Accept + backfill script (S1)

Derives daily-returns series from pine_archive/<card_id>/tv_trades.csv
and writes pine_archive/<card_id>/returns.csv. Wired into accept_scored
so all newly-accepted cards get returns.csv automatically.

Backfill script idempotently writes returns.csv for existing cards.

Foundation for tracking-error engine (S2) and correlation engine (S5).
"
```

---

## Task 2: Tracking-error engine + endpoint (S2)

**Files:**
- Create: `tradelab/src/tradelab/live/tracking_error.py`
- Create: `tradelab/tests/live/test_tracking_error.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `GET /tradelab/cards/<id>/tracking-error` endpoint)

- [ ] **Step 2.1: Pre-flight grep**

```bash
grep -n "GET /tradelab" tradelab/src/tradelab/web/handlers.py | head -20
grep -n "client_order_id" tradelab/src/tradelab/live/*.py
grep -n "alpaca_config" tradelab/src/tradelab/live/*.py
```
Expected: existing GET routes use `re.match(r"^/tradelab/...$", path)` or `if path == "/tradelab/...":` patterns. Confirm `client_order_id` is part of the Slice -0.5 fill tagging in receiver/cards code.

- [ ] **Step 2.2: Write the failing test**

Create `tradelab/tests/live/test_tracking_error.py`:

```python
"""Test distributional TE / Decay / K-S engine."""
from __future__ import annotations
from pathlib import Path
import csv
import pytest
from tradelab.live.tracking_error import (
    compute_tracking_error,
    TrackingErrorResult,
    TE_GREEN_THRESHOLD,
    TE_AMBER_THRESHOLD,
)


def _write_tv_trades(card_dir: Path, profits_pct: list[float]) -> None:
    """Write a synthetic tv_trades.csv with given exit profit_pct per trade."""
    card_dir.mkdir(parents=True, exist_ok=True)
    rows = ["Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %"]
    for i, p in enumerate(profits_pct, start=1):
        rows.append(f"{i},Entry long,enter,2026-01-{i:02d} 09:30:00,100.00,10,,")
        rows.append(f"{i},Exit long,exit,2026-01-{i:02d} 15:00:00,{100*(1+p/100):.2f},10,{p*10:.2f},{p:.2f}")
    (card_dir / "tv_trades.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_insufficient_sample_returns_status(tmp_path: Path) -> None:
    _write_tv_trades(tmp_path / "alpha-v1", [1.0, 2.0, -1.0, 0.5, 1.5] * 6)  # 30 backtest
    live_returns_pct = [1.2, 0.8, -0.5]  # only 3 live fills
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live_returns_pct,
    )
    assert result.status == "insufficient"
    assert result.n_live_trades == 3
    assert result.te is None
    assert result.ks_p is None


def test_te_ratio_above_threshold_marks_green(tmp_path: Path) -> None:
    backtest = [1.0, -0.5, 1.5, -0.3, 2.0] * 6  # n=30, mean=0.74%, ~PF=2.0
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    # Live trades close to backtest distribution.
    live = [0.9, -0.4, 1.4, -0.3, 1.8] * 6  # n=30
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.te is not None
    assert result.te > TE_GREEN_THRESHOLD  # >= 0.80
    assert result.ks_p is not None
    assert result.ks_p > 0.05  # similar distributions


def test_te_ratio_below_amber_threshold(tmp_path: Path) -> None:
    backtest = [2.0, -0.3, 2.0, -0.3, 2.0] * 6  # PF very high
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    # Live underperforming significantly.
    live = [0.5, -1.0, 0.4, -1.0, 0.5] * 6  # PF ~0.5
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.te is not None
    assert result.te < TE_AMBER_THRESHOLD  # < 0.60 → red bucket


def test_decay_series_has_11_points(tmp_path: Path) -> None:
    backtest = [1.0, -0.5, 1.5, -0.3, 2.0] * 8  # n=40
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [0.9, -0.4, 1.4, -0.3, 1.8] * 8
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.decay_series is not None
    assert len(result.decay_series) == 11


def test_ks_low_p_for_divergent_distributions(tmp_path: Path) -> None:
    backtest = [1.0] * 30  # all wins of +1%
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [-1.0] * 30  # all losses of -1%
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.ks_p is not None
    assert result.ks_p < 0.01  # very different distributions
```

- [ ] **Step 2.3: Run the test to verify failure**

```bash
pytest tradelab/tests/live/test_tracking_error.py -v
```
Expected: ImportError on `tradelab.live.tracking_error`.

- [ ] **Step 2.4: Implement `tradelab/src/tradelab/live/tracking_error.py`**

```python
"""Distributional tracking-error engine for LITE-on-Flow-A.

Compares live trade-return distribution to backtest trade-return distribution
(both as lists of profit_pct values). The backtest baseline is read from the
frozen pine_archive/<card_id>/tv_trades.csv at Accept time.

Returns:
- te: live PF / backtest PF over rolling last-N-trades window
- decay_series: 11-point smoothed rolling PF over live trades
- ks_p: two-sample K-S test p-value
- status: "ok" | "insufficient" (n_live < MIN_N_TRADES)
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import statistics
from pydantic import BaseModel
from scipy import stats as scipy_stats
from ..io.tv_csv import read_tv_csv

MIN_N_TRADES = 30
ROLLING_WINDOW = 30
DECAY_POINTS = 11
TE_GREEN_THRESHOLD = 0.80
TE_AMBER_THRESHOLD = 0.60
KS_AMBER = 0.05
KS_RED = 0.01


class TrackingErrorResult(BaseModel):
    te: Optional[float] = None
    decay_series: Optional[list[float]] = None
    ks_p: Optional[float] = None
    n_live_trades: int = 0
    n_backtest_trades: int = 0
    status: str = "insufficient"  # "ok" | "insufficient"


def _profit_factor(returns_pct: list[float]) -> Optional[float]:
    """PF = sum(wins) / abs(sum(losses)). Returns None if no losses."""
    wins = sum(r for r in returns_pct if r > 0)
    losses = sum(r for r in returns_pct if r < 0)
    if losses >= 0:
        return None  # no losses (or zero loss); PF undefined
    return wins / abs(losses)


def _decay_series(returns_pct: list[float], n_points: int = DECAY_POINTS) -> list[float]:
    """11 evenly-spaced rolling-PF samples over the trade sequence.

    Returns the rolling PF computed at n_points equally spaced anchor indices.
    Each anchor uses up to ROLLING_WINDOW prior trades.
    """
    if not returns_pct:
        return []
    n = len(returns_pct)
    if n_points >= n:
        # Not enough data for distinct anchors; return whatever we have.
        return [
            _profit_factor(returns_pct[: i + 1]) or 1.0
            for i in range(n)
        ]
    anchors = [int(i * (n - 1) / (n_points - 1)) for i in range(n_points)]
    series: list[float] = []
    for a in anchors:
        start = max(0, a + 1 - ROLLING_WINDOW)
        pf = _profit_factor(returns_pct[start : a + 1])
        series.append(pf if pf is not None else 1.0)
    return series


def compute_tracking_error(
    backtest_csv: Path,
    live_returns_pct: list[float],
) -> TrackingErrorResult:
    trades = read_tv_csv(backtest_csv)
    backtest_returns = [
        float(t.profit_pct) for t in trades
        if t.profit_pct is not None and t.exit_date is not None
    ]
    n_backtest = len(backtest_returns)
    n_live = len(live_returns_pct)
    if n_live < MIN_N_TRADES:
        return TrackingErrorResult(
            status="insufficient",
            n_live_trades=n_live,
            n_backtest_trades=n_backtest,
        )
    # Restrict to rolling window for TE ratio.
    live_window = live_returns_pct[-ROLLING_WINDOW:]
    live_pf = _profit_factor(live_window)
    backtest_pf = _profit_factor(backtest_returns)
    te: Optional[float] = None
    if live_pf is not None and backtest_pf is not None and backtest_pf > 0:
        te = round(live_pf / backtest_pf, 3)
    # K-S two-sample.
    ks_p: Optional[float] = None
    if backtest_returns:
        try:
            ks_result = scipy_stats.ks_2samp(live_returns_pct, backtest_returns)
            ks_p = round(float(ks_result.pvalue), 4)
        except Exception:
            ks_p = None
    decay = _decay_series(live_returns_pct)
    return TrackingErrorResult(
        te=te,
        decay_series=decay,
        ks_p=ks_p,
        n_live_trades=n_live,
        n_backtest_trades=n_backtest,
        status="ok",
    )
```

- [ ] **Step 2.5: Run unit tests to verify pass**

```bash
pytest tradelab/tests/live/test_tracking_error.py -v
```
Expected: 5 passed.

- [ ] **Step 2.6: Implement live-fills loader for the endpoint**

The endpoint needs to load live fill returns for a given card from Alpaca's fills (filtered by `client_order_id` matching the card). Per Slice -0.5, fills are tagged. Per `reference_alpaca_trade_history_source` memory, trades.csv is never written — fills come from Alpaca API + bot.log.

Add a helper in `tradelab/src/tradelab/live/tracking_error.py`:

```python
def load_live_returns_for_card(card_id: str, *, alpaca_client=None) -> list[float]:
    """Pull all paired-fill returns_pct from Alpaca filtered to this card.

    Strategy attribution: fills since Slice -0.5 carry `client_order_id`
    starting with f"tradelab:{card_id}:". Older fills require bot.log lookup
    (out-of-scope for this slice; returns only natively-tagged fills).

    Returns list of percent returns, oldest first.
    """
    from .alpaca_adapter import get_alpaca_client  # existing in repo
    if alpaca_client is None:
        alpaca_client = get_alpaca_client()
    # Fetch all filled orders for this account in last 90 days.
    fills = alpaca_client.list_filled_orders(days=90)
    # Filter by client_order_id prefix.
    prefix = f"tradelab:{card_id}:"
    card_fills = [f for f in fills if (f.client_order_id or "").startswith(prefix)]
    # Pair entry+exit fills by signal grouping. Detail in alpaca_adapter.
    paired = pair_entry_exit_fills(card_fills)
    return [round(p.return_pct, 4) for p in paired]
```

**Note:** the function names `get_alpaca_client`, `list_filled_orders`, `pair_entry_exit_fills` may not exist verbatim. Grep `tradelab/src/tradelab/live/` for the actual Alpaca-pull patterns. If `pair_entry_exit_fills` doesn't exist, implement it inline in this module — it's a small grouping function that walks the fills list, matches each `qty<0` (sell) to the immediately-prior `qty>0` (buy), computes `(sell_price - buy_price) / buy_price * 100`. Keep the entry-fills-pairing logic small and tested.

- [ ] **Step 2.7: Add the endpoint in `web/handlers.py`**

In `tradelab/src/tradelab/web/handlers.py`, locate the GET dispatch block (search for `def handle_get` or similar — pre-flight grep step 2.1). Add a new route block alongside the existing `^/tradelab/runs/.../metrics$` route:

```python
    m = re.match(r"^/tradelab/cards/([^/]+)/tracking-error$", path)
    if m:
        from ..live.tracking_error import compute_tracking_error, load_live_returns_for_card
        card_id = m.group(1)
        archive_root = _pine_archive_root()  # existing helper or inline
        backtest_csv = archive_root / card_id / "tv_trades.csv"
        if not backtest_csv.exists():
            return _err(f"no tv_trades.csv for card {card_id}"), 404
        try:
            live_returns = load_live_returns_for_card(card_id)
            result = compute_tracking_error(backtest_csv, live_returns)
            return _ok(result.model_dump()), 200
        except Exception as e:
            return _err(f"tracking-error compute failed: {e}"), 500
```

If `_pine_archive_root` isn't defined, inline: `archive_root = Path(__file__).resolve().parents[3] / "pine_archive"` (verify by grep — adjust `parents[N]` to land at repo root).

- [ ] **Step 2.8: Add endpoint smoke test**

In `tradelab/tests/web/test_handlers.py` (or wherever existing endpoint tests live — grep first), add:

```python
def test_tracking_error_endpoint_returns_insufficient_for_no_live(tmp_path, monkeypatch):
    """If a card has tv_trades but no live fills, status is 'insufficient'."""
    # Set up a fake archive_root with one card.
    archive = tmp_path / "pine_archive" / "alpha-v1"
    archive.mkdir(parents=True)
    (archive / "tv_trades.csv").write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30:00,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    # Monkeypatch _pine_archive_root and the live-returns loader.
    monkeypatch.setattr("tradelab.web.handlers._pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(
        "tradelab.live.tracking_error.load_live_returns_for_card",
        lambda card_id, **kw: [],
    )
    # Call the route handler and assert.
    # Adapt to whatever test fixture style web/test_handlers.py uses.
    ...  # GET /tradelab/cards/alpha-v1/tracking-error → 200, data.status == "insufficient"
```

- [ ] **Step 2.9: Run all tests**

```bash
pytest tradelab/tests/ -x
```
Expected: green. New TE tests pass.

- [ ] **Step 2.10: Manual smoke**

Start dashboard, hit endpoint:

```bash
# Restart launcher if needed
$env:PYTHONUTF8="1"; python launch_dashboard.py
# In another shell:
curl http://127.0.0.1:8877/tradelab/cards/<your-real-card-id>/tracking-error
```
Expected: JSON `{"error": null, "data": {"te": null, "decay_series": null, "ks_p": null, "n_live_trades": N, "n_backtest_trades": M, "status": "insufficient"}}` if you have <30 live fills (likely the case today).

- [ ] **Step 2.11: Commit**

```bash
git add tradelab/src/tradelab/live/tracking_error.py \
        tradelab/tests/live/test_tracking_error.py \
        tradelab/src/tradelab/web/handlers.py
# Add the test file you modified in step 2.8 too if it changed.
git commit -m "feat(live): tracking-error engine + endpoint (S2)

Distributional TE / 11-point Decay sparkline / K-S p-value computed
against frozen pine_archive/<card_id>/tv_trades.csv as backtest baseline.
Live returns loaded via Alpaca client_order_id prefix match.

GET /tradelab/cards/<id>/tracking-error returns
{te, decay_series, ks_p, n_live_trades, n_backtest_trades, status}.

Status='insufficient' when n_live < 30 (LITE honest-sparse-data rule).
"
```

---

## Task 3: Live card UI — TE bar / Decay sparkline / K-S badge / REVIEW NEEDED (S3)

**Files:**
- Modify: `C:\TradingScripts\command_center.html` — extend `renderLiveCard()` at line ~3946; add new CSS

- [ ] **Step 3.1: Pre-flight grep**

```bash
grep -n "renderLiveCard\|research-cards-grid\|researchLiveCards" "/c/TradingScripts/command_center.html"
grep -n "verdict-pill\|review-tag\|te-bar\|sparkline\|ks-tag" "/c/TradingScripts/command_center.html"
```
Expected: `renderLiveCard(liveId, tradelabName, runs)` defined ~line 3946; container `#researchLiveCards`; existing CSS classes for verdict pills (e.g. `verdict-pill verdict-robust`); CSS classes for `te-bar`, `sparkline`, `ks-tag`, `review-tag` likely DO NOT EXIST yet (this task adds them).

- [ ] **Step 3.2: Add CSS for new health-row elements**

Locate the existing `.research-card` CSS block in `command_center.html`. After it, add:

```css
/* === LITE-on-Flow-A: TE / Decay / K-S health rows on Live cards === */
.research-card .health-row { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; padding: 6px 0; border-top: 1px dashed var(--border-2, #353b4d); font-size: 11px; }
.research-card .health-row .lbl { color: var(--text-faint, #6b7280); text-transform: uppercase; font-size: 9px; letter-spacing: 0.05em; }
.te-bar { display: inline-flex; gap: 2px; }
.te-bar span { width: 8px; height: 12px; background: var(--border-2, #353b4d); border-radius: 1px; }
.te-bar.green span:nth-child(-n+4) { background: var(--accent, #22c55e); }
.te-bar.green-full span { background: var(--accent, #22c55e); }
.te-bar.amber span:nth-child(-n+3) { background: var(--amber, #f59e0b); }
.te-bar.red span:nth-child(-n+1) { background: var(--red, #ef4444); }
.te-bar.empty span { background: var(--border-2, #353b4d); }
.sparkline { height: 18px; width: 100%; }
.sparkline path { fill: none; stroke-width: 1.5; }
.sparkline .stable { stroke: var(--text-dim, #9aa0ac); }
.sparkline .climbing { stroke: var(--accent, #22c55e); }
.sparkline .declining { stroke: var(--amber, #f59e0b); }
.sparkline .dying { stroke: var(--red, #ef4444); }
.sparkline .sparse { stroke: var(--text-faint, #6b7280); stroke-dasharray: 2,2; }
.ks-tag { font-size: 10px; font-weight: 600; padding: 1px 5px; border-radius: 3px; font-variant-numeric: tabular-nums; }
.ks-tag.ok { background: rgba(34, 197, 94, 0.15); color: var(--accent, #22c55e); }
.ks-tag.warn { background: rgba(245, 158, 11, 0.15); color: var(--amber, #f59e0b); }
.ks-tag.fail { background: rgba(239, 68, 68, 0.15); color: var(--red, #ef4444); }
.ks-tag.sparse { background: rgba(107, 114, 128, 0.15); color: var(--text-faint, #6b7280); }
.review-tag { display: inline-block; padding: 2px 6px; font-size: 9px; font-weight: 600; background: rgba(245, 158, 11, 0.15); color: var(--amber, #f59e0b); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 3px; letter-spacing: 0.05em; margin-left: 6px; }
.review-tag.urgent { background: rgba(239, 68, 68, 0.15); color: var(--red, #ef4444); border-color: rgba(239, 68, 68, 0.4); }
.research-card.review-amber { border-color: rgba(245, 158, 11, 0.4); }
.research-card.review-red { border-color: rgba(239, 68, 68, 0.4); }
```

If CSS variables `--border-2`, `--accent`, etc. aren't defined in command_center.html (grep `--accent` to check), the inline fallbacks make the styles work anyway. Use the actual variable names if they exist.

- [ ] **Step 3.3: Extend `renderLiveCard()`**

Locate `renderLiveCard(liveId, tradelabName, runs)` at line ~3946. After the existing card-rendering body (where it sets `.research-card-stat` etc.), append a fetch + render of the tracking-error data.

The change has two parts: (a) when assembling each card's HTML, include placeholder health rows; (b) after rendering, fire `GET /tradelab/cards/<card_id>/tracking-error` per card and patch the placeholder rows.

Add this block at the end of `renderLiveCard()` (or just before the function returns/finalizes its DOM write):

```javascript
  // === LITE-on-Flow-A: TE / Decay / K-S health rows ===
  // Append placeholder health rows that get populated by an async fetch.
  card.insertAdjacentHTML("beforeend", `
    <div class="health-row" data-te-row>
      <span class="lbl">TE</span>
      <span class="te-bar empty"><span></span><span></span><span></span><span></span><span></span></span>
      <span style="color: var(--text-faint); font-size: 10px;">…</span>
    </div>
    <div class="health-row" data-decay-row style="border-top: none;">
      <span class="lbl">DECAY</span>
      <svg class="sparkline" viewBox="0 0 100 18" preserveAspectRatio="none"><path class="sparse" d="M0,9 L100,9"/></svg>
      <span style="color: var(--text-faint); font-size: 10px;">…</span>
    </div>
    <div class="health-row" data-ks-row style="border-top: none;">
      <span class="lbl">K-S</span>
      <span></span>
      <span class="ks-tag sparse">…</span>
    </div>
  `);
  // Fire the fetch.
  fetch(`/tradelab/cards/${encodeURIComponent(liveId)}/tracking-error`)
    .then(r => r.json())
    .then(env => {
      if (env.error) { return; }
      const d = env.data;
      patchTrackingError(card, d);
    })
    .catch(() => { /* leave placeholders */ });
```

Then add a sibling helper function (place near `renderLiveCard` in the same `<script>` block):

```javascript
function patchTrackingError(card, d) {
  // Status: "insufficient" → leave sparse placeholders with n=N badges.
  const teRow = card.querySelector("[data-te-row]");
  const decayRow = card.querySelector("[data-decay-row]");
  const ksRow = card.querySelector("[data-ks-row]");
  if (d.status === "insufficient") {
    if (teRow) teRow.querySelector("span:last-child").textContent = `n=${d.n_live_trades}`;
    if (decayRow) decayRow.querySelector("span:last-child").textContent = `n=${d.n_live_trades}`;
    if (ksRow) {
      const tag = ksRow.querySelector(".ks-tag");
      tag.textContent = `n=${d.n_live_trades} insufficient`;
    }
    return;
  }
  // status === "ok"
  if (teRow && d.te !== null) {
    const bar = teRow.querySelector(".te-bar");
    bar.classList.remove("empty", "green", "green-full", "amber", "red");
    if (d.te >= 0.95) bar.classList.add("green-full");
    else if (d.te >= 0.80) bar.classList.add("green");
    else if (d.te >= 0.60) bar.classList.add("amber");
    else bar.classList.add("red");
    teRow.querySelector("span:last-child").textContent = d.te.toFixed(2);
    teRow.querySelector("span:last-child").style.color =
      d.te >= 0.80 ? "var(--accent)" : d.te >= 0.60 ? "var(--amber)" : "var(--red)";
  }
  if (decayRow && d.decay_series && d.decay_series.length) {
    const path = decayRow.querySelector(".sparkline path");
    const series = d.decay_series;
    const min = Math.min(...series);
    const max = Math.max(...series);
    const range = (max - min) || 1;
    const dPath = series.map((y, i) => {
      const x = (i / (series.length - 1)) * 100;
      const yPx = 16 - ((y - min) / range) * 14;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${yPx.toFixed(1)}`;
    }).join(" ");
    path.setAttribute("d", dPath);
    // Pick stroke class from first-vs-last slope.
    const slope = series[series.length - 1] - series[0];
    path.classList.remove("sparse", "stable", "climbing", "declining", "dying");
    if (Math.abs(slope) < 0.05) path.classList.add("stable");
    else if (slope > 0) path.classList.add("climbing");
    else if (slope > -0.3) path.classList.add("declining");
    else path.classList.add("dying");
  }
  if (ksRow && d.ks_p !== null) {
    const tag = ksRow.querySelector(".ks-tag");
    tag.classList.remove("sparse", "ok", "warn", "fail");
    let cls = "ok", text = `p=${d.ks_p.toFixed(2)}`;
    if (d.ks_p < 0.01) { cls = "fail"; text += " ✗"; }
    else if (d.ks_p < 0.05) { cls = "warn"; text += " ⚠"; }
    tag.classList.add(cls);
    tag.textContent = text;
    // Surface REVIEW NEEDED / REVIEW URGENT into the card header.
    if (cls === "warn" || cls === "fail") {
      const verdictRow = card.querySelector(".research-card-verdict, .verdict-row");
      if (verdictRow && !verdictRow.querySelector(".review-tag")) {
        const tag2 = document.createElement("span");
        tag2.className = cls === "fail" ? "review-tag urgent" : "review-tag";
        tag2.textContent = cls === "fail" ? "REVIEW URGENT" : "REVIEW NEEDED";
        verdictRow.appendChild(tag2);
        card.classList.add(cls === "fail" ? "review-red" : "review-amber");
      }
    }
  }
}
```

**Verify before writing**: does the existing `renderLiveCard` use `card` as the DOM element variable? Grep first. Adjust the variable name to match.

- [ ] **Step 3.4: Reload dashboard and smoke-test**

```bash
# In a browser, open http://127.0.0.1:8877/dashboard.html (or whatever the dashboard URL is per launch_dashboard.py)
# Click Research tab. Each Live card should now show TE / DECAY / K-S health rows.
# For your dogfood card with <30 live trades, all three rows show "n=N insufficient".
# Verify no JS console errors.
```
Expected: rows render; no errors; "insufficient" badges on the dogfood card.

- [ ] **Step 3.5: Test artificially-high n live for one card**

Temporarily monkey-patch the endpoint to return n=30 fake live returns:

```bash
# Pick a card_id; in a Python REPL, simulate the endpoint return value
# OR (preferred) patch test_tracking_error.py to add a "with synthetic 30 live trades, K-S below 0.01 surfaces REVIEW URGENT in the UI mockup".
# Manual approach: use the spec's mockup file as visual reference;
# verify the live UI matches when te=0.43, ks_p=0.001, decay slope steep down.
```

This is a manual reasoning step, not automated. Skip if confident from step 3.4.

- [ ] **Step 3.6: Commit (parent repo, partial-staging)**

```bash
cd /c/TradingScripts
git status command_center.html  # confirm hunks
git add -p command_center.html  # interactively stage ONLY the LITE-S3 hunks
git commit -m "feat(dashboard): LITE Live-card TE/Decay/K-S health rows (S3)

Extends renderLiveCard() to fetch /tradelab/cards/<id>/tracking-error
and render TE bar / Decay sparkline / K-S badge per LITE mockup.

REVIEW NEEDED tag (amber, p<0.05) and REVIEW URGENT tag (red, p<0.01)
appear in the verdict row when K-S divergence is significant.
No auto-disable (LITE rule); manual Disable button stays available.

Pairs with backend tracking-error endpoint (S2).
"
```
Then return to tradelab repo dir.

---

## Task 4: Hold-out OOS gate — verdict signal #10 + Pipeline column + Score modal panel (S4)

**Files:**
- Modify: `tradelab/src/tradelab/results.py:121` (add `holdout_result` field to `WalkForwardResult`)
- Modify: `tradelab/src/tradelab/engines/walkforward.py` (compute hold-out backtest alongside WF folds)
- Modify: `tradelab/src/tradelab/robustness/verdict.py:102-317` (add `hold_out_oos` signal in `compute_verdict`)
- Modify: `tradelab.yaml` thresholds section (add `hold_out_robust_pf`, `hold_out_fragile_pf`, `hold_out_window_months`)
- Create: `tradelab/tests/robustness/test_verdict_holdout.py`
- Modify: `C:\TradingScripts\command_center.html` (add Hold-out column to research pipeline; add Hold-out gate panel to Score modal)

- [ ] **Step 4.1: Pre-flight grep**

```bash
grep -n "class WalkForwardResult\|aggregate_oos\|wfe_ratio" tradelab/src/tradelab/results.py
grep -n "def compute_verdict\|VerdictSignal" tradelab/src/tradelab/robustness/verdict.py
grep -n "robustness:\|thresholds:" tradelab.yaml
grep -n "researchPipelineBody\|researchLoadPipeline\|score-modal\|scoreModal" "/c/TradingScripts/command_center.html"
```

- [ ] **Step 4.2: Extend `WalkForwardResult` with `holdout_result`**

In `tradelab/src/tradelab/results.py:121-129`, add new field:

```python
class WalkForwardResult(BaseModel):
    strategy: str
    n_windows: int
    windows: list[WalkForwardWindow]
    aggregate_oos: BacktestMetrics
    wfe_ratio: float
    oos_trades: list[Trade]
    oos_equity_curve: list[dict]
    generated_at: str
    holdout_result: Optional["BacktestMetrics"] = None  # S4: hold-out OOS gate
    holdout_window_months: Optional[int] = None
```

If `BacktestMetrics` is in scope, no extra import. Otherwise, import it. Keep optional for backwards compat with old runs.

- [ ] **Step 4.3: Add hold-out backtest pass in walkforward**

In `tradelab/src/tradelab/engines/walkforward.py`, locate the function that orchestrates the WF run (`run_walkforward` or similar — grep `def run_walkforward`). After the WF folds complete and before the WalkForwardResult is built, add:

```python
    # S4: hold-out OOS pass on a trailing untouched window (separate from WF folds)
    holdout_months = config.robustness.hold_out_window_months  # default 6
    if holdout_months and holdout_months > 0:
        holdout_start, holdout_end = _slice_holdout_window(data, holdout_months)
        # Run a simple backtest on this window — same params used in WF aggregate_oos.
        holdout_metrics = run_backtest(data, params=best_params, start=holdout_start, end=holdout_end)
    else:
        holdout_metrics = None
```

The exact `run_backtest` signature must match what's in scope — grep `def run_backtest` in the engines folder. If `_slice_holdout_window` doesn't exist, implement it inline:

```python
def _slice_holdout_window(data, months: int):
    """Return (start, end) for the last `months` of data — the held-out tail."""
    end = data.index[-1]
    start = end - pd.DateOffset(months=months)
    return start, end
```

Pass `holdout_metrics` to the result constructor:

```python
    return WalkForwardResult(
        strategy=...,
        ...,
        holdout_result=holdout_metrics,
        holdout_window_months=holdout_months,
    )
```

- [ ] **Step 4.4: Add `hold_out_oos` signal in `compute_verdict`**

In `tradelab/src/tradelab/robustness/verdict.py:102-317`, find the existing signal-append pattern (e.g. `signals.append(VerdictSignal(name="wfe", ...))`). Mirror it:

```python
    # S4: hold-out OOS signal (Generalization category, Critical importance)
    if wf_result.holdout_result is not None:
        ho_pf = wf_result.holdout_result.profit_factor
        if ho_pf is None:
            outcome = "inconclusive"
            reason = "hold-out had no closed losses; PF undefined"
        elif ho_pf >= thresholds["hold_out_robust_pf"]:
            outcome = "robust"
            reason = f"hold-out PF {ho_pf:.2f} on {wf_result.holdout_window_months}mo untouched window"
        elif ho_pf < thresholds["hold_out_fragile_pf"]:
            outcome = "fragile"
            reason = f"hold-out PF {ho_pf:.2f} below fragile threshold {thresholds['hold_out_fragile_pf']}"
        else:
            outcome = "inconclusive"
            reason = f"hold-out PF {ho_pf:.2f} between fragile and robust thresholds"
        signals.append(VerdictSignal(name="hold_out_oos", outcome=outcome, reason=reason))
```

Threshold dict: `thresholds` should be the `_FALLBACK_THRESHOLDS`-merged-with-config dict per existing pattern (lines 88-95 of verdict.py per the verification report). Add the two new keys to `_FALLBACK_THRESHOLDS`:

```python
_FALLBACK_THRESHOLDS = {
    ...,
    "hold_out_robust_pf": 1.50,
    "hold_out_fragile_pf": 1.00,
}
```

- [ ] **Step 4.5: Update `tradelab.yaml`**

Open `C:\TradingScripts\tradelab\tradelab.yaml`. Under `robustness.thresholds:`, add:

```yaml
robustness:
  thresholds:
    # ... existing keys ...
    hold_out_robust_pf: 1.50
    hold_out_fragile_pf: 1.00
  hold_out_window_months: 6  # set to 0 to disable hold-out gate entirely
```

- [ ] **Step 4.6: Write the failing test**

Create `tradelab/tests/robustness/test_verdict_holdout.py`:

```python
"""Test hold_out_oos signal added to verdict.signals."""
from __future__ import annotations
import pytest
from tradelab.robustness.verdict import compute_verdict
# Import any other fixtures verdict.py uses — match existing tests' style.


def _make_wf_result(holdout_pf: float | None, **overrides):
    """Build a minimal WalkForwardResult with given hold-out PF."""
    from tradelab.results import WalkForwardResult, BacktestMetrics
    # ... fill in required fields with sensible defaults ...
    return WalkForwardResult(
        strategy="test",
        n_windows=3,
        windows=[],  # fixture expansion
        aggregate_oos=BacktestMetrics(profit_factor=1.5, ...),
        wfe_ratio=0.7,
        oos_trades=[],
        oos_equity_curve=[],
        generated_at="2026-01-01",
        holdout_result=BacktestMetrics(profit_factor=holdout_pf, ...) if holdout_pf else None,
        holdout_window_months=6,
        **overrides,
    )


def test_holdout_pf_above_threshold_is_robust():
    wf = _make_wf_result(holdout_pf=1.78)
    verdict = compute_verdict(wf, ...)  # match existing call signature
    sigs = {s.name: s for s in verdict.signals}
    assert "hold_out_oos" in sigs
    assert sigs["hold_out_oos"].outcome == "robust"


def test_holdout_pf_below_fragile_marks_fragile():
    wf = _make_wf_result(holdout_pf=0.85)
    verdict = compute_verdict(wf, ...)
    sigs = {s.name: s for s in verdict.signals}
    assert sigs["hold_out_oos"].outcome == "fragile"


def test_holdout_pf_in_between_inconclusive():
    wf = _make_wf_result(holdout_pf=1.20)
    verdict = compute_verdict(wf, ...)
    sigs = {s.name: s for s in verdict.signals}
    assert sigs["hold_out_oos"].outcome == "inconclusive"


def test_no_holdout_skips_signal():
    wf = _make_wf_result(holdout_pf=None)
    verdict = compute_verdict(wf, ...)
    sig_names = {s.name for s in verdict.signals}
    assert "hold_out_oos" not in sig_names
```

The `...` in `_make_wf_result` and `compute_verdict(wf, ...)` are fixture expansions specific to existing test patterns. Grep `tradelab/tests/robustness/` for an existing verdict test, copy its fixture style, fill in placeholders. Match what the function signature actually requires.

- [ ] **Step 4.7: Run tests to verify pass**

```bash
pytest tradelab/tests/robustness/test_verdict_holdout.py -v
pytest tradelab/tests/ -x
```
Expected: hold-out tests pass; no regressions.

- [ ] **Step 4.8: Add Hold-out column to Research Pipeline table**

In `command_center.html`, locate the pipeline table — search for the `<thead>` block of the research-pipeline `<table>` (line ~1097-1117 area; tbody at `#researchPipelineBody`). Add a new `<th>` between `Verdict` and `PF`:

```html
              <th class="research-pipeline-holdout">Hold-out <span class="gate-pill" title="S4: hold-out OOS gate">GATE</span></th>
```

Then in the JS function `researchLoadPipeline()` (line ~4035), where each row is built, insert a corresponding `<td>` cell. The cell renders the hold-out signal's outcome from `robustness_result.json::verdict.signals[name=hold_out_oos]`:

```javascript
        // Find hold_out_oos signal in the run's robustness data
        const sigList = run.robustness_signals || [];
        const ho = sigList.find(s => s.name === "hold_out_oos");
        const holdoutCell = ho
          ? `<td class="research-pipeline-holdout ${ho.outcome === 'robust' ? 'gate-pass' : ho.outcome === 'fragile' ? 'gate-fail' : 'gate-na'}">${ho.outcome === 'robust' ? '✓' : ho.outcome === 'fragile' ? '✗' : '—'} ${extractFirstNumeric(ho.reason)}</td>`
          : `<td class="research-pipeline-holdout gate-na">—</td>`;
```

Add CSS:

```css
.research-pipeline-holdout { font-variant-numeric: tabular-nums; }
.gate-pass { color: var(--accent, #22c55e); }
.gate-fail { color: var(--red, #ef4444); }
.gate-na { color: var(--text-faint, #6b7280); }
```

Whether `extractFirstNumeric` already exists — grep. If not, inline: `((s) => (s.match(/(\d+\.?\d*)/) || [''])[0])(ho.reason)`.

If pipeline rows already include robustness signals data, this works as-is. If not, the `researchLoadPipeline` fetch needs to be extended to include signal data — grep first.

- [ ] **Step 4.9: Add Hold-out gate panel to Score modal**

Locate the score modal markup in `command_center.html` (search `score-modal` or `scoreModal` per pre-flight grep). At the top of the modal body, BEFORE the existing diagnostics/9-signals section, add a placeholder block:

```html
          <div id="scoreHoldoutGate" class="holdout-gate" style="display:none;"></div>
```

Add CSS:

```css
.holdout-gate { margin-bottom: 20px; padding: 14px 16px; border-radius: 8px; border: 2px solid; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.holdout-gate.pass { background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.4); color: var(--accent, #22c55e); }
.holdout-gate.fail { background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.4); color: var(--red, #ef4444); }
.holdout-gate.inconclusive { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.4); color: var(--amber, #f59e0b); }
.holdout-gate .left { display: flex; align-items: center; gap: 12px; }
.holdout-gate .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim, #9aa0ac); }
.holdout-gate .verdict-text { font-size: 16px; font-weight: 600; }
.holdout-gate .detail { text-align: right; font-size: 12px; color: var(--text-dim, #9aa0ac); font-variant-numeric: tabular-nums; }
.gate-pill { display: inline-block; padding: 1px 6px; font-size: 9px; font-weight: 600; letter-spacing: 0.05em; background: rgba(6, 182, 212, 0.15); color: var(--gate, #06b6d4); border: 1px solid rgba(6, 182, 212, 0.4); border-radius: 4px; vertical-align: middle; margin-left: 6px; }
```

In the JS function that opens/populates the score modal (grep `scoreModal\|openScoreModal\|displayVerdict`), after fetching the verdict, render the panel:

```javascript
function renderHoldoutGate(verdict) {
  const panel = document.getElementById("scoreHoldoutGate");
  if (!panel) return;
  const ho = (verdict.signals || []).find(s => s.name === "hold_out_oos");
  if (!ho) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "flex";
  panel.classList.remove("pass", "fail", "inconclusive");
  panel.classList.add(ho.outcome === "robust" ? "pass" : ho.outcome === "fragile" ? "fail" : "inconclusive");
  panel.innerHTML = `
    <div class="left">
      <div>
        <div class="label">Hold-out OOS Gate <span class="gate-pill">GATE</span></div>
        <div class="verdict-text">${ho.outcome === "robust" ? "PASS" : ho.outcome === "fragile" ? "FAIL" : "INCONCLUSIVE"}</div>
      </div>
    </div>
    <div class="detail">${ho.reason}</div>
  `;
}
```

Call `renderHoldoutGate(verdict)` from wherever the modal is populated (alongside the existing diagnostics rendering).

- [ ] **Step 4.10: Smoke**

```bash
# Restart any running tradelab process to pick up tradelab.yaml changes
# Re-run a verdict for an existing card:
python -m tradelab run <strategy> --robustness --report
# Confirm robustness_result.json now contains a hold_out_oos signal
cat tradelab/reports/<latest>/robustness_result.json | python -c "import json,sys; d=json.load(sys.stdin); print([s for s in d['verdict']['signals'] if s['name']=='hold_out_oos'])"
# Reload dashboard, open Score modal for a candidate. Hold-out gate panel renders at top.
# Open Research Pipeline. Hold-out column renders.
```

- [ ] **Step 4.11: Commit (two repos, partial-staging)**

In tradelab repo:

```bash
git add tradelab/src/tradelab/results.py \
        tradelab/src/tradelab/engines/walkforward.py \
        tradelab/src/tradelab/robustness/verdict.py \
        tradelab/tests/robustness/test_verdict_holdout.py \
        tradelab.yaml
git commit -m "feat(robustness): hold-out OOS gate as verdict signal #10 (S4)

Extends WalkForwardResult with holdout_result; engines/walkforward
runs a backtest on a trailing untouched window (default 6 months).
verdict.compute_verdict appends hold_out_oos signal: PF >= 1.50 robust,
PF < 1.00 fragile. Configurable in tradelab.yaml.
"
```

In parent repo:

```bash
cd /c/TradingScripts
git add -p command_center.html
git commit -m "feat(dashboard): Hold-out gate column + Score modal panel (S4)"
```

---

## Task 5: Correlation engine + endpoints (S5)

**Files:**
- Create: `tradelab/src/tradelab/robustness/correlation.py`
- Create: `tradelab/tests/robustness/test_correlation.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `GET /tradelab/correlation/<run_id>` and `GET /tradelab/portfolio-health`)

- [ ] **Step 5.1: Pre-flight grep**

```bash
grep -n "import numpy\|import pandas" tradelab/src/tradelab/robustness/*.py
grep -n "cards.json\|load_cards" tradelab/src/tradelab/live/cards.py
ls pine_archive/*/returns.csv 2>/dev/null | head -5
```
Expected: numpy and pandas already in deps (likely via robustness modules); cards loader exists; at least 1 returns.csv exists post-Task-1 backfill.

- [ ] **Step 5.2: Write the failing test**

Create `tradelab/tests/robustness/test_correlation.py`:

```python
"""Test correlation engine: return ρ, DD ρ, entry-time overlap."""
from __future__ import annotations
from pathlib import Path
import csv
import pytest
from tradelab.robustness.correlation import (
    compute_pairwise_correlations,
    PortfolioHealthResult,
)


def _write_returns(tmp_path: Path, card_id: str, rows: list[tuple[str, float]]) -> Path:
    """Write pine_archive/<card_id>/returns.csv at tmp_path/pine_archive."""
    archive = tmp_path / "pine_archive" / card_id
    archive.mkdir(parents=True, exist_ok=True)
    p = archive / "returns.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "return_pct"])
        w.writeheader()
        for d, r in rows:
            w.writerow({"date": d, "return_pct": f"{r:.2f}"})
    return p


def test_two_uncorrelated_cards(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", (-1.0) ** i * 1.5) for i in range(1, 32)])
    _write_returns(tmp_path, "beta-v1", [(f"2026-01-{i:02d}", 0.5) for i in range(1, 32)])
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "beta-v1"],
    )
    assert result.max_return_rho < 0.5
    assert len(result.pairs) == 1
    assert result.pairs[0].a in ("alpha-v1", "beta-v1")
    assert result.pairs[0].b != result.pairs[0].a


def test_two_perfectly_correlated_cards(tmp_path: Path) -> None:
    same = [(f"2026-01-{i:02d}", float(i % 5 - 2)) for i in range(1, 32)]
    _write_returns(tmp_path, "alpha-v1", same)
    _write_returns(tmp_path, "beta-v1", same)
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "beta-v1"],
    )
    assert result.max_return_rho == pytest.approx(1.0, abs=0.01)


def test_single_card_returns_empty_pairs(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)])
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1"],
    )
    assert result.pairs == []
    assert result.max_return_rho == 0.0


def test_missing_card_skipped(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)])
    # 'missing-v1' has no returns.csv — should be skipped without error.
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "missing-v1"],
    )
    assert result.pairs == []
```

- [ ] **Step 5.3: Run tests (expect failure)**

```bash
pytest tradelab/tests/robustness/test_correlation.py -v
```
Expected: ImportError on `tradelab.robustness.correlation`.

- [ ] **Step 5.4: Implement `tradelab/src/tradelab/robustness/correlation.py`**

```python
"""Pairwise correlation engine over per-card returns.csv series.

Computes:
- return_rho: Pearson correlation of aligned daily returns
- dd_rho: correlation of drawdown-time series (1 if both in DD that day, 0 otherwise)
- entry_overlap: % of trade-entry timestamps that fall within shared 30-min windows

Used by Portfolio Health panel + Score modal Portfolio fit gate (S6).
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import csv
import numpy as np
from pydantic import BaseModel


class PairResult(BaseModel):
    a: str
    b: str
    return_rho: float
    dd_rho: float
    entry_overlap: float
    n_aligned: int


class PortfolioHealthResult(BaseModel):
    pairs: list[PairResult]
    max_return_rho: float
    max_dd_rho: float
    max_entry_overlap: float


def _load_returns(archive_root: Path, card_id: str) -> dict[str, float]:
    p = archive_root / card_id / "returns.csv"
    if not p.exists():
        return {}
    out: dict[str, float] = {}
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out[row["date"]] = float(row["return_pct"])
    return out


def _drawdown_mask(returns: list[float]) -> list[int]:
    """1 if cumulative equity is below running max on this day, else 0."""
    eq = 100.0
    peak = 100.0
    out: list[int] = []
    for r in returns:
        eq *= (1 + r / 100)
        peak = max(peak, eq)
        out.append(1 if eq < peak else 0)
    return out


def compute_pair(
    archive_root: Path, card_a: str, card_b: str
) -> Optional[PairResult]:
    ra = _load_returns(archive_root, card_a)
    rb = _load_returns(archive_root, card_b)
    common = sorted(set(ra.keys()) & set(rb.keys()))
    if len(common) < 5:
        return None
    arr_a = np.array([ra[d] for d in common])
    arr_b = np.array([rb[d] for d in common])
    if arr_a.std() == 0 or arr_b.std() == 0:
        return_rho = 0.0
    else:
        return_rho = round(float(np.corrcoef(arr_a, arr_b)[0, 1]), 3)
    # DD correlation
    dd_a = _drawdown_mask(arr_a.tolist())
    dd_b = _drawdown_mask(arr_b.tolist())
    if sum(dd_a) == 0 or sum(dd_b) == 0:
        dd_rho = 0.0
    else:
        a_arr, b_arr = np.array(dd_a), np.array(dd_b)
        if a_arr.std() == 0 or b_arr.std() == 0:
            dd_rho = 0.0
        else:
            dd_rho = round(float(np.corrcoef(a_arr, b_arr)[0, 1]), 3)
    # Entry overlap requires intra-day timestamps; absent here, default 0.
    # Future: extend returns.csv to include trade-entry HH:MM and compute overlap.
    entry_overlap = 0.0
    return PairResult(
        a=card_a, b=card_b,
        return_rho=return_rho, dd_rho=dd_rho,
        entry_overlap=entry_overlap, n_aligned=len(common),
    )


def compute_pairwise_correlations(
    archive_root: Path,
    card_ids: list[str],
) -> PortfolioHealthResult:
    pairs: list[PairResult] = []
    for i, a in enumerate(card_ids):
        for b in card_ids[i + 1:]:
            p = compute_pair(archive_root, a, b)
            if p is not None:
                pairs.append(p)
    max_return = max((p.return_rho for p in pairs), default=0.0)
    max_dd = max((p.dd_rho for p in pairs), default=0.0)
    max_entry = max((p.entry_overlap for p in pairs), default=0.0)
    return PortfolioHealthResult(
        pairs=pairs,
        max_return_rho=round(max_return, 3),
        max_dd_rho=round(max_dd, 3),
        max_entry_overlap=round(max_entry, 3),
    )


def compute_candidate_vs_cohort(
    archive_root: Path,
    candidate_returns: list[tuple[str, float]],
    cohort_card_ids: list[str],
) -> PortfolioHealthResult:
    """For Score modal: candidate (not yet accepted, no returns.csv) vs each
    enabled live card. candidate_returns is [(date, return_pct)] derived from
    the candidate's tv_trades.csv at scoring time.
    """
    cand_dict = dict(candidate_returns)
    pairs: list[PairResult] = []
    for cohort_id in cohort_card_ids:
        # Inline-compute pair against cand_dict as a synthetic 'candidate'
        # without writing it to disk.
        rb = _load_returns(archive_root, cohort_id)
        common = sorted(set(cand_dict.keys()) & set(rb.keys()))
        if len(common) < 5:
            continue
        arr_a = np.array([cand_dict[d] for d in common])
        arr_b = np.array([rb[d] for d in common])
        if arr_a.std() == 0 or arr_b.std() == 0:
            return_rho = 0.0
        else:
            return_rho = round(float(np.corrcoef(arr_a, arr_b)[0, 1]), 3)
        dd_a = _drawdown_mask(arr_a.tolist())
        dd_b = _drawdown_mask(arr_b.tolist())
        if sum(dd_a) == 0 or sum(dd_b) == 0 or np.array(dd_a).std() == 0 or np.array(dd_b).std() == 0:
            dd_rho = 0.0
        else:
            dd_rho = round(float(np.corrcoef(np.array(dd_a), np.array(dd_b))[0, 1]), 3)
        pairs.append(PairResult(
            a="candidate", b=cohort_id,
            return_rho=return_rho, dd_rho=dd_rho,
            entry_overlap=0.0, n_aligned=len(common),
        ))
    return PortfolioHealthResult(
        pairs=pairs,
        max_return_rho=max((p.return_rho for p in pairs), default=0.0),
        max_dd_rho=max((p.dd_rho for p in pairs), default=0.0),
        max_entry_overlap=0.0,
    )
```

**Note on entry-overlap:** the spec proposes entry-time overlap, but our returns.csv doesn't carry intra-day entry timestamps (only daily aggregates). For S5/S6 we hardcode `entry_overlap = 0.0` and the UI shows it as "—". Adding real entry-overlap would require extending returns.csv schema; out of scope for this slice. Spec section 8 risk #2 covers this.

- [ ] **Step 5.5: Run unit tests**

```bash
pytest tradelab/tests/robustness/test_correlation.py -v
```
Expected: 4 passed.

- [ ] **Step 5.6: Add endpoints in `web/handlers.py`**

```python
    if path == "/tradelab/portfolio-health":
        from ..robustness.correlation import compute_pairwise_correlations
        from ..live.cards import load_cards
        archive_root = _pine_archive_root()
        cards = load_cards()  # match existing signature
        enabled = [c["card_id"] for c in cards if c.get("status") == "enabled"]
        result = compute_pairwise_correlations(archive_root, enabled)
        return _ok(result.model_dump()), 200

    m = re.match(r"^/tradelab/correlation/([^/]+)$", path)
    if m:
        from ..robustness.correlation import compute_candidate_vs_cohort
        from ..live.cards import load_cards
        from ..io.returns import derive_daily_returns
        run_id = m.group(1)
        # Look up the run's tv_trades.csv from audit DB (existing helper).
        run_folder = audit_reader.get_run_folder(run_id, db_path=_db_path())
        if run_folder is None:
            return _err("run not found"), 404
        tv_csv = run_folder / "tv_trades.csv"
        if not tv_csv.exists():
            return _err("run has no tv_trades.csv"), 404
        candidate_returns_rows = derive_daily_returns(tv_csv)
        candidate_pairs = [(r["date"], r["return_pct"]) for r in candidate_returns_rows]
        archive_root = _pine_archive_root()
        cards = load_cards()
        enabled = [c["card_id"] for c in cards if c.get("status") == "enabled"]
        result = compute_candidate_vs_cohort(archive_root, candidate_pairs, enabled)
        return _ok(result.model_dump()), 200
```

- [ ] **Step 5.7: Smoke**

```bash
curl http://127.0.0.1:8877/tradelab/portfolio-health
# Expected: {"error":null,"data":{"pairs":[...],"max_return_rho":N,...}}
curl http://127.0.0.1:8877/tradelab/correlation/<some_run_id>
```

- [ ] **Step 5.8: Commit**

```bash
git add tradelab/src/tradelab/robustness/correlation.py \
        tradelab/tests/robustness/test_correlation.py \
        tradelab/src/tradelab/web/handlers.py
git commit -m "feat(robustness): pairwise correlation engine + endpoints (S5)

Computes return_rho + dd_rho + entry_overlap (placeholder) over
pine_archive/<card_id>/returns.csv pairs. Two endpoints:
- GET /tradelab/portfolio-health: across all enabled cards
- GET /tradelab/correlation/<run_id>: candidate vs cohort for Score modal

entry_overlap returns 0.0 for now (requires intra-day timestamps in
returns.csv schema; extension deferred).
"
```

---

## Task 6: Score modal Portfolio fit gate + Pipeline Corr column + Relative context (S6 + S7 bundled, plus Relative context)

**Files:**
- Modify: `C:\TradingScripts\command_center.html` — Score modal portfolio-fit panel + Accept-button gate; Pipeline Corr column; Score modal Relative context section
- Modify: `tradelab/src/tradelab/web/handlers.py` — add `GET /tradelab/relative-context/<run_id>` endpoint (lightweight aggregator)

- [ ] **Step 6.1: Pre-flight grep**

```bash
grep -n "scoreModal\|score-modal\|openScoreModal\|displayVerdict\|acceptCard" "/c/TradingScripts/command_center.html"
grep -n "OVERRIDE\|FRAGILE.*confirm\|confirm.*FRAGILE" "/c/TradingScripts/command_center.html"
grep -n "load_cards\|read_cards" tradelab/src/tradelab/live/cards.py | head
```
Expected: identify the Accept-button click handler and the existing FRAGILE confirm prompt (we mirror it for the OVERRIDE flow).

- [ ] **Step 6.2: Add Portfolio fit panel to Score modal markup**

After the Hold-out gate panel (added in Task 4), add:

```html
          <div id="scorePortfolioFit" class="portfolio-fit" style="display:none;"></div>
```

CSS:

```css
.portfolio-fit { margin-bottom: 16px; padding: 12px 14px; background: var(--panel-2, #1c2030); border: 1px solid var(--border, #2a2f3e); border-radius: 6px; }
.portfolio-fit h3 { margin: 0 0 6px; font-size: 13px; color: var(--text-dim, #9aa0ac); text-transform: uppercase; letter-spacing: 0.04em; }
.portfolio-fit .legend-row { display: flex; gap: 16px; font-size: 10px; color: var(--text-faint, #6b7280); padding-bottom: 6px; border-bottom: 1px dashed var(--border-2, #353b4d); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.04em; }
.portfolio-fit .fit-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 12px; padding: 4px 0; font-size: 12px; align-items: center; }
.portfolio-fit .fit-row .name { color: var(--text-dim, #9aa0ac); }
.portfolio-fit .fit-row .val { font-variant-numeric: tabular-nums; font-weight: 600; }
.portfolio-fit .gate-fail { color: var(--red, #ef4444); font-weight: 600; }
.portfolio-fit .gate-pass { color: var(--accent, #22c55e); font-weight: 600; }
```

- [ ] **Step 6.3: Add JS to populate panel + gate Accept button**

```javascript
async function renderPortfolioFit(scoringRunId) {
  const panel = document.getElementById("scorePortfolioFit");
  if (!panel) return { gate: "pass", max_rho: 0 };
  try {
    const r = await fetch(`/tradelab/correlation/${encodeURIComponent(scoringRunId)}`);
    const env = await r.json();
    if (env.error) {
      panel.style.display = "none";
      return { gate: "pass", max_rho: 0 };  // fail open
    }
    const d = env.data;
    if (!d.pairs.length) {
      panel.style.display = "block";
      panel.innerHTML = `<h3>Portfolio fit <span class="gate-pill">GATE</span></h3>
                         <p style="font-size: 11px; color: var(--text-dim);">No enabled live cards to compare against. Gate passes by default.</p>`;
      return { gate: "pass", max_rho: 0 };
    }
    const max_rho = d.max_return_rho;
    const gate = max_rho > 0.70 ? "fail" : max_rho > 0.50 ? "warn" : "pass";
    const rows = d.pairs.map(p => {
      const cls = p.return_rho > 0.70 ? "gate-fail" : p.return_rho > 0.50 ? "gate-warn" : "gate-pass";
      return `<div class="fit-row">
                <span class="name">${p.b}</span>
                <span class="val ${cls}" style="width:60px;text-align:right;">${p.return_rho.toFixed(2)}</span>
                <span class="val" style="width:60px;text-align:right;">${p.dd_rho.toFixed(2)}</span>
                <span class="val" style="width:60px;text-align:right;">—</span>
              </div>`;
    }).join("");
    panel.style.display = "block";
    panel.innerHTML = `
      <h3>Portfolio fit <span class="gate-pill">GATE</span></h3>
      <div class="legend-row">
        <span style="flex:1;">Live card</span>
        <span style="width:60px;text-align:right;">Return ρ</span>
        <span style="width:60px;text-align:right;">DD ρ</span>
        <span style="width:60px;text-align:right;">Entry overlap</span>
      </div>
      ${rows}
      <div style="font-size: 11px; color: var(--text-dim); margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border-2);">
        Max return ρ: <strong class="${gate === 'fail' ? 'gate-fail' : gate === 'warn' ? 'gate-warn' : 'gate-pass'}">${max_rho.toFixed(2)}</strong>
        ${gate === "fail" ? " — <strong class='gate-fail'>BLOCKED at threshold 0.70</strong>" : gate === "warn" ? " — high but accepted" : " — pass"}
      </div>
    `;
    return { gate, max_rho };
  } catch (e) {
    panel.style.display = "none";
    return { gate: "pass", max_rho: 0 };  // fail open on network error
  }
}
```

Then locate the existing Accept-button click handler. Wrap it so it runs the gate first:

```javascript
// Existing: acceptBtn.onclick = async () => { ... runs accept_scored ... };
// Wrap:
async function runAcceptWithPortfolioGate(scoringRunId) {
  const { gate, max_rho } = await renderPortfolioFit(scoringRunId);
  if (gate === "fail") {
    const typed = prompt(`Portfolio fit BLOCKED — max return ρ = ${max_rho.toFixed(2)} > threshold 0.70.\nThis candidate is highly correlated with an enabled live card. Type OVERRIDE (uppercase) to proceed anyway.`);
    if (typed !== "OVERRIDE") {
      return false;  // do not call accept
    }
  }
  return true;  // safe to call accept
}
```

Hook this into the existing Accept handler — find where it does the actual fetch to `/tradelab/accept`. Wrap it: `if (!await runAcceptWithPortfolioGate(scoringRunId)) return;` immediately before the existing accept fetch.

Also call `renderPortfolioFit(scoringRunId)` whenever the score modal opens (so the panel is visible even before clicking Accept).

- [ ] **Step 6.4: Add Corr column to Research Pipeline table**

In the `<thead>` of the pipeline table, add (after the DD column):

```html
              <th class="research-pipeline-corr">Corr</th>
```

In `researchLoadPipeline()`, for each row, also call `/tradelab/correlation/<run_id>` (parallel-fetch the run's max_return_rho) and inject:

```javascript
        // Lightweight: just the max_rho, not the full pair detail
        const corrPromise = fetch(`/tradelab/correlation/${encodeURIComponent(run.run_id)}`)
          .then(r => r.json())
          .then(env => env.error ? null : env.data.max_return_rho)
          .catch(() => null);
        // ... in row build, after PF/WR/DD cells:
        // <td class="research-pipeline-corr" data-run-id="${run.run_id}">…</td>
```

Then after all rows render, fire the parallel fetches and patch in:

```javascript
        // After pipeline render, populate Corr cells.
        document.querySelectorAll('.research-pipeline-corr[data-run-id]').forEach(async cell => {
          const runId = cell.dataset.runId;
          try {
            const env = await (await fetch(`/tradelab/correlation/${encodeURIComponent(runId)}`)).json();
            if (env.error || !env.data || !env.data.pairs.length) {
              cell.textContent = "—";
              return;
            }
            const max_rho = env.data.max_return_rho;
            cell.textContent = max_rho.toFixed(2);
            cell.classList.add(max_rho > 0.70 ? "gate-fail" : max_rho > 0.50 ? "gate-warn" : "gate-pass");
          } catch (e) {
            cell.textContent = "—";
          }
        });
```

CSS:

```css
.research-pipeline-corr { font-variant-numeric: tabular-nums; text-align: right; }
.gate-warn { color: var(--amber, #f59e0b); font-weight: 600; }
```

- [ ] **Step 6.5: Add Relative context endpoint and panel**

Backend (`web/handlers.py`):

```python
    m = re.match(r"^/tradelab/relative-context/([^/]+)$", path)
    if m:
        from ..live.cards import load_cards
        from pathlib import Path
        import json as _json
        run_id = m.group(1)
        run_folder = audit_reader.get_run_folder(run_id, db_path=_db_path())
        if run_folder is None:
            return _err("run not found"), 404
        # Load candidate metrics from this run's robustness_result.json
        cand_file = run_folder / "robustness_result.json"
        if not cand_file.exists():
            return _err("no robustness_result.json for run"), 404
        cand = _json.loads(cand_file.read_text(encoding="utf-8"))
        # Walk enabled cards and load each's latest verdict.json from pine_archive
        archive_root = _pine_archive_root()
        cards = load_cards()
        cohort_metrics: list[dict] = []
        for c in cards:
            if c.get("status") != "enabled":
                continue
            vfile = archive_root / c["card_id"] / "verdict.json"
            if not vfile.exists():
                continue
            try:
                v = _json.loads(vfile.read_text(encoding="utf-8"))
                cohort_metrics.append({
                    "card_id": c["card_id"],
                    "pf": v.get("metrics", {}).get("profit_factor"),
                    "dsr": v.get("dsr_probability"),
                    "dd": v.get("metrics", {}).get("max_drawdown_pct"),
                })
            except Exception:
                continue
        def _rank_stat(value, cohort, key, lower_is_better=False):
            vals = [c[key] for c in cohort if c.get(key) is not None]
            vals.append(value)
            sorted_vals = sorted(vals, reverse=not lower_is_better)
            rank = sorted_vals.index(value) + 1
            return {
                "rank": rank,
                "out_of": len(vals),
                "median": round(sorted(vals)[len(vals)//2], 3) if vals else None,
                "worst": round(min(vals) if lower_is_better else max(vals[:-1] or [value]), 3) if len(vals) > 1 else None,
            }
        # Pull candidate values
        cand_pf = cand.get("metrics", {}).get("profit_factor") or cand.get("verdict", {}).get("dsr_probability")
        cand_dsr = cand.get("dsr_probability")
        cand_dd = cand.get("metrics", {}).get("max_drawdown_pct")
        # Build response — handle missing values gracefully
        result = {"n_cohort": len(cohort_metrics), "rows": []}
        if cand_pf is not None and any(c.get("pf") is not None for c in cohort_metrics):
            result["rows"].append({"label": "Hold-out PF", "value": cand_pf, **_rank_stat(cand_pf, cohort_metrics, "pf")})
        if cand_dsr is not None and any(c.get("dsr") is not None for c in cohort_metrics):
            result["rows"].append({"label": "DSR", "value": cand_dsr, **_rank_stat(cand_dsr, cohort_metrics, "dsr")})
        if cand_dd is not None and any(c.get("dd") is not None for c in cohort_metrics):
            result["rows"].append({"label": "DD", "value": cand_dd, **_rank_stat(cand_dd, cohort_metrics, "dd", lower_is_better=False)})
        return _ok(result), 200
```

**Note**: the exact JSON shape of `verdict.json` and `robustness_result.json` may differ from the keys used above (`metrics.profit_factor`, `dsr_probability`, `metrics.max_drawdown_pct`). Grep one of the existing files at execution: `cat pine_archive/<some_card>/verdict.json | python -m json.tool | head -40` and adjust key paths. The function-shape stays the same.

Frontend — add to Score modal markup, between Diagnostics section and Portfolio fit panel:

```html
          <div id="scoreRelativeContext" class="relative-context" style="display:none;"></div>
```

CSS:

```css
.relative-context { margin-bottom: 16px; padding: 10px 14px; background: var(--panel-2, #1c2030); border: 1px solid var(--border, #2a2f3e); border-radius: 6px; font-size: 12px; }
.relative-context h3 { margin: 0 0 6px; font-size: 13px; color: var(--text-dim, #9aa0ac); text-transform: uppercase; letter-spacing: 0.04em; }
.relative-context .row { display: flex; justify-content: space-between; padding: 3px 0; }
.relative-context .row .anchor { color: var(--text-dim, #9aa0ac); }
.relative-context .row .anchor strong { color: var(--text, #e4e6eb); }
.relative-context .rank { color: var(--accent, #22c55e); font-weight: 600; }
.relative-context .rank.sparse { color: var(--text-faint, #6b7280); font-weight: 400; }
```

JS — call from the modal-open handler:

```javascript
async function renderRelativeContext(scoringRunId) {
  const panel = document.getElementById("scoreRelativeContext");
  if (!panel) return;
  try {
    const env = await (await fetch(`/tradelab/relative-context/${encodeURIComponent(scoringRunId)}`)).json();
    if (env.error || !env.data) {
      panel.style.display = "none";
      return;
    }
    const d = env.data;
    if (d.n_cohort < 1 || !d.rows.length) {
      panel.style.display = "block";
      panel.innerHTML = `<h3>Relative context</h3>
        <p style="font-size: 11px; color: var(--text-faint);">No enabled live cards to compare against. Useful at n≥3 cohort cards.</p>`;
      return;
    }
    const rows = d.rows.map(r => {
      const cls = d.n_cohort < 2 ? "sparse" : "";
      return `<div class="row">
                <span class="anchor">${r.label} <strong>${typeof r.value === "number" ? r.value.toFixed(2) : r.value}</strong></span>
                <span class="rank ${cls}">#${r.rank} of ${r.out_of} · live median ${r.median != null ? r.median.toFixed(2) : "—"} · worst ${r.worst != null ? r.worst.toFixed(2) : "—"}</span>
              </div>`;
    }).join("");
    panel.style.display = "block";
    panel.innerHTML = `<h3>Relative context</h3>${rows}`;
  } catch (e) { panel.style.display = "none"; }
}
```

Hook `renderRelativeContext(scoringRunId)` into the score modal's open handler (alongside `renderHoldoutGate` and `renderPortfolioFit`).

- [ ] **Step 6.6: Smoke**

Open the Score modal for an existing run. Portfolio fit panel renders below Hold-out gate. Relative context renders between Diagnostics and Portfolio fit. Pipeline shows Corr column populated. Accept-button click flow: if max_rho ≤ 0.70 it proceeds normally; if > 0.70 the OVERRIDE prompt appears.

- [ ] **Step 6.7: Commit**

First commit the Relative-context endpoint in tradelab repo:

```bash
git add tradelab/src/tradelab/web/handlers.py
git commit -m "feat(web): /tradelab/relative-context/<run_id> endpoint (S6 sub)

Aggregates candidate's PF/DSR/DD ranks against enabled-card cohort.
Reads each enabled card's pine_archive/<card_id>/verdict.json and
computes rank/median/worst inline.
"
```

Then commit the parent-repo frontend changes:

```bash
cd /c/TradingScripts
git add -p command_center.html
git commit -m "feat(dashboard): Score modal Portfolio fit gate + Relative context + Pipeline Corr column (S6+S7)

Score modal: Hold-out gate (top) → Diagnostics → Relative context (rank
candidate vs cohort) → Portfolio fit panel (gates Accept on max ρ > 0.70
with OVERRIDE typed-confirm).

Pipeline: Corr column shows each run's max return ρ vs current enabled
cohort, color-coded green/amber/red.

Backed by /tradelab/correlation/<run_id> + /tradelab/relative-context/<run_id>.
"
```

---

## Task 7: Portfolio Health panel on Research tab (S8)

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 7.1: Pre-flight grep**

```bash
grep -n "research-section-title\|researchLiveCards" "/c/TradingScripts/command_center.html"
```
Expected: confirm Live Strategies section header + grid IDs from earlier verification.

- [ ] **Step 7.2: Add Portfolio Health markup**

Insert below the Live Strategies grid (before Research Pipeline header):

```html
        <h3 class="research-section-title">Portfolio Health</h3>
        <section id="researchPortfolioHealth" class="portfolio-health">
          <div class="ph-grid">
            <div class="ph-cell">
              <div class="label">Return correlation (max)</div>
              <div class="value sparse" data-ph-return-rho>…</div>
              <div class="detail" data-ph-return-pair></div>
            </div>
            <div class="ph-cell">
              <div class="label">Drawdown correlation (max)</div>
              <div class="value sparse" data-ph-dd-rho>…</div>
              <div class="detail" data-ph-dd-pair></div>
            </div>
            <div class="ph-cell">
              <div class="label">Entry-time overlap</div>
              <div class="value sparse" data-ph-entry-overlap>—</div>
              <div class="detail">requires intra-day timestamps (deferred)</div>
            </div>
          </div>
        </section>
```

CSS:

```css
.portfolio-health { background: var(--panel, #161922); border-left: 3px solid var(--blue, #3b82f6); border: 1px solid var(--border, #2a2f3e); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.ph-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.ph-cell { padding: 10px 12px; background: var(--panel-2, #1c2030); border: 1px solid var(--border, #2a2f3e); border-radius: 6px; }
.ph-cell .label { font-size: 11px; color: var(--text-dim, #9aa0ac); text-transform: uppercase; letter-spacing: 0.04em; }
.ph-cell .value { font-size: 18px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.ph-cell .value.sparse { color: var(--text-faint, #6b7280); font-size: 13px; }
.ph-cell .value.warn { color: var(--amber, #f59e0b); }
.ph-cell .value.ok { color: var(--accent, #22c55e); }
.ph-cell .detail { font-size: 11px; color: var(--text-faint, #6b7280); margin-top: 2px; }
```

- [ ] **Step 7.3: Add JS loader**

```javascript
async function loadPortfolioHealth() {
  try {
    const env = await (await fetch("/tradelab/portfolio-health")).json();
    if (env.error || !env.data || !env.data.pairs.length) {
      // Fewer than 2 enabled cards → leave sparse placeholders.
      return;
    }
    const d = env.data;
    const r = document.querySelector("[data-ph-return-rho]");
    if (r) {
      r.textContent = d.max_return_rho.toFixed(2);
      r.classList.remove("sparse");
      r.classList.add(d.max_return_rho > 0.70 ? "warn" : "ok");
    }
    const dd = document.querySelector("[data-ph-dd-rho]");
    if (dd) {
      dd.textContent = d.max_dd_rho.toFixed(2);
      dd.classList.remove("sparse");
      dd.classList.add(d.max_dd_rho > 0.70 ? "warn" : "ok");
    }
    // Find the pairs that produced the max for the detail line.
    const maxR = d.pairs.find(p => p.return_rho === d.max_return_rho);
    const rPair = document.querySelector("[data-ph-return-pair]");
    if (maxR && rPair) rPair.textContent = `${maxR.a} × ${maxR.b}`;
    const maxD = d.pairs.find(p => p.dd_rho === d.max_dd_rho);
    const ddPair = document.querySelector("[data-ph-dd-pair]");
    if (maxD && ddPair) ddPair.textContent = `${maxD.a} × ${maxD.b}`;
  } catch (e) {
    /* leave sparse */
  }
}
// Call from wherever the Research tab is initialized:
loadPortfolioHealth();
```

Find where Research-tab init happens (probably in a function called when the tab becomes active or DOMContentLoaded). Add `loadPortfolioHealth()` to that init.

- [ ] **Step 7.4: Smoke**

Reload dashboard, click Research tab. Portfolio Health panel renders. Today: with 1 enabled card, all values stay "—" / "…". With 2+ cards (after another Accept), values populate.

- [ ] **Step 7.5: Commit**

```bash
cd /c/TradingScripts
git add -p command_center.html
git commit -m "feat(dashboard): Portfolio Health panel on Research tab (S8)

Three-cell panel: max return ρ, max DD ρ, entry-time overlap (deferred).
Reads /tradelab/portfolio-health (S5). Shows sparse placeholders below
2 enabled cards.
"
```

---

## Task 8: Regime banner (S9)

**Files:**
- Create: `tradelab/src/tradelab/regime/__init__.py`
- Create: `tradelab/src/tradelab/regime/banner.py`
- Create: `tradelab/tests/regime/test_banner.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `GET /tradelab/regime`)
- Modify: `C:\TradingScripts\command_center.html` (regime banner panel)

- [ ] **Step 8.1: Pre-flight grep**

```bash
grep -rn "alpaca_py\|alpaca-py\|StockHistoricalDataClient" tradelab/src/ | head
grep -n "alpaca_config\|api_key" tradelab/src/tradelab/live/*.py
```
Verify alpaca-py is in deps and a client-construction helper exists.

- [ ] **Step 8.2: Write failing test**

Create `tradelab/tests/regime/test_banner.py`:

```python
"""Test regime banner derivation logic (independent of alpaca client)."""
from __future__ import annotations
import pytest
from tradelab.regime.banner import classify_regime, RegimeResult


def test_low_vol_trending_narrow():
    result = classify_regime(
        vix=14.8, realized_vol_30d=0.112,
        spx_above_50ma=True, spx_above_200ma=True, adx=26,
        breadth_pct_above_50d=44,
    )
    assert result.vol == "LOW"
    assert result.trend == "TRENDING"
    assert result.breadth == "NARROW"


def test_high_vol_choppy_broad():
    result = classify_regime(
        vix=28.5, realized_vol_30d=0.24,
        spx_above_50ma=False, spx_above_200ma=True, adx=14,
        breadth_pct_above_50d=72,
    )
    assert result.vol == "HIGH"
    assert result.trend == "CHOPPY"
    assert result.breadth == "BROAD"


def test_medium_vol_unclear_trend():
    result = classify_regime(
        vix=20.0, realized_vol_30d=0.18,
        spx_above_50ma=True, spx_above_200ma=False, adx=18,
        breadth_pct_above_50d=55,
    )
    assert result.vol == "MED"
    # SPX above 50 below 200 → divergent
    assert result.trend in ("UNCLEAR", "TRENDING", "CHOPPY")  # implementation choice
```

- [ ] **Step 8.3: Run test (expect failure)**

```bash
pytest tradelab/tests/regime/ -v
```

- [ ] **Step 8.4: Implement classifier + alpaca data fetch**

`tradelab/src/tradelab/regime/__init__.py`:

```python
from .banner import classify_regime, fetch_regime, RegimeResult

__all__ = ["classify_regime", "fetch_regime", "RegimeResult"]
```

`tradelab/src/tradelab/regime/banner.py`:

```python
"""Market regime classification for the Research-tab banner.

Pure logic: classify_regime takes raw inputs, returns labels.
fetch_regime: end-to-end via alpaca-py.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Optional


class RegimeResult(BaseModel):
    vol: str  # LOW | MED | HIGH
    trend: str  # TRENDING | CHOPPY | UNCLEAR
    breadth: str  # BROAD | MIXED | NARROW
    vix: Optional[float] = None
    realized_vol_30d: Optional[float] = None
    adx: Optional[float] = None
    breadth_pct_above_50d: Optional[float] = None
    last_shift_date: Optional[str] = None  # YYYY-MM-DD
    days_stable: Optional[int] = None


def classify_regime(
    vix: float,
    realized_vol_30d: float,
    spx_above_50ma: bool,
    spx_above_200ma: bool,
    adx: float,
    breadth_pct_above_50d: float,
) -> RegimeResult:
    # Volatility
    if vix < 17 and realized_vol_30d < 0.13:
        vol = "LOW"
    elif vix > 25 or realized_vol_30d > 0.22:
        vol = "HIGH"
    else:
        vol = "MED"
    # Trend
    if spx_above_50ma and spx_above_200ma and adx > 20:
        trend = "TRENDING"
    elif (not spx_above_50ma) and adx < 18:
        trend = "CHOPPY"
    else:
        trend = "UNCLEAR"
    # Breadth
    if breadth_pct_above_50d >= 60:
        breadth = "BROAD"
    elif breadth_pct_above_50d >= 50:
        breadth = "MIXED"
    else:
        breadth = "NARROW"
    return RegimeResult(
        vol=vol, trend=trend, breadth=breadth,
        vix=round(vix, 2), realized_vol_30d=round(realized_vol_30d, 4),
        adx=round(adx, 2), breadth_pct_above_50d=round(breadth_pct_above_50d, 1),
    )


def fetch_regime() -> RegimeResult:
    """Pull live data via alpaca-py and classify.

    Caches in memory for 1 hour to avoid repeated API hits.
    """
    # alpaca-py client construction matches existing pattern in live/alpaca_adapter.py.
    # If breadth (% above 50d) is unavailable from alpaca-py for the S&P 500
    # universe, fall back to a static estimate (60.0) and document this in
    # the Spec section 8 risk #1.
    from ..live.alpaca_adapter import get_data_client
    client = get_data_client()
    # ... call client.get_stock_bars for SPY/VIX, compute MAs/ADX/realized vol ...
    # This is implementation detail; keep this skeleton small and add a
    # `tests/regime/test_fetch_regime_smoke.py` that hits the real API only
    # when ALPACA_LIVE_TESTS=1 env var is set.
    raise NotImplementedError("fetch_regime: complete during execution")
```

The `fetch_regime` is sketched; the exact alpaca-py calls (`get_stock_bars` etc.) need verification at execution time. Implementation should:
- Pull last 250 bars of SPX (^SPX or SPY), compute 50/200 MAs and ADX
- Pull VIX last 30 daily closes, compute mean
- Pull SPX-500 universe constituents — if alpaca-py doesn't expose, hardcode breadth at 60.0 and add a TODO note (Spec section 8 risk #1)

- [ ] **Step 8.5: Add endpoint**

In `web/handlers.py`:

```python
    if path == "/tradelab/regime":
        from ..regime.banner import fetch_regime
        try:
            result = fetch_regime()
            return _ok(result.model_dump()), 200
        except NotImplementedError:
            # Stub fallback while fetch_regime is being implemented
            return _ok({
                "vol": "UNKNOWN", "trend": "UNKNOWN", "breadth": "UNKNOWN",
                "vix": None, "realized_vol_30d": None,
                "adx": None, "breadth_pct_above_50d": None,
                "last_shift_date": None, "days_stable": None,
            }), 200
        except Exception as e:
            return _err(f"regime fetch failed: {e}"), 500
```

- [ ] **Step 8.6: Frontend banner**

Insert at the very top of the Research tab content, BEFORE the Calibration banner / Live Strategies header:

```html
        <section id="researchRegime" class="regime-banner">
          <h3 class="research-section-title">Market Regime</h3>
          <div class="regime-grid">
            <div class="regime-cell">
              <div class="label">Volatility</div>
              <div class="value" data-regime-vol>…</div>
              <div class="meta" data-regime-vol-meta></div>
            </div>
            <div class="regime-cell">
              <div class="label">Trend</div>
              <div class="value" data-regime-trend>…</div>
              <div class="meta" data-regime-trend-meta></div>
            </div>
            <div class="regime-cell">
              <div class="label">Breadth</div>
              <div class="value" data-regime-breadth>…</div>
              <div class="meta" data-regime-breadth-meta></div>
            </div>
          </div>
        </section>
```

CSS:

```css
.regime-banner { background: linear-gradient(135deg, rgba(34, 197, 94, 0.08), rgba(59, 130, 246, 0.08)); border: 1px solid var(--border, #2a2f3e); border-left: 3px solid var(--accent, #22c55e); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.regime-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.regime-cell .label { font-size: 11px; color: var(--text-dim, #9aa0ac); text-transform: uppercase; letter-spacing: 0.04em; }
.regime-cell .value { font-size: 16px; font-weight: 600; margin-top: 2px; }
.regime-cell .meta { font-size: 11px; color: var(--text-faint, #6b7280); margin-top: 2px; }
```

JS loader:

```javascript
async function loadRegime() {
  try {
    const env = await (await fetch("/tradelab/regime")).json();
    if (env.error) return;
    const d = env.data;
    const setText = (key, val, color) => {
      const el = document.querySelector(`[data-regime-${key}]`);
      if (el) {
        el.textContent = val ?? "—";
        if (color) el.style.color = color;
      }
    };
    const colorFor = (label) => {
      if (label === "LOW" || label === "TRENDING" || label === "BROAD") return "var(--accent)";
      if (label === "HIGH" || label === "CHOPPY" || label === "NARROW") return "var(--amber)";
      return "var(--text-dim)";
    };
    setText("vol", d.vol, colorFor(d.vol));
    setText("trend", d.trend, colorFor(d.trend));
    setText("breadth", d.breadth, colorFor(d.breadth));
    const m1 = document.querySelector("[data-regime-vol-meta]");
    if (m1) m1.textContent = `VIX ${d.vix ?? '—'} · 30d realized ${d.realized_vol_30d != null ? (d.realized_vol_30d*100).toFixed(1)+'%' : '—'}`;
    const m2 = document.querySelector("[data-regime-trend-meta]");
    if (m2) m2.textContent = `ADX ${d.adx ?? '—'}`;
    const m3 = document.querySelector("[data-regime-breadth-meta]");
    if (m3) m3.textContent = `${d.breadth_pct_above_50d != null ? d.breadth_pct_above_50d.toFixed(0)+'%' : '—'} of S&P 500 above 50d`;
  } catch (e) { /* leave placeholders */ }
}
loadRegime();
```

- [ ] **Step 8.7: Smoke**

Reload dashboard. Regime banner renders. If `fetch_regime` is still stub (NotImplementedError path), all values show "UNKNOWN" — that's expected and acceptable for first-cut. Implement the real fetch when ready.

- [ ] **Step 8.8: Commit (two repos)**

```bash
git add tradelab/src/tradelab/regime/ \
        tradelab/tests/regime/ \
        tradelab/src/tradelab/web/handlers.py
git commit -m "feat(regime): regime banner module + endpoint (S9)

classify_regime is pure logic over (vix, realized_vol_30d, spx_above_50ma,
spx_above_200ma, adx, breadth_pct_above_50d). fetch_regime calls alpaca-py
(implementation detail to fill in at execution; stub path returns
UNKNOWN until live fetch wired).

GET /tradelab/regime returns RegimeResult model_dump.
"
```

```bash
cd /c/TradingScripts
git add -p command_center.html
git commit -m "feat(dashboard): regime banner panel on Research tab (S9)"
```

---

## Task 9: Calibration banner (S10)

**Files:**
- Create: `tradelab/src/tradelab/calibration/__init__.py`
- Create: `tradelab/src/tradelab/calibration/summary.py`
- Create: `tradelab/tests/calibration/test_summary.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `GET /tradelab/calibration-summary`)
- Modify: `C:\TradingScripts\command_center.html` (calibration banner panel)

- [ ] **Step 9.1: Pre-flight grep**

```bash
grep -rn "load_cards\|read_cards" tradelab/src/tradelab/live/cards.py | head
```

- [ ] **Step 9.2: Write failing test**

Create `tradelab/tests/calibration/test_summary.py`:

```python
"""Test calibration summary aggregations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytest
from tradelab.calibration.summary import (
    CalibrationSummaryResult,
    summarize_calibration,
    is_te_tripped_within_30d,
)


def test_empty_cards_yields_zero_counts():
    result = summarize_calibration(cards=[], te_loader=lambda card_id: {"status": "insufficient", "n_live_trades": 0})
    assert result.n_accepted == 0
    assert result.n_te_tripped_30d == 0
    assert result.median_pf_gap is None


def test_n_accepted_counts_only_accepted_cards():
    cards = [
        {"card_id": "a", "accepted_bool": True, "created_at": "2026-01-01T00:00:00Z"},
        {"card_id": "b", "accepted_bool": False, "created_at": "2026-01-02T00:00:00Z"},
    ]
    result = summarize_calibration(cards=cards, te_loader=lambda c: {"status": "insufficient", "n_live_trades": 0})
    assert result.n_accepted == 1


def test_te_tripped_logic():
    # If a card's TE went below 0.60 in any of first-30-days, it's tripped.
    assert is_te_tripped_within_30d({"decay_series": [0.9, 0.8, 0.5, 0.6, 0.7], "status": "ok"})
    assert not is_te_tripped_within_30d({"decay_series": [0.9, 0.85, 0.8, 0.78, 0.82], "status": "ok"})
    assert not is_te_tripped_within_30d({"status": "insufficient", "decay_series": None})
```

- [ ] **Step 9.3: Implement**

`tradelab/src/tradelab/calibration/__init__.py`:

```python
from .summary import summarize_calibration, CalibrationSummaryResult

__all__ = ["summarize_calibration", "CalibrationSummaryResult"]
```

`tradelab/src/tradelab/calibration/summary.py`:

```python
"""Calibration summary — aggregate over accepted-card outcomes."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable
import statistics
from pydantic import BaseModel

TE_TRIPPED_THRESHOLD = 0.60


class CalibrationSummaryResult(BaseModel):
    n_accepted: int = 0
    n_te_tripped_30d: int = 0
    n_disabled_60d: int = 0
    median_pf_gap: Optional[float] = None
    window_days: int = 90


def is_te_tripped_within_30d(te_data: dict) -> bool:
    if te_data.get("status") != "ok":
        return False
    decay = te_data.get("decay_series")
    if not decay:
        return False
    return any(v < TE_TRIPPED_THRESHOLD for v in decay)


def summarize_calibration(
    cards: list[dict],
    te_loader: Callable[[str], dict],
    window_days: int = 90,
) -> CalibrationSummaryResult:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    accepted_in_window = [
        c for c in cards
        if c.get("accepted_bool")
        and _parse_iso(c.get("created_at")) and _parse_iso(c["created_at"]) >= cutoff
    ]
    if not accepted_in_window:
        return CalibrationSummaryResult(window_days=window_days)
    n_tripped = 0
    pf_gaps: list[float] = []
    for c in accepted_in_window:
        te_data = te_loader(c["card_id"])
        if is_te_tripped_within_30d(te_data):
            n_tripped += 1
        # PF gap (if we have both live PF and backtest PF)
        if te_data.get("status") == "ok":
            te = te_data.get("te")
            if te is not None and te > 0:
                # backtest_pf is implied; we approximate gap as (1 - te)*backtest_pf
                # — for now, use simpler proxy: |te - 1.0| as gap-magnitude.
                pf_gaps.append(round(1.0 - te, 3))
    n_disabled = sum(1 for c in accepted_in_window if c.get("status") == "disabled")
    return CalibrationSummaryResult(
        n_accepted=len(accepted_in_window),
        n_te_tripped_30d=n_tripped,
        n_disabled_60d=n_disabled,
        median_pf_gap=round(statistics.median(pf_gaps), 3) if pf_gaps else None,
        window_days=window_days,
    )


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
```

- [ ] **Step 9.4: Add endpoint**

```python
    if path == "/tradelab/calibration-summary":
        from ..calibration.summary import summarize_calibration
        from ..live.cards import load_cards
        from ..live.tracking_error import compute_tracking_error, load_live_returns_for_card
        cards = load_cards()
        archive_root = _pine_archive_root()
        def _te_loader(card_id: str) -> dict:
            csv_path = archive_root / card_id / "tv_trades.csv"
            if not csv_path.exists():
                return {"status": "insufficient", "decay_series": None}
            try:
                live = load_live_returns_for_card(card_id)
                return compute_tracking_error(csv_path, live).model_dump()
            except Exception:
                return {"status": "insufficient", "decay_series": None}
        result = summarize_calibration(cards=cards, te_loader=_te_loader)
        return _ok(result.model_dump()), 200
```

- [ ] **Step 9.5: Frontend banner**

Insert in Research tab between Regime banner and Live Strategies:

```html
        <section id="researchCalibration" class="calibration">
          <h3 class="research-section-title">Verdict Calibration</h3>
          <div class="cal-stat-row">
            <div class="cal-stat"><div class="num sparse" data-cal-tripped>—</div><div class="label">TE tripped within 30d</div></div>
            <div class="cal-stat"><div class="num sparse" data-cal-disabled>—</div><div class="label">Manually disabled within 60d</div></div>
            <div class="cal-stat"><div class="num sparse" data-cal-pf-gap>—</div><div class="label">Median PF gap</div></div>
          </div>
        </section>
```

CSS:

```css
.calibration { background: rgba(245, 158, 11, 0.06); border: 1px solid var(--border, #2a2f3e); border-left: 3px solid var(--amber, #f59e0b); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
.cal-stat-row { display: flex; gap: 24px; align-items: center; }
.cal-stat { display: flex; flex-direction: column; }
.cal-stat .num { font-size: 20px; font-weight: 600; color: var(--amber, #f59e0b); }
.cal-stat .num.sparse { color: var(--text-faint, #6b7280); font-size: 14px; }
.cal-stat .label { font-size: 11px; color: var(--text-dim, #9aa0ac); text-transform: uppercase; letter-spacing: 0.04em; }
```

JS loader:

```javascript
async function loadCalibrationSummary() {
  try {
    const env = await (await fetch("/tradelab/calibration-summary")).json();
    if (env.error) return;
    const d = env.data;
    if (d.n_accepted < 3) {
      // Sparse: leave dashes; below n=3 the numbers are noise.
      const note = document.querySelector("#researchCalibration");
      if (note && !note.querySelector(".cal-sparse-note")) {
        const p = document.createElement("p");
        p.className = "cal-sparse-note";
        p.style.cssText = "font-size: 11px; color: var(--text-faint); margin: 8px 0 0;";
        p.textContent = `Insufficient sample (n=${d.n_accepted}); banner will populate at n≥3 accepted cards.`;
        note.appendChild(p);
      }
      return;
    }
    document.querySelector("[data-cal-tripped]").textContent = `${d.n_te_tripped_30d} / ${d.n_accepted}`;
    document.querySelector("[data-cal-tripped]").classList.remove("sparse");
    document.querySelector("[data-cal-disabled]").textContent = `${d.n_disabled_60d} / ${d.n_accepted}`;
    document.querySelector("[data-cal-disabled]").classList.remove("sparse");
    if (d.median_pf_gap != null) {
      document.querySelector("[data-cal-pf-gap]").textContent = (d.median_pf_gap >= 0 ? "+" : "") + d.median_pf_gap.toFixed(2);
      document.querySelector("[data-cal-pf-gap]").classList.remove("sparse");
    }
  } catch (e) { /* leave sparse */ }
}
loadCalibrationSummary();
```

- [ ] **Step 9.6: Smoke**

Reload dashboard. With n_accepted=1 today, banner shows the "insufficient sample" note. As more cards accumulate, real numbers populate.

- [ ] **Step 9.7: Commit**

```bash
git add tradelab/src/tradelab/calibration/ \
        tradelab/tests/calibration/ \
        tradelab/src/tradelab/web/handlers.py
git commit -m "feat(calibration): summary banner module + endpoint (S10)

Aggregates over accepted-card outcomes: how many tripped TE within 30d,
how many disabled within 60d, median PF gap. Honest sparse-data:
returns insufficient flag below n=3 accepted cards.

GET /tradelab/calibration-summary
"
```

```bash
cd /c/TradingScripts
git add -p command_center.html
git commit -m "feat(dashboard): calibration banner on Research tab (S10)"
```

---

## Self-Review

After completing all 9 tasks, verify against the spec:

- [ ] **Spec coverage check.** Walk through spec section 2 in/out lists; section 3 architecture; section 4 data-flow table. Every line maps to a task above. Any gap → add a follow-up task here, then implement before declaring done.
- [ ] **Run full test suite once more:** `pytest tradelab/tests/ -x` — expect green and ≥35 new tests added (Tasks 1, 2, 4, 5, 8, 9).
- [ ] **Manual smoke:** click through every panel/element in `research_tab_lite_applied_to_flow_a.html` and verify the live dashboard matches.
- [ ] **Commit-pattern audit:** ensure parent-repo `command_center.html` commits each contained ONLY their slice's hunks (no months-dirty unrelated changes).
- [ ] **Update memory:** add an entry for "LITE-for-Flow-A shipped" with HEAD SHA, and update `project_validation_redesign_2026-04-28.md` from PAUSED to SHIPPED.

---

## Risk register (carried from spec section 8)

The plan addresses spec risks #1, #2, #3, #4, #5 inline:

- **#1 alpaca-py breadth:** Task 8 step 8.4 notes the fall-back to static estimate
- **#2 Distributional vs paired K-S:** Task 2's design is purely distributional per spec (no per-fill match)
- **#3 pine_archive filesystem:** Task 1 step 1.6 reads/writes through `accept_scored` which already operates on dashboard side
- **#4 Backfill script:** Task 1 step 1.9 + 1.10 covers
- **#5 command_center.html months-dirty:** every frontend task uses `git add -p` partial-staging
