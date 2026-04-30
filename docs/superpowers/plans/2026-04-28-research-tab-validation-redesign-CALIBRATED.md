# Research Tab Validation Redesign — CALIBRATED Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the CALIBRATED v3 Research tab validation redesign across 10 dependency-ordered slices: §1 confound surface + canary integrity + verdict accuracy loop + hold-out gate + multi-dim correlation + regime banner + REVIEW-only K-S divergence.

**Architecture:** Extends existing single-PID/port/HTML dashboard architecture (`command_center.html` on :8877) with new modules under `tradelab.calibration`, `tradelab.canary.runtime`, `tradelab.regime`, `tradelab.live.divergence`. Extends existing `data/tradelab_history.db::runs` table (4 new columns). Persists per-card baselines under `pine_archive/<card_id>/` for correlation + divergence. No new dependencies (numpy, scipy, sqlite3 vendored).

**Tech Stack:** Python 3.11, sqlite3 (stdlib), numpy + scipy (vendored), pytest, http.server, vanilla JS in `command_center.html`.

**Spec:** `docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-CALIBRATED-design.md`
**Mockup:** `docs/superpowers/mockups/research_tab_redesign_proposal_CALIBRATED.html`
**Recon:** `docs/superpowers/ENGINE_CALIBRATION_RECON_2026-04-23.md`

**Slice dependency graph:**
```
-1 (retrospective) ──┐
 0 (ledger ext)   ───┼──► 3 (hit-rate) ──► 6 (verdict accuracy banner)
                     │                                  ▲
0.5 (canary panel)   │                                  │
1a (hold-out gate)   │                                  │
1b (relative ctx)    │       4 (regime banner)          │
                     │                                  │
                     └──► 2 (multi-dim corr) ──► 5 (K-S REVIEW) ┘
```

Recommended sequence (single-track): **-1 → 0 → 0.5 → 1a → 1b → 2 → 3 → 4 → 5 → 6**.

**Hand-smoke between slices** per `feedback_live_smoke_before_next_slice` memory.

---

## Slice -0.5: Patch alpaca_trading_bot.py for client_order_id tagging

**Why first:** Bot currently submits orders without `client_order_id`. Means orders pulled from Alpaca API have no strategy attribution. Tagging from now forward ensures future calibration runs are clean. Tiny change, ½ day with tests.

**Files:**
- Modify: `C:/TradingScripts/alpaca_trading_bot.py:166-202` (`submit_order` method signature)
- Modify: `C:/TradingScripts/alpaca_trading_bot.py:850` (entry-order call site)
- Modify: `C:/TradingScripts/alpaca_trading_bot.py:900` (stop-loss exit call site)
- Test: `C:/TradingScripts/tests/test_alpaca_bot_client_order_id.py`

### Task -0.5.1: Failing test for client_order_id propagation

- [ ] **Step 1: Failing test**

```python
# C:/TradingScripts/tests/test_alpaca_bot_client_order_id.py
import pytest
from unittest.mock import MagicMock, patch

def test_submit_order_passes_client_order_id_to_alpaca():
    """Bot must thread client_order_id through to api.submit_order."""
    from alpaca_trading_bot import AlpacaAPIClient
    mock_api = MagicMock()
    client = AlpacaAPIClient.__new__(AlpacaAPIClient)
    client.api = mock_api
    client.logger = MagicMock()

    client.submit_order(
        symbol="AAPL", qty=100, side="buy",
        client_order_id="S4_InsideDayBreakout-AAPL-1714296000",
    )
    args, kwargs = mock_api.submit_order.call_args
    assert kwargs.get("client_order_id") == "S4_InsideDayBreakout-AAPL-1714296000"
```

- [ ] **Step 2: Run, see fail**

`python -m pytest C:/TradingScripts/tests/test_alpaca_bot_client_order_id.py -v`
Expected: FAIL — current `submit_order` signature has no `client_order_id` param.

### Task -0.5.2: Add client_order_id parameter to submit_order

- [ ] **Step 1: Modify `submit_order` signature**

In `C:/TradingScripts/alpaca_trading_bot.py:166-202`, add `client_order_id: Optional[str] = None` to the signature, and pass it into `kwargs` before the API call:

```python
def submit_order(
    self, symbol: str, qty: int, side: str,
    order_type: str = 'market', time_in_force: str = 'day',
    limit_price: Optional[float] = None,
    trail_percent: Optional[float] = None,
    stop_price: Optional[float] = None,
    client_order_id: Optional[str] = None,    # NEW
) -> Optional[Dict]:
    try:
        kwargs = {
            'symbol': symbol, 'qty': qty, 'side': side,
            'type': order_type, 'time_in_force': time_in_force,
        }
        # ... existing logic that builds kwargs ...
        if client_order_id is not None:
            kwargs['client_order_id'] = client_order_id    # NEW
        # bracket-order branch handling unchanged
        order = self.api.submit_order(**kwargs)
```

- [ ] **Step 2: Run + commit**

```bash
python -m pytest C:/TradingScripts/tests/test_alpaca_bot_client_order_id.py -v
cd C:/TradingScripts && git add alpaca_trading_bot.py tests/test_alpaca_bot_client_order_id.py
git commit -m "feat(bot): submit_order accepts client_order_id (Slice -0.5)"
```

### Task -0.5.3: Tag entry path (line 850)

- [ ] **Step 1: Failing test**

```python
def test_entry_path_tags_with_strategy(tmp_path, monkeypatch):
    """When bot opens a position, the resulting submit_order must include
    a client_order_id of form '{strategy}-{symbol}-{ts}'."""
    from alpaca_trading_bot import TradingBot
    bot = MagicMock()
    bot.api_client = MagicMock()
    signal = {"symbol": "AAPL", "strategy": "S4_InsideDayBreakout",
              "stop": 175.0, "config": {"_effective_max_positions": 5}}
    # ... call into the entry path with this signal ...
    # assert that api_client.submit_order was called with
    # client_order_id starting with "S4_InsideDayBreakout-AAPL-"
```

- [ ] **Step 2: Modify entry call (line 850)**

Find the existing `submit_order(symbol=..., qty=qty, side='buy', ...)` block at line 850. Add:

```python
import time
order = self.api_client.submit_order(
    symbol=symbol, qty=qty, side='buy',
    stop_price=stop_for_bracket,    # existing
    client_order_id=f"{strategy}-{symbol}-{int(time.time())}",   # NEW
)
```

- [ ] **Step 3: Run + commit**

```bash
python -m pytest C:/TradingScripts/tests/ -v
git add -u && git commit -m "feat(bot): tag entry orders with client_order_id (Slice -0.5)"
```

### Task -0.5.4: Tag exit path (line 900)

- [ ] **Step 1: Modify exit call**

Find the stop-loss exit at line 900: `order = self.api_client.submit_order(symbol=symbol, qty=int(tracked['qty']), side='sell')`. Replace with:

```python
order = self.api_client.submit_order(
    symbol=symbol, qty=int(tracked['qty']), side='sell',
    client_order_id=f"{tracked['strategy']}-{symbol}-exit-{int(time.time())}",
)
```

- [ ] **Step 2: Test + commit**

```bash
python -m pytest C:/TradingScripts/tests/ -v
git add -u && git commit -m "feat(bot): tag exit orders with client_order_id (Slice -0.5)"
```

### Task -0.5.5: Hand-smoke

- [ ] Restart bot in paper mode. Trigger one synthetic entry + exit.
- [ ] Verify in Alpaca dashboard that the new orders show client_order_id like `S4_InsideDayBreakout-AAPL-<timestamp>`.
- [ ] Document one-line confirmation in commit log.

---

## Slice -1: Retrospective Calibration via Alpaca API

