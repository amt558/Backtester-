"""Per-card activity — what ONE strategy's card actually did on Alpaca (S3).

Attribution rule: the paper engine stamps every order it places with
``client_order_id = f"{card_id}-{bar_date}-{side}"`` (strategy_runner.reconcile_card),
so an order belongs to a card iff its client_order_id starts with ``f"{card_id}-"``.
Orders without that prefix (the legacy bot, manual trades) are never attributed.

Round-trips are paired per symbol with a qty-aware FIFO of open lots — the same
rule tracking_error.load_live_returns_for_card uses — but here each closed lot
also yields dollars and dates so a strategy tab can draw its own P&L calendar.

Everything is pure over plain dicts; the Alpaca calls are injected so the
handler can fail soft (empty activity + an ``error`` string, never a 500).
"""
from __future__ import annotations

import re
from collections import deque
from typing import Callable, Iterable, Optional

# Alpaca's get_orders caps a page at 500; the client does not page. When a
# window returns exactly that many orders, older fills may be missing and the
# card's FIFO pairing could be wrong — the envelope says so via ``truncated``.
ORDERS_PAGE_LIMIT = 500


def card_prefix(card_id: str) -> str:
    return f"{card_id}-"


def card_order_pattern(card_id: str) -> "re.Pattern[str]":
    """Strict shape of a card-stamped client_order_id:
    ``{card_id}-YYYY-MM-DD[-HH]-(buy|sell)`` from the daemon (daily or hourly
    bucket, see strategy_runner._bar_bucket) and
    ``{card_id}-YYYY-MM-DD-HHMMSS-flatten-SYM`` from the tab's Flatten button.
    A bare prefix match would let ``alpha-v1`` claim ``alpha-v1-extra-...`` ids
    some other tool stamped."""
    return re.compile(
        rf"^{re.escape(card_id)}-\d{{4}}-\d{{2}}-\d{{2}}(?:-\d{{2}}|-\d{{6}})?"
        r"-(buy|sell|flatten)(?:-[A-Z0-9.]{1,10})?$"
    )


def _fill_qty(o: dict) -> float:
    fq = o.get("filled_qty")
    if fq is not None and float(fq) > 0:
        return float(fq)
    q = o.get("qty")
    return float(q) if q is not None else 0.0


def orders_for_card(card_id: str, closed_orders: Iterable[dict]) -> list[dict]:
    """Filled orders that carry this card's client_order_id prefix, oldest first."""
    pat = card_order_pattern(card_id)
    out = [
        {
            "id": o.get("id"),
            "client_order_id": o.get("client_order_id"),
            "symbol": o.get("symbol"),
            "side": (o.get("side") or "").lower(),
            "qty": _fill_qty(o),
            "price": float(o["filled_avg_price"]),
            "filled_at": o.get("filled_at"),
            "status": o.get("status"),
        }
        for o in closed_orders
        if pat.match(o.get("client_order_id") or "")
        and o.get("filled_avg_price") is not None
        and _fill_qty(o) > 0
    ]
    out.sort(key=lambda o: o.get("filled_at") or "")
    return out


def pair_round_trips(card_orders: list[dict]) -> list[dict]:
    """FIFO-pair entries with exits per symbol. Returns closed round-trips with
    dollar P&L; open lots (no exit yet) are excluded — they are positions, not
    trades. Partial fills split lots exactly like tracking_error does."""
    open_lots: dict[str, deque] = {}
    trips: list[dict] = []
    for o in card_orders:
        sym, side, price, qty = o["symbol"], o["side"], float(o["price"]), float(o["qty"])
        if price <= 0 or qty <= 0:
            continue
        lots = open_lots.setdefault(sym, deque())
        if not lots or lots[0][2] == side:
            lots.append([qty, price, side, o.get("filled_at")])
            continue
        remaining = qty
        while remaining > 0 and lots:
            lot = lots[0]
            take = min(lot[0], remaining)
            entry_price, entry_side, entry_at = lot[1], lot[2], lot[3]
            if entry_side == "buy":
                pnl = (price - entry_price) * take
                pct = (price - entry_price) / entry_price * 100.0
            else:
                pnl = (entry_price - price) * take
                pct = (entry_price - price) / entry_price * 100.0
            trips.append({
                "symbol": sym,
                "side": "long" if entry_side == "buy" else "short",
                "qty": round(take, 4),
                "entry_at": entry_at,
                "exit_at": o.get("filled_at"),
                "entry_price": round(entry_price, 4),
                "exit_price": round(price, 4),
                "pnl_usd": round(pnl, 2),
                "return_pct": round(pct, 4),
            })
            lot[0] -= take
            remaining -= take
            if lot[0] <= 0:
                lots.popleft()
        if remaining > 0:
            lots.append([remaining, price, side, o.get("filled_at")])
    return trips


