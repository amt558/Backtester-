"""Paper-locked desired-state execution engine for Python cards.

Pure decision core + a thin daemon (added in later tasks). EVERY Alpaca
interaction is an injected callable so tests never touch a real account.
Paper-only until an explicit config flip enables live (out of scope here)."""
from __future__ import annotations

import math
from typing import Optional


def desired_position(latest_bar: dict) -> str:
    """Map a strategy's latest-bar signals to a desired position.
    sell_signal (explicit exit) wins over buy_signal. Neither -> 'hold'
    (leave the current position untouched; the engine never invents an exit)."""
    if bool(latest_bar.get("sell_signal")):
        return "flat"
    if bool(latest_bar.get("buy_signal")):
        return "long"
    return "hold"


def size_qty(allocation_usd: Optional[float], price: Optional[float]) -> int:
    """Whole-share qty from a card's dollar allocation. 0 on any invalid input."""
    try:
        a = float(allocation_usd)
        p = float(price)
    except (TypeError, ValueError):
        return 0
    if a <= 0 or p <= 0:
        return 0
    return int(math.floor(a / p))


def safety_block_reason(config: dict, *, daily_pnl: float, is_entry: bool) -> Optional[str]:
    """Return a human reason to BLOCK an order, or None to allow.
    Hard gates: paper_trading must be True; kill_switch halts everything; a
    breached daily_loss_limit halts new ENTRIES (exits still allowed)."""
    alpaca = config.get("alpaca", {}) or {}
    trading = config.get("trading", {}) or {}
    if not (alpaca.get("paper_trading", True) is True):
        return "paper_trading is not True (live trading is disabled in this engine)"
    if bool(trading.get("kill_switch", False)):
        return "kill_switch is engaged"
    limit = trading.get("daily_loss_limit")
    if is_entry and limit is not None:
        try:
            if float(daily_pnl) <= float(limit):
                return f"daily loss {daily_pnl:.0f} breached limit {float(limit):.0f}"
        except (TypeError, ValueError):
            pass
    return None


def reconcile_card(*, card: dict, desired: str, actual_qty: int, price: float,
                   bar_date: str, submit_fn) -> dict:
    """Reconcile one card's desired position with its actual Alpaca position by
    placing at most ONE market order via submit_fn. Idempotent: a card already
    in its desired state is a no-op. submit_fn(symbol, side, quantity,
    client_order_id) is injected (real or mock)."""
    symbol = card["symbol"]
    cid = card["card_id"]
    if desired == "long" and actual_qty <= 0:
        qty = size_qty(card.get("allocation_usd"), price)
        if qty <= 0:
            return {"action": "skip", "reason": "allocation/price yields 0 shares"}
        submit_fn(symbol, "buy", qty, client_order_id=f"{cid}-{bar_date}-buy")
        return {"action": "buy", "qty": qty}
    if desired == "flat" and actual_qty > 0:
        submit_fn(symbol, "sell", actual_qty, client_order_id=f"{cid}-{bar_date}-sell")
        return {"action": "sell", "qty": actual_qty}
    return {"action": "none"}
