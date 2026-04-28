"""Thin wrapper around alpaca-py for placing market orders.

Reads credentials once from C:/TradingScripts/alpaca_config.json (the same file
the dashboard proxy uses). paper_trading flag routes to paper vs live URL.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

CONFIG_PATH = Path("C:/TradingScripts/alpaca_config.json")

_client: Optional[TradingClient] = None
_lock = Lock()
logger = logging.getLogger("tradelab.live.alpaca")


def get_client() -> TradingClient:
    global _client
    with _lock:
        if _client is None:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            api_key = cfg["alpaca"]["api_key"]
            secret = cfg["alpaca"]["secret_key"]
            paper = bool(cfg["alpaca"].get("paper_trading", True))
            _client = TradingClient(api_key, secret, paper=paper)
            logger.info("alpaca client ready (paper=%s)", paper)
        return _client


def submit_market_order(
    symbol: str,
    side: str,
    quantity: float,
    client_order_id: Optional[str] = None,
) -> dict:
    client = get_client()
    req = MarketOrderRequest(
        symbol=symbol,
        qty=quantity,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
        extended_hours=False,
    )
    order = client.submit_order(req)
    return {
        "id": str(order.id),
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "qty": str(order.qty),
        "side": order.side.value if hasattr(order.side, "value") else str(order.side),
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
    }


from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
from alpaca.common.enums import Sort


def list_open_orders() -> list[dict]:
    """Return all open orders in the Alpaca account as plain dicts.

    Each dict has: id, client_order_id, symbol, qty, side, status.
    Used by panic.py L2 step.
    """
    client = get_client()
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    orders = client.get_orders(filter=req)
    return [
        {
            "id": str(o.id),
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "qty": str(o.qty),
            "side": o.side.value if hasattr(o.side, "value") else str(o.side),
            "status": o.status.value if hasattr(o.status, "value") else str(o.status),
        }
        for o in orders
    ]


def list_closed_orders(days: int = 90) -> list[dict]:
    """List filled/closed orders from the last ``days`` days.

    Returns list of dicts with: id, client_order_id, symbol, side, qty,
    filled_qty, filled_avg_price, filled_at, status. Results are returned
    oldest-first (``direction=Sort.ASC``) for chronological pairing by
    callers. ``filled_qty`` lets consumers correctly scale partial fills
    when pairing buys with sells.
    """
    from datetime import datetime, timedelta, timezone

    client = get_client()
    after = datetime.now(timezone.utc) - timedelta(days=days)
    req = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        after=after,
        limit=500,
        direction=Sort.ASC,
    )
    orders = client.get_orders(filter=req)
    return [
        {
            "id": str(o.id),
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "side": o.side.value if hasattr(o.side, "value") else str(o.side),
            "qty": float(o.qty) if o.qty else 0.0,
            "filled_qty": float(o.filled_qty) if getattr(o, "filled_qty", None) else 0.0,
            "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            "status": o.status.value if hasattr(o.status, "value") else str(o.status),
        }
        for o in orders
    ]


def cancel_order_by_id(order_id: str) -> None:
    """Cancel a single Alpaca order by its server-side ID. Raises on failure."""
    client = get_client()
    client.cancel_order_by_id(order_id)


def list_positions() -> list[dict]:
    """Return all open positions in the Alpaca account as plain dicts.

    Each dict has: symbol, qty (string for precision), side.
    Used by panic.py L3 step.
    """
    client = get_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": str(p.qty),
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
        }
        for p in positions
    ]
