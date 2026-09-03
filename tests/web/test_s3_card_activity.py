"""S3 (2026-09-02) — per-card activity attribution for the strategy tab."""
from __future__ import annotations

import json

import pytest

from tradelab.live import card_activity as ca
from tradelab.web import handlers


def _o(cid, sym, side, qty, price, at, filled_qty=None):
    return {"id": f"{cid}{at}", "client_order_id": cid, "symbol": sym, "side": side, "qty": qty,
            "filled_qty": filled_qty if filled_qty is not None else qty,
            "filled_avg_price": price, "filled_at": at, "status": "filled"}


CLOSED = [
    _o("alpha-v1-2026-08-01-buy", "NVDA", "buy", 10, 100.0, "2026-08-01T14:30:00Z"),
    _o("beta-v1-2026-08-01-buy", "NVDA", "buy", 5, 100.0, "2026-08-01T14:31:00Z"),   # other card, same symbol
    _o(None, "NVDA", "buy", 7, 101.0, "2026-08-01T15:00:00Z"),                         # legacy bot, no prefix
    _o("alpha-v1-2026-08-05-sell", "NVDA", "sell", 4, 110.0, "2026-08-05T20:00:00Z"),
    _o("alpha-v1-2026-08-09-sell", "NVDA", "sell", 6, 95.0, "2026-08-09T20:00:00Z"),
    _o("alpha-v1-2026-08-12-buy", "AAPL", "buy", 3, 200.0, "2026-08-12T14:30:00Z"),  # still open
]


def test_orders_for_card_uses_prefix_only():
    got = ca.orders_for_card("alpha-v1", CLOSED)
    assert [o["client_order_id"] for o in got] == [
        "alpha-v1-2026-08-01-buy", "alpha-v1-2026-08-05-sell",
        "alpha-v1-2026-08-09-sell", "alpha-v1-2026-08-12-buy",
    ]
    assert all(not (o["client_order_id"] or "").startswith("beta") for o in got)


def test_prefix_does_not_match_a_longer_card_id():
    """alpha-v1 must not claim alpha-v10's orders."""
    closed = [_o("alpha-v10-2026-08-01-buy", "NVDA", "buy", 1, 1.0, "2026-08-01T00:00:00Z")]
    assert ca.orders_for_card("alpha-v1", closed) == []


def test_round_trips_fifo_with_partial_exits_and_dollars():
    trips = ca.pair_round_trips(ca.orders_for_card("alpha-v1", CLOSED))
    assert len(trips) == 2
    first, second = trips
    assert first["qty"] == 4 and first["pnl_usd"] == 40.0 and first["exit_at"].startswith("2026-08-05")
    assert second["qty"] == 6 and second["pnl_usd"] == -30.0 and second["exit_at"].startswith("2026-08-09")
    assert first["side"] == "long" and first["return_pct"] == 10.0


def test_daily_pnl_groups_by_exit_date():
    trips = ca.pair_round_trips(ca.orders_for_card("alpha-v1", CLOSED))
    assert ca.daily_pnl(trips) == {"2026-08-05": 40.0, "2026-08-09": -30.0}


def test_open_lot_is_a_position_not_a_trade():
    trips = ca.pair_round_trips(ca.orders_for_card("alpha-v1", CLOSED))
    assert not any(t["symbol"] == "AAPL" for t in trips)


def test_positions_filtered_to_card_symbols():
    pos = [{"symbol": "AAPL", "qty": "3", "side": "long", "avg_entry_price": "200", "current_price": "210",
            "market_value": "630", "unrealized_pl": "30"},
           {"symbol": "MNST", "qty": "108", "side": "long", "avg_entry_price": "91.73", "current_price": "44.42",
            "market_value": "4797", "unrealized_pl": "-5108"}]
    got = ca.positions_for_card(["aapl", "NVDA"], pos)
    assert [p["symbol"] for p in got] == ["AAPL"] and got[0]["unrealized_pl"] == 30.0


def test_build_activity_totals_and_soft_failure():
    card = {"card_id": "alpha-v1", "symbol": "PORTFOLIO"}
    act = ca.build_activity(card, card_symbols=["NVDA", "AAPL"],
                            list_closed_orders=lambda: CLOSED,
                            list_positions=lambda: (_ for _ in ()).throw(RuntimeError("alpaca down")))
    assert act["totals"]["realized_pnl"] == 10.0
    assert act["totals"]["closed_trades"] == 2 and act["totals"]["wins"] == 1 and act["totals"]["win_rate"] == 50.0
    assert act["open_positions"] == [] and "alpaca down" in act["error"]
    assert act["symbols"] == ["AAPL", "NVDA"]