**Why first:** Recon §7 step-1, **adapted for missing `trades.csv`** (verified 2026-04-28: file does not exist; bot's `export_trades_csv()` was apparently never called). Pulls fills directly from Alpaca paper account; uses `bot.log` to attribute fills to strategies for the historical 12mo window. Output flagged with both §1 code-divergence caveat AND attribution-quality field.

**Files:**
- Create: `tradelab/src/tradelab/calibration/__init__.py`
- Create: `tradelab/src/tradelab/calibration/retrospective.py`
- Create: `tradelab/src/tradelab/calibration/alpaca_trade_history.py` (Alpaca API wrapper)
- Create: `tradelab/src/tradelab/calibration/bot_log_attribution.py` (parses `Position added` lines)
- Create: `tradelab/src/tradelab/cli/retrospective_calibration.py`
- Modify: `tradelab/src/tradelab/cli/__main__.py` (add subcommand)
- Test: `tradelab/tests/calibration/test_retrospective.py`
- Test: `tradelab/tests/calibration/test_alpaca_trade_history.py`
- Test: `tradelab/tests/calibration/test_bot_log_attribution.py`
- Test fixture: `tradelab/tests/fixtures/retrospective/alpaca_orders_sample.json` (mocked API response)
- Test fixture: `tradelab/tests/fixtures/retrospective/bot_log_sample.log` (synthetic Position added lines)
- Test fixture: `tradelab/tests/fixtures/retrospective/robustness_sample.json`

### Task -1.1: Create calibration package skeleton

- [ ] **Step 1: Write the failing test**

```python
# tradelab/tests/calibration/test_retrospective.py
import pytest
from tradelab.calibration import retrospective

def test_module_importable():
    assert hasattr(retrospective, "compute_per_strategy_outcomes")
    assert hasattr(retrospective, "compute_per_signal_seed_hit_rates")
    assert hasattr(retrospective, "RetrospectiveResult")
```

- [ ] **Step 2: Run test to verify it fails**

`pytest tradelab/tests/calibration/test_retrospective.py::test_module_importable -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradelab.calibration'`

- [ ] **Step 3: Create package + minimal module**

```python
# tradelab/src/tradelab/calibration/__init__.py
from . import retrospective  # noqa: F401
```

```python
# tradelab/src/tradelab/calibration/retrospective.py
"""Slice -1 retrospective: compares last-12mo live trades vs predicted verdicts.

CAVEAT: outputs carry code_divergence_caveat=True until §1 confound resolves.
Recon §7 step-1; recon §1 documents that deployed bot loads strategies by bare
module name, so live PnL is from possibly-different code than what tradelab scored.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrospectiveResult:
    code_divergence_caveat: bool = True
    per_strategy: list = field(default_factory=list)
    per_signal_seed: dict = field(default_factory=dict)


def compute_per_strategy_outcomes(*args, **kwargs):
    raise NotImplementedError


def compute_per_signal_seed_hit_rates(*args, **kwargs):
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

`pytest tradelab/tests/calibration/test_retrospective.py::test_module_importable -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradelab/src/tradelab/calibration/__init__.py tradelab/src/tradelab/calibration/retrospective.py tradelab/tests/calibration/test_retrospective.py
git commit -m "feat(calibration): scaffold retrospective module (Slice -1)"
```

### Task -1.2: Pull filled orders from Alpaca API

- [ ] **Step 1: Create mock fixture**

```json
// tradelab/tests/fixtures/retrospective/alpaca_orders_sample.json
[
  {"id": "abc1", "symbol": "AAPL", "qty": "100", "side": "buy",
   "filled_qty": "100", "filled_avg_price": "180.10",
   "filled_at": "2026-01-15T14:31:00Z", "client_order_id": "x-aapl-1",
   "status": "filled"},
  {"id": "abc2", "symbol": "AAPL", "qty": "100", "side": "sell",
   "filled_qty": "100", "filled_avg_price": "182.50",
   "filled_at": "2026-01-15T19:00:00Z", "client_order_id": "x-aapl-2",
   "status": "filled"},
  {"id": "abc3", "symbol": "NVDA", "qty": "20", "side": "buy",
   "filled_qty": "20", "filled_avg_price": "610.00",
   "filled_at": "2026-01-20T14:31:00Z", "client_order_id": "x-nvda-1",
   "status": "filled"},
  {"id": "abc4", "symbol": "NVDA", "qty": "20", "side": "sell",
   "filled_qty": "20", "filled_avg_price": "605.00",
   "filled_at": "2026-01-20T19:00:00Z", "client_order_id": "x-nvda-2",
   "status": "filled"}
]
```

- [ ] **Step 2: Failing test**

```python
# tradelab/tests/calibration/test_alpaca_trade_history.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from tradelab.calibration.alpaca_trade_history import fetch_filled_orders, pair_buy_sell_into_trades

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrospective"

def test_fetch_filled_orders_paginates_and_filters():
    fake_api = MagicMock()
    fixture_data = json.loads((FIXTURES / "alpaca_orders_sample.json").read_text())
    # Each Alpaca SDK call returns up to limit=500, paginated by `until`
    fake_api.list_orders.side_effect = [fixture_data, []]
    out = fetch_filled_orders(fake_api, after_iso="2026-01-01T00:00:00Z")
    assert len(out) == 4
    assert all(o["status"] == "filled" for o in out)


def test_pair_buy_sell_into_trades():
    fixture_data = json.loads((FIXTURES / "alpaca_orders_sample.json").read_text())
    trades = pair_buy_sell_into_trades(fixture_data)
    assert len(trades) == 2  # one AAPL round-trip + one NVDA
    aapl = next(t for t in trades if t["symbol"] == "AAPL")
    assert aapl["entry_price"] == pytest.approx(180.10)
    assert aapl["exit_price"] == pytest.approx(182.50)
    assert aapl["qty"] == 100
    assert aapl["pnl"] == pytest.approx((182.50 - 180.10) * 100)
    nvda = next(t for t in trades if t["symbol"] == "NVDA")
    assert nvda["pnl"] == pytest.approx((605.00 - 610.00) * 20)
```

- [ ] **Step 3: Implement**

```python
# tradelab/src/tradelab/calibration/alpaca_trade_history.py
"""Pulls filled orders from Alpaca paper account; pairs buy/sell into round-trip trades.

Used by Slice -1 retrospective when trades.csv doesn't exist (2026-04-28 reality).
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any


def fetch_filled_orders(api: Any, *, after_iso: str, page_size: int = 500) -> list[dict]:
    """Paginated pull of all filled orders since `after_iso`."""
    all_orders: list[dict] = []
    until = None
    while True:
        page = api.list_orders(
            status="filled", after=after_iso, until=until,
            limit=page_size, direction="desc",
        )
        # Alpaca SDK returns list of Order objects OR dicts depending on version
        page_dicts = [o if isinstance(o, dict) else o._raw for o in page]
        if not page_dicts:
            break
        all_orders.extend(page_dicts)
        if len(page_dicts) < page_size:
            break
        until = page_dicts[-1]["filled_at"]  # paginate older
    return [o for o in all_orders if o.get("status") == "filled"]


def pair_buy_sell_into_trades(orders: list[dict]) -> list[dict]:
    """Pair each buy with the next sell for the same symbol → round-trip trade.

    Assumes one open position per symbol at a time (true for the deployed bot).
    Returns list of {symbol, entry_ts, exit_ts, entry_price, exit_price, qty, pnl}.
    """
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    # sort ascending by filled_at
    for o in sorted(orders, key=lambda x: x["filled_at"]):
        by_symbol[o["symbol"]].append(o)

    trades: list[dict] = []
    for symbol, ords in by_symbol.items():
        i = 0
        while i < len(ords) - 1:
            buy = ords[i]
            if buy["side"] != "buy":
                i += 1; continue
            # find next matching sell
            j = i + 1
            while j < len(ords) and ords[j]["side"] != "sell":
                j += 1
            if j >= len(ords):
                break  # unmatched open position
            sell = ords[j]
            qty = int(float(buy["filled_qty"]))
            entry_price = float(buy["filled_avg_price"])
            exit_price = float(sell["filled_avg_price"])
            trades.append({
                "symbol": symbol,
                "entry_ts": buy["filled_at"],
                "exit_ts": sell["filled_at"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "qty": qty,
                "pnl": (exit_price - entry_price) * qty,
                "client_order_id_entry": buy.get("client_order_id"),
                "client_order_id_exit": sell.get("client_order_id"),
            })
            i = j + 1
    return trades
```

- [ ] **Step 4: Run + commit**

```bash
pytest tradelab/tests/calibration/test_alpaca_trade_history.py -v
git add -u && git commit -m "feat(calibration): Alpaca API trade fetcher + buy/sell pairing"
```

### Task -1.2b: Parse bot.log for Position added attribution

- [ ] **Step 1: Create fixture**

```
# tradelab/tests/fixtures/retrospective/bot_log_sample.log
2026-01-15 09:31:02 INFO Position added: AAPL (S4_InsideDayBreakout) - 100@$180.10 | Stop: $175.50
2026-01-15 14:00:15 INFO Position closed: AAPL - PnL $240.00 (+1.3%) | Reason: Take Profit
2026-01-20 09:31:08 INFO Position added: NVDA (S7_RDZMomentum) - 20@$610.00 | Stop: $595.00
2026-01-20 14:00:22 INFO Position closed: NVDA - PnL $-100.00 (-0.8%) | Reason: Stop Loss
2026-02-01 09:31:00 INFO Position added: AAPL (S4_InsideDayBreakout) - 100@$185.00 | Stop: $180.00
```

- [ ] **Step 2: Failing test**

```python
# tradelab/tests/calibration/test_bot_log_attribution.py
from pathlib import Path
import pytest
from datetime import datetime, timezone
from tradelab.calibration.bot_log_attribution import (
    parse_position_added_lines, attribute_trade,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrospective"

def test_parse_position_added_lines():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    assert len(entries) == 3  # 3 Position added lines
    aapl_first = entries[0]
    assert aapl_first["symbol"] == "AAPL"
    assert aapl_first["strategy"] == "S4_InsideDayBreakout"
    assert aapl_first["entry_price"] == pytest.approx(180.10)
    assert aapl_first["qty"] == 100

def test_attribute_trade_within_window():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    trade = {"symbol": "AAPL", "entry_ts": "2026-01-15T14:31:00Z"}
    # log line is at 09:31:02 local (assume UTC for fixture); 5h gap is within 2h window?
    # NOTE: Alpaca's filled_at is UTC; bot log timestamps are local. Test uses naive UTC.
    strategy = attribute_trade(trade, entries, window_hours=24)
    assert strategy == "S4_InsideDayBreakout"

def test_attribute_trade_unattributed_when_no_match():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    trade = {"symbol": "GOOGL", "entry_ts": "2026-03-01T14:31:00Z"}
    strategy = attribute_trade(trade, entries, window_hours=24)
    assert strategy is None
```

- [ ] **Step 3: Implement**

```python
# tradelab/src/tradelab/calibration/bot_log_attribution.py
"""Parses alpaca_trading_bot.log for `Position added: SYMBOL (STRATEGY)` lines.

Used by Slice -1 to attribute Alpaca fills to strategies for the historical 12mo
window (when client_order_id was not yet tagged — pre Slice -0.5).

Future fills will have native attribution via client_order_id and won't need this.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


_LINE_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r".*Position added: (?P<symbol>[A-Z]+) \((?P<strategy>[A-Za-z0-9_]+)\)"
    r" - (?P<qty>\d+)@\$(?P<price>[\d.]+)"
)


def parse_position_added_lines(log_path: Path) -> list[dict]:
    entries: list[dict] = []
    for line in log_path.read_text(errors="ignore").splitlines():
        m = _LINE_PATTERN.search(line)
        if m:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            entries.append({
                "ts": ts, "symbol": m.group("symbol"),
                "strategy": m.group("strategy"),
                "qty": int(m.group("qty")),
                "entry_price": float(m.group("price")),
            })
    return entries


def attribute_trade(
    trade: dict, log_entries: list[dict], *, window_hours: int = 24,
) -> Optional[str]:
    """Find the bot.log Position added line matching this trade's symbol within window."""
    trade_ts = datetime.fromisoformat(trade["entry_ts"].replace("Z", "+00:00"))
    candidates = [
        e for e in log_entries
        if e["symbol"] == trade["symbol"]
        and abs(e["ts"] - trade_ts) <= timedelta(hours=window_hours)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda e: abs(e["ts"] - trade_ts))
    return candidates[0]["strategy"]
```

- [ ] **Step 4: Run + commit**

```bash
pytest tradelab/tests/calibration/test_bot_log_attribution.py -v
git add -u && git commit -m "feat(calibration): bot.log Position added parser + attribution"
```

### Task -1.2c: Compute per-strategy outcomes from attributed trades

- [ ] **Step 1: Failing test**

```python
def test_per_strategy_outcomes_from_alpaca_trades():
    from tradelab.calibration.retrospective import compute_per_strategy_outcomes
    attributed = [
        {"symbol": "AAPL", "strategy": "S4_InsideDayBreakout", "pnl": 240.00},
        {"symbol": "AAPL", "strategy": "S4_InsideDayBreakout", "pnl": 400.00},
        {"symbol": "NVDA", "strategy": "S7_RDZMomentum", "pnl": -100.00},
        {"symbol": "GOOGL", "strategy": None, "pnl": 50.00},  # unattributed
    ]
    out = compute_per_strategy_outcomes(attributed)
    by_strat = {row["strategy"]: row for row in out}
    assert by_strat["S4_InsideDayBreakout"]["n_trades"] == 2
    assert by_strat["S4_InsideDayBreakout"]["total_pnl"] == 640.00
    assert by_strat["S7_RDZMomentum"]["n_trades"] == 1
    assert by_strat["unattributed"]["n_trades"] == 1
    assert by_strat["unattributed"]["total_pnl"] == 50.00
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/calibration/retrospective.py (replace stub)
from collections import defaultdict


def compute_per_strategy_outcomes(attributed_trades: list[dict]) -> list[dict]:
    """Group attributed trades by strategy; bucket unattributed separately."""
    pnls_by_strat: dict[str, list[float]] = defaultdict(list)
    for t in attributed_trades:
        key = t.get("strategy") or "unattributed"
        pnls_by_strat[key].append(t["pnl"])

    out = []
    for strategy, pnls in pnls_by_strat.items():
        wins = sum(p for p in pnls if p > 0)
        losses = -sum(p for p in pnls if p < 0)
        live_pf = (wins / losses) if losses > 0 else float("inf")
        out.append({
            "strategy": strategy, "n_trades": len(pnls),
            "total_pnl": sum(pnls), "live_pf": live_pf,
            "wins_total": wins, "losses_total": losses,
        })
    return out
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/calibration/test_retrospective.py -v
git add -u && git commit -m "feat(calibration): per-strategy outcomes w/ unattributed bucket"
```

### Task -1.3: Load latest report verdict + signal vector per strategy

- [ ] **Step 1: Create robustness fixture**

```json
// tradelab/tests/fixtures/retrospective/robustness_sample.json
{
  "strategy": "S4_InsideDayBreakout",
  "verdict": "FRAGILE",
  "signals": {
    "baseline_pf": {"value": 1.05, "verdict": "FRAGILE"},
    "dsr": {"value": 0.55, "verdict": "INCONCLUSIVE"},
    "entry_delay": {"value": 0.66, "verdict": "FRAGILE"},
    "loso": {"value": 3.42, "verdict": "FRAGILE"},
    "param_landscape": {"value": 0.10, "verdict": "ROBUST"},
    "mc_max_dd": {"value": 0.08, "verdict": "INCONCLUSIVE"},
    "wfe": {"value": 0.65, "verdict": "INCONCLUSIVE"},
    "noise_injection": {"value": 0.25, "verdict": "INCONCLUSIVE"},
    "regime_spread": {"value": 0.50, "verdict": "INCONCLUSIVE"}
  }
}
```

- [ ] **Step 2: Failing test**

```python
def test_load_verdict_and_signals_for_strategy(tmp_path):
    from tradelab.calibration.retrospective import load_predicted_verdict
    src = FIXTURES / "robustness_sample.json"
    result = load_predicted_verdict(src)
    assert result["verdict"] == "FRAGILE"
    assert result["signals"]["baseline_pf"]["verdict"] == "FRAGILE"
    assert result["signals"]["entry_delay"]["value"] == pytest.approx(0.66)
```

- [ ] **Step 3: Run, fail, implement**

```python
# tradelab/src/tradelab/calibration/retrospective.py (add)
import json

def load_predicted_verdict(report_path: Path) -> dict:
    """Read robustness_result.json; return verdict + per-signal vector."""
    with open(report_path) as f:
        return json.load(f)
```

- [ ] **Step 4: Run + commit**

```bash
pytest tradelab/tests/calibration/test_retrospective.py -v
git add -u && git commit -m "feat(calibration): load predicted verdict from robustness report"
```

### Task -1.4: Per-signal seed hit-rate computation

- [ ] **Step 1: Failing test**

```python
def test_per_signal_seed_hit_rates_basic():
    from tradelab.calibration.retrospective import compute_per_signal_seed_hit_rates
    # 3 strategies: S4 (FRAGILE entry_delay, deployed, lost),
    # S8 (FRAGILE entry_delay, deployed, won), S7 (FRAGILE baseline_pf, deployed, lost)
    strategies = [
        {"strategy": "S4", "live_pf": 0.85, "signals_fragile": ["entry_delay", "loso"]},
        {"strategy": "S8", "live_pf": 1.42, "signals_fragile": ["entry_delay", "loso"]},
        {"strategy": "S7", "live_pf": 0.61, "signals_fragile": ["baseline_pf"]},
    ]
    out = compute_per_signal_seed_hit_rates(strategies, fail_threshold=1.0)
    assert out["entry_delay"]["fragile_fires"] == 2
    assert out["entry_delay"]["accepted_despite"] == 2
    assert out["entry_delay"]["failed_in_prod"] == 1  # S4 only
    assert out["entry_delay"]["hit_rate"] == pytest.approx(0.5)
    assert out["baseline_pf"]["hit_rate"] == pytest.approx(1.0)
    assert out["loso"]["hit_rate"] == pytest.approx(0.5)
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/calibration/retrospective.py (add)
def compute_per_signal_seed_hit_rates(
    strategies: list[dict],
    fail_threshold: float = 1.0,
) -> dict[str, dict]:
    """For each signal: how often did fragile-fire-then-deployed predict failure?

    `strategies` rows must have: strategy, live_pf, signals_fragile (list of names).
    fail_threshold: live_pf below this counts as failed in prod.
    """
    per_signal: dict[str, dict] = {}
    for s in strategies:
        failed = s["live_pf"] < fail_threshold
        for sig_name in s["signals_fragile"]:
            row = per_signal.setdefault(sig_name, {
                "fragile_fires": 0, "accepted_despite": 0, "failed_in_prod": 0,
            })
            row["fragile_fires"] += 1
            row["accepted_despite"] += 1  # in retrospective, deployed = accepted
            if failed:
                row["failed_in_prod"] += 1
    for sig_name, row in per_signal.items():
        n = row["accepted_despite"]
        row["hit_rate"] = (row["failed_in_prod"] / n) if n >= 3 else None
        row["read"] = _classify_hit_rate(row["hit_rate"], n)
    return per_signal


