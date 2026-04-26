"""Tests for the new alpaca_client wrappers added in Slice 6."""
from unittest.mock import MagicMock, patch

import pytest

from tradelab.live import alpaca_client


@pytest.fixture
def mock_trading_client():
    """Replace get_client() with a MagicMock for the duration of a test."""
    with patch.object(alpaca_client, "get_client") as gc:
        client = MagicMock()
        gc.return_value = client
        yield client


def test_list_open_orders_returns_dicts(mock_trading_client):
    o1 = MagicMock()
    o1.id = "alp-1"
    o1.client_order_id = "card_a-1714142887000"
    o1.symbol = "AAPL"
    o1.qty = "10"
    o1.side.value = "buy"
    o1.status.value = "new"
    mock_trading_client.get_orders.return_value = [o1]

    out = alpaca_client.list_open_orders()

    assert out == [{
        "id": "alp-1",
        "client_order_id": "card_a-1714142887000",
        "symbol": "AAPL",
        "qty": "10",
        "side": "buy",
        "status": "new",
    }]
    # Verify it asked for OPEN status only
    call_args = mock_trading_client.get_orders.call_args
    assert call_args is not None


def test_list_open_orders_empty(mock_trading_client):
    mock_trading_client.get_orders.return_value = []
    assert alpaca_client.list_open_orders() == []


def test_cancel_order_by_id_calls_through(mock_trading_client):
    alpaca_client.cancel_order_by_id("alp-1")
    mock_trading_client.cancel_order_by_id.assert_called_once_with("alp-1")


def test_list_positions_returns_dicts(mock_trading_client):
    p1 = MagicMock()
    p1.symbol = "AAPL"
    p1.qty = "10"
    p1.side.value = "long"
    mock_trading_client.get_all_positions.return_value = [p1]

    out = alpaca_client.list_positions()
    assert out == [{"symbol": "AAPL", "qty": "10", "side": "long"}]


def test_list_positions_empty(mock_trading_client):
    mock_trading_client.get_all_positions.return_value = []
    assert alpaca_client.list_positions() == []
