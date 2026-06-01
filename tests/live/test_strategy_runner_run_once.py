from tradelab.live.strategy_runner import run_once


def _deps(latest_bar, positions, config, daily_pnl=0.0, price=100.0):
    calls = []
    return {
        "load_latest_bar": lambda strat, sym, tf: latest_bar,
        "get_positions": lambda: positions,             # {symbol: qty}
        "get_price": lambda sym: price,
        "get_daily_pnl": lambda: daily_pnl,
        "get_config": lambda: config,
        "submit_fn": (lambda *a, **k: calls.append((a, k))),
        "_calls": calls,
    }

PAPER = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": False, "daily_loss_limit": -5000}}


def _card(**kw):
    base = {"card_id": "frog-v1", "symbol": "AAPL", "timeframe": "1D", "strategy": "frog",
            "status": "enabled", "source": "python", "mode": "paper", "allocation_usd": 1000}
    base.update(kw); return base


def test_run_once_buys_on_signal():
    d = _deps({"buy_signal": True, "sell_signal": False}, {}, PAPER)
    res = run_once({"frog-v1": _card()}, deps=d, bar_date="2026-05-31")
    assert len(d["_calls"]) == 1
    assert res["frog-v1"]["action"] == "buy"


def test_run_once_blocks_all_orders_when_paper_off():
    cfg = {"alpaca": {"paper_trading": False}, "trading": {}}
    d = _deps({"buy_signal": True}, {}, cfg)
    res = run_once({"frog-v1": _card()}, deps=d, bar_date="d")
    assert d["_calls"] == []
    assert res["frog-v1"]["action"] == "blocked"


def test_run_once_kill_switch_blocks_even_exits():
    cfg = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": True}}
    d = _deps({"sell_signal": True}, {"AAPL": 10}, cfg)   # wants to EXIT
    res = run_once({"frog-v1": _card()}, deps=d, bar_date="d")
    assert d["_calls"] == []
    assert res["frog-v1"]["action"] == "blocked"


def test_run_once_daily_loss_blocks_entry_but_allows_exit():
    cfg = {"alpaca": {"paper_trading": True}, "trading": {"daily_loss_limit": -5000}}
    # entry attempt blocked
    d1 = _deps({"buy_signal": True}, {}, cfg, daily_pnl=-6000.0)
    r1 = run_once({"frog-v1": _card()}, deps=d1, bar_date="d")
    assert d1["_calls"] == [] and r1["frog-v1"]["action"] == "blocked"
    # exit attempt allowed (de-risk)
    d2 = _deps({"sell_signal": True}, {"AAPL": 10}, cfg, daily_pnl=-6000.0)
    r2 = run_once({"frog-v1": _card()}, deps=d2, bar_date="d")
    assert len(d2["_calls"]) == 1 and r2["frog-v1"]["action"] == "sell"


def test_run_once_skips_disabled_non_python_and_non_paper():
    d = _deps({"buy_signal": True}, {}, PAPER)
    cards = {
        "a": _card(card_id="a", status="disabled"),
        "b": _card(card_id="b", source="pine"),
        "c": _card(card_id="c", mode="live"),
    }
    res = run_once(cards, deps=d, bar_date="d")
    assert d["_calls"] == []


def test_run_once_one_bad_card_does_not_stop_others():
    def boom(strat, sym, tf):
        raise RuntimeError("data fail")
    calls = []
    d = {"load_latest_bar": boom, "get_positions": lambda: {}, "get_price": lambda s: 100.0,
         "get_daily_pnl": lambda: 0.0, "get_config": lambda: PAPER,
         "submit_fn": lambda *a, **k: calls.append(1)}
    # one card raises on load; assert run_once returns an error entry, doesn't throw
    res = run_once({"frog-v1": _card()}, deps=d, bar_date="d")
    assert res["frog-v1"]["action"] == "error"