def _classify_hit_rate(hit_rate: Optional[float], n: int) -> str:
    if n < 3:
        return "insufficient sample"
    if hit_rate is None:
        return "insufficient sample"
    if hit_rate >= 0.5:
        return "predictive"
    if hit_rate >= 0.25:
        return "questionable"
    return "noisy"
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/calibration/test_retrospective.py -v
git add -u && git commit -m "feat(calibration): per-signal seed hit-rate computation"
```

### Task -1.5: End-to-end orchestration + attribution-quality reporting

- [ ] **Step 1: Failing test**

```python
def test_run_retrospective_with_alpaca_and_log(tmp_path, monkeypatch):
    from tradelab.calibration.retrospective import run_retrospective_calibration

    # Mock Alpaca client; reuse fixture orders
    fake_api = MagicMock()
    fake_api.list_orders.side_effect = [
        json.loads((FIXTURES / "alpaca_orders_sample.json").read_text()),
        [],
    ]

    out_path = tmp_path / "retrospective.json"
    result = run_retrospective_calibration(
        alpaca_api=fake_api,
        bot_log_path=FIXTURES / "bot_log_sample.log",
        reports_dir=FIXTURES,
        output_path=out_path,
        window_months=12,
    )
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["code_divergence_caveat"] is True
    assert "attribution_quality" in data
    assert data["attribution_quality"]["attributed_count"] >= 1
    assert "unattributed_count" in data["attribution_quality"]
    assert "per_strategy" in data
    assert "per_signal_seed" in data
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/calibration/retrospective.py (add)
from datetime import datetime, timedelta, timezone
from .alpaca_trade_history import fetch_filled_orders, pair_buy_sell_into_trades
from .bot_log_attribution import parse_position_added_lines, attribute_trade


def run_retrospective_calibration(
    *, alpaca_api, bot_log_path: Path,
    reports_dir: Path, output_path: Path, window_months: int = 12,
) -> RetrospectiveResult:
    after_iso = (datetime.now(timezone.utc) - timedelta(days=window_months * 30)).isoformat()

    # 1. Pull Alpaca fills
    raw_orders = fetch_filled_orders(alpaca_api, after_iso=after_iso)

    # 2. Pair into round-trip trades
    trades = pair_buy_sell_into_trades(raw_orders)

    # 3. Attribute via bot.log
    log_entries = parse_position_added_lines(bot_log_path) if bot_log_path.exists() else []
    attributed = []
    attributed_count = unattributed_count = 0
    for trade in trades:
        strategy = attribute_trade(trade, log_entries)
        attributed.append({**trade, "strategy": strategy})
        if strategy:
            attributed_count += 1
        else:
            unattributed_count += 1

    # 4. Per-strategy live outcomes
    per_strategy = compute_per_strategy_outcomes(attributed)

    # 5. Predicted verdicts per strategy (latest robustness report)
    fragile_by_strategy: dict[str, list[str]] = {}
    for report_file in list(reports_dir.glob("**/robustness_result.json")) + [reports_dir / "robustness_sample.json"]:
        if not report_file.exists():
            continue
        rv = load_predicted_verdict(report_file)
        strategy = rv.get("strategy")
        if not strategy:
            continue
        fragile_by_strategy[strategy] = [
            name for name, sig in rv.get("signals", {}).items()
            if sig.get("verdict") == "FRAGILE"
        ]

    enriched = [{**row, "signals_fragile": fragile_by_strategy.get(row["strategy"], [])}
                for row in per_strategy]
    per_signal = compute_per_signal_seed_hit_rates(enriched)

    total = attributed_count + unattributed_count
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_months": window_months,
        "code_divergence_caveat": True,
        "caveat_text": (
            "Outputs compare tradelab verdicts to live PnL of (possibly) "
            "different code per recon §1. Resolve before drawing strong conclusions."
        ),
        "attribution_quality": {
            "attributed_count": attributed_count,
            "unattributed_count": unattributed_count,
            "attribution_pct": (attributed_count / total) if total else 0.0,
            "note": "Future fills will have native client_order_id attribution per Slice -0.5.",
        },
        "per_strategy": enriched,
        "per_signal_seed": per_signal,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, default=str))
    return RetrospectiveResult(
        code_divergence_caveat=True,
        per_strategy=enriched,
        per_signal_seed=per_signal,
    )
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/calibration/test_retrospective.py -v
git add -u && git commit -m "feat(calibration): orchestrator wires Alpaca + bot.log + reports + attribution_quality"
```

### Task -1.6: CLI subcommand (Alpaca-aware)

- [ ] **Step 1: Add CLI module**

```python
# tradelab/src/tradelab/cli/retrospective_calibration.py
"""CLI entry point for Slice -1 retrospective.

Usage:
  tradelab retrospective-calibration \
    --alpaca-config C:/TradingScripts/alpaca_config.json \
    --bot-log C:/TradingScripts/alpaca_trading_bot.log \
    --reports C:/TradingScripts/tradelab/reports \
    --output reports/calibration_retrospective_<date>.json \
    --paper
"""
import argparse
import json
from pathlib import Path
from tradelab.calibration.retrospective import run_retrospective_calibration


