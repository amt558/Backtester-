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