def closing_order_count(card_orders: list[dict]) -> int:
    """Number of distinct orders that closed (or reduced) a lot — the unit the
    Rung-3 evidence ladder counts as one 'closed trade', regardless of how
    many FIFO lots a single exit fill happened to sweep."""
    open_side: dict[str, Optional[str]] = {}
    open_qty: dict[str, float] = {}
    n = 0
    for o in card_orders:
        sym, side, qty = o["symbol"], o["side"], float(o["qty"])
        if qty <= 0:
            continue
        cur = open_side.get(sym)
        if cur is None or open_qty.get(sym, 0.0) <= 0 or cur == side:
            open_side[sym] = side
            open_qty[sym] = open_qty.get(sym, 0.0) + qty
            continue
        n += 1
        left = open_qty[sym] - qty
        if left > 0:
            open_qty[sym] = left
        elif left < 0:
            open_side[sym], open_qty[sym] = side, -left
        else:
            open_side[sym], open_qty[sym] = None, 0.0
    return n


def open_lots(card_orders: list[dict]) -> dict[str, float]:
    """Net signed open quantity per symbol implied by the card's own fills
    (buys positive, sells negative). Compared against the account's real
    positions to flag lots the card thinks it holds but the account does not —
    e.g. a position flattened outside the card's order stamp."""
    net: dict[str, float] = {}
    for o in card_orders:
        sign = 1.0 if o["side"] == "buy" else -1.0
        net[o["symbol"]] = round(net.get(o["symbol"], 0.0) + sign * float(o["qty"]), 4)
    return {s: q for s, q in net.items() if abs(q) > 1e-9}


def flatten_stamp(card_id: str, symbol: str, now) -> str:
    """client_order_id for a tab-initiated flatten: carries the card prefix so
    the exit is attributed to the card (FIFO pairing stays intact), a
    to-the-second bucket so two flattens of one symbol never collide, and the
    symbol so a multi-symbol card can flatten everything in one click."""
    return f"{card_id}-{now.strftime('%Y-%m-%d-%H%M%S')}-flatten-{symbol.upper()}"


def plan_flatten(card_orders: list[dict], positions: Iterable[dict]) -> dict:
    """Decide what closing orders would return this card to flat WITHOUT
    touching another strategy's (or the legacy bot's) share of a symbol.

    Only the card's own net open lots are closed, and only up to what the
    account actually holds on that side. Returns {"orders": [...], "skipped":
    [...]} — each order {symbol, side, qty}; each skip {symbol, reason}."""
    held: dict[str, float] = {}
    for p in positions:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        q = abs(float(p.get("qty") or 0))
        held[sym] = q if (p.get("side") or "long") == "long" else -q
    orders, skipped = [], []
    for sym, lot in sorted(open_lots(card_orders).items()):
        acct = held.get(sym, 0.0)
        if acct == 0:
            skipped.append({"symbol": sym, "reason": "card holds a lot the account no longer has (flattened elsewhere)"})
            continue
        if acct * lot < 0:
            skipped.append({"symbol": sym, "reason": "account position is on the opposite side of the card's lot"})
            continue
        qty = min(abs(lot), abs(acct))
        orders.append({"symbol": sym, "side": "sell" if lot > 0 else "buy", "qty": round(qty, 4)})
    return {"orders": orders, "skipped": skipped}


