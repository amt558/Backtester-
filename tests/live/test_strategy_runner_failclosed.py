"""Regression: the paper engine must FAIL CLOSED. A missing/garbage paper flag
or unreadable P&L must never let an order fire. (Caught by code review — the
original `.get("paper_trading", True)` default fired orders on a missing key.)"""
from __future__ import annotations

from tradelab.live.strategy_runner import run_once, safety_block_reason


def test_missing_paper_key_blocks_entries_and_exits():
    cfg = {"alpaca": {}, "trading": {}}
    assert safety_block_reason(cfg, daily_pnl=0.0, is_entry=True) is not None
    assert safety_block_reason(cfg, daily_pnl=0.0, is_entry=False) is not None


def test_nonbool_truthy_paper_flag_blocks():
    for v in (1, "true", "True", "yes", 1.0):
        cfg = {"alpaca": {"paper_trading": v}, "trading": {}}
        assert safety_block_reason(cfg, daily_pnl=0.0, is_entry=True) is not None, v


def test_unreadable_daily_pnl_blocks_entry_but_allows_exit():
    cfg = {"alpaca": {"paper_trading": True}, "trading": {"daily_loss_limit": -5000}}
    assert safety_block_reason(cfg, daily_pnl="oops", is_entry=True) is not None
    assert safety_block_reason(cfg, daily_pnl="oops", is_entry=False) is None


def test_run_once_missing_paper_key_places_no_orders():
    calls = []
    deps = {
        "load_latest_bar": lambda *a: {"buy_signal": True},
        "get_positions": lambda: {},
        "get_price": lambda s: 100.0,
        "get_daily_pnl": lambda: 0.0,
        "get_config": lambda: {"alpaca": {}, "trading": {}},
        "submit_fn": lambda *a, **k: calls.append(1),
    }
    card = {"card_id": "f", "symbol": "AAPL", "timeframe": "1D", "strategy": "frog",
            "status": "enabled", "source": "python", "mode": "paper", "allocation_usd": 1000}
    res = run_once({"f": card}, deps=deps, bar_date="d")
    assert calls == []
    assert res["f"]["action"] == "blocked"
