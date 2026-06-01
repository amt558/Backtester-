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
