"""The go-live gate (S9): how an Accepted card is allowed onto the LIVE account.

Pure functions over plain dicts, so the handler, the board and the tests share
one definition. Nothing here touches Alpaca; the handler supplies facts.

    who        a current Full trial routing CLEAR, or ADVISORY with an ACTIVE
               override (the cap applies on live exactly as on paper)
    arming     live keys in the environment + the strategy's exact name and
               the word LIVE, typed
    numbers    tradelab.yaml `live:` — max_total_allocation_usd (sum over live
               cards), daily_loss_limit_usd (engine, entries only),
               require_flat_paper (no open paper lots when going live)
    receipt    card["live"] = {granted_at, scoring_run_id, thresholds_hash,
               route, allocation_usd, confirm}; written ONLY by the go-live
               route, never by PATCH. The engine refuses a live card without it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from tradelab import override as _override


class GoLiveRefused(Exception):
    """A gate refusal; ``code`` names which check (for the 422 body)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def policy_from_config(cfg) -> dict:
    """Plain-dict view of LiveConfig (or a dict already)."""
    p = getattr(cfg, "live", cfg)
    get = (lambda k, d: getattr(p, k, d)) if not isinstance(p, dict) else (lambda k, d: p.get(k, d))
    return {
        "max_total_allocation_usd": float(get("max_total_allocation_usd", 25000.0)),
        "daily_loss_limit_usd": float(get("daily_loss_limit_usd", 1000.0)),
        "require_flat_paper": bool(get("require_flat_paper", True)),
    }


def expected_confirm(strategy: str) -> str:
    return f"{strategy} LIVE"


def is_live(card: Optional[dict]) -> bool:
    return bool(card) and str((card or {}).get("mode") or "").lower() == "live"


def live_allocation_total(cards: Iterable[dict], *, exclude_card_id: Optional[str] = None) -> float:
    """Sum of allocation_usd over live cards (Off or On — an armed card's
    allocation is committed budget whether or not it is trading right now)."""
    total = 0.0
    for c in cards:
        if not is_live(c) or c.get("card_id") == exclude_card_id:
            continue
        try:
            total += max(0.0, float(c.get("allocation_usd") or 0.0))
        except (TypeError, ValueError):
            continue
    return total


def check_budget(*, allocation_usd, policy: dict, others_total: float) -> float:
    """Validated allocation, or GoLiveRefused('allocation' | 'budget')."""
    try:
        alloc = float(allocation_usd)
    except (TypeError, ValueError):
        raise GoLiveRefused("allocation", "a live allocation in dollars is required")
    if not alloc > 0:
        raise GoLiveRefused("allocation", "the live allocation must be greater than 0")
    cap = policy["max_total_allocation_usd"]
    if others_total + alloc > cap + 1e-9:
        raise GoLiveRefused("budget", f"live budget exceeded: {others_total:,.0f} already committed to live cards + "
                                      f"{alloc:,.0f} > max_total_allocation_usd {cap:,.0f}")
    return alloc


def validate_request(*, strategy: str, confirm: Optional[str], route: Optional[str], card: dict,
                     live_ready: bool, full_trial: dict, canary_mismatch: bool, symbols: list,
                     open_paper_lots: int, policy: dict, now: datetime) -> None:
    """Raise GoLiveRefused for the first check the request fails. Order is the
    order the modal lists them, so the first refusal is the one to fix first."""
    if (confirm or "").strip() != expected_confirm(strategy):
        raise GoLiveRefused("confirm", f"type exactly: {expected_confirm(strategy)}")
    if not live_ready:
        raise GoLiveRefused("not_configured", "live keys are not configured — set ALPACA_LIVE_API_KEY and "
                                              "ALPACA_LIVE_SECRET_KEY in tradelab/.env and restart the dashboard")
    if not (full_trial or {}).get("ok"):
        raise GoLiveRefused((full_trial or {}).get("code") or "no_run",
                            f"needs a current Full trial: {(full_trial or {}).get('reason') or 'none on record'}")
    if canary_mismatch:
        raise GoLiveRefused("canary", "engine integrity canaries do not match — fix the engine before going live")
    if route == "BLOCKED":
        raise GoLiveRefused("blocked", "BLOCKED route (hard disqualifier) — this strategy cannot go live by any path")
    if route == "ADVISORY":
        if not card.get("override"):
            raise GoLiveRefused("override_required", "ADVISORY route — going live needs an active override "
                                                     "(typed name + written reason)")
        if not _override.is_active(card, now):
            raise GoLiveRefused("override_expired", "this card's override has expired — renew it before going live")
    elif route != "CLEAR":
        raise GoLiveRefused("no_route", "no promotion route on record for this card's scoring run")
    if not symbols:
        raise GoLiveRefused("no_tickers", "the strategy declares no tickers — add `symbols = [...]` to the class")
    if policy.get("require_flat_paper", True) and open_paper_lots > 0:
        raise GoLiveRefused("flatten_paper_first", f"{open_paper_lots} open paper lot(s) on this card — flatten "
                                                   "them first so paper and live never overlap")


