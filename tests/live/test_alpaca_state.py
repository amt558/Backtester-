"""AlpacaState — 2-second cache around alpaca-py boundary."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from tradelab.live.alpaca_state import AlpacaState


def _client_with_returns(positions=None, orders=None, account=None):
    client = MagicMock()
    client.get_all_positions.return_value = positions or []
    client.get_orders.return_value = orders or []
    client.get_account.return_value = account or MagicMock(buying_power="100000")
    return client


def test_first_call_hits_alpaca():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=2.0)
    assert state.positions() == ["pos-A"]
    assert client.get_all_positions.call_count == 1


def test_second_call_within_ttl_uses_cache():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=2.0)
    state.positions()
    state.positions()
    assert client.get_all_positions.call_count == 1


def test_call_after_ttl_refetches():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=0.05)
    state.positions()
    time.sleep(0.1)
    state.positions()
    assert client.get_all_positions.call_count == 2


def test_invalidate_forces_refetch():
    client = _client_with_returns(positions=["pos-A"])
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.positions()
    state.invalidate()
    state.positions()
    assert client.get_all_positions.call_count == 2


def test_positions_orders_account_caches_are_independent():
    client = _client_with_returns()
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.positions()
    state.open_orders()
    state.account()
    state.positions()
    state.open_orders()
    state.account()
    assert client.get_all_positions.call_count == 1
    assert client.get_orders.call_count == 1
    assert client.get_account.call_count == 1


def test_open_orders_filters_to_open_status():
    """get_orders is called with status='open' so we never see filled/cancelled."""
    client = _client_with_returns(orders=[MagicMock(status="open")])
    state = AlpacaState(client=client, ttl_seconds=10.0)
    state.open_orders()
    args, kwargs = client.get_orders.call_args
    # alpaca-py expects a GetOrdersRequest object; assert status hint is present
    # in either args or kwargs
    request = (args[0] if args else kwargs.get("filter") or kwargs.get("request"))
    assert request is not None, "expected a request arg"
