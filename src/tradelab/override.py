"""The override policy (S6): how an ADVISORY strategy is allowed onto paper.

Pure functions over plain dicts — the handler, the paper engine and the
board all call these so the policy has exactly one definition:

    applies to   ADVISORY only (CLEAR needs none, BLOCKED refuses one)
    confirm      the strategy's exact name, typed
    reason       written, >= promotion.override_reason_min_chars
    expiry       promotion.override_expiry_days from the grant
    cap          promotion.override_allocation_cap_pct of allocation_usd,
                 enforced in the paper engine's sizing (0 once expired)
    budget       promotion.override_budget active overrides at any time
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional


class OverrideRefused(Exception):
    """A policy refusal; ``code`` names which rule (for the 422 body)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def policy_from_config(cfg) -> dict:
    """Plain-dict view of PromotionConfig (or a dict already)."""
    p = getattr(cfg, "promotion", cfg)
    get = (lambda k, d: getattr(p, k, d)) if not isinstance(p, dict) else (lambda k, d: p.get(k, d))
    return {
        "expiry_days": int(get("override_expiry_days", 30)),
        "cap_pct": float(get("override_allocation_cap_pct", 50.0)),
        "budget": int(get("override_budget", 2)),
        "reason_min_chars": int(get("override_reason_min_chars", 20)),
    }


def is_active(card: Optional[dict], now: datetime) -> bool:
    """True while the card's override exists and has not expired."""
    ov = (card or {}).get("override") or {}
    exp = _parse(ov.get("expires_at"))
    return bool(exp and exp > now)


def is_expired(card: Optional[dict], now: datetime) -> bool:
    ov = (card or {}).get("override") or {}
    exp = _parse(ov.get("expires_at"))
    return bool(exp and exp <= now)


def active_overrides(cards: Iterable[dict], now: datetime, *, exclude_card_id: Optional[str] = None) -> list[dict]:
    return [c for c in cards if is_active(c, now) and c.get("card_id") != exclude_card_id]


def validate_request(*, strategy: str, confirm: Optional[str], reason: Optional[str],
                     route: Optional[str], policy: dict, active_count: int) -> None:
    """Raise OverrideRefused for the first rule the request breaks."""
    if route == "BLOCKED":
        raise OverrideRefused("blocked", "BLOCKED routes cannot be overridden by any path (hard disqualifier)")
    if route == "CLEAR":
        raise OverrideRefused("not_needed", "a CLEAR route needs no override — accept it normally")
    if route != "ADVISORY":
        raise OverrideRefused("no_route", "no promotion route on record for this run")
    if (confirm or "").strip() != strategy:
        raise OverrideRefused("confirm", f"type the strategy's exact name to confirm: {strategy}")
    r = (reason or "").strip()
    if len(r) < policy["reason_min_chars"]:
        raise OverrideRefused("reason", f"a written reason of at least {policy['reason_min_chars']} characters is required")
    if active_count >= policy["budget"]:
        raise OverrideRefused("budget", f"override budget spent: {active_count} of {policy['budget']} active — "
                                        "wait for one to expire, qualify, or retire")


def build_record(*, reason: str, now: datetime, policy: dict, scoring_run_id: Optional[str],
                 thresholds_hash: Optional[str]) -> dict:
    return {
        "reason": reason.strip(),
        "granted_at": _iso(now),
        "expires_at": _iso(now + timedelta(days=policy["expiry_days"])),
        "allocation_cap_pct": policy["cap_pct"],
        "scoring_run_id": scoring_run_id,
        "thresholds_hash": thresholds_hash,
    }


def effective_allocation(card: dict, now: datetime) -> Optional[float]:
    """What the paper engine may size from. No override → the allocation as
    is. Active override → allocation × cap. Expired override → 0: nothing
    trades even if the tick that disables the card has not run yet."""
    alloc = card.get("allocation_usd")
    ov = card.get("override")
    if not ov:
        return alloc
    if is_active(card, now):
        try:
            # Clamped: a hand-edited receipt cannot size above the allocation;
            # a receipt with no cap at all sizes at 0 (fail closed).
            cap = min(100.0, max(0.0, float(ov.get("allocation_cap_pct", 0.0))))
            return float(alloc) * cap / 100.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


class LedgerUnavailable(Exception):
    """The audit ledger could not record an override grant/renewal. Grants
    are fail-CLOSED on this: a receipt with no audit row is not a receipt."""


def days_left(card: dict, now: datetime) -> Optional[int]:
    exp = _parse((card.get("override") or {}).get("expires_at"))
    if not exp:
        return None
    return max(0, (exp - now).days)


def receipt(card: dict, now: datetime) -> Optional[dict]:
    """Board/tab view of a card's override, or None."""
    ov = card.get("override")
    if not ov:
        return None
    return {
        **{k: ov.get(k) for k in ("reason", "granted_at", "expires_at", "allocation_cap_pct", "scoring_run_id")},
        "active": is_active(card, now),
        "expired": is_expired(card, now),
        "days_left": days_left(card, now),
        "expired_at": card.get("override_expired_at"),
    }