def build_receipt(*, now: datetime, scoring_run_id: Optional[str], thresholds_hash: Optional[str],
                  route: Optional[str], allocation_usd: float, confirm: str, ledger_row_id=None) -> dict:
    return {
        "granted_at": _iso(now),
        "scoring_run_id": scoring_run_id,
        "thresholds_hash": thresholds_hash,
        "route": route,
        "allocation_usd": float(allocation_usd),
        "confirm": confirm,
        "ledger_row_id": ledger_row_id,
    }


RECEIPT_ACTIONS = ("go_live", "live_allocation", "live_rearm")


def receipt_matches_ledger(card: Optional[dict], row: Optional[dict]) -> bool:
    """A live receipt is real only if the ledger row it names says the same
    thing: an ARMING action for THIS card, this strategy, this scoring run,
    this allocation — and ``row`` must be the card's LATEST live-action row
    (the caller fetches it by card_id), so a leave_live newer than the receipt
    fails it and a copied receipt from live_history cannot re-arm. A
    hand-edited cards.json cannot produce one (the ledger is append-only and
    written BEFORE the card). Anything unreadable → False (fail closed)."""
    if not card or not isinstance(card.get("live"), dict) or not isinstance(row, dict):
        return False
    lv = card["live"]
    try:
        if row.get("action") not in RECEIPT_ACTIONS:
            return False
        if str(row.get("card_id") or "") != str(card.get("card_id") or ""):
            return False
        if str(row.get("strategy_name") or "") != str(card.get("strategy") or card.get("base_name") or ""):
            return False
        if (row.get("scoring_run_id") or None) != (lv.get("scoring_run_id") or None):
            return False
        if abs(float(row.get("live_allocation_usd")) - float(lv.get("allocation_usd"))) > 1e-6:
            return False
        if int(row.get("id")) != int(lv.get("ledger_row_id")):
            return False
    except (TypeError, ValueError):
        return False
    return True


def checks_view(*, strategy: str, route: Optional[str], card: dict, live_ready: bool, full_trial: dict,
                canary_mismatch: bool, symbols: list, open_paper_lots: int, policy: dict,
                others_total: float, now: datetime) -> dict:
    """Everything the go-live modal shows: each check with ok + reason, the
    budget used, and the expected confirmation string. Read-only."""
    adv_ok = route == "CLEAR" or (route == "ADVISORY" and bool(card.get("override")) and _override.is_active(card, now))
    if route == "BLOCKED":
        route_reason = "BLOCKED — cannot go live"
    elif route == "ADVISORY":
        route_reason = ("ADVISORY with an active override — allowed at the override cap" if adv_ok
                        else ("ADVISORY — override expired; renew first" if card.get("override") else "ADVISORY — needs an active override"))
    elif route == "CLEAR":
        route_reason = "CLEAR"
    else:
        route_reason = "no route on record"
    checks = [
        {"key": "keys", "label": "Live keys configured", "ok": bool(live_ready),
         "reason": "" if live_ready else "ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY missing in tradelab/.env"},
        {"key": "full_trial", "label": "Current Full trial", "ok": bool((full_trial or {}).get("ok")),
         "reason": "" if (full_trial or {}).get("ok") else ((full_trial or {}).get("reason") or "none on record")},
        {"key": "canary", "label": "Canaries match", "ok": not canary_mismatch,
         "reason": "" if not canary_mismatch else "engine integrity mismatch"},
        {"key": "route", "label": "Route allows live", "ok": bool(adv_ok), "reason": route_reason},
        {"key": "tickers", "label": "Tickers declared", "ok": bool(symbols),
         "reason": ", ".join(symbols) if symbols else "none — add `symbols = [...]` to the strategy class"},
        {"key": "flat_paper", "label": "No open paper lots",
         "ok": (open_paper_lots == 0) or not policy.get("require_flat_paper", True),
         "reason": "" if open_paper_lots == 0 else f"{open_paper_lots} open lot(s) — flatten first"},
    ]
    return {
        "strategy": strategy,
        "expected_confirm": expected_confirm(strategy),
        "checks": checks,
        "all_ok": all(c["ok"] for c in checks),
        "budget": {"committed": others_total, "max": policy["max_total_allocation_usd"],
                   "available": max(0.0, policy["max_total_allocation_usd"] - others_total)},
        "daily_loss_limit_usd": policy["daily_loss_limit_usd"],
        "override_cap_pct": (card.get("override") or {}).get("allocation_cap_pct") if route == "ADVISORY" else None,
    }
