# Phase 4 — Paper Execution Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A paper-locked desired-state reconciler that makes enabled Python cards trade on paper: each cadence, run the strategy, compute the desired position from the latest bar, reconcile against the live Alpaca position.

**Architecture:** Pure, injected-dependency core (desired-position / sizing / safety / reconcile) that is 100% unit-tested with a MOCK Alpaca — **no test ever places a real or paper order**. A thin daemon ties it together and is registered in `launch_dashboard.py`. Spec: `docs/superpowers/specs/2026-05-31-phase4-paper-execution-engine-design.md`.

**SAFETY (non-negotiable):** Every order path is gated by `paper_trading==True` (hard refuse otherwise), `kill_switch`, and the −$5000 `daily_loss_limit`. All Alpaca calls go through injected callables; tests inject mocks. Real money requires a separate, deliberate config flip (out of scope).

**Verified primitives:** `tradelab.live.alpaca_client`: `submit_market_order(symbol, side, quantity, client_order_id)` (side "buy"/"sell"; calls `get_client()` internally), `list_positions() -> [{symbol, qty, side}]`, `get_client()` reads `C:/TradingScripts/alpaca_config.json` (`alpaca.paper_trading`, `trading.kill_switch`, `trading.daily_loss_limit`). `instantiate_strategy(name)`, `enrich_universe`, `marketdata.download_symbols`/`cache.read`, `run_backtest` exist. Card schema (Phase 3a): `strategy`, `symbol`, `timeframe`, `status`, `source:"python"`, `mode:"paper"`. Daemon registration pattern: `module.start()` + `atexit.register(module.stop)` in `launch_dashboard.py` (see `notify_dispatcher`).

---

### Task 1: Pure decision core

**Files:**
- Create: `src/tradelab/live/strategy_runner.py`
- Test: `tests/live/test_strategy_runner_core.py` (+ `tests/live/__init__.py` if missing)

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_strategy_runner_core.py
import math
import pytest
from tradelab.live.strategy_runner import desired_position, size_qty, safety_block_reason


def test_desired_position_from_signals():
    assert desired_position({"buy_signal": True,  "sell_signal": False}) == "long"
    assert desired_position({"buy_signal": False, "sell_signal": True})  == "flat"
    assert desired_position({"buy_signal": False, "sell_signal": False}) == "hold"
    # explicit exit wins over a stale buy on the same bar
    assert desired_position({"buy_signal": True,  "sell_signal": True})  == "flat"


def test_size_qty_floors_and_guards():
    assert size_qty(1000.0, 100.0) == 10
    assert size_qty(1050.0, 100.0) == 10        # floor
    assert size_qty(50.0, 100.0) == 0           # under one share
    assert size_qty(None, 100.0) == 0
    assert size_qty(1000.0, 0.0) == 0           # bad price
    assert size_qty(-5.0, 100.0) == 0


def test_safety_block_reason():
    base = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": False, "daily_loss_limit": -5000}}
    assert safety_block_reason(base, daily_pnl=-100.0, is_entry=True) is None
    # paper off -> always blocked
    off = {"alpaca": {"paper_trading": False}, "trading": {}}
    assert "paper" in safety_block_reason(off, daily_pnl=0.0, is_entry=True).lower()
    # kill switch
    ks = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": True}}
    assert "kill" in safety_block_reason(ks, daily_pnl=0.0, is_entry=True).lower()
    # daily loss breached blocks ENTRIES but not exits
    dl = {"alpaca": {"paper_trading": True}, "trading": {"daily_loss_limit": -5000}}
    assert safety_block_reason(dl, daily_pnl=-6000.0, is_entry=True) is not None
    assert safety_block_reason(dl, daily_pnl=-6000.0, is_entry=False) is None
```

- [ ] **Step 2: Run to verify it fails** — `cd tradelab && python -m pytest tests/live/test_strategy_runner_core.py -q` → FAIL (import error).

- [ ] **Step 3: Implement** — create `src/tradelab/live/strategy_runner.py`:

```python
"""Paper-locked desired-state execution engine for Python cards.

Pure decision core + a thin daemon. EVERY Alpaca interaction is an injected
callable so tests never touch a real account. Paper-only until an explicit
config flip enables live (out of scope here)."""
from __future__ import annotations

import math
from typing import Optional


def desired_position(latest_bar: dict) -> str:
    """Map a strategy's latest-bar signals to a desired position.

    sell_signal (explicit exit) wins over buy_signal. Neither -> 'hold'
    (leave the current position untouched; the engine never invents an exit)."""
    if bool(latest_bar.get("sell_signal")):
        return "flat"
    if bool(latest_bar.get("buy_signal")):
        return "long"
    return "hold"


