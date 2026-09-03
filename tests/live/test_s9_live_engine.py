"""S9 — the engine on the live account and multi-ticker execution.

Every Alpaca touch is an injected callable; the live deps are a second dict
so the tests can see exactly which account an order went to."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradelab.live import strategy_runner as sr

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
CFG_OK = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": False, "daily_loss_limit": -2500}}
LIVE_CFG = {"max_total_allocation_usd": 25000.0, "daily_loss_limit_usd": 1000.0, "require_flat_paper": True}


def _card(**over):
    base = {"card_id": "alpha-v1", "strategy": "alpha", "symbol": "NVDA", "timeframe": "1D", "status": "enabled",
            "source": "python", "mode": "live", "allocation_usd": 10000, "live": {"granted_at": "x", "allocation_usd": 10000}}
    base.update(over)
    return base


def _deps(*, paper_calls, live_calls, live=True, live_pnl=0.0, held_live=None, held_paper=None, bars=None, declared=None):
    bars = bars or {"NVDA": {"buy_signal": True, "sell_signal": False}}
    d = {
        "get_config": lambda: CFG_OK,
        "load_latest_bar": lambda strategy, symbol, tf: bars[symbol],
        "get_positions": lambda: dict(held_paper or {}),
        "get_price": lambda symbol: 100.0,
        "get_daily_pnl": lambda: 0.0,
        "submit_fn": lambda symbol, side, qty, client_order_id=None: paper_calls.append((symbol, side, qty, client_order_id)),
        "live_config": LIVE_CFG,
        "verify_live_receipt": lambda card: True,
    }
    if declared is not None:
        d["declared_symbols"] = lambda strategy: declared
    if live:
        d["live"] = {
            "get_positions": lambda: dict(held_live or {}),
            "get_price": lambda symbol: 100.0,
            "get_daily_pnl": lambda: live_pnl,
            "submit_fn": lambda symbol, side, qty, client_order_id=None: live_calls.append((symbol, side, qty, client_order_id)),
        }
    else:
        d["live"] = None
    return d


def test_live_card_without_live_deps_is_blocked_never_routed_to_paper():
    paper, live = [], []
    res = sr.run_once({"alpha-v1": _card()}, deps=_deps(paper_calls=paper, live_calls=live, live=False), bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and "live keys" in res["alpha-v1"]["reason"]
    assert paper == [] and live == []


def test_live_card_without_receipt_is_blocked():
    paper, live = [], []
    res = sr.run_once({"alpha-v1": _card(live=None)}, deps=_deps(paper_calls=paper, live_calls=live), bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and "receipt" in res["alpha-v1"]["reason"]
    assert live == []


def test_kill_switch_halts_live_entries_and_exits():
    paper, live = [], []
    d = _deps(paper_calls=paper, live_calls=live, held_live={"NVDA": 50}, bars={"NVDA": {"sell_signal": True}})
    d["get_config"] = lambda: {**CFG_OK, "trading": {"kill_switch": True}}
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and "kill_switch" in res["alpha-v1"]["reason"]
    assert live == []


def test_live_daily_loss_limit_blocks_entries_but_not_exits():
    paper, live = [], []
    d = _deps(paper_calls=paper, live_calls=live, live_pnl=-1000.0)
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and "entries stopped" in res["alpha-v1"]["reason"] and live == []
    d = _deps(paper_calls=paper, live_calls=live, live_pnl=-5000.0, held_live={"NVDA": 30}, bars={"NVDA": {"sell_signal": True}})
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"] == {"action": "sell", "qty": 30}
    assert live == [("NVDA", "sell", 30, "alpha-v1-2026-09-03-sell")] and paper == []


def test_live_entry_goes_to_the_live_client_only_and_paper_flag_is_not_required():
    paper, live = [], []
    d = _deps(paper_calls=paper, live_calls=live)
    d["get_config"] = lambda: {"alpaca": {"paper_trading": False}, "trading": {}}   # paper gate would block a paper card
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"] == {"action": "buy", "qty": 100}
    assert live == [("NVDA", "buy", 100, "alpha-v1-2026-09-03-buy")] and paper == []


def test_advisory_override_cap_applies_on_live():
    paper, live = [], []
    card = _card(override={"expires_at": (NOW + timedelta(days=5)).isoformat(), "allocation_cap_pct": 50.0})
    res = sr.run_once({"alpha-v1": card}, deps=_deps(paper_calls=paper, live_calls=live), bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"] == {"action": "buy", "qty": 50}
    expired = _card(override={"expires_at": (NOW - timedelta(days=1)).isoformat(), "allocation_cap_pct": 50.0})
    res = sr.run_once({"alpha-v1": expired}, deps=_deps(paper_calls=paper, live_calls=[]), bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "skip" and "override expired" in res["alpha-v1"]["reason"]


def test_portfolio_card_trades_each_declared_ticker_from_one_signal_pass():
    paper, live, passes = [], [], []
    bars = {"NVDA": {"buy_signal": True}, "AMD": {"sell_signal": True}, "MU": {}}
    d = _deps(paper_calls=paper, live_calls=live, held_live={"AMD": 7}, declared=["NVDA", "AMD", "MU"])
    d["load_latest_bars"] = lambda strategy, symbols, tf: (passes.append(list(symbols)), bars)[1]
    d["load_latest_bar"] = lambda *a: (_ for _ in ()).throw(AssertionError("single-ticker loader must not be used"))
    res = sr.run_once({"alpha-v1": _card(symbol="PORTFOLIO", allocation_usd=9000, live={"granted_at": "x", "allocation_usd": 9000})}, deps=d, bar_date="2026-09-03", now=NOW)
    assert passes == [["NVDA", "AMD", "MU"]]                       # ONE pass over the whole list
    assert res["alpha-v1"]["action"] == "multi"
    per = res["alpha-v1"]["symbols"]
    assert per["NVDA"] == {"action": "buy", "qty": 30}             # 9000 / 3 tickers / $100
    assert per["AMD"] == {"action": "sell", "qty": 7}
    assert per["MU"] == {"action": "none"}
    assert sorted(live) == [("AMD", "sell", 7, "alpha-v1-2026-09-03-sell-AMD"), ("NVDA", "buy", 30, "alpha-v1-2026-09-03-buy-NVDA")]


def test_portfolio_card_falls_back_to_per_ticker_loader_and_isolates_one_tickers_failure():
    paper, live = [], []
    bars = {"NVDA": {"buy_signal": True}, "AMD": {"buy_signal": True}}
    d = _deps(paper_calls=paper, live_calls=live, bars=bars, declared=["NVDA", "AMD"])
    d["live"]["get_price"] = lambda symbol: 100.0 if symbol == "NVDA" else (_ for _ in ()).throw(ValueError("no cache"))
    res = sr.run_once({"alpha-v1": _card(symbol="PORTFOLIO", allocation_usd=4000, live={"granted_at": "x", "allocation_usd": 4000})}, deps=d, bar_date="2026-09-03", now=NOW)
    per = res["alpha-v1"]["symbols"]
    assert per["NVDA"] == {"action": "buy", "qty": 20} and per["AMD"]["action"] == "error" and "no cache" in per["AMD"]["reason"]


def test_no_declared_tickers_is_an_error_result_not_a_silent_skip():
    paper, live = [], []
    d = _deps(paper_calls=paper, live_calls=live, declared=[])
    res = sr.run_once({"alpha-v1": _card(symbol="PORTFOLIO")}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "error" and "no tickers" in res["alpha-v1"]["reason"] and live == []
    # no declared_symbols dep at all → same
    d.pop("declared_symbols")
    res = sr.run_once({"alpha-v1": _card(symbol="PORTFOLIO")}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "error"


def test_paper_portfolio_card_uses_paper_client_and_stamps_symbols():
    paper, live = [], []
    bars = {"NVDA": {"buy_signal": True}, "AMD": {"buy_signal": True}}
    d = _deps(paper_calls=paper, live_calls=live, bars=bars, declared=["NVDA", "AMD"])
    res = sr.run_once({"p-v1": _card(card_id="p-v1", mode="paper", symbol="PORTFOLIO", allocation_usd=2000, live=None)},
                      deps=d, bar_date="2026-09-03", now=NOW)
    assert res["p-v1"]["action"] == "multi"
    assert sorted(paper) == [("AMD", "buy", 10, "p-v1-2026-09-03-buy-AMD"), ("NVDA", "buy", 10, "p-v1-2026-09-03-buy-NVDA")]
    assert live == []


def test_paper_daily_loss_limit_blocks_entries_only_per_ticker():
    paper, live = [], []
    bars = {"NVDA": {"buy_signal": True}, "AMD": {"sell_signal": True}}
    d = _deps(paper_calls=paper, live_calls=live, bars=bars, declared=["NVDA", "AMD"], held_paper={"AMD": 4})
    d["get_daily_pnl"] = lambda: -3000.0
    res = sr.run_once({"p-v1": _card(card_id="p-v1", mode="paper", symbol="PORTFOLIO", live=None)}, deps=d, bar_date="2026-09-03", now=NOW)
    per = res["p-v1"]["symbols"]
    assert per["NVDA"]["action"] == "blocked" and per["AMD"] == {"action": "sell", "qty": 4}


def test_card_symbols_and_live_block_reason_helpers():
    assert sr.card_symbols({"symbol": "nvda"}) == ["NVDA"]
    assert sr.card_symbols({"symbol": "PORTFOLIO", "strategy": "s"}, lambda s: ["a", "b", "a", ""]) == ["A", "B"]
    assert sr.card_symbols({"symbol": "PORTFOLIO"}, lambda s: (_ for _ in ()).throw(RuntimeError())) == []
    assert sr.live_block_reason({"trading": {"kill_switch": True}}, live_config=LIVE_CFG, daily_pnl=0, is_entry=False, live_ready=True)
    assert sr.live_block_reason({}, live_config=LIVE_CFG, daily_pnl=0, is_entry=False, live_ready=False)
    assert sr.live_block_reason({}, live_config=LIVE_CFG, daily_pnl="?", is_entry=True, live_ready=True)
    assert sr.live_block_reason({}, live_config=LIVE_CFG, daily_pnl=-999, is_entry=True, live_ready=True) is None
    assert sr.live_block_reason({}, live_config=LIVE_CFG, daily_pnl=-1000, is_entry=True, live_ready=True)
    assert sr.live_block_reason({}, live_config=None, daily_pnl=-1000, is_entry=True, live_ready=True)   # defaults apply
    assert sr.live_block_reason({}, live_config=LIVE_CFG, daily_pnl=-1e9, is_entry=False, live_ready=True) is None


def test_live_keys_gate_in_alpaca_client(monkeypatch):
    from tradelab.live import alpaca_client as ac
    monkeypatch.delenv(ac.LIVE_KEY_ENV, raising=False); monkeypatch.delenv(ac.LIVE_SECRET_ENV, raising=False)
    monkeypatch.setattr("tradelab.env.load_env", lambda *a, **k: {})
    ac._clients.pop("live", None)
    assert ac.live_keys_present() is False
    import pytest
    with pytest.raises(ac.LiveNotConfigured):
        ac.get_client("live")
    with pytest.raises(ValueError):
        ac.get_client("sandbox")
    monkeypatch.setenv(ac.LIVE_KEY_ENV, "k"); monkeypatch.setenv(ac.LIVE_SECRET_ENV, "s")
    assert ac.live_keys_present() is True


def test_unverified_or_forged_receipt_blocks_and_live_sizes_from_the_ledgered_allocation():
    paper, live = [], []
    d = _deps(paper_calls=paper, live_calls=live)
    d["verify_live_receipt"] = lambda card: False
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and "does not verify" in res["alpha-v1"]["reason"] and live == []
    d.pop("verify_live_receipt")                                   # no verifier at all → blocked
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and live == []
    d["verify_live_receipt"] = lambda card: (_ for _ in ()).throw(RuntimeError("db"))
    res = sr.run_once({"alpha-v1": _card()}, deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"]["action"] == "blocked" and live == []
    # a hand-edited allocation_usd is ignored: the receipt's (ledgered) number sizes the order
    d["verify_live_receipt"] = lambda card: True
    res = sr.run_once({"alpha-v1": _card(allocation_usd=1_000_000, live={"granted_at": "x", "allocation_usd": 2000})},
                      deps=d, bar_date="2026-09-03", now=NOW)
    assert res["alpha-v1"] == {"action": "buy", "qty": 20} and live[-1][2] == 20


def test_stamps_normalise_dashed_tickers():
    calls = []
    sr.reconcile_symbol(card={"card_id": "c-v1", "allocation_usd": 1000}, symbol="BRK-B", desired="long", actual_qty=0, price=100.0,
                        bar_date="2026-09-03", submit_fn=lambda *a, **k: calls.append(k["client_order_id"]), now=NOW, share=1.0, stamp_symbol=True)
    assert calls == ["c-v1-2026-09-03-buy-BRK.B"]
    from tradelab.live.card_activity import card_order_pattern
    assert card_order_pattern("c-v1").match(calls[0])


def test_run_tick_switches_a_live_card_off_when_its_receipt_or_evidence_fails(monkeypatch):
    seen = []
    monkeypatch.setattr(sr, "run_once", lambda cards, *, deps, bar_date, now=None: (seen.extend(cards.keys()), {k: {"action": "none"} for k in cards})[1])
    updates = {}

    class _Reg:
        def __init__(self):
            self.cards = {
                "ok":    {**_card(card_id="ok")},
                "bad":   {**_card(card_id="bad")},
                "stale": {**_card(card_id="stale")},
                "paper": {**_card(card_id="paper", mode="paper", live=None)},
            }
        def all(self): return {k: dict(v) for k, v in self.cards.items()}
        def update(self, cid, fields): updates[cid] = fields; self.cards[cid].update(fields)

    deps = {"verify_live_receipt": lambda c: c["card_id"] != "bad",
            "live_evidence_stale": lambda c: "strategy code changed since the Full trial" if c["card_id"] == "stale" else None}
    reg = _Reg()
    sr.run_tick(registry=reg, deps=deps, now=NOW)
    assert set(seen) == {"ok", "paper"}
    assert updates["bad"]["status"] == "disabled" and "live_receipt_invalid_at" in updates["bad"]
    assert updates["stale"]["status"] == "disabled" and "live_evidence_stale_at" in updates["stale"] and "code changed" in updates["stale"]["live_off_reason"]
    # no verifier at all → every live card goes Off
    seen.clear(); updates.clear(); reg = _Reg()
    sr.run_tick(registry=reg, deps={}, now=NOW)
    assert "ok" not in seen and updates["ok"]["status"] == "disabled"
