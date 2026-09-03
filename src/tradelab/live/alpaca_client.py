"""Thin wrapper around alpaca-py for placing market orders.

Two accounts, never confused (S9):

  paper  credentials from C:/TradingScripts/alpaca_config.json (the same
         file the dashboard proxy uses); its paper_trading flag picks the URL
         exactly as before.
  live   credentials ONLY from ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY
         (process env or tradelab's .env). Absent keys raise
         LiveNotConfigured — there is no fallback to the paper file.

Every wrapper takes ``account=`` and defaults to "paper", so every caller
that predates S9 is unchanged.
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
LIVE_KEY_ENV = "ALPACA_LIVE_API_KEY"
LIVE_SECRET_ENV = "ALPACA_LIVE_SECRET_KEY"
ACCOUNTS = ("paper", "live")

_clients: dict[str, TradingClient] = {}
_lock = Lock()
logger = logging.getLogger("tradelab.live.alpaca")


class LiveNotConfigured(Exception):
    """No live keys in the environment — nothing may touch the live account."""


class PaperMisconfigured(Exception):
    """alpaca_config.json's paper_trading flag is not True. Now that a real
    live path exists, the "paper" client must never point at a live URL:
    any caller asking for paper gets this instead of a client."""


def live_keys_present() -> bool:
    """True when both live keys are set (after loading .env). Never logs or
    returns the values."""
    import os
    try:
        from tradelab.env import load_env
        load_env()
    except Exception:  # noqa: BLE001
        pass
    return bool(os.environ.get(LIVE_KEY_ENV, "").strip()) and bool(os.environ.get(LIVE_SECRET_ENV, "").strip())


def _check_account(account: str) -> str:
    if account not in ACCOUNTS:
        raise ValueError(f"account must be one of {ACCOUNTS}, got {account!r}")
    return account


def get_client(account: str = "paper") -> TradingClient:
    account = _check_account(account)
    with _lock:
        c = _clients.get(account)
        if c is None:
            if account == "live":
                import os
                if not live_keys_present():
                    raise LiveNotConfigured(
                        f"live keys missing — set {LIVE_KEY_ENV} and {LIVE_SECRET_ENV} in tradelab/.env")
                c = TradingClient(os.environ[LIVE_KEY_ENV].strip(), os.environ[LIVE_SECRET_ENV].strip(), paper=False)
                logger.info("alpaca LIVE client ready")
            else:
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
                api_key = cfg["alpaca"]["api_key"]
                secret = cfg["alpaca"]["secret_key"]
                if cfg["alpaca"].get("paper_trading") is not True:
                    raise PaperMisconfigured("alpaca_config.json: paper_trading must be exactly true — the paper "
                                             "client refuses to point anywhere else (live goes through env keys)")
                c = TradingClient(api_key, secret, paper=True)
                logger.info("alpaca client ready (paper=True)")
            _clients[account] = c
        return c


def submit_market_order(
    symbol: str,
    side: str,
    quantity: float,
    client_order_id: Optional[str] = None,
    account: str = "paper",
) -> dict:
    client = get_client(account)
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


def list_open_orders(account: str = "paper") -> list[dict]:
    """Return all open orders in the Alpaca account as plain dicts.

    Each dict has: id, client_order_id, symbol, qty, side, status.
    Used by panic.py L2 step.
    """
    client = get_client(account)
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


def list_closed_orders(days: int = 90, account: str = "paper") -> list[dict]:
    """List filled/closed orders from the last ``days`` days.

    Returns list of dicts with: id, client_order_id, symbol, side, qty,
    filled_qty, filled_avg_price, filled_at, status. Results are returned
    oldest-first (``direction=Sort.ASC``) for chronological pairing by
    callers. ``filled_qty`` lets consumers correctly scale partial fills
    when pairing buys with sells.
    """
    from datetime import datetime, timedelta, timezone

    client = get_client(account)
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


def list_positions_detail(account: str = "paper") -> list[dict]:
    """Open positions with the fields a strategy tab shows (S3). Separate from
    list_positions() so panic's contract stays untouched."""
    client = get_client(account)
    out = []
    for p in client.get_all_positions():
        out.append({
            "symbol": p.symbol,
            "qty": str(p.qty),
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
            "avg_entry_price": str(getattr(p, "avg_entry_price", "") or ""),
            "current_price": str(getattr(p, "current_price", "") or ""),
            "market_value": str(getattr(p, "market_value", "") or ""),
            "unrealized_pl": str(getattr(p, "unrealized_pl", "") or ""),
        })
    return out


def cancel_order_by_id(order_id: str, account: str = "paper") -> None:
    """Cancel a single Alpaca order by its server-side ID. Raises on failure."""
    client = get_client(account)
    client.cancel_order_by_id(order_id)


def list_positions(account: str = "paper") -> list[dict]:
    """Return all open positions in the Alpaca account as plain dicts.

    Each dict has: symbol, qty (string for precision), side.
    Used by panic.py L3 step.
    """
    client = get_client(account)
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": str(p.qty),
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
        }
        for p in positions
    ]


def account_day_pnl(account: str = "paper") -> float:
    """equity − last_equity for the account; raises on any unreadable value
    (callers fail closed)."""
    acct = get_client(account).get_account()
    return float(acct.equity) - float(acct.last_equity)