def daily_pnl(trips: Iterable[dict]) -> dict[str, float]:
    """Realized P&L per exit date (YYYY-MM-DD), the calendar's input."""
    out: dict[str, float] = {}
    for t in trips:
        day = (t.get("exit_at") or "")[:10]
        if not day:
            continue
        out[day] = round(out.get(day, 0.0) + float(t["pnl_usd"]), 2)
    return out


def positions_for_card(card_symbols: Iterable[str], positions: Iterable[dict]) -> list[dict]:
    """Open positions whose symbol the card trades. Attribution by symbol is
    imperfect when two cards share a ticker — the tab says so."""
    wanted = {s.upper() for s in card_symbols if s}
    out = []
    for p in positions:
        sym = (p.get("symbol") or "").upper()
        if sym in wanted:
            out.append({
                "symbol": sym,
                "qty": float(p.get("qty") or 0),
                "side": p.get("side"),
                "avg_entry_price": _f(p.get("avg_entry_price")),
                "current_price": _f(p.get("current_price")),
                "market_value": _f(p.get("market_value")),
                "unrealized_pl": _f(p.get("unrealized_pl")),
            })
    return out


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def build_activity(
    card: dict,
    *,
    card_symbols: Iterable[str],
    list_closed_orders: Callable[[], list[dict]],
    list_positions: Callable[[], list[dict]],
) -> dict:
    """Assemble the activity envelope for one card. Alpaca failures degrade to
    empty sections with the error recorded — a tab must render on a bad day."""
    card_id = card["card_id"]
    errors: list[str] = []
    try:
        closed = list_closed_orders()
    except Exception as e:  # noqa: BLE001
        closed, errors = [], errors + [f"orders: {type(e).__name__}: {e}"]
    try:
        positions = list_positions()
    except Exception as e:  # noqa: BLE001
        positions, errors = [], errors + [f"positions: {type(e).__name__}: {e}"]

    orders = orders_for_card(card_id, closed)
    trips = pair_round_trips(orders)
    by_day = daily_pnl(trips)
    open_pos = positions_for_card(card_symbols, positions)
    realized = round(sum(t["pnl_usd"] for t in trips), 2)
    unrealized = round(sum((p["unrealized_pl"] or 0.0) for p in open_pos), 2)
    wins = sum(1 for t in trips if t["pnl_usd"] > 0)
    truncated = len(closed) >= ORDERS_PAGE_LIMIT
    if truncated:
        errors.append(f"orders: window returned {len(closed)} (page limit) — older fills may be missing")
    # Orphaned lots: the card's fills say it still holds something the account
    # does not (or the sign disagrees). Usually a flatten outside the card stamp.
    held = {p["symbol"]: p["qty"] * (1 if (p.get("side") or "long") == "long" else -1) for p in open_pos}
    orphaned = sorted(
        s for s, q in open_lots(orders).items()
        if s not in held or held[s] * q <= 0 or abs(held[s]) + 1e-9 < abs(q)
    )
    return {
        "card_id": card_id,
        "symbols": sorted({s.upper() for s in card_symbols if s}),
        "orders": orders[-100:],
        "round_trips": trips[-200:],
        "daily_pnl": by_day,
        "open_positions": open_pos,
        "card_lots": open_lots(orders),
        "orphaned_lots": orphaned,
        "truncated": truncated,
        "totals": {
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "closed_trades": len(trips),
            "closed_orders": closing_order_count(orders),
            "wins": wins,
            "win_rate": round(wins / len(trips) * 100.0, 1) if trips else None,
            "first_fill": orders[0]["filled_at"] if orders else None,
            "last_fill": orders[-1]["filled_at"] if orders else None,
        },
        "error": "; ".join(errors) if errors else None,
    }
