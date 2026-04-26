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

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tradelab.live.alpaca_client import submit_market_order
from tradelab.live.cards import CardRegistry
from tradelab.live.guardrails import (
    CardRuntimeState,
    get_rth_window_start,
)
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

    client_order_id = f"{alert.card_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    try:
        result = await asyncio.to_thread(
            submit_market_order, alert_symbol, alert.action, qty, client_order_id
        )
        _log_alert(payload_dict, alert.card_id, "order_submitted", result)
        return {"ok": True, "order": result}
    except Exception as e:
        _log_alert(payload_dict, alert.card_id, "order_failed", {"error": str(e)})
        return JSONResponse({"error": f"order placement failed: {e}"}, status_code=500)
