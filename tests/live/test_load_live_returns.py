"""Test load_live_returns_for_card pairing logic.

These tests use monkeypatch to replace list_closed_orders in the
alpaca_client module (which the function imports lazily), so no real
Alpaca credentials are needed.
"""
from __future__ import annotations

import pytest

from tradelab.live.tracking_error import load_live_returns_for_card


def _make_order(
    coid: str,
    symbol: str,
    side: str,
    price: float,
    ts: str,
    oid: str = "1",
    qty: float = 1.0,
    filled_qty: float | None = None,
) -> dict:
    """Convenience factory for a minimal closed-order dict.

    ``filled_qty`` defaults to ``qty`` (full fill) when not specified.
    """
    return {
        "id": oid,
        "client_order_id": coid,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "filled_qty": qty if filled_qty is None else filled_qty,
        "filled_avg_price": price,
        "filled_at": ts,
        "status": "filled",
    }


def test_no_orders_returns_empty(monkeypatch):
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: [])
    result = load_live_returns_for_card("alpha-v1")
    assert result == []


def test_unmatched_card_id_returns_empty(monkeypatch):
    fills = [
        _make_order("other-card-123", "AAPL", "buy", 100.0, "2026-01-01T10:00:00+00:00"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert result == []


def test_long_round_trip_winner(monkeypatch):
    fills = [
        _make_order("alpha-v1-100", "AAPL", "buy",  100.0, "2026-01-01T10:00:00+00:00", "1"),
        _make_order("alpha-v1-101", "AAPL", "sell", 110.0, "2026-01-01T15:00:00+00:00", "2"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert result == [pytest.approx(10.0, abs=0.001)]


def test_long_round_trip_loser(monkeypatch):
    fills = [
        _make_order("alpha-v1-100", "AAPL", "buy",  100.0, "2026-01-01T10:00:00+00:00", "1"),
        _make_order("alpha-v1-101", "AAPL", "sell",  95.0, "2026-01-01T15:00:00+00:00", "2"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert result == [pytest.approx(-5.0, abs=0.001)]


def test_unpaired_entry_ignored(monkeypatch):
    """Entry without matching exit (open position) should not appear in returns."""
    fills = [
        _make_order("alpha-v1-100", "AAPL", "buy", 100.0, "2026-01-01T10:00:00+00:00", "1"),
        # No exit order
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert result == []


def test_alpaca_failure_returns_empty(monkeypatch):
    """If Alpaca pull raises, return [] so endpoint reports 'insufficient'."""
    def boom(days=90):
        raise RuntimeError("alpaca down")

    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", boom)
    result = load_live_returns_for_card("alpha-v1")
    assert result == []


def test_multiple_round_trips_chronological(monkeypatch):
    """Multiple completed round-trips are returned in chronological order."""
    fills = [
        # Round trip 1: AAPL +5%
        _make_order("alpha-v1-100", "AAPL", "buy",  100.0, "2026-01-01T10:00:00+00:00", "1"),
        _make_order("alpha-v1-101", "AAPL", "sell", 105.0, "2026-01-01T15:00:00+00:00", "2"),
        # Round trip 2: MSFT -2%
        _make_order("alpha-v1-200", "MSFT", "buy",  50.0, "2026-01-02T10:00:00+00:00", "3"),
        _make_order("alpha-v1-201", "MSFT", "sell", 49.0, "2026-01-02T15:00:00+00:00", "4"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert len(result) == 2
    assert result[0] == pytest.approx(5.0, abs=0.001)
    assert result[1] == pytest.approx(-2.0, abs=0.001)


def test_fifo_pairs_oldest_entry_first(monkeypatch):
    """Two stacked entries then two exits → exits pair against entries in FIFO order."""
    fills = [
        # Two open entries (same side, same symbol)
        _make_order("alpha-v1-100", "AAPL", "buy", 100.0, "2026-01-01T10:00:00+00:00", "1", qty=1.0),
        _make_order("alpha-v1-101", "AAPL", "buy", 110.0, "2026-01-01T11:00:00+00:00", "2", qty=1.0),
        # Two exits — first should pair with $100 entry, second with $110 entry
        _make_order("alpha-v1-200", "AAPL", "sell", 120.0, "2026-01-01T15:00:00+00:00", "3", qty=1.0),
        _make_order("alpha-v1-201", "AAPL", "sell", 121.0, "2026-01-01T16:00:00+00:00", "4", qty=1.0),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert len(result) == 2
    # First exit ($120) vs oldest entry ($100) → 20%
    assert result[0] == pytest.approx(20.0, abs=0.001)
    # Second exit ($121) vs second entry ($110) → 10%
    assert result[1] == pytest.approx(10.0, abs=0.001)


def test_partial_fill_splits_entry(monkeypatch):
    """Entry qty 10 paired against exit qty 4 yields one return; 6 shares stay open."""
    fills = [
        _make_order(
            "alpha-v1-100", "AAPL", "buy", 100.0,
            "2026-01-01T10:00:00+00:00", "1", qty=10.0,
        ),
        _make_order(
            "alpha-v1-101", "AAPL", "sell", 110.0,
            "2026-01-01T15:00:00+00:00", "2", qty=4.0,
        ),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    # Only one round-trip pair emitted; 6 shares of the entry remain open.
    assert len(result) == 1
    assert result[0] == pytest.approx(10.0, abs=0.001)


def test_partial_fill_exit_consumes_multiple_entries(monkeypatch):
    """Exit qty 7 spans entry-A (qty 5 @ $100) and entry-B (qty 3 @ $110) FIFO,
    producing two profit_pct entries; 1 share of entry-B stays open."""
    fills = [
        _make_order("alpha-v1-100", "AAPL", "buy", 100.0, "2026-01-01T10:00:00+00:00", "1", qty=5.0),
        _make_order("alpha-v1-101", "AAPL", "buy", 110.0, "2026-01-01T11:00:00+00:00", "2", qty=3.0),
        _make_order("alpha-v1-200", "AAPL", "sell", 120.0, "2026-01-01T15:00:00+00:00", "3", qty=7.0),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert len(result) == 2
    # 5 shares of entry-A @ $100 → +20%
    assert result[0] == pytest.approx(20.0, abs=0.001)
    # 2 shares of entry-B @ $110 → ~9.0909%
    assert result[1] == pytest.approx(100.0 * (120.0 - 110.0) / 110.0, abs=0.001)


def test_different_symbols_do_not_cross_pair(monkeypatch):
    """A SELL on MSFT must not close an open AAPL BUY — symbols are siloed."""
    fills = [
        # Open AAPL long — should stay open and yield no return
        _make_order("alpha-v1-100", "AAPL", "buy",  100.0, "2026-01-01T10:00:00+00:00", "1"),
        # MSFT round-trip in between — must NOT consume the AAPL entry
        _make_order("alpha-v1-200", "MSFT", "buy",   50.0, "2026-01-01T11:00:00+00:00", "2"),
        _make_order("alpha-v1-201", "MSFT", "sell",  55.0, "2026-01-01T12:00:00+00:00", "3"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    # Only the MSFT round-trip should appear (+10%), AAPL stays open.
    assert len(result) == 1
    assert result[0] == pytest.approx(10.0, abs=0.001)


def test_short_round_trip(monkeypatch):
    """Sell-then-buy short trade returns positive when buy price is below sell."""
    fills = [
        _make_order("alpha-v1-100", "AAPL", "sell", 100.0, "2026-01-01T10:00:00+00:00", "1"),
        _make_order("alpha-v1-101", "AAPL", "buy",   90.0, "2026-01-01T15:00:00+00:00", "2"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    assert result == [pytest.approx(10.0, abs=0.001)]


def test_card_id_prefix_is_strict(monkeypatch):
    """A card_id that is a prefix-substring (no trailing dash) of another must
    not pull the wrong card's fills."""
    fills = [
        # Real fills for "alpha-v1"
        _make_order("alpha-v1-1", "AAPL", "buy",  100.0, "2026-01-01T10:00:00+00:00", "1"),
        _make_order("alpha-v1-2", "AAPL", "sell", 105.0, "2026-01-01T15:00:00+00:00", "2"),
        # Fills tagged for a *different* card whose id starts with "alpha-v1"
        _make_order("alpha-v10-1", "TSLA", "buy",  200.0, "2026-01-02T10:00:00+00:00", "3"),
        _make_order("alpha-v10-2", "TSLA", "sell", 220.0, "2026-01-02T15:00:00+00:00", "4"),
    ]
    monkeypatch.setattr("tradelab.live.alpaca_client.list_closed_orders", lambda days=90: fills)
    result = load_live_returns_for_card("alpha-v1")
    # Only alpha-v1's AAPL round-trip should be returned (+5%).
    assert len(result) == 1
    assert result[0] == pytest.approx(5.0, abs=0.001)