def test_activity_route_404_for_unknown_card(tmp_path, monkeypatch):
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    body, status = handlers.handle_get_with_status("/tradelab/cards/ghost-v1/activity")
    assert status == 404


def test_activity_route_uses_card_symbols_and_injected_alpaca(tmp_path, monkeypatch):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"alpha-v1": {"card_id": "alpha-v1", "symbol": "NVDA", "status": "disabled",
                                              "strategy": "alpha", "base_name": "alpha", "version": 1}}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    import tradelab.live.alpaca_client as ac
    # S9: the route passes the card's account explicitly (paper here).
    monkeypatch.setattr(ac, "list_closed_orders", lambda days=90, account="paper": CLOSED if account == "paper" else [])
    monkeypatch.setattr(ac, "list_positions_detail", lambda account="paper": [
        {"symbol": "NVDA", "qty": "10", "side": "long", "avg_entry_price": "100", "current_price": "105",
         "market_value": "1050", "unrealized_pl": "50"}])
    body, status = handlers.handle_get_with_status("/tradelab/cards/alpha-v1/activity?days=30")
    assert status == 200
    d = json.loads(body)["data"]
    assert d["days"] == 30 and d["symbols"] == ["NVDA"]
    assert d["totals"]["closed_trades"] == 2 and d["open_positions"][0]["unrealized_pl"] == 50.0
    assert d["daily_pnl"]["2026-08-05"] == 40.0


def test_card_symbols_prefers_card_symbol_then_declared(monkeypatch):
    assert handlers._card_symbols({"symbol": "nvda"}) == ["NVDA"]
    import tradelab.registry as reg
    class Decl:
        symbols = ["AAPL", "MSFT"]
    monkeypatch.setattr(reg, "load_strategy_class", lambda name: Decl)
    assert handlers._card_symbols({"symbol": "PORTFOLIO", "strategy": "x"}) == ["AAPL", "MSFT"]


# ---- S3 review notes (specialist) --------------------------------------------

def test_strict_stamp_shape_rejects_foreign_ids_with_same_prefix():
    closed = [
        _o("alpha-v1-manual-note", "NVDA", "buy", 1, 1.0, "2026-08-01T00:00:00Z"),
        _o("alpha-v1-2026-08-01-buy-extra", "NVDA", "buy", 1, 1.0, "2026-08-01T00:00:01Z"),
        _o("alpha-v1-2026-08-02-flatten", "NVDA", "sell", 1, 2.0, "2026-08-02T00:00:00Z"),
    ]
    got = ca.orders_for_card("alpha-v1", closed)
    assert [o["client_order_id"] for o in got] == ["alpha-v1-2026-08-02-flatten"]


def test_closed_orders_counts_exit_orders_not_lots():
    """Two buys swept by one sell = 2 FIFO lots but ONE closing order."""
    closed = [
        _o("alpha-v1-2026-08-01-buy", "NVDA", "buy", 5, 100.0, "2026-08-01T14:30:00Z"),
        _o("alpha-v1-2026-08-02-buy", "NVDA", "buy", 5, 102.0, "2026-08-02T14:30:00Z"),
        _o("alpha-v1-2026-08-05-sell", "NVDA", "sell", 10, 110.0, "2026-08-05T20:00:00Z"),
    ]
    orders = ca.orders_for_card("alpha-v1", closed)
    assert len(ca.pair_round_trips(orders)) == 2
    assert ca.closing_order_count(orders) == 1
    act = ca.build_activity({"card_id": "alpha-v1"}, card_symbols=["NVDA"],
                            list_closed_orders=lambda: closed, list_positions=lambda: [])
    assert act["totals"]["closed_trades"] == 2 and act["totals"]["closed_orders"] == 1


def test_truncated_flag_when_window_hits_page_limit():
    closed = [_o(None, "SPY", "buy", 1, 1.0, f"2026-01-01T00:{i//60:02d}:{i%60:02d}Z")
              for i in range(ca.ORDERS_PAGE_LIMIT)]
    act = ca.build_activity({"card_id": "alpha-v1"}, card_symbols=["SPY"],
                            list_closed_orders=lambda: closed, list_positions=lambda: [])
    assert act["truncated"] is True and "page limit" in act["error"]
    act2 = ca.build_activity({"card_id": "alpha-v1"}, card_symbols=["SPY"],
                             list_closed_orders=lambda: closed[:-1], list_positions=lambda: [])
    assert act2["truncated"] is False and act2["error"] is None


