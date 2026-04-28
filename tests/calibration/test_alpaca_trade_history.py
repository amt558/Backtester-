import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from tradelab.calibration.alpaca_trade_history import (
    fetch_filled_orders, pair_buy_sell_into_trades,
)

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
    assert len(trades) == 2
    aapl = next(t for t in trades if t["symbol"] == "AAPL")
    assert aapl["entry_price"] == pytest.approx(180.10)
    assert aapl["exit_price"] == pytest.approx(182.50)
    assert aapl["qty"] == 100
    assert aapl["pnl"] == pytest.approx((182.50 - 180.10) * 100)
    nvda = next(t for t in trades if t["symbol"] == "NVDA")
    assert nvda["pnl"] == pytest.approx((605.00 - 610.00) * 20)


def test_pair_buy_sell_handles_unmatched_open_position():
    """If a buy has no corresponding sell, it must be skipped (not error)."""
    orders = [
        {"id": "a", "symbol": "TSLA", "side": "buy", "qty": "10",
         "filled_qty": "10", "filled_avg_price": "200.0",
         "filled_at": "2026-01-01T14:00:00Z", "client_order_id": "x-1",
         "status": "filled"},
    ]
    trades = pair_buy_sell_into_trades(orders)
    assert trades == []


def test_fetch_filled_orders_handles_object_returns():
    """Alpaca SDK sometimes returns Order objects with _raw, not dicts."""
    fake_api = MagicMock()
    class FakeOrder:
        def __init__(self, raw):
            self._raw = raw
    raws = json.loads((FIXTURES / "alpaca_orders_sample.json").read_text())
    fake_api.list_orders.side_effect = [[FakeOrder(r) for r in raws], []]
    out = fetch_filled_orders(fake_api, after_iso="2026-01-01T00:00:00Z")
    assert len(out) == 4
    assert out[0]["symbol"] == "AAPL"