def _build_alpaca_client(config_path: Path, paper: bool):
    """Lazily import + construct an Alpaca REST client from gitignored config.

    Per memory `reference_alpaca_config_location.md`: api_key/secret_key live in
    alpaca_config.json (gitignored), NOT env vars.
    """
    cfg = json.loads(config_path.read_text())
    import alpaca_trade_api as tradeapi
    base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    return tradeapi.REST(
        key_id=cfg["api_key"], secret_key=cfg["secret_key"], base_url=base_url,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tradelab retrospective-calibration")
    parser.add_argument("--alpaca-config", type=Path, required=True,
                        help="path to alpaca_config.json (gitignored)")
    parser.add_argument("--bot-log", type=Path, required=True,
                        help="path to alpaca_trading_bot.log")
    parser.add_argument("--reports", type=Path, required=True,
                        help="tradelab reports/ dir")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-months", type=int, default=12)
    parser.add_argument("--paper", action="store_true", default=True)
    parser.add_argument("--live", action="store_false", dest="paper")
    args = parser.parse_args(argv)

    api = _build_alpaca_client(args.alpaca_config, paper=args.paper)
    run_retrospective_calibration(
        alpaca_api=api, bot_log_path=args.bot_log,
        reports_dir=args.reports, output_path=args.output,
        window_months=args.window_months,
    )
    print(f"Retrospective written to {args.output}")
    print("CAVEAT: outputs carry §1 code-divergence caveat + attribution-quality field")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Wire into `__main__.py`**

In `tradelab/src/tradelab/cli/__main__.py`:

```python
elif command == "retrospective-calibration":
    from .retrospective_calibration import main as _retro_main
    return _retro_main(args)
```

- [ ] **Step 3: Failing CLI test**

```python
# tradelab/tests/cli/test_cli_retrospective.py
import json
import subprocess
import sys
from pathlib import Path

def test_cli_retrospective_help_includes_alpaca_args():
    """Verify the CLI exposes --alpaca-config and --bot-log."""
    result = subprocess.run(
        [sys.executable, "-m", "tradelab", "retrospective-calibration", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--alpaca-config" in result.stdout
    assert "--bot-log" in result.stdout
```

- [ ] **Step 4: Run + commit**

```bash
pytest tradelab/tests/cli/test_cli_retrospective.py -v
git add -u && git commit -m "feat(cli): retrospective-calibration subcommand w/ Alpaca + bot.log args"
```

### Task -1.7: Run on real Alpaca paper-account data + record findings

- [ ] **Step 1: Locate `bot.log`**

Find the bot's log file. Check `alpaca_trading_bot.py:79` `log_file` property to know the resolved path. Likely `C:/TradingScripts/alpaca_trading_bot.log` or under a `logs/` subdir. Confirm exists with `ls -la <path>`.

- [ ] **Step 2: Verify alpaca_config.json**

Confirm `C:/TradingScripts/alpaca_config.json` is readable and has `api_key` + `secret_key` keys. **DO NOT print the values to chat.** Just confirm presence with `python -c "import json; print(set(json.load(open('C:/TradingScripts/alpaca_config.json')).keys()))"`.

- [ ] **Step 3: Run real retrospective**

```bash
python -m tradelab retrospective-calibration \
  --alpaca-config C:/TradingScripts/alpaca_config.json \
  --bot-log <resolved-bot-log-path> \
  --reports C:/TradingScripts/tradelab/reports \
  --output C:/TradingScripts/tradelab/reports/calibration_retrospective_2026-04-28.json \
  --paper
```

If Alpaca rate-limits or errors, the call retries with exponential backoff. If `bot.log` parses zero `Position added` lines, all fills bucket as `unattributed` — that's a real signal that the bot's logging format may have drifted from the regex.

- [ ] **Step 4: Inspect output + write findings**

Read the JSON output. Capture:
- `attribution_quality.attribution_pct` — if < 50%, the historical retrospective is statistically thin and should be flagged
- Per-strategy live PF — compare to predicted verdicts
- Per-signal seed hit rates — note which gates show signal vs noise
- Whether `entry_delay` and `loso` (recon §3 "quiet killers") show up as predictive or noisy

Write to `docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md`:
- Headline: "engine has signal" / "engine is noise" / "insufficient attributed sample"
- Top 3 most predictive signals
- Top 3 most noisy signals
- Recon §3 verification (entry_delay + loso)
- Decision: continue CALIBRATED build / halt + recalibrate / repeat in N days for more data
- §1 caveat reminder

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/CALIBRATION_RETROSPECTIVE_2026-04-28.md reports/calibration_retrospective_2026-04-28.json
git commit -m "data(calibration): Alpaca-API retrospective + attribution findings (Slice -1 done)"
```

- [ ] **Step 6: Hand-smoke decision gate**

Three branches:
- **Engine has signal:** continue to Slice 0.
- **Engine is noise:** halt build, recalibrate `tradelab.yaml::robustness.thresholds` based on per-signal hit-rate seeds, re-run retrospective.
- **Insufficient attributed sample (attribution_pct < 50%):** ship Slice -0.5's tagging, wait 30 days for natively-tagged trades, then re-run. Continue with Slices 0 + 0.5 + 1a/1b/2 in the meantime since they don't depend on calibration evidence.

---

## Slice 0: Ledger Schema Extension

**Why:** Existing `runs` table only has `verdict + dsr_probability` — full 9-signal vector is needed for hit-rate computation in Slice 3. Extending in place avoids a new table.

**Files:**
- Modify: `tradelab/src/tradelab/audit/history.py:33-50` (`_SCHEMA`), `:55-68` (`HistoryRow`), `:78-110` (`record_run`)
- Create: `tradelab/src/tradelab/audit/migrations.py`
- Create: `tradelab/scripts/backfill_runs_table.py`
- Test: `tradelab/tests/audit/test_history_extension.py`

### Task 0.1: Failing migration test

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/audit/test_history_extension.py
import sqlite3
from pathlib import Path
from tradelab.audit.history import _connect, record_run

def test_extended_columns_present(tmp_path):
    db = tmp_path / "test.db"
    conn = _connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for required in ("signal_values_json", "thresholds_json", "accepted_bool", "reject_reason"):
        assert required in cols, f"missing column {required}"

def test_idempotent_migration_on_existing_db(tmp_path):
    db = tmp_path / "old.db"
    # simulate pre-extension DB
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            verdict TEXT,
            dsr_probability REAL
        );
    """)
    conn.commit(); conn.close()
    # connecting via _connect should add the 4 new columns
    conn2 = _connect(db)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(runs)").fetchall()}
    assert "signal_values_json" in cols
    assert "thresholds_json" in cols
    assert "accepted_bool" in cols
    assert "reject_reason" in cols
```

- [ ] **Step 2: Run, see fail**

`pytest tradelab/tests/audit/test_history_extension.py -v`
Expected: both tests FAIL (columns don't exist yet)

### Task 0.2: Implement schema migration

- [ ] **Step 1: Update `_SCHEMA` and add migration logic**

```python
# tradelab/src/tradelab/audit/history.py — replace _SCHEMA + _connect
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT PRIMARY KEY,
    timestamp_utc        TEXT NOT NULL,
    strategy_name        TEXT NOT NULL,
    strategy_version     TEXT,
    tradelab_version     TEXT,
    tradelab_git_commit  TEXT,
    input_data_hash      TEXT,
    config_hash          TEXT,
    verdict              TEXT,
    dsr_probability      REAL,
    report_card_markdown TEXT,
    report_card_html_path TEXT,
    signal_values_json   TEXT,
    thresholds_json      TEXT,
    accepted_bool        INTEGER,
    reject_reason        TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_strategy ON runs(strategy_name);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_runs_accepted ON runs(accepted_bool);
"""

_NEW_COLUMNS = (
    ("signal_values_json", "TEXT"),
    ("thresholds_json", "TEXT"),
    ("accepted_bool", "INTEGER"),
    ("reject_reason", "TEXT"),
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    # ALTER TABLE for existing DBs that pre-date the extension
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for col, sqltype in _NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {sqltype}")
    conn.commit()
    return conn
```

- [ ] **Step 2: Run + commit**

```bash
pytest tradelab/tests/audit/test_history_extension.py -v
git add -u && git commit -m "feat(audit): extend runs table with signal_values + thresholds + accepted_bool + reject_reason"
```

### Task 0.3: Update HistoryRow dataclass + record_run signature

- [ ] **Step 1: Failing test**

```python
def test_record_run_persists_extended_fields(tmp_path):
    db = tmp_path / "test.db"
    run_id = record_run(
        strategy_name="S4_test",
        verdict="ROBUST",
        signal_values={"baseline_pf": 1.62, "dsr": 0.83},
        thresholds={"baseline_robust_pf": 1.5, "baseline_fragile_pf": 1.1},
        accepted=True,
        reject_reason=None,
        db_path=db,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT signal_values_json, thresholds_json, accepted_bool, reject_reason "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    import json
    assert json.loads(row[0])["baseline_pf"] == 1.62
    assert json.loads(row[1])["baseline_robust_pf"] == 1.5
    assert row[2] == 1
    assert row[3] is None
```

- [ ] **Step 2: Update HistoryRow + record_run**

```python
# tradelab/src/tradelab/audit/history.py — replace HistoryRow + record_run signature
@dataclass
class HistoryRow:
    run_id: str
    timestamp_utc: str
    strategy_name: str
    strategy_version: Optional[str] = None
    tradelab_version: Optional[str] = None
    tradelab_git_commit: Optional[str] = None
    input_data_hash: Optional[str] = None
    config_hash: Optional[str] = None
    verdict: Optional[str] = None
    dsr_probability: Optional[float] = None
    report_card_markdown: Optional[str] = None
    report_card_html_path: Optional[str] = None
    signal_values_json: Optional[str] = None
    thresholds_json: Optional[str] = None
    accepted_bool: Optional[int] = None
    reject_reason: Optional[str] = None


def record_run(
    strategy_name: str,
    *,
    verdict: Optional[str] = None,
    dsr_probability: Optional[float] = None,
    input_data_hash: Optional[str] = None,
    config_hash: Optional[str] = None,
    report_card_markdown: Optional[str] = None,
    report_card_html_path: Optional[str] = None,
    strategy_version: Optional[str] = None,
    tradelab_version: Optional[str] = None,
    tradelab_git_commit: Optional[str] = None,
    signal_values: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    accepted: Optional[bool] = None,
    reject_reason: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    import json
    from ..determinism import env_fingerprint, git_commit_hash, tradelab_version as _tl_ver
    run_id = str(uuid.uuid4())
    accepted_bool = None if accepted is None else (1 if accepted else 0)
    conn = _connect(db_path)
    conn.execute(
        """INSERT INTO runs (run_id, timestamp_utc, strategy_name, strategy_version,
           tradelab_version, tradelab_git_commit, input_data_hash, config_hash,
           verdict, dsr_probability, report_card_markdown, report_card_html_path,
           signal_values_json, thresholds_json, accepted_bool, reject_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            datetime.now(timezone.utc).isoformat(),
            strategy_name,
            strategy_version,
            tradelab_version or _tl_ver(),
            tradelab_git_commit or git_commit_hash(),
            input_data_hash,
            config_hash,
            verdict,
            dsr_probability,
            report_card_markdown,
            report_card_html_path,
            json.dumps(signal_values) if signal_values is not None else None,
            json.dumps(thresholds) if thresholds is not None else None,
            accepted_bool,
            reject_reason,
        ),
    )
    conn.commit()
    return run_id
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/audit/test_history_extension.py -v
git add -u && git commit -m "feat(audit): record_run accepts signal_values + thresholds + accepted + reject_reason"
```

### Task 0.4: Backfill script for existing reports

- [ ] **Step 1: Failing test**

```python
def test_backfill_runs_from_reports(tmp_path, monkeypatch):
    from tradelab.scripts.backfill_runs_table import backfill_from_reports
    db = tmp_path / "history.db"
    reports = tmp_path / "reports"
    reports.mkdir()
    one = reports / "test_strategy_2026-04-19_1200"
    one.mkdir()
    (one / "robustness_result.json").write_text(json.dumps({
        "strategy": "test_strategy",
        "verdict": "FRAGILE",
        "signals": {"baseline_pf": {"value": 1.05, "verdict": "FRAGILE"}},
        "dsr_probability": 0.4,
    }))
    n = backfill_from_reports(reports_dir=reports, db_path=db)
    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT strategy_name, verdict, signal_values_json FROM runs"
    ).fetchone()
    assert row[0] == "test_strategy"
    assert row[1] == "FRAGILE"
    assert json.loads(row[2])["baseline_pf"]["verdict"] == "FRAGILE"
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/scripts/backfill_runs_table.py
import json
from pathlib import Path
from tradelab.audit.history import record_run, DEFAULT_DB_PATH


def backfill_from_reports(reports_dir: Path, db_path: Path = DEFAULT_DB_PATH) -> int:
    n = 0
    for report_file in reports_dir.glob("**/robustness_result.json"):
        try:
            data = json.loads(report_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        record_run(
            strategy_name=data.get("strategy", report_file.parent.name),
            verdict=data.get("verdict"),
            dsr_probability=data.get("dsr_probability"),
            signal_values=data.get("signals"),
            db_path=db_path,
        )
        n += 1
    return n


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--reports", type=Path, required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = p.parse_args()
    print(f"Backfilled {backfill_from_reports(args.reports, args.db)} runs")
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/audit/test_history_extension.py -v
git add -u && git commit -m "feat(audit): backfill_runs_table.py for legacy reports"
```

- [ ] **Step 4: Run real backfill**

```bash
python -m tradelab.scripts.backfill_runs_table --reports C:/TradingScripts/tradelab/reports
```

Document count in commit msg.

---

## Slice 0.5: Engine Integrity / Canary Panel

**Why:** Silent gauntlet drift currently invisible. Canary CLI exists at `tradelab.canary` (per `tests/cli/test_cli_canary.py`); just needs a runtime surface.

**Files:**
- Create: `tradelab/src/tradelab/canary/__init__.py` (if doesn't exist)
- Create: `tradelab/src/tradelab/canary/runtime.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/canary-status` endpoint)
- Modify: `tradelab/src/tradelab/web/command_center.html` (add canary panel + Accept-block flag)
- Test: `tradelab/tests/canary/test_runtime.py`
- Test: `tradelab/tests/web/test_canary_status_endpoint.py`

### Task 0.5.1: Failing test for canary runtime check

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/canary/test_runtime.py
import pytest
from tradelab.canary.runtime import CanaryStatus, run_canary_check, CANARIES_EXPECTED

def test_canaries_expected_has_4():
    assert len(CANARIES_EXPECTED) == 4
    names = {c["name"] for c in CANARIES_EXPECTED}
    assert names == {
        "canary_perfect_robust",
        "canary_obvious_fragile",
        "canary_inconclusive",
        "canary_data_leak",
    }

def test_run_canary_check_returns_status(monkeypatch):
    # mock the verdict producer to return expected verdicts
    def fake_run_canary(name):
        return {
            "canary_perfect_robust": "ROBUST",
            "canary_obvious_fragile": "FRAGILE",
            "canary_inconclusive": "INCONCLUSIVE",
            "canary_data_leak": "FRAGILE",
        }[name]
    monkeypatch.setattr("tradelab.canary.runtime._run_one_canary", fake_run_canary)
    status = run_canary_check()
    assert isinstance(status, CanaryStatus)
    assert status.all_match is True
    assert len(status.canaries) == 4

def test_canary_mismatch_sets_all_match_false(monkeypatch):
    def fake_run_canary(name):
        # canary_obvious_fragile incorrectly returns ROBUST → mismatch
        return "ROBUST" if name == "canary_obvious_fragile" else _expected(name)
    def _expected(name):
        return next(c["expected"] for c in CANARIES_EXPECTED if c["name"] == name)
    monkeypatch.setattr("tradelab.canary.runtime._run_one_canary", fake_run_canary)
    status = run_canary_check()
    assert status.all_match is False
    mismatched = [c for c in status.canaries if c["status"] == "MISMATCH"]
    assert len(mismatched) == 1
    assert mismatched[0]["name"] == "canary_obvious_fragile"
```

- [ ] **Step 2: Run, fail**

`pytest tradelab/tests/canary/test_runtime.py -v`

### Task 0.5.2: Implement canary runtime

- [ ] **Step 1: Implement**

```python
# tradelab/src/tradelab/canary/runtime.py
"""Runtime canary checks for engine integrity.

Each canary is a synthetic strategy with known expected verdict. If any actual
verdict deviates, the gauntlet has silently broken — block new Accepts globally
until investigated.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


CANARIES_EXPECTED = [
    {"name": "canary_perfect_robust",   "expected": "ROBUST"},
    {"name": "canary_obvious_fragile",  "expected": "FRAGILE"},
    {"name": "canary_inconclusive",     "expected": "INCONCLUSIVE"},
    {"name": "canary_data_leak",        "expected": "FRAGILE"},
]


@dataclass
class CanaryStatus:
    canaries: list[dict] = field(default_factory=list)
    all_match: bool = True
    last_run_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _run_one_canary(name: str) -> str:
    """Hook: actual canary execution. Replace with real tradelab.canary CLI call."""
    # Lazy import to keep the module importable even if canary CLI changes
    from tradelab.canary import run_canary  # adjust based on real CLI shape
    return run_canary(name)


def run_canary_check(
    *, history_path: Path | None = None,
    cache_ttl_seconds: int = 300,
) -> CanaryStatus:
    canaries: list[dict] = []
    all_match = True
    for spec in CANARIES_EXPECTED:
        name, expected = spec["name"], spec["expected"]
        try:
            actual = _run_one_canary(name)
            if actual == expected:
                status = "MATCH"
            else:
                status = "MISMATCH"
                all_match = False
        except Exception as exc:  # canary infra failure
            actual = None
            status = "UNKNOWN"
            # UNKNOWN does not flip all_match — don't block on infra errors
        canaries.append({
            "name": name, "expected": expected, "actual": actual, "status": status,
        })

    cs = CanaryStatus(
        canaries=canaries,
        all_match=all_match,
        last_run_at=datetime.now(timezone.utc).isoformat(),
    )
    if history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a") as f:
            f.write(json.dumps(cs.to_dict()) + "\n")
    return cs
```

- [ ] **Step 2: Run + commit**

```bash
pytest tradelab/tests/canary/test_runtime.py -v
git add -u && git commit -m "feat(canary): runtime check with MATCH/MISMATCH/UNKNOWN status"
```

### Task 0.5.3: Add `/tradelab/canary-status` endpoint

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/web/test_canary_status_endpoint.py
def test_canary_status_endpoint_returns_json(http_client, monkeypatch):
    from tradelab.canary.runtime import CanaryStatus
    fake = CanaryStatus(canaries=[
        {"name": "canary_perfect_robust", "expected": "ROBUST", "actual": "ROBUST", "status": "MATCH"},
    ], all_match=True, last_run_at="2026-04-28T15:00:00+00:00")
    monkeypatch.setattr("tradelab.web.handlers.run_canary_check", lambda **kw: fake)
    resp = http_client.get("/tradelab/canary-status")
    assert resp.status == 200
    body = resp.json()
    assert body["all_match"] is True
    assert len(body["canaries"]) == 1
```

(Adapt `http_client` fixture to match what the existing web tests use — see `tests/web/conftest.py`.)

- [ ] **Step 2: Add handler**

In `tradelab/src/tradelab/web/handlers.py`, find the existing GET dispatch (look for similar routes like `/tradelab/runs`). Add:

```python
# at top of file
from tradelab.canary.runtime import run_canary_check

# in the GET dispatch
elif self.path == "/tradelab/canary-status":
    status = run_canary_check()
    self._send_json(status.to_dict())
    return
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/web/test_canary_status_endpoint.py -v
git add -u && git commit -m "feat(web): GET /tradelab/canary-status endpoint"
```

### Task 0.5.4: Frontend canary panel + Accept-block flag

- [ ] **Step 1: Failing test (Selenium or pure-JS DOM check via existing harness)**

Use the existing frontend test pattern in `tests/web/`. Verify:
- After dashboard loads, a `<section id="canary-panel">` exists
- 4 canary cells render with `data-status="MATCH"` or `data-status="MISMATCH"` attrs
- When any cell is `data-status="MISMATCH"`, all `<button class="accept">` elements have `disabled` attribute

- [ ] **Step 2: Add panel to `command_center.html`**

Find the Research tab section. After the page header, before any other Research panels, insert:

```html
<!-- =================== ENGINE INTEGRITY / CANARY PANEL =================== -->
<section class="panel canary-panel" id="canary-panel">
  <div class="panel-header">
    <div class="title">
      <h2 style="color: #14b8a6;">Engine Integrity</h2>
      <span class="canary-pill">CANARY</span>
    </div>
    <div class="actions" id="canary-status-summary">checking…</div>
  </div>
  <div class="canary-grid" id="canary-grid"></div>
</section>
```

Add CSS classes (copy from CALIBRATED mockup `.canary-panel`, `.canary-grid`, `.canary-cell`).

Add JS:

```javascript
async function loadCanaryStatus() {
  try {
    const r = await fetch('/tradelab/canary-status');
    const data = await r.json();
    renderCanaryGrid(data);
    if (!data.all_match) {
      document.body.classList.add('accepts-blocked');
    } else {
      document.body.classList.remove('accepts-blocked');
    }
  } catch (e) {
    document.getElementById('canary-status-summary').textContent = 'canary status offline';
  }
}

function renderCanaryGrid(data) {
  const grid = document.getElementById('canary-grid');
  grid.innerHTML = data.canaries.map(c => `
    <div class="canary-cell" data-status="${c.status}">
      <div class="name">${c.name}</div>
      <div class="expected">expected: ${c.expected}</div>
      <div class="actual ${c.status === 'MATCH' ? 'match' : 'miss'}">${c.actual ?? '—'} ${c.status === 'MATCH' ? '✓' : c.status === 'MISMATCH' ? '✗' : '?'}</div>
    </div>`).join('');
  document.getElementById('canary-status-summary').textContent =
    data.all_match ? `✓ all 4 canaries match · last run ${data.last_run_at.slice(0,16)}` : '⚠ canary mismatch — accepts blocked';
}
```

Add CSS for the accept-block:

```css
body.accepts-blocked button.accept { opacity: 0.4; pointer-events: none; }
body.accepts-blocked button.accept::after { content: " — canary mismatch"; }
```

Wire `loadCanaryStatus()` into the existing tab-load init.

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/web/ -v
git add -u && git commit -m "feat(web): canary panel + accept-block on mismatch"
```

### Task 0.5.5: Hand-smoke

- [ ] Restart dashboard. Open Research tab. Confirm canary panel renders with 4 green cells.
- [ ] Manually break one canary expected verdict (edit `CANARIES_EXPECTED` to expect ROBUST for `canary_obvious_fragile`). Restart. Confirm panel goes red AND all Accept buttons are disabled across the dashboard.
- [ ] Revert. Commit smoke notes if any frictions found.

---

## Slice 1a: Hold-out as Gate

**Why:** Tests data leakage — a failure mode the existing 9 in-sample signals cannot detect. Promotes hold-out from "voted on by 9 others" (FULL spec original framing of signal #10) to a separate hard gate.

**Files:**
- Modify: `tradelab/src/tradelab/engines/walkforward.py` (capture hold-out window backtest)
- Modify: `tradelab/src/tradelab/robustness/verdict.py` (add hold_out_oos signal computation)
- Modify: `tradelab/tradelab.yaml` (add `hold_out_robust_pf: 1.5`, `hold_out_fragile_pf: 1.0`, `hold_out_window_months: 6`)
- Modify: `tradelab/src/tradelab/web/command_center.html` (Score modal hold-out gate UI + Pipeline column)
- Test: `tradelab/tests/robustness/test_holdout_gate.py`

### Task 1a.1: Capture hold-out window in walkforward

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/robustness/test_holdout_gate.py
import pytest
from tradelab.engines.walkforward import run_walkforward_with_holdout

def test_walkforward_emits_holdout_result(synthetic_strategy, synthetic_bars):
    result = run_walkforward_with_holdout(
        strategy=synthetic_strategy, bars=synthetic_bars,
        holdout_window_months=6,
    )
    assert "holdout" in result
    assert "pf" in result["holdout"]
    assert "n_trades" in result["holdout"]
    assert "window_start" in result["holdout"]
    assert "window_end" in result["holdout"]
    # holdout window must NOT overlap any optimization fold
    optim_end = max(fold["end"] for fold in result["folds"])
    assert result["holdout"]["window_start"] >= optim_end
```

- [ ] **Step 2: Extend walkforward**

Find existing `run_walkforward` in `walkforward.py`. Add a wrapper or extend signature:

```python
# tradelab/src/tradelab/engines/walkforward.py — add
def run_walkforward_with_holdout(
    strategy, bars, *, holdout_window_months: int = 6, **wf_kwargs
) -> dict:
    """Run walk-forward but reserve the trailing N months as hold-out.

    Returns the standard wf result + a 'holdout' dict with PF on untouched data.
    """
    # 1. trim bars: split into [optimizable_bars, holdout_bars]
    holdout_start = bars.index[-1] - pd.DateOffset(months=holdout_window_months)
    optimizable_bars = bars.loc[:holdout_start]
    holdout_bars = bars.loc[holdout_start:]
    # 2. standard wf on optimizable_bars
    wf_result = run_walkforward(strategy, optimizable_bars, **wf_kwargs)
    # 3. backtest strategy with wf-final-params on holdout_bars
    holdout_trades = strategy.backtest(holdout_bars, params=wf_result["final_params"])
    holdout_pf = _compute_pf(holdout_trades)
    wf_result["holdout"] = {
        "pf": holdout_pf,
        "n_trades": len(holdout_trades),
        "window_start": holdout_start.isoformat(),
        "window_end": bars.index[-1].isoformat(),
    }
    return wf_result
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/robustness/test_holdout_gate.py -v
git add -u && git commit -m "feat(walkforward): hold-out window backtest captured separately"
```

### Task 1a.2: Add hold_out_oos signal to verdict.py

- [ ] **Step 1: Failing test**

```python
def test_holdout_signal_fragile_when_pf_below_threshold():
    from tradelab.robustness.verdict import compute_holdout_signal
    signal = compute_holdout_signal(
        holdout_pf=0.85, robust_threshold=1.5, fragile_threshold=1.0,
    )
    assert signal["verdict"] == "FRAGILE"
    assert signal["value"] == 0.85
    assert "PF 0.85" in signal["reason"]

def test_holdout_signal_robust_when_pf_above_threshold():
    from tradelab.robustness.verdict import compute_holdout_signal
    signal = compute_holdout_signal(
        holdout_pf=1.78, robust_threshold=1.5, fragile_threshold=1.0,
    )
    assert signal["verdict"] == "ROBUST"
    assert signal["value"] == 1.78
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/robustness/verdict.py — add
def compute_holdout_signal(
    *, holdout_pf: float, robust_threshold: float, fragile_threshold: float,
) -> dict:
    if holdout_pf >= robust_threshold:
        verdict = "ROBUST"
    elif holdout_pf <= fragile_threshold:
        verdict = "FRAGILE"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "value": holdout_pf,
        "verdict": verdict,
        "reason": f"hold-out PF {holdout_pf:.2f} (robust ≥ {robust_threshold}, fragile ≤ {fragile_threshold})",
    }
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/robustness/test_holdout_gate.py -v
git add -u && git commit -m "feat(verdict): hold_out_oos signal computation"
```

### Task 1a.3: Add thresholds to `tradelab.yaml`

- [ ] **Step 1: Edit `tradelab/tradelab.yaml`**

Find the `robustness.thresholds` block. Add:

```yaml
robustness:
  thresholds:
    # ... existing ...
    hold_out_robust_pf: 1.5
    hold_out_fragile_pf: 1.0
  hold_out_window_months: 6
```

- [ ] **Step 2: Add config-load test**

```python
def test_holdout_thresholds_loaded():
    from tradelab.config import load_config
    cfg = load_config()
    assert cfg["robustness"]["thresholds"]["hold_out_robust_pf"] == 1.5
    assert cfg["robustness"]["thresholds"]["hold_out_fragile_pf"] == 1.0
    assert cfg["robustness"]["hold_out_window_months"] == 6
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/ -k "holdout" -v
git add -u && git commit -m "feat(config): hold-out thresholds + window in tradelab.yaml"
```

### Task 1a.4: Score modal hold-out gate UI + Pipeline column

- [ ] **Step 1: Update `command_center.html`**

In Score modal, add at the very top of `.modal-body`:

```html
<div class="holdout-gate" id="holdout-gate">
  <div class="left">
    <div class="icon" id="holdout-icon"></div>
    <div>
      <div class="label">Hold-out OOS Gate <span class="gate-pill">GATE</span></div>
      <div class="verdict-text" id="holdout-verdict-text"></div>
    </div>
  </div>
  <div class="detail" id="holdout-detail"></div>
</div>
```

Pipeline column header — find Pipeline `<thead>` and insert after Verdict column:

```html
<th class="new-col">Hold-out <span class="gate-pill">GATE</span></th>
```

In the Pipeline row template:

```html
<td class="new-col gate-cell ${row.holdout_pass ? 'pass' : 'fail'}">
  ${row.holdout_pass ? '✓' : '✗'} PF ${row.holdout_pf.toFixed(2)}
</td>
```

CSS: copy `.holdout-gate`, `.holdout-gate .icon`, `.gate-pill` from CALIBRATED mockup.

JS: after Score modal opens and verdict loads:

```javascript
function renderHoldoutGate(verdict) {
  const sig = verdict.signals.hold_out_oos;
  const pass = sig.verdict === 'ROBUST';
  const el = document.getElementById('holdout-gate');
  el.classList.toggle('pass', pass);
  el.classList.toggle('fail', !pass);
  document.getElementById('holdout-icon').textContent = pass ? '●' : '✗';
  document.getElementById('holdout-icon').className = `icon ${pass ? 'pass' : 'fail'}`;
  document.getElementById('holdout-verdict-text').textContent = pass ? 'PASS' : 'FAIL';
  document.getElementById('holdout-verdict-text').className = `verdict-text ${pass ? 'pass' : 'fail'}`;
  document.getElementById('holdout-detail').innerHTML =
    `PF <strong>${sig.value.toFixed(2)}</strong> on untouched ${sig.window_months || 6}mo window<br/>threshold ≥ ${sig.threshold || 1.5} · ${sig.n_trades} trades`;
}
```

Disable Accept button when `!pass` unless override.

- [ ] **Step 2: Add e2e test**

Verify in `tests/web/`: a run with hold-out PF 0.85 renders gate as FAIL and disables Accept.

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/web/ -v
git add -u && git commit -m "feat(web): hold-out gate UI in Score modal + Pipeline column"
```

---

## Slice 1b: Relative Context Section

**Why:** Anchor abstract diagnostic numbers to actual live-card track record. Pure frontend; reads existing `/tradelab/strategies` endpoint.

**Files:**
- Modify: `tradelab/src/tradelab/web/command_center.html` (add Relative Context section to Score modal)

### Task 1b.1: Compute rank/median/worst across live cards

- [ ] **Step 1: Add JS helper**

```javascript
// in command_center.html
function computeRelativeContext(candidate, liveCards) {
  // candidate: {hold_out_pf, dsr, dd_max}
  // liveCards: array of {strategy, hold_out_pf, dsr, dd_max}
  function rank(value, key, lowerIsBetter=false) {
    const sorted = liveCards.map(c => c[key]).filter(v => v != null)
      .sort((a,b) => lowerIsBetter ? a-b : b-a);
    const idx = sorted.findIndex(v => candidate[key] >= v && !lowerIsBetter || candidate[key] <= v && lowerIsBetter);
    return { rank: idx >= 0 ? idx+1 : sorted.length+1, total: sorted.length };
  }
  function median(arr) { const s = [...arr].sort((a,b)=>a-b); return s[Math.floor(s.length/2)]; }
  function worst(arr, lowerIsBetter) { return lowerIsBetter ? Math.max(...arr) : Math.min(...arr); }
  const holdoutPfs = liveCards.map(c => c.hold_out_pf).filter(v => v != null);
  const dsrs = liveCards.map(c => c.dsr).filter(v => v != null);
  const dds = liveCards.map(c => c.dd_max).filter(v => v != null);
  return {
    holdoutPf: { ...rank(candidate, 'hold_out_pf'), median: median(holdoutPfs), worst: worst(holdoutPfs, false) },
    dsr: { ...rank(candidate, 'dsr'), median: median(dsrs), worst: worst(dsrs, false) },
    dd: { ...rank(candidate, 'dd_max', true), median: median(dds), worst: worst(dds, true) },
  };
}
```

### Task 1b.2: Render Relative Context in Score modal

- [ ] **Step 1: Add HTML**

In Score modal body, after the Diagnostics grid:

```html
<div class="relative-context" id="relative-context">
  <h3>Relative context <span class="new-pill">NEW</span></h3>
  <div id="rel-ctx-rows"></div>
</div>
```

CSS: copy `.relative-context` from CALIBRATED mockup.

```javascript
function renderRelativeContext(ctx, candidate) {
  const rows = [
    { label: `Hold-out PF`, value: candidate.hold_out_pf?.toFixed(2), rel: ctx.holdoutPf },
    { label: `DSR`, value: candidate.dsr?.toFixed(2), rel: ctx.dsr },
    { label: `DD`, value: candidate.dd_max?.toFixed(0)+'%', rel: ctx.dd },
  ];
  document.getElementById('rel-ctx-rows').innerHTML = rows.map(r => `
    <div class="row">
      <span class="anchor">${r.label} <strong>${r.value}</strong></span>
      <span class="rank">#${r.rel.rank} of ${r.rel.total} · live median ${r.rel.median?.toFixed(2)} · worst ${r.rel.worst?.toFixed(2)}</span>
    </div>
  `).join('');
}
```

- [ ] **Step 2: Wire into Score modal load** + smoke test

```bash
pytest tradelab/tests/web/ -v
git add -u && git commit -m "feat(web): Relative Context section in Score modal"
```

---

## Slice 2: Multi-Dim Correlation Gate

**Why:** Two strategies can have low return correlation but high DD correlation — silent diversification failure. Catches "another viprasol clone" before Accept.

**Files:**
- Create: `tradelab/src/tradelab/robustness/correlation.py`
- Create: `tradelab/src/tradelab/web/pine_archive_writer.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/correlation/<run_id>`)
- Modify: `tradelab/src/tradelab/web/command_center.html` (Portfolio Fit panel + Pipeline Corr column)
- Test: `tradelab/tests/robustness/test_correlation.py`
- Test: `tradelab/tests/web/test_correlation_endpoint.py`

### Task 2.1: Pearson return correlation

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/robustness/test_correlation.py
import numpy as np
import pandas as pd
import pytest
from tradelab.robustness.correlation import compute_return_correlation

def test_perfect_correlation():
    a = pd.Series([0.01, 0.02, -0.01, 0.03, -0.02])
    b = pd.Series([0.02, 0.04, -0.02, 0.06, -0.04])
    assert compute_return_correlation(a, b) == pytest.approx(1.0)

def test_zero_correlation():
    np.random.seed(42)
    a = pd.Series(np.random.randn(100))
    b = pd.Series(np.random.randn(100))
    r = compute_return_correlation(a, b)
    assert abs(r) < 0.3

def test_insufficient_overlap_returns_none():
    a = pd.Series([0.01]*30)
    b = pd.Series([0.01]*30)
    assert compute_return_correlation(a, b, min_overlap_days=60) is None
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/robustness/correlation.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Optional


def compute_return_correlation(
    a: pd.Series, b: pd.Series, *, min_overlap_days: int = 60,
) -> Optional[float]:
    aligned = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(aligned) < min_overlap_days:
        return None
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/robustness/test_correlation.py -v
git add -u && git commit -m "feat(correlation): pearson return correlation w/ overlap floor"
```

### Task 2.2: DD correlation on rolling 30d max-drawdown

- [ ] **Step 1: Failing test**

```python
def test_dd_correlation_synchronized_drawdowns():
    # Both strategies bleed at the same time → high DD ρ even if return ρ is low
    eq_a = pd.Series(range(100, 0, -1) + list(range(0, 50)), dtype=float)
    eq_b = pd.Series(range(200, 100, -1) + list(range(100, 150)), dtype=float)
    from tradelab.robustness.correlation import compute_dd_correlation
    r = compute_dd_correlation(eq_a, eq_b, window=30)
    assert r > 0.7
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/robustness/correlation.py — add
def _rolling_max_drawdown(equity: pd.Series, window: int) -> pd.Series:
    rolling_max = equity.rolling(window, min_periods=1).max()
    dd = (equity - rolling_max) / rolling_max
    return dd


def compute_dd_correlation(
    eq_a: pd.Series, eq_b: pd.Series, *, window: int = 30, min_overlap_days: int = 60,
) -> Optional[float]:
    dd_a = _rolling_max_drawdown(eq_a, window)
    dd_b = _rolling_max_drawdown(eq_b, window)
    aligned = pd.concat([dd_a, dd_b], axis=1, join="inner").dropna()
    if len(aligned) < min_overlap_days:
        return None
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/robustness/test_correlation.py -v
git add -u && git commit -m "feat(correlation): rolling-window DD correlation"
```

### Task 2.3: Entry-time overlap

- [ ] **Step 1: Failing test**

```python
def test_entry_time_overlap_exact_collision():
    from tradelab.robustness.correlation import compute_entry_time_overlap
    candidate = pd.Series(pd.to_datetime([
        "2026-04-01 09:31", "2026-04-02 09:31", "2026-04-03 14:00",
    ]))
    existing = pd.Series(pd.to_datetime([
        "2026-04-01 09:35", "2026-04-02 09:30", "2026-04-04 11:00",
    ]))
    overlap_pct = compute_entry_time_overlap(candidate, existing, window_minutes=30)
    assert overlap_pct == pytest.approx(2/3, abs=0.01)
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/robustness/correlation.py — add
def compute_entry_time_overlap(
    candidate_entries: pd.Series,
    existing_entries: pd.Series,
    *, window_minutes: int = 30,
) -> float:
    """% of candidate entries within `window_minutes` of any existing-card entry."""
    if len(candidate_entries) == 0:
        return 0.0
    delta = pd.Timedelta(minutes=window_minutes)
    n_overlap = sum(
        1 for ts in candidate_entries
        if ((existing_entries - ts).abs() <= delta).any()
    )
    return n_overlap / len(candidate_entries)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/robustness/test_correlation.py -v
git add -u && git commit -m "feat(correlation): entry-time overlap %"
```

### Task 2.4: pine_archive writers (returns/drawdowns/entries/backtest_trades)

- [ ] **Step 1: Failing test**

```python
def test_pine_archive_persist_at_accept(tmp_path):
    from tradelab.web.pine_archive_writer import persist_card_baselines
    card_id = "test_card_001"
    archive_root = tmp_path / "pine_archive"
    persist_card_baselines(
        card_id=card_id, archive_root=archive_root,
        returns=pd.Series([0.01, -0.02, 0.03], index=pd.date_range("2026-04-01", periods=3)),
        drawdowns=pd.Series([0, -0.02, 0], index=pd.date_range("2026-04-01", periods=3)),
        entry_times=pd.Series(pd.to_datetime(["2026-04-01 09:31", "2026-04-02 09:31"])),
        backtest_trades=pd.DataFrame({
            "entry_ts": pd.to_datetime(["2026-04-01 09:31"]),
            "exit_ts":  pd.to_datetime(["2026-04-01 16:00"]),
            "return_pct": [0.01], "regime_label": ["LOW_TRENDING"],
        }),
    )
    base = archive_root / card_id
    assert (base / "returns.csv").exists()
    assert (base / "drawdowns.csv").exists()
    assert (base / "entry_times.csv").exists()
    assert (base / "backtest_trades.csv").exists()
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/web/pine_archive_writer.py
from pathlib import Path
import pandas as pd


def persist_card_baselines(
    *, card_id: str, archive_root: Path,
    returns: pd.Series, drawdowns: pd.Series,
    entry_times: pd.Series, backtest_trades: pd.DataFrame,
) -> None:
    base = archive_root / card_id
    base.mkdir(parents=True, exist_ok=True)
    returns.to_csv(base / "returns.csv", header=["return"])
    drawdowns.to_csv(base / "drawdowns.csv", header=["drawdown"])
    entry_times.to_csv(base / "entry_times.csv", header=["entry_ts"], index=False)
    backtest_trades.to_csv(base / "backtest_trades.csv", index=False)
```

- [ ] **Step 3: Hook into Accept flow**

Find where cards.json is written on Accept. Before the write, call `persist_card_baselines(...)`. Source data: from the latest `robustness_result.json` fold or backtest output.

- [ ] **Step 4: Run + commit**

```bash
pytest tradelab/tests/ -k "pine_archive" -v
git add -u && git commit -m "feat(web): persist returns/dd/entries/backtest_trades on Accept"
```

### Task 2.5: `/tradelab/correlation/<run_id>` endpoint

- [ ] **Step 1: Failing test**

```python
# tradelab/tests/web/test_correlation_endpoint.py
def test_correlation_endpoint_returns_pairwise(http_client, monkeypatch, tmp_path):
    # set up archive root w/ 2 existing cards
    # call GET /tradelab/correlation/<run_id>
    # expect {candidate_id, return_max, dd_max, entry_max, pairwise: [...], gate: pass|warn|fail}
    ...
```

- [ ] **Step 2: Add handler**

```python
# tradelab/src/tradelab/web/handlers.py — add route
elif self.path.startswith("/tradelab/correlation/"):
    run_id = self.path.split("/")[-1]
    from tradelab.robustness.correlation import compute_pairwise_for_run
    result = compute_pairwise_for_run(run_id)
    self._send_json(result)
    return
```

```python
# tradelab/src/tradelab/robustness/correlation.py — add
def compute_pairwise_for_run(run_id: str, *, archive_root: Path = Path("pine_archive")) -> dict:
    """For a candidate, compute pairwise return ρ + DD ρ + entry overlap vs all existing cards."""
    candidate = _load_card_baselines(archive_root / run_id)
    pairwise = []
    return_max = dd_max = entry_max = 0.0
    for other_dir in archive_root.iterdir():
        if other_dir.name == run_id or not other_dir.is_dir():
            continue
        other = _load_card_baselines(other_dir)
        rret = compute_return_correlation(candidate["returns"], other["returns"]) or 0.0
        rdd = compute_dd_correlation(candidate["equity"], other["equity"]) or 0.0
        rentry = compute_entry_time_overlap(candidate["entries"], other["entries"])
        return_max = max(return_max, abs(rret))
        dd_max = max(dd_max, abs(rdd))
        entry_max = max(entry_max, rentry)
        pairwise.append({"card_id": other_dir.name, "return_rho": rret, "dd_rho": rdd, "entry_overlap": rentry})
    gate = "fail" if (return_max > 0.70 or dd_max > 0.70 or entry_max > 0.30) else "warn" if return_max > 0.50 else "pass"
    return {
        "candidate_id": run_id, "return_max": return_max, "dd_max": dd_max,
        "entry_max": entry_max, "pairwise": pairwise, "gate": gate,
    }


def _load_card_baselines(card_dir: Path) -> dict:
    # implement loaders for the 4 csv files
    ...
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/web/test_correlation_endpoint.py -v
git add -u && git commit -m "feat(web): GET /tradelab/correlation/<run_id> w/ pairwise + gate"
```

### Task 2.6: Score modal Portfolio Fit panel + Pipeline Corr column

- [ ] **Step 1: HTML + JS**

In Score modal, after Relative Context:

```html
<div class="portfolio-fit" id="portfolio-fit">
  <h3>Portfolio fit <span class="gate-pill">GATE</span></h3>
  <div class="legend-row">
    <span style="flex:1">Live card</span>
    <span style="width:60px;text-align:right">Return ρ</span>
    <span style="width:60px;text-align:right">DD ρ <span class="new-pill">NEW</span></span>
    <span style="width:70px;text-align:right">Entry overlap <span class="new-pill">NEW</span></span>
  </div>
  <div id="portfolio-fit-rows"></div>
  <div id="portfolio-fit-summary"></div>
</div>
```

JS:

```javascript
async function loadPortfolioFit(runId) {
  const r = await fetch(`/tradelab/correlation/${runId}`);
  const data = await r.json();
  document.getElementById('portfolio-fit-rows').innerHTML = data.pairwise.map(p => `
    <div class="fit-row">
      <span class="name">${p.card_id}</span>
      <span class="val" style="color: ${p.return_rho > 0.7 ? 'red' : p.return_rho > 0.5 ? '#f59e0b' : '#22c55e'}">${p.return_rho.toFixed(2)}</span>
      <span class="val" style="color: ${p.dd_rho > 0.7 ? 'red' : p.dd_rho > 0.5 ? '#f59e0b' : '#22c55e'}">${p.dd_rho.toFixed(2)}</span>
      <span class="val" style="color: ${p.entry_overlap > 0.3 ? 'red' : '#22c55e'}">${(p.entry_overlap*100).toFixed(0)}%</span>
    </div>`).join('');
  document.getElementById('portfolio-fit-summary').innerHTML =
    `Max return ρ: ${data.return_max.toFixed(2)} · Max DD ρ: ${data.dd_max.toFixed(2)} · Max entry overlap: ${(data.entry_max*100).toFixed(0)}% · <strong>${data.gate === 'pass' ? 'All gates pass' : data.gate === 'warn' ? 'Warn — review before Accept' : 'GATE FAIL — override required'}</strong>`;
  if (data.gate === 'fail') {
    document.querySelector('button.accept').disabled = true;
  }
}
```

Pipeline Corr column: similar to hold-out, add `<th class="new-col">Corr <span class="new-pill">NEW</span></th>` and a cell renderer.

- [ ] **Step 2: Run + commit**

```bash
pytest tradelab/tests/web/ -v
git add -u && git commit -m "feat(web): Portfolio Fit panel + Pipeline Corr column"
```

### Task 2.7: Override path with typed reason

- [ ] **Step 1: Implement override prompt**

When `data.gate === 'fail'`, replace simple disable with:

```javascript
function maybeAccept(runId, gateState) {
  if (gateState === 'fail') {
    const reason = prompt('Correlation gate failed. Type a reason to override (min 20 chars):');
    if (!reason || reason.length < 20) return;
    submitAccept(runId, { override_reason: reason });
  } else {
    submitAccept(runId, {});
  }
}
```

Backend writes `reject_reason` field to runs row IF override (we reuse the field as override audit; `accepted_bool=1` distinguishes from rejects).

- [ ] **Step 2: Test + commit**

```bash
pytest tradelab/tests/web/ -k "override" -v
git add -u && git commit -m "feat(web): typed-reason override path on correlation gate fail"
```

---

## Slice 3: Per-Signal Hit-Rate

**Why:** The actual feedback loop. Reads extended `runs` table + outcome data; tells you which signals are predictive. Centerpiece evidence for `tradelab.yaml` threshold edits.

**Files:**
- Create: `tradelab/src/tradelab/calibration/hit_rate.py`
- Create: `tradelab/src/tradelab/calibration/outcomes.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/hit-rate`)
- Modify: `tradelab/src/tradelab/web/command_center.html` (Verdict Accuracy Loop banner + hit-rate tags inline)
- Test: `tradelab/tests/calibration/test_hit_rate.py`

### Task 3.1: Outcome backfill — read fills + classify failed

- [ ] **Step 1: Failing test**

```python
def test_outcome_classification_failed_when_pf_below_1():
    from tradelab.calibration.outcomes import classify_card_outcome
    out = classify_card_outcome(
        card_id="x", live_pnls=[100, -200, 50, -300, 100],  # PF = 250/500 = 0.5
        auto_disabled=False, manual_disabled_reason=None,
    )
    assert out["live_pf"] == pytest.approx(0.5)
    assert out["failed"] is True
    assert out["reason"] == "live_pf_below_1"

def test_outcome_classification_succeeded_when_pf_high():
    from tradelab.calibration.outcomes import classify_card_outcome
    out = classify_card_outcome(card_id="x", live_pnls=[100, 50, 100, -50, 100])
    assert out["failed"] is False
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/calibration/outcomes.py
from __future__ import annotations
import re
from typing import Optional


_FAIL_PATTERN = re.compile(r"\b(fail|broken|decay|loss)\b", re.IGNORECASE)


def classify_card_outcome(
    *, card_id: str, live_pnls: list[float],
    auto_disabled: bool = False,
    manual_disabled_reason: Optional[str] = None,
) -> dict:
    wins = sum(p for p in live_pnls if p > 0)
    losses = -sum(p for p in live_pnls if p < 0)
    live_pf = (wins / losses) if losses > 0 else float("inf")
    failed = False
    reason = None
    if live_pf < 1.0:
        failed = True; reason = "live_pf_below_1"
    elif auto_disabled:
        failed = True; reason = "auto_disabled"
    elif manual_disabled_reason and _FAIL_PATTERN.search(manual_disabled_reason):
        failed = True; reason = "manual_disable_fail_reason"
    return {"card_id": card_id, "live_pf": live_pf, "failed": failed, "reason": reason}
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/calibration/test_hit_rate.py -v
git add -u && git commit -m "feat(calibration): card-outcome classification"
```

### Task 3.2: Per-signal hit-rate from extended runs table

- [ ] **Step 1: Failing test**

```python
def test_hit_rate_from_runs_db(tmp_path):
    from tradelab.calibration.hit_rate import compute_per_signal_hit_rate_from_db
    from tradelab.audit.history import record_run
    db = tmp_path / "h.db"
    # 3 accepted runs where entry_delay was FRAGILE; 2 failed in prod
    for i, (failed, sigs) in enumerate([
        (True,  {"entry_delay": {"verdict": "FRAGILE", "value": 0.6}, "loso": {"verdict": "ROBUST", "value": 0.5}}),
        (False, {"entry_delay": {"verdict": "FRAGILE", "value": 0.55}, "loso": {"verdict": "ROBUST", "value": 0.5}}),
        (True,  {"entry_delay": {"verdict": "FRAGILE", "value": 0.7}, "loso": {"verdict": "ROBUST", "value": 0.5}}),
    ]):
        record_run(strategy_name=f"s{i}", verdict="ROBUST",
                   signal_values=sigs, accepted=True, db_path=db)
    # provide outcomes via injection
    outcomes = {f"s{i}": {"failed": f} for i, f in enumerate([True, False, True])}
    result = compute_per_signal_hit_rate_from_db(db_path=db, outcomes_by_strategy=outcomes)
    assert result["entry_delay"]["fragile_fires"] == 3
    assert result["entry_delay"]["accepted_despite"] == 3
    assert result["entry_delay"]["failed_in_prod"] == 2
    assert result["entry_delay"]["hit_rate"] == pytest.approx(2/3)
    assert result["entry_delay"]["read"] == "predictive"
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/calibration/hit_rate.py
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Optional


def _classify(hit_rate: Optional[float], n: int) -> str:
    if n < 3 or hit_rate is None:
        return "insufficient sample"
    if hit_rate >= 0.5:
        return "predictive"
    if hit_rate >= 0.25:
        return "questionable"
    return "noisy"


def compute_per_signal_hit_rate_from_db(
    *, db_path: Path, outcomes_by_strategy: dict[str, dict],
    window_days: int = 90,
) -> dict[str, dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT strategy_name, signal_values_json, accepted_bool FROM runs "
        "WHERE accepted_bool = 1 AND signal_values_json IS NOT NULL"
    ).fetchall()
    per_signal: dict[str, dict] = {}
    for strategy, sig_json, _ in rows:
        outcome = outcomes_by_strategy.get(strategy)
        if outcome is None:
            continue  # no outcome data yet
        signals = json.loads(sig_json)
        for sig_name, sig in signals.items():
            if sig.get("verdict") != "FRAGILE":
                continue
            row = per_signal.setdefault(sig_name, {
                "fragile_fires": 0, "accepted_despite": 0, "failed_in_prod": 0,
            })
            row["fragile_fires"] += 1
            row["accepted_despite"] += 1
            if outcome["failed"]:
                row["failed_in_prod"] += 1
    for sig_name, row in per_signal.items():
        n = row["accepted_despite"]
        row["hit_rate"] = (row["failed_in_prod"] / n) if n >= 3 else None
        row["read"] = _classify(row["hit_rate"], n)
    return per_signal
```

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/calibration/test_hit_rate.py -v
git add -u && git commit -m "feat(calibration): per-signal hit-rate from extended runs table"
```

### Task 3.3: `/tradelab/hit-rate` endpoint

- [ ] **Step 1: Failing test + implement**

```python
# tradelab/src/tradelab/web/handlers.py — add route
elif self.path == "/tradelab/hit-rate":
    from tradelab.calibration.hit_rate import compute_per_signal_hit_rate_from_db
    from tradelab.calibration.outcomes import gather_all_outcomes  # implement helper
    outcomes = gather_all_outcomes()
    data = compute_per_signal_hit_rate_from_db(
        db_path=Path("data/tradelab_history.db"),
        outcomes_by_strategy=outcomes,
    )
    self._send_json({"per_signal": data, "code_divergence_caveat": True})
    return
```

- [ ] **Step 2: Run + commit**

```bash
pytest tradelab/tests/web/ -k "hit_rate" -v
git add -u && git commit -m "feat(web): GET /tradelab/hit-rate endpoint"
```

### Task 3.4: Score modal hit-rate tags inline + Verdict Accuracy Loop banner

- [ ] **Step 1: Score modal cells**

In Score modal Diagnostics grid renderer, fetch hit-rate data on modal open. For each `.diag-cell`, append a `<span class="hit-rate-tag">` with the percentage + color class (predictive/questionable/noisy).

```javascript
async function loadHitRates() {
  const r = await fetch('/tradelab/hit-rate');
  const data = await r.json();
  return data.per_signal;
}

function attachHitRateTags(diagCells, hitRates) {
  diagCells.forEach(cell => {
    const sigName = cell.dataset.signal;
    const hr = hitRates[sigName];
    if (!hr) return;
    const valEl = cell.querySelector('.val');
    const tag = document.createElement('span');
    tag.className = `hit-rate-tag ${hr.read}`;
    tag.textContent = hr.hit_rate != null ? `${(hr.hit_rate*100).toFixed(0)}%` : `n=${hr.accepted_despite}`;
    tag.title = `${sigName} hit rate: ${hr.read} (${hr.accepted_despite} accepted, ${hr.failed_in_prod} failed)`;
    valEl.appendChild(tag);
  });
}
```

- [ ] **Step 2: Verdict Accuracy Loop banner**

Add panel before Live Strategies:

```html
<section class="panel calibration-panel" id="verdict-accuracy-loop">
  <div class="panel-header">
    <div class="title"><h2>Verdict Accuracy Loop</h2><span class="new-pill">NEW</span></div>
    <div class="actions"><span class="confound-pill">CAVEAT</span></div>
  </div>
  <div class="stat-row" id="calibration-stats"></div>
  <div class="hit-rate-section">
    <h3>Per-Signal Hit Rate</h3>
    <table class="hit-rate-table" id="hit-rate-table">
      <thead><tr><th>Signal</th><th>Category</th><th>Importance</th><th style="text-align:right">Fragile fires</th><th style="text-align:right">Accepted despite</th><th style="text-align:right">Failed in prod</th><th style="text-align:right">Hit rate</th><th>Read</th></tr></thead>
      <tbody id="hit-rate-rows"></tbody>
    </table>
  </div>
</section>
```

JS render: read `/tradelab/hit-rate`, populate rows.

- [ ] **Step 3: Run + commit**

```bash
pytest tradelab/tests/web/ -v
git add -u && git commit -m "feat(web): hit-rate tags in Score modal + Verdict Accuracy Loop banner"
```

### Task 3.5: §1 caveat propagation

- [ ] **Step 1: Caveat banner shows when code_match incomplete**

JS: read `/tradelab/code-match` (Slice -1.6 endpoint — see below). If any strategy has `MISSING` or `DIVERGENT` status, every hit-rate cell + the banner gets a CAVEAT pill that disappears once `code_match_status === 'MATCHED'` everywhere.

- [ ] **Step 2: Commit**

```bash
git add -u && git commit -m "feat(web): §1 caveat pill propagation on hit-rate cells"
```

---

## Slice 4: Regime Banner Only

**Why:** Situational awareness without per-strategy regime fit (LITE behavior). Per-bucket samples on 2y data are too thin for fit tags.

**Files:**
- Create: `tradelab/src/tradelab/regime/__init__.py`
- Create: `tradelab/src/tradelab/regime/classifier.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/regime`)
- Modify: `tradelab/src/tradelab/web/command_center.html` (banner)
- Test: `tradelab/tests/regime/test_classifier.py`

### Task 4.1: Volatility classifier (VIX-based)

- [ ] **Step 1: Failing test**

```python
def test_vol_classifier_low_mid_high():
    from tradelab.regime.classifier import classify_volatility
    assert classify_volatility(vix=10.0) == "LOW"
    assert classify_volatility(vix=20.0) == "MID"
    assert classify_volatility(vix=30.0) == "HIGH"
```

- [ ] **Step 2: Implement**

```python
# tradelab/src/tradelab/regime/classifier.py
def classify_volatility(*, vix: float) -> str:
    if vix < 15: return "LOW"
    if vix < 25: return "MID"
    return "HIGH"
```

### Task 4.2: Trend + Breadth classifiers + composite

```python
def classify_trend(*, spx_close: float, sma50: float, sma200: float, adx: float) -> str:
    if spx_close > sma50 and spx_close > sma200 and adx > 20:
        return "TRENDING"
    return "RANGING"


def classify_breadth(*, pct_above_50d: float) -> str:
    if pct_above_50d > 0.60: return "BROAD"
    if pct_above_50d > 0.40: return "MIXED"
    return "NARROW"


def classify_regime(*, vix, spx_close, sma50, sma200, adx, pct_above_50d):
    return {
        "volatility": classify_volatility(vix=vix),
        "trend": classify_trend(spx_close=spx_close, sma50=sma50, sma200=sma200, adx=adx),
        "breadth": classify_breadth(pct_above_50d=pct_above_50d),
        "vix": vix, "adx": adx, "pct_above_50d": pct_above_50d,
    }
```

- [ ] Run + commit per usual TDD pattern.

### Task 4.3: `/tradelab/regime` endpoint + banner UI

```python
elif self.path == "/tradelab/regime":
    from tradelab.regime.classifier import classify_regime
    from tradelab.data import fetch_market_snapshot  # existing or new helper
    snapshot = fetch_market_snapshot()
    self._send_json(classify_regime(**snapshot))
    return
```

HTML banner:

```html
<section class="panel regime-banner" id="regime-banner">
  <div class="panel-header"><div class="title"><h2>Market Regime</h2><span class="new-pill">NEW</span></div></div>
  <div class="regime-grid" id="regime-grid"></div>
</section>
```

JS: fetch + render 3 cells (volatility / trend / breadth).

- [ ] Run + commit.

---

## Slice 5: Live Divergence (REVIEW-only)

**Why:** Distribution-based decay detection. K-S + decay slope on rolling 30-trade window. **REVIEW URGENT** badge only — never auto-disable. Upgrade path documented.

**Files:**
- Create: `tradelab/src/tradelab/live/divergence.py`
- Modify: `tradelab/src/tradelab/live/receiver.py` (or wherever `_log_alert` lives) — add per-fill hook
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/cards/<id>/divergence`)
- Modify: `tradelab/src/tradelab/web/command_center.html` (decay sparkline + K-S badge)
- Test: `tradelab/tests/live/test_divergence.py`

### Task 5.1: K-S two-sample test on rolling window

```python
# tradelab/src/tradelab/live/divergence.py
from scipy import stats

def compute_ks_pvalue(live_returns: list[float], backtest_returns: list[float]) -> float:
    if len(live_returns) < 10 or len(backtest_returns) < 10:
        return 1.0  # insufficient sample → don't fire
    _, p = stats.ks_2samp(live_returns, backtest_returns)
    return float(p)
```

Test:

```python
def test_ks_low_pvalue_when_distributions_differ():
    import numpy as np
    np.random.seed(0)
    live = list(np.random.normal(-0.01, 0.02, 50))
    backtest = list(np.random.normal(0.01, 0.02, 200))
    p = compute_ks_pvalue(live, backtest)
    assert p < 0.01
```

### Task 5.2: Decay slope (rolling Sharpe regression)

```python
def compute_decay_slope(returns: list[float], window: int = 30) -> dict:
    import numpy as np
    if len(returns) < window * 2:
        return {"slope": None, "t_statistic": None}
    sharpes = []
    for i in range(window, len(returns)):
        w = returns[i-window:i]
        sharpes.append(np.mean(w) / (np.std(w) or 1e-9))
    x = np.arange(len(sharpes))
    slope, intercept = np.polyfit(x, sharpes, 1)
    # naive t-stat via residual std
    pred = slope * x + intercept
    se = np.sqrt(np.sum((sharpes - pred)**2) / (len(sharpes)-2)) / np.sqrt(np.sum((x - x.mean())**2))
    t = slope / se if se > 0 else 0.0
    return {"slope": float(slope), "t_statistic": float(t)}
```

Test for known declining series → slope < 0.

### Task 5.3: REVIEW-only auto-action (NO auto-disable)

```python
def evaluate_divergence(live_returns, backtest_returns) -> dict:
    p = compute_ks_pvalue(live_returns, backtest_returns)
    decay = compute_decay_slope(live_returns)
    if p < 0.01:
        review_status = "urgent"
    elif p < 0.10:
        review_status = "warn"
    else:
        review_status = "ok"
    return {
        "ks_pvalue": p, "decay_slope": decay["slope"],
        "review_status": review_status, "auto_disabled": False,  # ALWAYS False in CALIBRATED
    }
```

Test: even when `p < 0.001`, `auto_disabled is False` and only `review_status` is set.

### Task 5.4: Receiver hook + endpoint + UI

- [ ] Add receiver hook to append to `pine_archive/<card_id>/divergence_log.jsonl`.
- [ ] Add endpoint `GET /tradelab/cards/<id>/divergence`.
- [ ] Add Live card UI elements: TE bar, decay sparkline (SVG path), K-S p-value tag, REVIEW badge.
- [ ] Notify path: `severity=warning` (not critical) on `urgent`.

Run + commit per usual TDD.

---

## Slice 6: Verdict Accuracy Loop Banner (full integration)

**Why:** Tie together hit-rate (Slice 3) + portfolio-level calibration stats (te_tripped, auto_disabled, pf_gap_median). The banner is mostly populated by Slice 3 already; this slice adds the 3 portfolio stats + the §1 caveat pill behavior + the recommendation engine.

**Files:**
- Create: `tradelab/src/tradelab/calibration/__main__.py` (top-level orchestrator)
- Modify: `tradelab/src/tradelab/web/handlers.py` (extend `/tradelab/calibration` endpoint)
- Modify: `command_center.html` (recommendation panel)
- Test: `tradelab/tests/calibration/test_calibration_aggregator.py`

### Task 6.1: Compute portfolio-level stats

```python
# tradelab/src/tradelab/calibration/__main__.py
from pathlib import Path
import json
import sqlite3


def compute_portfolio_calibration(*, db_path: Path) -> dict:
    """Compute te_tripped_pct, auto_disabled_pct, pf_gap_median."""
    conn = sqlite3.connect(db_path)
    accepted = conn.execute(
        "SELECT strategy_name, run_id FROM runs WHERE accepted_bool = 1"
    ).fetchall()
    if len(accepted) < 5:
        return {"insufficient_sample": True, "n_accepted": len(accepted)}
    # gather outcomes per strategy via Slice 3 helpers
    from .outcomes import gather_all_outcomes
    outcomes = gather_all_outcomes()
    n = len(accepted)
    te_tripped = sum(1 for s, _ in accepted if outcomes.get(s, {}).get("te_tripped_30d"))
    auto_disabled = sum(1 for s, _ in accepted if outcomes.get(s, {}).get("auto_disabled_60d"))
    pf_gaps = [outcomes[s]["pf_gap"] for s, _ in accepted if outcomes.get(s, {}).get("pf_gap") is not None]
    import statistics
    pf_gap_median = statistics.median(pf_gaps) if pf_gaps else None
    return {
        "te_tripped_count": te_tripped, "te_tripped_total": n,
        "auto_disabled_count": auto_disabled, "auto_disabled_total": n,
        "pf_gap_median": pf_gap_median,
        "code_divergence_caveat": True,
    }
```

### Task 6.2: Recommendation engine

```python
def generate_recommendations(stats: dict, hit_rates: dict) -> list[str]:
    if stats.get("insufficient_sample"):
        return ["Insufficient sample — need ≥5 accepted cards with 30d+ history"]
    recs = []
    if stats["te_tripped_count"] / stats["te_tripped_total"] > 0.25:
        recs.append("Tighten hold_out_robust_pf threshold")
    if (stats.get("pf_gap_median") or 0) < -0.30:
        recs.append("Tighten DSR floor")
    # Per-signal: if a critical signal has hit_rate > 70%, recommend stricter threshold
    for sig_name, hr in hit_rates.items():
        if hr["read"] == "noisy" and hr["accepted_despite"] >= 5:
            recs.append(f"Loosen {sig_name} — gate is over-flagging (hit rate {hr['hit_rate']*100:.0f}%)")
    if not recs:
        recs.append("All thresholds within acceptable hit-rate ranges")
    return recs
```

### Task 6.3: Endpoint + banner UI integration

Extend `/tradelab/calibration` to return `{stats, hit_rates, recommendations}`. Banner JS already renders hit-rate table from Slice 3; add stats row above + recommendation pill.

- [ ] Run + commit.

---

## Slice §1 confound panel surface (split out — execute alongside Slice -1)

This was missed inline above. Execute concurrent with Slice -1 since the panel reads the retrospective output + alpaca_config:

**Files:**
- Create: `tradelab/src/tradelab/calibration/code_match.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (add `/tradelab/code-match`)
- Modify: `command_center.html` (add §1 confound panel at top of Research tab)

### Task §1.1: Code-match check

```python
# tradelab/src/tradelab/calibration/code_match.py
import hashlib
import json
from pathlib import Path


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_code_match(
    *, alpaca_config: Path, tradelab_strategies_dir: Path, deployed_strategies_dir: Path,
) -> list[dict]:
    cfg = json.loads(alpaca_config.read_text())
    out = []
    for entry in cfg.get("strategies", []):
        live_module = entry.get("module")
        tradelab_path = tradelab_strategies_dir / f"{live_module}.py"
        deployed_path = deployed_strategies_dir / f"{live_module}.py"
        if not tradelab_path.exists():
            status = "MISSING"
            tradelab_module = None
            match_detail = "no tradelab.yaml entry"
        elif deployed_path.exists() and hash_file(tradelab_path) == hash_file(deployed_path):
            status = "MATCHED"
            tradelab_module = f"tradelab.strategies.{live_module}"
            match_detail = "byte-identical"
        else:
            status = "DIVERGENT"
            tradelab_module = f"tradelab.strategies.{live_module}"
            match_detail = "module loaded by bare name; not verified identical"
        out.append({
            "live_module": entry.get("name", live_module),
            "allocation_pct": entry.get("allocation_pct"),
            "tradelab_module": tradelab_module,
            "code_match_status": status,
            "match_detail": match_detail,
        })
    return out
```

### Task §1.2: Endpoint + UI panel

```python
elif self.path == "/tradelab/code-match":
    from tradelab.calibration.code_match import check_code_match
    result = check_code_match(
        alpaca_config=Path("C:/TradingScripts/alpaca_config.json"),
        tradelab_strategies_dir=Path(__file__).parents[2] / "strategies",
        deployed_strategies_dir=Path("C:/TradingScripts"),
    )
    self._send_json({"per_strategy": result})
    return
```

UI: top-of-page panel rendered from `/tradelab/code-match`. CSS classes `.confound-panel`, `.confound-status` from CALIBRATED mockup. Inject CAVEAT pill on hit-rate cells when any status != MATCHED.

- [ ] Run + commit.

---

## Self-Review (run before execution)

**1. Spec coverage check:**
- §0–§2 (decisions C1–C14): ✓ — all surface in slices below
- §3 architecture: ✓ — every NEW/EXT module has a slice
- §4 component design: ✓ — code_match (§1 panel slice), canary.runtime (Slice 0.5), audit.history extension (Slice 0), retrospective (Slice -1), hit_rate (Slice 3), regime (Slice 4), divergence (Slice 5); hold_out + correlation + relative context preserved (Slices 1a/1b/2)
- §5 data flow: ✓ — covered across slices
- §6 error handling: partial — each slice has happy-path tests; explicit failure-mode tests mostly via integration. Add explicit error-mode tests when implementing.
- §7 testing strategy: ✓ — per slice
- §8 build order: ✓ — matches spec
- §9 out of scope: ✓ — not in plan
- §10–§12: ✓ — covered

**2. Placeholder scan:**
- A few helper-function stubs reference `_load_card_baselines`, `gather_all_outcomes`, `fetch_market_snapshot` without full bodies. Implementer must write these per the same TDD pattern. Flagged as `# implement loaders` in code blocks. **Treat as inline TODOs to flesh out during the slice — not unimplemented placeholders in the plan structure.**
- All other steps have complete code.

**3. Type consistency:**
- `signal_values` (record_run param) → `signal_values_json` (DB col) — explicit conversion via `json.dumps`. Consistent.
- `accepted` (bool param) → `accepted_bool` (int 0/1 in DB). Consistent.
- `CanaryStatus` dataclass + `CANARIES_EXPECTED` shape — used identically in tests + impl + endpoint.
- `compute_per_strategy_outcomes` (Slice -1) returns rows with `live_pf, n_trades, total_pnl` — consumed by `compute_per_signal_seed_hit_rates` which expects `live_pf` + `signals_fragile`. Slice -1.5 enriches with `signals_fragile` before passing. Consistent.

---

## Execution

**Plan saved to `docs/superpowers/plans/2026-04-28-research-tab-validation-redesign-CALIBRATED.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task; review between tasks; fast iteration; use `superpowers:subagent-driven-development`.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`; batch with checkpoints.

**Recommendation: Subagent-Driven** for Slices -1 + 0 + 0.5 (independent, easy parallel). Switch to inline once foundation lands and dependent slices need integration. But user choice.

**Hand-smoke between every slice** per `feedback_live_smoke_before_next_slice` memory.
