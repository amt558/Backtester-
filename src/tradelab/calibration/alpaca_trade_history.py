"""Pulls filled orders from Alpaca paper account; pairs buy/sell into round-trip trades.

Used by Slice -1 retrospective when trades.csv doesn't exist (verified 2026-04-28).
Per memory reference_alpaca_trade_history_source.md.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any


def fetch_filled_orders(api: Any, *, after_iso: str, page_size: int = 500) -> list[dict]:
    """Paginated pull of all filled orders since `after_iso`."""
    all_orders: list[dict] = []
    until = None
    while True:
        page = api.list_orders(
            status="filled", after=after_iso, until=until,
            limit=page_size, direction="desc",
        )
        # Alpaca SDK returns list of Order objects OR dicts depending on version
        page_dicts = [o if isinstance(o, dict) else o._raw for o in page]
        if not page_dicts:
            break
        all_orders.extend(page_dicts)
        if len(page_dicts) < page_size:
            break
        until = page_dicts[-1]["filled_at"]  # paginate older
    return [o for o in all_orders if o.get("status") == "filled"]


def pair_buy_sell_into_trades(orders: list[dict]) -> list[dict]:
    """Pair each buy with the next sell for the same symbol → round-trip trade.

    Assumes one open position per symbol at a time (true for the deployed bot).
    Returns list of {symbol, entry_ts, exit_ts, entry_price, exit_price, qty, pnl,
    client_order_id_entry, client_order_id_exit}.
    """
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for o in sorted(orders, key=lambda x: x["filled_at"]):
        by_symbol[o["symbol"]].append(o)

    trades: list[dict] = []
    for symbol, ords in by_symbol.items():
        i = 0
        while i < len(ords) - 1:
            buy = ords[i]
            if buy["side"] != "buy":
                i += 1
                continue
            j = i + 1
            while j < len(ords) and ords[j]["side"] != "sell":
                j += 1
            if j >= len(ords):
                break
            sell = ords[j]
            qty = int(float(buy["filled_qty"]))
            entry_price = float(buy["filled_avg_price"])
            exit_price = float(sell["filled_avg_price"])
            trades.append({
                "symbol": symbol,
                "entry_ts": buy["filled_at"],
                "exit_ts": sell["filled_at"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "qty": qty,
                "pnl": (exit_price - entry_price) * qty,
                "client_order_id_entry": buy.get("client_order_id"),
                "client_order_id_exit": sell.get("client_order_id"),
            })
            i = j + 1
    return trades