def size_qty(allocation_usd: Optional[float], price: Optional[float]) -> int:
    """Whole-share qty from a card's dollar allocation. 0 on any invalid input."""
    try:
        a = float(allocation_usd)
        p = float(price)
    except (TypeError, ValueError):
        return 0
    if a <= 0 or p <= 0:
        return 0
    return int(math.floor(a / p))


def safety_block_reason(config: dict, *, daily_pnl: float, is_entry: bool) -> Optional[str]:
    """Return a human reason to BLOCK an order, or None to allow.

    Hard gates: paper_trading must be True; kill_switch halts everything; a
    breached daily_loss_limit halts new ENTRIES (exits still allowed to de-risk)."""
    alpaca = config.get("alpaca", {}) or {}
    trading = config.get("trading", {}) or {}
    if not bool(alpaca.get("paper_trading", True) is True):
        return "paper_trading is not True (live trading is disabled in this engine)"
    if bool(trading.get("kill_switch", False)):
        return "kill_switch is engaged"
    limit = trading.get("daily_loss_limit")
    if is_entry and limit is not None:
        try:
            if float(daily_pnl) <= float(limit):
                return f"daily loss {daily_pnl:.0f} breached limit {float(limit):.0f}"
        except (TypeError, ValueError):
            pass
    return None
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/live/test_strategy_runner_core.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add src/tradelab/live/strategy_runner.py tests/live/ && git commit -m "feat(live): paper-engine decision core (desired_position, size_qty, safety gate)"`

---

### Task 2: Reconciler (with mocked Alpaca)

**Files:** Modify `src/tradelab/live/strategy_runner.py`; test `tests/live/test_strategy_runner_reconcile.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/live/test_strategy_runner_reconcile.py
from tradelab.live.strategy_runner import reconcile_card


def _calls():
    out = []
    def submit(symbol, side, quantity, client_order_id=None):
        out.append({"symbol": symbol, "side": side, "qty": quantity, "coid": client_order_id})
        return {"id": "mock"}
    return out, submit


def test_reconcile_buys_to_open_when_desired_long_and_flat():
    calls, submit = _calls()
    act = reconcile_card(card={"card_id": "frog-v1", "symbol": "AAPL", "allocation_usd": 1000},
                         desired="long", actual_qty=0, price=100.0, bar_date="2026-05-31",
                         submit_fn=submit)
    assert act["action"] == "buy" and act["qty"] == 10
    assert calls == [{"symbol": "AAPL", "side": "buy", "qty": 10,
                      "coid": "frog-v1-2026-05-31-buy"}]


def test_reconcile_sells_to_close_when_desired_flat_and_long():
    calls, submit = _calls()
    act = reconcile_card(card={"card_id": "frog-v1", "symbol": "AAPL", "allocation_usd": 1000},
                         desired="flat", actual_qty=10, price=100.0, bar_date="2026-05-31",
                         submit_fn=submit)
    assert act["action"] == "sell" and act["qty"] == 10
    assert calls[0]["side"] == "sell" and calls[0]["qty"] == 10


def test_reconcile_noop_when_already_in_desired_state():
    calls, submit = _calls()
    a1 = reconcile_card(card={"card_id": "f", "symbol": "AAPL", "allocation_usd": 1000},
                        desired="long", actual_qty=10, price=100.0, bar_date="d", submit_fn=submit)
    a2 = reconcile_card(card={"card_id": "f", "symbol": "AAPL", "allocation_usd": 1000},
                        desired="hold", actual_qty=10, price=100.0, bar_date="d", submit_fn=submit)
    a3 = reconcile_card(card={"card_id": "f", "symbol": "AAPL", "allocation_usd": 1000},
                        desired="flat", actual_qty=0, price=100.0, bar_date="d", submit_fn=submit)
    assert a1["action"] == "none" and a2["action"] == "none" and a3["action"] == "none"
    assert calls == []


def test_reconcile_skips_when_size_zero():
    calls, submit = _calls()
    act = reconcile_card(card={"card_id": "f", "symbol": "AAPL", "allocation_usd": 50},
                         desired="long", actual_qty=0, price=100.0, bar_date="d", submit_fn=submit)
    assert act["action"] == "skip" and calls == []
```

- [ ] **Step 2: Run to verify it fails** — FAIL (no `reconcile_card`).

- [ ] **Step 3: Implement** — append to `strategy_runner.py`:

```python
def reconcile_card(*, card: dict, desired: str, actual_qty: int, price: float,
                   bar_date: str, submit_fn) -> dict:
    """Reconcile one card's desired position with its actual Alpaca position by
    placing at most ONE market order via submit_fn. Idempotent: a card already
    in its desired state is a no-op. submit_fn(symbol, side, quantity,
    client_order_id) is injected (real or mock)."""
    symbol = card["symbol"]
    cid = card["card_id"]
    if desired == "long" and actual_qty <= 0:
        qty = size_qty(card.get("allocation_usd"), price)
        if qty <= 0:
            return {"action": "skip", "reason": "allocation/price yields 0 shares"}
        submit_fn(symbol, "buy", qty, client_order_id=f"{cid}-{bar_date}-buy")
        return {"action": "buy", "qty": qty}
    if desired == "flat" and actual_qty > 0:
        submit_fn(symbol, "sell", actual_qty, client_order_id=f"{cid}-{bar_date}-sell")
        return {"action": "sell", "qty": actual_qty}
    return {"action": "none"}
