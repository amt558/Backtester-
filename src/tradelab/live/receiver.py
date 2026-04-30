"""FastAPI webhook receiver — Session 1 prototype.

Pipeline: TV alert JSON → validate → card lookup → secret check → Alpaca order.
Every alert (accepted or rejected) appends one JSON line to alerts.jsonl.

Run:
    python -m uvicorn tradelab.live.receiver:app --host 127.0.0.1 --port 8878
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from alpaca.common.exceptions import APIError

from tradelab.live.alpaca_client import get_client, submit_market_order
from tradelab.live.alpaca_state import AlpacaState
from tradelab.live.cards import CardRegistry
from tradelab.live.guardrails import (
    CardRuntimeState,
    evaluate_guardrails,
    get_rth_window_start,
)
from tradelab.live import notify as _notify
from tradelab.live.notify import Severity
from tradelab.live.schema import AlertPayload

LIVE_DATA_DIR = Path("C:/TradingScripts/tradelab/live")
LIVE_DATA_DIR.mkdir(parents=True, exist_ok=True)

CARDS_PATH = LIVE_DATA_DIR / "cards.json"
ALERT_LOG = LIVE_DATA_DIR / "alerts.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("tradelab.live.receiver")

class _CardsReloadHandler(FileSystemEventHandler):
    """Watchdog handler that calls registry.reload() on cards.json change.

    Uses an mtime gate to dedupe events. Atomic os.replace can fire two
    events on Windows (RENAMED_NEW_NAME + synthesized MODIFIED) — both
    carry the same post-write mtime, so the gate skips the second.

    No time-based debounce: a 100ms cooldown silently swallowed any
    burst writes that landed within the window, leaving the receiver's
    in-memory registry stale relative to disk. mtime advances on every
    real write, so the gate alone does the right thing.
    """
    def __init__(self, registry: CardRegistry, watched_path: Path):
        self._registry = registry
        self._watched_name = watched_path.name
        self._watched_path = watched_path.resolve()
        self._lock = Lock()
        self._last_mtime: float = 0.0

    def _maybe_reload(self) -> None:
        with self._lock:
            try:
                mtime = self._watched_path.stat().st_mtime
            except FileNotFoundError:
                return
            if mtime <= self._last_mtime:
                return
            self._last_mtime = mtime
        try:
            self._registry.reload()
            logger.info("cards.json reloaded; cards_loaded=%d",
                        self._registry.count())
        except Exception as e:
            logger.error("cards.json reload failed: %s", e)

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == self._watched_name:
            self._maybe_reload()

    def on_created(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).name == self._watched_name:
            self._maybe_reload()

    def on_moved(self, event):
        # Atomic os.replace generates a move event on Windows native
        # Observer with cards.json as dest_path. Without this, every
        # PATCH/DELETE mutation through the dashboard would persist to
        # disk but the receiver would keep stale state.
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", "") or ""
        if Path(dest).name == self._watched_name:
            self._maybe_reload()


def _start_cards_watcher(registry: CardRegistry, *, polling: bool = False):
    """Start a watchdog observer on the parent dir of registry.path.

    Returns the started observer; caller is responsible for stopping it.
    polling=True forces watchdog.PollingObserver (deterministic for tests
    on Windows where the native ReadDirectoryChangesW can be flaky in
    short-lived processes).
    """
    handler = _CardsReloadHandler(registry, registry.path)
    observer_cls = PollingObserver if polling else Observer
    observer = observer_cls()
    # Watch the parent directory; filter by filename in the handler
    watch_dir = str(registry.path.parent.resolve())
    Path(watch_dir).mkdir(parents=True, exist_ok=True)
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    return observer


cards = CardRegistry(CARDS_PATH)

_card_state: dict[str, CardRuntimeState] = {}


def record_attempt(states: dict[str, CardRuntimeState], card_id: str, now: datetime) -> None:
    state = states.setdefault(card_id, CardRuntimeState())
    state.last_attempted_at = now


def record_fire(states: dict[str, CardRuntimeState], card_id: str, now: datetime) -> None:
    state = states.setdefault(card_id, CardRuntimeState())
    current_window = get_rth_window_start(now)
    if state.fire_window_start is None or state.fire_window_start < current_window:
        state.fires_today = 1
        state.fire_window_start = current_window
    else:
        state.fires_today += 1
    state.last_fired_at = now


def hydrate_card_state_from_alerts_log(
    log_path: Path, now: datetime, max_lines: int = 500,
) -> dict[str, CardRuntimeState]:
    """Replay the last `max_lines` of alerts.jsonl to rebuild fire state.

    Only `order_submitted` records contribute. fires_today counts only
    submissions whose ts falls within the current RTH window.
    """
    states: dict[str, CardRuntimeState] = {}
    if not log_path.exists():
        return states
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()[-max_lines:]
    except OSError:
        return states
    current_window = get_rth_window_start(now)
    for line in lines:
        try:
            rec_obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec_obj.get("status") != "order_submitted":
            continue
        cid = rec_obj.get("card_id")
        ts_str = rec_obj.get("ts")
        if not cid or not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        state = states.setdefault(cid, CardRuntimeState())
        # Always update last_fired_at to the most recent fire we see
        if state.last_fired_at is None or ts > state.last_fired_at:
            state.last_fired_at = ts
        if ts >= current_window:
            if state.fire_window_start is None or state.fire_window_start < current_window:
                state.fires_today = 1
                state.fire_window_start = current_window
            else:
                state.fires_today += 1
    return states


_alpaca_state: Optional["AlpacaState"] = None
_data_client: Optional["StockHistoricalDataClient"] = None


def _ensure_alpaca_state() -> AlpacaState:
    global _alpaca_state
    if _alpaca_state is None:
        _alpaca_state = AlpacaState(client=get_client(), ttl_seconds=2.0)
    return _alpaca_state


def _ensure_data_client():
    """Lazy singleton for the market-data client (last-price lookups).

    Reads alpaca_config.json once on first webhook; subsequent calls
    return the cached client. Mirrors the trading-client memoization
    in alpaca_client.get_client().
    """
    global _data_client
    if _data_client is not None:
        return _data_client
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from tradelab.live.alpaca_client import CONFIG_PATH
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    _data_client = StockHistoricalDataClient(
        cfg["alpaca"]["api_key"], cfg["alpaca"]["secret_key"],
    )
    return _data_client


def _fetch_last_price(symbol: str) -> float:
    """Best-effort last-trade price for buying-power check.

    Returns 0.0 on any failure (paper accounts without market data, network
    errors, missing subscriptions). 0.0 makes the buying-power candidate
    notional 0, which always passes (the check is intentionally lenient on
    data unavailability — a flat-out cap miss is more user-hostile than
    a missed check).
    """
    try:
        from alpaca.data.requests import StockLatestTradeRequest
        client = _ensure_data_client()
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        trade = client.get_stock_latest_trade(req)[symbol]
        return float(trade.price)
    except Exception as e:
        logger.warning("last-price fetch failed for %s: %s", symbol, e)
        return 0.0


app = FastAPI(title="tradelab live webhook receiver", version="0.1.0")


@app.on_event("startup")
def _on_startup() -> None:
    global _cards_observer, _card_state
    _cards_observer = _start_cards_watcher(cards, polling=False)
    logger.info("cards.json watcher started on %s", cards.path)
    _card_state = hydrate_card_state_from_alerts_log(
        ALERT_LOG, datetime.now(timezone.utc),
    )
    logger.info("hydrated runtime state for %d cards", len(_card_state))


@app.on_event("shutdown")
def _on_shutdown() -> None:
    global _cards_observer
    if _cards_observer is not None:
        _cards_observer.stop()
        _cards_observer.join(timeout=3.0)
        _cards_observer = None


_cards_observer = None


def _log_alert(payload: dict | str, card_id: str, status: str, details: dict | None = None) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "card_id": card_id,
        "status": status,
        "payload": payload,
        "details": details or {},
    }
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error("failed to write alert log: %s", e)
    logger.info("alert %s card=%s %s", status, card_id, details or "")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "cards_loaded": cards.count()}


@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    try:
        payload_dict = json.loads(raw)
    except Exception as e:
        _log_alert(raw.decode("utf-8", errors="replace")[:500], "?", "invalid_json", {"error": str(e)})
        return JSONResponse({"error": f"invalid json: {e}"}, status_code=400)

    try:
        alert = AlertPayload(**payload_dict)
    except ValidationError as e:
        card_id = str(payload_dict.get("card_id", "?"))
        _log_alert(payload_dict, card_id, "validation_error", {"errors": e.errors()})
        return JSONResponse({"error": "validation failed", "details": e.errors()}, status_code=422)

    card = cards.get(alert.card_id)
    if card is None:
        _log_alert(payload_dict, alert.card_id, "unknown_card")
        return JSONResponse({"error": "unknown card_id"}, status_code=404)

    if not hmac.compare_digest(str(card.get("secret", "")), alert.secret):
        _log_alert(payload_dict, alert.card_id, "bad_secret")
        return JSONResponse({"error": "bad secret"}, status_code=403)

    if card.get("status") != "enabled":
        _log_alert(payload_dict, alert.card_id, "card_disabled")
        return JSONResponse({"error": "card disabled"}, status_code=403)

    card_symbol = str(card.get("symbol", "")).upper()
    alert_symbol = alert.symbol.upper()
    if card_symbol != alert_symbol:
        _log_alert(
            payload_dict,
            alert.card_id,
            "symbol_mismatch",
            {"card_symbol": card_symbol, "alert_symbol": alert_symbol},
        )
        return JSONResponse(
            {"error": f"symbol mismatch: card={card_symbol} alert={alert_symbol}"},
            status_code=422,
        )

    if card.get("quantity") is not None:
        qty = float(card["quantity"])
    else:
        qty = float(alert.contracts or 0)

    if qty <= 0:
        _log_alert(payload_dict, alert.card_id, "bad_quantity", {"qty": qty})
        return JSONResponse({"error": f"bad quantity: {qty}"}, status_code=422)

    # ── Guardrail pipeline ───────────────────────────────────────────
    # Order matters: evaluate FIRST (reading the prior last_attempted_at),
    # THEN record this attempt. Recording first would self-block every
    # card's first webhook on cooldown (elapsed = 0 < cooldown_seconds).
    now = datetime.now(timezone.utc)
    last_price = _fetch_last_price(alert_symbol)
    alpaca_state = _ensure_alpaca_state()
    hydrated_card = {**card, "card_id": alert.card_id}
    # FAIL-CLOSED: any exception bubbling out of evaluate_guardrails (which
    # internally calls alpaca_state.positions() / .account() / .open_orders())
    # means we cannot trust our view of the account. Block the trade rather
    # than risk submitting against a stale or unknown state.
    try:
        block = evaluate_guardrails(
            card=hydrated_card,
            action=alert.action,
            qty=qty,
            last_price=last_price,
            registry=cards.all_hydrated(),
            states=_card_state,
            alpaca_state=alpaca_state,
            now=now,
        )
    except APIError as e:
        record_attempt(_card_state, alert.card_id, now)
        _log_alert(
            payload_dict, alert.card_id, "guardrail_blocked",
            {"reason": "alpaca_unreachable", "message": str(e)},
        )
        _notify.notify(
            Severity.CRITICAL,
            "Alpaca state fetch failed",
            f"{alert.card_id} {alert.action} {alert_symbol}: alpaca_unreachable — {e}",
        )
        return JSONResponse(
            {"error": f"alpaca_unreachable: {e}"},
            status_code=503,
        )
    except Exception as e:
        # NOTE: this MUST come after `except APIError` — APIError is a subclass
        # of Exception, so swapping the handler order would silently absorb
        # APIError into this branch and neutralize the specific-error path.
        # Broader catch: SDK transport quirks, JSON decode errors mid-stream, etc.
        # Same fail-closed pattern.
        record_attempt(_card_state, alert.card_id, now)
        _log_alert(
            payload_dict, alert.card_id, "guardrail_blocked",
            {"reason": "alpaca_unreachable", "message": f"{type(e).__name__}: {e}"},
        )
        _notify.notify(
            Severity.CRITICAL,
            "Alpaca state fetch raised unexpected error",
            f"{alert.card_id} {alert.action} {alert_symbol}: {type(e).__name__}: {e}",
        )
        return JSONResponse(
            {"error": f"alpaca_unreachable: {type(e).__name__}: {e}"},
            status_code=503,
        )
    # Record the attempt regardless of outcome (debounces a flood of
    # blocked webhooks — each one pushes the cooldown forward).
    record_attempt(_card_state, alert.card_id, now)

    if block is not None:
        _log_alert(
            payload_dict, alert.card_id, "guardrail_blocked",
            {"reason": block.code, "message": block.message, **block.details},
        )
        _notify.notify(
            Severity.CRITICAL,
            "Guardrail blocked",
            f"{alert.card_id} {alert.action} {alert_symbol}: {block.code} — {block.message}",
        )
        return JSONResponse(
            {"error": f"{block.code}: {block.message}"},
            status_code=403,
        )

    client_order_id = f"{alert.card_id}-{int(now.timestamp() * 1000)}"
    try:
        result = await asyncio.to_thread(
            submit_market_order, alert_symbol, alert.action, qty, client_order_id
        )
        record_fire(_card_state, alert.card_id, now)
        alpaca_state.invalidate()
        try:
            cards.update(alert.card_id, {"last_fired_at": now.isoformat()})
        except Exception as e:
            logger.warning("failed to persist last_fired_at: %s", e)
        _log_alert(payload_dict, alert.card_id, "order_submitted", result)
        return {"ok": True, "order": result}
    except Exception as e:
        _log_alert(payload_dict, alert.card_id, "order_failed", {"error": str(e)})
        _notify.notify(
            Severity.CRITICAL,
            "Alpaca order failed",
            f"{alert.card_id} {alert.action} {alert_symbol} qty={card['quantity']}: {type(e).__name__}: {e}",
        )
        return JSONResponse({"error": f"order placement failed: {e}"}, status_code=502)
