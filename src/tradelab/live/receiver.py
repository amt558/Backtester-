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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tradelab.live.alpaca_client import submit_market_order
from tradelab.live.cards import CardRegistry
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

cards = CardRegistry(CARDS_PATH)
app = FastAPI(title="tradelab live webhook receiver", version="0.1.0")


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