```

- [ ] **Step 4: Run to verify it passes** — PASS (4 tests).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(live): reconcile_card (idempotent buy-to-open/sell-to-close, injected submit)"`

---

### Task 3: `run_once` orchestration (all deps injected)

**Files:** Modify `strategy_runner.py`; test `tests/live/test_strategy_runner_run_once.py`.

- [ ] **Step 1: Write the failing test** — assert that, given a fake card set + injected deps (config, a fake strategy whose latest bar says buy, a positions map, a recording submit, a fixed price/pnl), `run_once` places exactly the expected order; and that a kill_switch / paper-off config places NONE. Use injected callables only — NO real Alpaca, NO real data.

```python
from tradelab.live.strategy_runner import run_once

def _deps(latest_bar, positions, config, daily_pnl=0.0, price=100.0):
    calls = []
    return {
        "load_latest_bar": lambda strat, sym, tf: latest_bar,   # returns the dict
        "get_positions": lambda: positions,                     # {symbol: qty}
        "get_price": lambda sym: price,
        "get_daily_pnl": lambda: daily_pnl,
        "get_config": lambda: config,
        "submit_fn": (lambda *a, **k: calls.append((a, k))),
        "_calls": calls,
    }

PAPER = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": False, "daily_loss_limit": -5000}}

def test_run_once_buys_on_signal():
    d = _deps({"buy_signal": True, "sell_signal": False}, {}, PAPER)
    cards = {"frog-v1": {"card_id": "frog-v1", "symbol": "AAPL", "timeframe": "1D",
                         "strategy": "frog", "status": "enabled", "source": "python",
                         "mode": "paper", "allocation_usd": 1000}}
    res = run_once(cards, deps=d, bar_date="2026-05-31")
    assert len(d["_calls"]) == 1                      # one buy placed
    assert res["frog-v1"]["action"] == "buy"

def test_run_once_blocks_when_paper_off():
    cfg = {"alpaca": {"paper_trading": False}, "trading": {}}
    d = _deps({"buy_signal": True}, {}, cfg)
    cards = {"frog-v1": {"card_id": "frog-v1", "symbol": "AAPL", "timeframe": "1D",
                         "strategy": "frog", "status": "enabled", "source": "python",
                         "mode": "paper", "allocation_usd": 1000}}
    res = run_once(cards, deps=d, bar_date="d")
    assert d["_calls"] == []                          # nothing placed
    assert "block" in res["frog-v1"]["action"] or res["frog-v1"]["action"] == "blocked"

def test_run_once_skips_disabled_and_non_python():
    d = _deps({"buy_signal": True}, {}, PAPER)
    cards = {
        "a": {"card_id": "a", "symbol": "X", "timeframe": "1D", "strategy": "frog",
              "status": "disabled", "source": "python", "mode": "paper", "allocation_usd": 1000},
        "b": {"card_id": "b", "symbol": "Y", "timeframe": "1D", "strategy": "frog",
              "status": "enabled", "source": "pine", "mode": "paper", "allocation_usd": 1000},
    }
    res = run_once(cards, deps=d, bar_date="d")
    assert d["_calls"] == []
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement** `run_once(cards, *, deps, bar_date)` in `strategy_runner.py`:
  - For each card: skip unless `status=="enabled"` and `source=="python"` and `mode=="paper"`.
  - `config = deps["get_config"]()`; compute `desired = desired_position(deps["load_latest_bar"](card["strategy"], card["symbol"], card["timeframe"]))`.
  - `actual_qty = int(deps["get_positions"]().get(card["symbol"], 0))`.
  - `is_entry = (desired == "long" and actual_qty <= 0)`.
  - `reason = safety_block_reason(config, daily_pnl=deps["get_daily_pnl"](), is_entry=is_entry)`; if reason and is_entry → record `{"action":"blocked","reason":reason}` and continue (exits are allowed even when entries are blocked, but paper-off/kill-switch block everything — encode that: if reason and (is_entry OR reason is paper/kill) skip).
  - else `price = deps["get_price"](card["symbol"])`; `result = reconcile_card(card=card, desired=desired, actual_qty=actual_qty, price=price, bar_date=bar_date, submit_fn=deps["submit_fn"])`.
  - Return `{card_id: result}`. Wrap each card in try/except so one bad card never stops the loop (record `{"action":"error","reason":...}`).

  (Make the paper-off/kill-switch block apply to BOTH entries and exits — `safety_block_reason` returns a reason for those regardless of `is_entry`; only the daily-loss gate is entry-only. In run_once, if `reason` is set AND (`is_entry` is True OR the reason is paper/kill), skip. Simplest: block if `reason` and not (it is the daily-loss reason on an exit). Implement by calling `safety_block_reason` with `is_entry`, and additionally a paper/kill pre-check that blocks exits too.)

- [ ] **Step 4: Run to verify it passes.**

- [ ] **Step 5: Commit** — `git commit -m "feat(live): run_once reconciles enabled paper python cards (injected deps, safety-gated)"`

---

### Task 4: Live dependency wiring + daemon

**Files:** Modify `strategy_runner.py` (real deps + `start()`/`stop()`); modify `launch_dashboard.py` (register daemon); test `tests/live/test_strategy_runner_daemon.py`.

- [ ] **Step 1:** Add `_real_deps()` building the injected callables from real modules: `get_config` reads `C:/TradingScripts/alpaca_config.json`; `get_positions` from `alpaca_client.list_positions()` → `{symbol: int(float(qty))}`; `submit_fn = alpaca_client.submit_market_order`; `get_price` from the latest cached bar Close (or a light quote); `load_latest_bar` does `download_symbols([sym])` (cache refresh) → `enrich_universe` → `instantiate_strategy(strat).generate_signals(...)` → the last row as a dict; `get_daily_pnl` from `get_client().get_account()` (`float(equity) - float(last_equity)`). Each wrapped so a failure is logged and treated as a safe default (positions empty, pnl 0 → but pnl-fetch failure on the loss gate should be treated conservatively: if pnl can't be read, BLOCK entries).
- [ ] **Step 2:** Add a `start()` that launches a daemon thread looping: sleep to the next per-timeframe bar close, load `CardRegistry(_cards_path).all()`, call `run_once(..., deps=_real_deps(), bar_date=today)`, log results; and `stop()` to halt it. Mirror `notify_dispatcher`'s start/stop + thread style.
- [ ] **Step 3:** Test (mock `run_once` and the registry) that `start()`/`stop()` don't crash and the loop calls `run_once` at least once; assert the daemon NEVER calls real Alpaca in the test (inject a fake clock/registry).
- [ ] **Step 4:** Register in `launch_dashboard.py` next to the other daemons: `from tradelab.live import strategy_runner; strategy_runner.start(); atexit.register(strategy_runner.stop)` inside a try/except that logs and continues if it fails (Research stays up).
- [ ] **Step 5:** Run the live test suite; commit both repos.

---

### Task 5: Card `allocation_usd` (accept + Overview input)

**Files:** Modify `src/tradelab/web/approve_strategy.py` (accept stamps `allocation_usd`), the card-update path, and `command_center.html` (Overview card $-allocation input); tests.

- [ ] **Step 1:** Add `allocation_usd: Optional[float] = None` param to `accept_python_run`; include `"allocation_usd": allocation_usd` in the card dict. Pass it through the `/tradelab/strategies/accept` route (optional). TDD.
- [ ] **Step 2:** Reuse/confirm a card-update endpoint to set `allocation_usd` on an existing card (the Overview "$ per strategy" input → `CardRegistry.update(card_id, {"allocation_usd": x})`). Add a small route if none exists. TDD.
- [ ] **Step 3:** Overview card: a `$` number input that PATCHes `allocation_usd`. FE test asserts the input + the update call. Failure count unchanged.
- [ ] **Step 4:** Run tests; commit both repos.

---

## Self-review
- **Spec coverage:** sizing from `allocation_usd` (Task 1 `size_qty` + Task 5) ✓; exits from Python `sell_signal` (Task 1 `desired_position`) ✓; safety = paper-lock + kill-switch + $5k daily-loss (Task 1 `safety_block_reason`, applied in Task 3) ✓; cadence by timeframe (Task 4 daemon) ✓; desired-state reconcile (Task 2) ✓.
- **No real orders in tests:** Tasks 1-3 inject all Alpaca/data deps; Task 4's daemon test mocks `run_once`/registry. ✓
- **Placeholder scan:** Tasks 4-5 have READ/confirm steps for the daemon clock + card-update endpoint — investigations, not placeholders; the decision-core Tasks 1-3 ship complete code.

## Out of scope (explicit follow-ups)
Live (real-money) flip; trailing-stop/bracket parity; partial-fill handling; multi-symbol cards; market-calendar-accurate bar-close detection (Task 4 may start with a simple per-timeframe time check + a TODO for a holiday-aware calendar).
