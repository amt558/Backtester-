"""Panic panel core logic — Slice 6.

L1: Disable all cards.
L2: L1 + cancel open tradelab orders (optionally all open orders).
L3: L2 + flatten all positions (whole-account).

Each Alpaca call is wrapped in try/except so partial failures don't abort
the panic. Failures are recorded as PanicAction(ok=False) entries and
included in the audit log + notification.

Per spec §10: lives in dashboard launcher process. Receiver picks up L1
via existing watchdog reload of cards.json. L2/L3 hit Alpaca directly.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PANIC_LOG_PATH = Path(__file__).resolve().parents[3] / "live" / "panic_events.jsonl"


# ─── Dataclasses ─────────────────────────────────────────────────────────

@dataclass
class CancelAction:
    ok: bool
    error: Optional[str]
    order_id: Optional[str]
    client_order_id: Optional[str]
    card_id: Optional[str]  # None if non-tradelab order


@dataclass
class FlattenAction:
    ok: bool
    error: Optional[str]
    symbol: str
    qty: str  # alpaca returns string; preserve precision
    side: str  # "buy" or "sell" — opposite of held position
    order_id: Optional[str]


@dataclass
class PanicResult:
    ts: str
    level: str  # "L1" | "L2" | "L3"
    before_state_snapshot: list[dict]
    cards_disabled: list[str]
    orders_cancelled: list[CancelAction]
    positions_flattened: list[FlattenAction]


# ─── Notification body helpers ───────────────────────────────────────────

_TRUNC_AT = 10


def _truncate_for_notification(ids: list[str]) -> str:
    """Render a list of IDs as a comma-separated string, truncated after 10
    items with a '… +N more' suffix. Returns '(none)' for empty."""
    if not ids:
        return "(none)"
    if len(ids) <= _TRUNC_AT:
        return ", ".join(ids)
    head = ", ".join(ids[:_TRUNC_AT])
    return f"{head}… +{len(ids) - _TRUNC_AT} more"


def _build_notification_body(result: PanicResult) -> str:
    """Build the multi-line CRITICAL notification body. Same string to all
    five channels (truncation per channel happens client-side).
    """
    ts_local = result.ts  # already includes TZ
    cancelled_ids = [a.client_order_id or "?" for a in result.orders_cancelled if a.ok]
    flattened_strs = [
        f"{a.symbol}({a.qty} {a.side})"
        for a in result.positions_flattened if a.ok
    ]
    cancel_failures = sum(1 for a in result.orders_cancelled if not a.ok)
    flatten_failures = sum(1 for a in result.positions_flattened if not a.ok)
    total_failures = cancel_failures + flatten_failures

    lines = [
        f"{result.level} panic at {ts_local}",
        "",
        f"Cards disabled ({len(result.cards_disabled)}): {_truncate_for_notification(result.cards_disabled)}",
        f"Orders cancelled ({sum(1 for a in result.orders_cancelled if a.ok)}): {_truncate_for_notification(cancelled_ids)}",
        f"Positions flattened: {_truncate_for_notification(flattened_strs)}",
    ]
    if total_failures > 0:
        lines.append(f"Errors: {total_failures} failed action(s) (see audit log).")
    return "\n".join(lines)


# ─── Module-level injectable hooks (test seam) ───────────────────────────

def _default_notify(severity, title, body, **kwargs):
    from tradelab.live import notify as _n
    return _n.notify(severity, title, body, **kwargs)

_notify_fn = _default_notify  # tests monkey-patch this


def _load_registry():
    """Load the live CardRegistry. Tests monkey-patch this."""
    from tradelab.live.cards import CardRegistry
    path = Path(__file__).resolve().parents[3] / "live" / "cards.json"
    return CardRegistry(path)


# ─── Audit log ───────────────────────────────────────────────────────────

def _append_audit(result: PanicResult) -> None:
    """Append one JSON line to panic_events.jsonl. Best-effort — failure to
    write the audit log MUST NOT crash the panic (the panic itself succeeded).
    """
    try:
        PANIC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_serialize_result(result))
        with open(PANIC_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[panic] audit append failed: {type(e).__name__}: {e}", file=sys.stderr)


def _serialize_result(result: PanicResult) -> dict:
    d = asdict(result)
    return d


# ─── execute_panic dispatch ──────────────────────────────────────────────

_VALID_LEVELS = {"L1", "L2", "L3"}


def execute_panic(level: str, also_cancel_nontradelab: bool = False) -> PanicResult:
    """Execute panic at the given level.

    Always succeeds — partial failures (failed Alpaca calls) are recorded
    inside PanicResult as PanicAction(ok=False, error=...) entries. Raises
    ValueError only on programmer error (bad level).
    """
    if level not in _VALID_LEVELS:
        raise ValueError(f"invalid panic level: {level!r}; expected one of {sorted(_VALID_LEVELS)}")

    ts = datetime.now(ET).isoformat()

    # Step 1: snapshot current state
    registry = _load_registry()
    cards_now = registry.all_hydrated()
    snapshot = [
        {
            "card_id": c.get("card_id", cid),
            "base_name": c.get("base_name"),
            "status": c.get("status"),
            "qty": c.get("qty") or c.get("quantity"),
            "last_fired_at": c.get("last_fired_at"),
        }
        for cid, c in cards_now.items()
    ]

    # Step 2: L1 — disable all enabled cards
    cards_disabled: list[str] = []
    for cid, card in cards_now.items():
        if card.get("status") == "enabled":
            try:
                registry.set_status(cid, "disabled")
                cards_disabled.append(cid)
            except Exception as e:
                # Per-card disable failure: still record what we attempted
                print(f"[panic] failed to disable {cid}: {type(e).__name__}: {e}", file=sys.stderr)

    orders_cancelled: list[CancelAction] = []
    positions_flattened: list[FlattenAction] = []

    # Step 3: L2 — cancel open orders (L2/L3 only)
    if level in ("L2", "L3"):
        orders_cancelled = _cancel_orders_step(
            card_ids=set(cards_now.keys()),
            also_cancel_nontradelab=also_cancel_nontradelab,
        )

    # Step 4: L3 — flatten all positions (L3 only)
    if level == "L3":
        positions_flattened = _flatten_positions_step()

    result = PanicResult(
        ts=ts,
        level=level,
        before_state_snapshot=snapshot,
        cards_disabled=cards_disabled,
        orders_cancelled=orders_cancelled,
        positions_flattened=positions_flattened,
    )

    _append_audit(result)

    title = f"🚨 {level} panic — {len(cards_disabled)} cards disabled"
    body = _build_notification_body(result)
    from tradelab.live.notify import Severity
    _notify_fn(Severity.CRITICAL, title, body)

    return result


def _classify_order_card(client_order_id: Optional[str], card_ids: set) -> Optional[str]:
    """Return the card_id this order belongs to, or None if not tradelab.
    Spec rule: client_order_id.startswith(f"{cid}-") for some cid."""
    if not client_order_id:
        return None
    for cid in card_ids:
        if client_order_id.startswith(f"{cid}-"):
            return cid
    return None


def _cancel_orders_step(
    *, card_ids: set, also_cancel_nontradelab: bool
) -> list[CancelAction]:
    """L2 step. Returns one CancelAction per order processed (whether cancel
    succeeded or failed). On list_open_orders failure, returns a single synthetic
    CancelAction with ok=False so the audit log shows the issue."""
    from tradelab.live import alpaca_client

    try:
        orders = alpaca_client.list_open_orders()
    except Exception as e:
        return [CancelAction(
            ok=False,
            error=f"list_open_orders failed: {type(e).__name__}: {e}",
            order_id=None, client_order_id=None, card_id=None,
        )]

    actions: list[CancelAction] = []
    for o in orders:
        coid = o.get("client_order_id")
        card_id = _classify_order_card(coid, card_ids)
        if card_id is None and not also_cancel_nontradelab:
            continue  # skip non-tradelab orders unless flag is set
        order_id = o.get("id")
        try:
            alpaca_client.cancel_order_by_id(order_id)
            actions.append(CancelAction(
                ok=True, error=None,
                order_id=order_id, client_order_id=coid, card_id=card_id,
            ))
        except Exception as e:
            actions.append(CancelAction(
                ok=False, error=f"{type(e).__name__}: {e}",
                order_id=order_id, client_order_id=coid, card_id=card_id,
            ))
    return actions


def _flatten_positions_step() -> list[FlattenAction]:
    """L3 step. For each open position, submit a market order on the opposite
    side to close. Returns one FlattenAction per position attempted. On
    list_positions failure, returns a single synthetic FlattenAction.
    Whole-account — affects positions tradelab did not open."""
    from tradelab.live import alpaca_client

    try:
        positions = alpaca_client.list_positions()
    except Exception as e:
        return [FlattenAction(
            ok=False,
            error=f"list_positions failed: {type(e).__name__}: {e}",
            symbol="", qty="0", side="", order_id=None,
        )]

    actions: list[FlattenAction] = []
    for p in positions:
        symbol = p.get("symbol", "?")
        qty = p.get("qty", "0")
        held_side = (p.get("side") or "long").lower()
        # Convert held side to closing side
        close_side = "sell" if held_side in ("long", "buy") else "buy"
        try:
            order = alpaca_client.submit_market_order(
                symbol=symbol, side=close_side, quantity=float(qty),
            )
            actions.append(FlattenAction(
                ok=True, error=None,
                symbol=symbol, qty=qty, side=close_side,
                order_id=str(order.get("id")) if order else None,
            ))
        except Exception as e:
            actions.append(FlattenAction(
                ok=False, error=f"{type(e).__name__}: {e}",
                symbol=symbol, qty=qty, side=close_side, order_id=None,
            ))
    return actions