def test_orphaned_lot_when_account_no_longer_holds_it():
    """Card bought AAPL and never sold under its stamp, but the account has no
    AAPL — somebody flattened it outside the card. The tab must say so."""
    act = ca.build_activity({"card_id": "alpha-v1"}, card_symbols=["NVDA", "AAPL"],
                            list_closed_orders=lambda: CLOSED, list_positions=lambda: [])
    assert act["orphaned_lots"] == ["AAPL"]
    act2 = ca.build_activity({"card_id": "alpha-v1"}, card_symbols=["NVDA", "AAPL"],
                             list_closed_orders=lambda: CLOSED,
                             list_positions=lambda: [{"symbol": "AAPL", "qty": "3", "side": "long"}])
    assert act2["orphaned_lots"] == []


def _patch(handlers_mod, card_id, payload):
    return handlers_mod.handle_patch_with_status(f"/tradelab/cards/{card_id}", json.dumps(payload).encode())


def _seed(tmp_path, monkeypatch, **fields):
    cards = tmp_path / "cards.json"
    base = {"card_id": "alpha-v1", "symbol": "NVDA", "status": "disabled", "strategy": "alpha",
            "base_name": "alpha", "version": 1, "allocation_usd": 0}
    base.update(fields)
    cards.write_text(json.dumps({"alpha-v1": base}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    return cards


def test_patch_refuses_enable_for_blocked_route(tmp_path, monkeypatch):
    cards = _seed(tmp_path, monkeypatch, promotion_route="BLOCKED", allocation_usd=500)
    body, status = _patch(handlers, "alpha-v1", {"status": "enabled"})
    assert status == 422 and "BLOCKED" in body
    assert json.loads(cards.read_text())["alpha-v1"]["status"] == "disabled"


def test_patch_allows_enable_for_clear_route_with_allocation(tmp_path, monkeypatch):
    cards = _seed(tmp_path, monkeypatch, promotion_route="CLEAR", allocation_usd=500)
    body, status = _patch(handlers, "alpha-v1", {"status": "enabled"})
    assert status == 200
    assert json.loads(cards.read_text())["alpha-v1"]["status"] == "enabled"


def test_patch_refuses_enable_for_advisory_without_override_and_for_no_route(tmp_path, monkeypatch):
    """S4: ADVISORY needs an override record (S6 writes it); a card with no
    route on record (accepted before routes were stored) is refused too."""
    _seed(tmp_path, monkeypatch, promotion_route="ADVISORY", allocation_usd=500)
    body, status = _patch(handlers, "alpha-v1", {"status": "enabled"})
    assert status == 422 and "ADVISORY" in body
    _seed(tmp_path, monkeypatch, promotion_route="ADVISORY", allocation_usd=500,
          override={"reason": "test", "expires_at": "2099-01-01"})
    assert _patch(handlers, "alpha-v1", {"status": "enabled"})[1] == 200
    _seed(tmp_path, monkeypatch, allocation_usd=500)
    body, status = _patch(handlers, "alpha-v1", {"status": "enabled"})
    assert status == 422 and "no promotion route" in body


def test_patch_disable_and_allocation_never_gated(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, promotion_route="BLOCKED", status="enabled")
    assert _patch(handlers, "alpha-v1", {"status": "disabled"})[1] == 200
    assert _patch(handlers, "alpha-v1", {"allocation_usd": 100})[1] == 200


# ---- Flatten (review note 1 + 2): prefixed, card-scoped, Off-first -----------

from datetime import datetime, timezone

NOW = datetime(2026, 9, 2, 14, 5, 9, tzinfo=timezone.utc)


def test_flatten_stamp_matches_pattern_and_is_per_symbol():
    stamp = ca.flatten_stamp("alpha-v1", "nvda", NOW)
    assert stamp == "alpha-v1-2026-09-02-140509-flatten-NVDA"
    assert ca.card_order_pattern("alpha-v1").match(stamp)
    assert ca.card_order_pattern("alpha-v1").match("alpha-v1-2026-09-02-14-buy")   # hourly bucket
    assert not ca.card_order_pattern("alpha-v10").match(stamp)


def test_plan_flatten_closes_only_the_cards_share():
    """Card is net long 6 NVDA + 3 AAPL by its own fills; the account holds 20
    NVDA (legacy bot too) and no AAPL. Plan: sell 6 NVDA, skip AAPL as orphan."""
    orders = ca.orders_for_card("alpha-v1", CLOSED)
    assert ca.open_lots(orders) == {"AAPL": 3.0}  # 10 bought, 4+6 sold → NVDA flat
    more = CLOSED + [_o("alpha-v1-2026-08-20-buy", "NVDA", "buy", 6, 90.0, "2026-08-20T14:30:00Z")]
    orders = ca.orders_for_card("alpha-v1", more)
    plan = ca.plan_flatten(orders, [{"symbol": "NVDA", "qty": "20", "side": "long"}])
    assert plan["orders"] == [{"symbol": "NVDA", "side": "sell", "qty": 6.0}]
    assert [s["symbol"] for s in plan["skipped"]] == ["AAPL"]


def test_plan_flatten_caps_at_account_qty_and_skips_opposite_side():
    orders = [{"symbol": "NVDA", "side": "buy", "qty": 10.0, "price": 1.0, "filled_at": "t"},
              {"symbol": "MSFT", "side": "buy", "qty": 2.0, "price": 1.0, "filled_at": "t"}]
    plan = ca.plan_flatten(orders, [{"symbol": "NVDA", "qty": "4", "side": "long"},
                                    {"symbol": "MSFT", "qty": "2", "side": "short"}])
    assert plan["orders"] == [{"symbol": "NVDA", "side": "sell", "qty": 4.0}]
    assert plan["skipped"][0]["symbol"] == "MSFT"


def test_flatten_route_forces_off_then_submits_prefixed_sells(tmp_path, monkeypatch):
    cards = _seed(tmp_path, monkeypatch, status="enabled", allocation_usd=500)
    more = CLOSED + [_o("alpha-v1-2026-08-20-buy", "NVDA", "buy", 6, 90.0, "2026-08-20T14:30:00Z")]
    sent = []
    deps = {"list_closed_orders": lambda: more,
            "list_positions": lambda: [{"symbol": "NVDA", "qty": "20", "side": "long"}],
            "submit": lambda sym, side, qty, cid: sent.append((sym, side, qty, cid)) or {"id": "o1"},
            "now": NOW}
    body, status = handlers._flatten_card("alpha-v1", {}, deps=deps)
    assert status == 200, body
    d = json.loads(body)["data"]
    assert d["forced_off"] is True
    assert json.loads(cards.read_text())["alpha-v1"]["status"] == "disabled"
    assert sent == [("NVDA", "sell", 6.0, "alpha-v1-2026-09-02-140509-flatten-NVDA")]
    assert d["submitted"][0]["order_id"] == "o1" and d["skipped"][0]["symbol"] == "AAPL"


def test_flatten_dry_run_neither_submits_nor_forces_off(tmp_path, monkeypatch):
    cards = _seed(tmp_path, monkeypatch, status="enabled")
    sent = []
    deps = {"list_closed_orders": lambda: CLOSED,
            "list_positions": lambda: [{"symbol": "AAPL", "qty": "3", "side": "long"}],
            "submit": lambda *a: sent.append(a), "now": NOW}
    body, status = handlers._flatten_card("alpha-v1", {"dry_run": True}, deps=deps)
    d = json.loads(body)["data"]
    assert status == 200 and d["planned"] == [{"symbol": "AAPL", "side": "sell", "qty": 3.0}]
    assert sent == [] and d["forced_off"] is False
    assert json.loads(cards.read_text())["alpha-v1"]["status"] == "enabled"


def test_flatten_refuses_when_order_window_truncated(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    closed = [_o(None, "SPY", "buy", 1, 1.0, "2026-01-01T00:00:00Z")] * ca.ORDERS_PAGE_LIMIT
    sent = []
    deps = {"list_closed_orders": lambda: closed, "list_positions": lambda: [],
            "submit": lambda *a: sent.append(a), "now": NOW}
    body, status = handlers._flatten_card("alpha-v1", {}, deps=deps)
    assert status == 409 and sent == []


def test_flatten_route_dispatch_and_404(tmp_path, monkeypatch):
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    body, status = handlers.handle_post_with_status("/tradelab/cards/ghost-v1/flatten", b'{"dry_run": true}')
    assert status == 404
