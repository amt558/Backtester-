"""Daily email digest — render + tick + start/stop daemon thread.

Runs in the dashboard launcher process. Mirrors silence_checker shape.
Renders an end-of-day HTML email summarizing today's anomalies and
current system snapshot, sends via notify_channels.email.send() (NOT
through notify() — see spec §3.3 for why), with idempotent state in
digest_state.json to prevent same-day re-fires.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    import pytz
    _ET = pytz.timezone("America/New_York")

from tradelab.live import _jsonl_helpers


_LIVE_DIR = Path(__file__).resolve().parents[3] / "live"
ALERTS_PATH = _LIVE_DIR / "alerts.jsonl"
NOTIFY_PATH = _LIVE_DIR / "notify_events.jsonl"
PANIC_PATH = _LIVE_DIR / "panic_events.jsonl"
STATE_PATH = _LIVE_DIR / "digest_state.json"
CARDS_PATH = _LIVE_DIR / "cards.json"


# ────────────────────────────────────────────────────────────────────────────
# Data source readers — small wrappers around _jsonl_helpers + filtering
# ────────────────────────────────────────────────────────────────────────────

def _today_panics(today_et: date) -> list[dict]:
    """All entries in panic_events.jsonl with ts on today_et."""
    return _jsonl_helpers.read_today_lines(PANIC_PATH, today_et)


def _today_silent_transitions(today_et: date) -> list[dict]:
    """notify_events entries today with severity=WARNING and title containing 'silent'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "WARNING"
        and "silent" in str(e.get("title", "")).lower()
    ]


def _today_guardrail_blocks(today_et: date) -> list[dict]:
    """alerts.jsonl entries today with status='guardrail_blocked'."""
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return [e for e in entries if e.get("status") == "guardrail_blocked"]


def _today_order_failures(today_et: date) -> list[dict]:
    """alerts.jsonl entries today with status='order_failed'."""
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return [e for e in entries if e.get("status") == "order_failed"]


def _today_receiver_downtimes(today_et: date) -> list[dict]:
    """notify_events entries today with severity=CRITICAL and title containing 'receiver down'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "CRITICAL"
        and "receiver down" in str(e.get("title", "")).lower()
    ]


def _today_ngrok_changes(today_et: date) -> list[dict]:
    """notify_events entries today with severity=CRITICAL and title containing 'ngrok'."""
    entries = _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et)
    return [
        e for e in entries
        if str(e.get("severity", "")).upper() == "CRITICAL"
        and "ngrok" in str(e.get("title", "")).lower()
    ]


# ────────────────────────────────────────────────────────────────────────────
# Render — anomaly section
# ────────────────────────────────────────────────────────────────────────────

def _ts_to_et_hhmm(ts: str) -> str:
    """Format an ISO 8601 UTC ts as HH:MM ET."""
    try:
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        return dt.astimezone(_ET).strftime("%H:%M") + " ET"
    except Exception:
        return ts


def _safe_call(fn, *args, default):
    """Call fn(*args); on any exception return (default, exc_type_name).
    Logs the exception to stderr for operator visibility — the rendered
    [error: <type>] placeholder shows the type but stderr shows the detail."""
    try:
        return fn(*args), None
    except Exception as e:
        print(f"[daily_summary] {fn.__name__} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return default, type(e).__name__


_BADGE_CRIT = 'style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;color:#fff;background:#d32f2f;margin-right:6px"'
_BADGE_WARN = 'style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;color:#fff;background:#f57c00;margin-right:6px"'
_HEADER_OK = 'style="margin:16px 0 6px 0;font-size:13px;font-weight:600;color:#388e3c;border-bottom:1px solid #f0f0f0;padding-bottom:3px"'
_HEADER = 'style="margin:16px 0 6px 0;font-size:13px;font-weight:600;color:#444;border-bottom:1px solid #f0f0f0;padding-bottom:3px"'
_META = 'style="color:#888;font-size:11px"'


def _render_anomaly_section(today_et: date) -> tuple[str, dict[str, int]]:
    """Render the anomaly section HTML. Returns (html_str, counts_dict).
    Each sub-section wrapped in try; on failure shows [error: <type>] placeholder."""
    counts = {"panic": 0, "block": 0, "fail": 0, "silent": 0, "downtime": 0, "ngrok": 0}
    items: list[str] = []

    panics, err = _safe_call(_today_panics, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] panic events failed to load</li>")
    else:
        counts["panic"] = len(panics)
        for p in panics:
            level = p.get("level", "?")
            cards = p.get("cards_disabled") or p.get("cards_count") or 0
            t = _ts_to_et_hhmm(p.get("ts", ""))
            items.append(
                f'<li><span {_BADGE_CRIT}>PANIC {level}</span> {t} — {cards} cards disabled</li>'
            )

    blocks, err = _safe_call(_today_guardrail_blocks, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] guardrail blocks failed to load</li>")
    else:
        counts["block"] = len(blocks)
        if blocks:
            # Group by card_id, count, list reasons
            by_card: dict[str, list[str]] = {}
            for b in blocks:
                cid = b.get("card_id", "?")
                by_card.setdefault(cid, []).append(b.get("reason", "?"))
            breakdown_parts = []
            for cid, reasons in list(by_card.items())[:5]:
                # Show count + first reason
                breakdown_parts.append(f"<code>{cid}</code> ×{len(reasons)} ({reasons[0]})")
            breakdown = " · ".join(breakdown_parts)
            items.append(
                f'<li><span {_BADGE_CRIT}>BLOCK</span> {len(blocks)} guardrail blocks: {breakdown}</li>'
            )

    fails, err = _safe_call(_today_order_failures, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] order failures failed to load</li>")
    else:
        counts["fail"] = len(fails)
        if fails:
            items.append(
                f'<li><span {_BADGE_CRIT}>FAIL</span> {len(fails)} order failures (Alpaca rejected or network error)</li>'
            )

    silents, err = _safe_call(_today_silent_transitions, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] silent transitions failed to load</li>")
    else:
        counts["silent"] = len(silents)
        if silents:
            ids = ", ".join(f"<code>{e.get('card_id', '?')}</code>" for e in silents[:5])
            items.append(
                f'<li><span {_BADGE_WARN}>SILENT</span> {len(silents)} silent transition(s): {ids}</li>'
            )

    downs, err = _safe_call(_today_receiver_downtimes, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] receiver downtimes failed to load</li>")
    else:
        counts["downtime"] = len(downs)
        if downs:
            items.append(
                f'<li><span {_BADGE_CRIT}>DOWN</span> {len(downs)} receiver downtime event(s)</li>'
            )

    ngrok, err = _safe_call(_today_ngrok_changes, today_et, default=[])
    if err:
        items.append(f"<li>[error: {err}] ngrok changes failed to load</li>")
    else:
        counts["ngrok"] = len(ngrok)
        if ngrok:
            items.append(
                f'<li><span {_BADGE_CRIT}>NGROK</span> {len(ngrok)} ngrok URL change(s)</li>'
            )

    total = sum(counts.values())
    if total == 0 and not any("[error:" in s for s in items):
        return f'<h4 {_HEADER_OK}>✓ No anomalies today</h4>', counts

    body = (
        f'<h4 {_HEADER}>⚠ Anomalies ({total})</h4>\n'
        '<ul style="margin:4px 0;padding-left:22px">\n'
        + "\n".join(items)
        + "\n</ul>"
    )
    return body, counts


# ────────────────────────────────────────────────────────────────────────────
# Data sources for snapshot section
# ────────────────────────────────────────────────────────────────────────────

def _card_counts() -> dict:
    """Return {total, enabled, disabled, silent} from cards.json + silence_checker."""
    from tradelab.live.cards import CardRegistry
    from tradelab.live import silence_checker

    cards = CardRegistry(CARDS_PATH).all_hydrated().values()
    total = len(cards)
    enabled = sum(1 for c in cards if c.get("status") == "enabled")
    disabled = sum(1 for c in cards if c.get("status") == "disabled")
    try:
        silent = len(silence_checker.silent_set())
    except Exception:
        silent = 0
    return {"total": total, "enabled": enabled, "disabled": disabled, "silent": silent}


def _today_order_submission_count(today_et: date) -> int:
    entries = _jsonl_helpers.read_today_lines(ALERTS_PATH, today_et)
    return sum(1 for e in entries if e.get("status") == "order_submitted")


def _today_notify_counts_by_severity(today_et: date) -> dict[str, int]:
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
    for e in _jsonl_helpers.read_today_lines(NOTIFY_PATH, today_et):
        sev = str(e.get("severity", "")).upper()
        if sev in counts:
            counts[sev] += 1
    return counts


def _open_positions() -> list[dict]:
    from tradelab.live import alpaca_client
    return alpaca_client.list_positions()


def _open_orders() -> list[dict]:
    from tradelab.live import alpaca_client
    return alpaca_client.list_open_orders()


def _receiver_status() -> dict:
    """Best-effort: probe the receiver's status endpoint.
    Returns {up, ngrok_url}. On failure: {up: False, ngrok_url: "—"}.
    Note: uptime is not available from the current endpoint shape; see
    Slice 7a follow-up for adding receiver_uptime_seconds to handlers.py."""
    try:
        import urllib.request
        import json as _json
        with urllib.request.urlopen("http://127.0.0.1:8877/tradelab/receiver/status", timeout=2) as r:
            data = _json.loads(r.read().decode("utf-8")).get("data", {})
        return {
            "up": bool(data.get("receiver_up", False)),
            "ngrok_url": data.get("ngrok_url", "—") or "—",
        }
    except Exception:
        return {"up": False, "ngrok_url": "—"}


def _humanize_seconds(s: int) -> str:
    """120 → '2m', 7320 → '2h 2m', 0 → '0m'."""
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# ────────────────────────────────────────────────────────────────────────────
# Render — snapshot section
# ────────────────────────────────────────────────────────────────────────────

def _render_snapshot_section(today_et: date) -> str:
    parts: list[str] = [f'<h4 {_HEADER}>📊 Health snapshot (now)</h4>']

    cc, err = _safe_call(_card_counts, default={"total": 0, "enabled": 0, "disabled": 0, "silent": 0})
    if err:
        parts.append(f'<p>[error: {err}] cards counts</p>')
    else:
        parts.append(
            f'<p><strong>Cards:</strong> {cc["total"]} total · '
            f'<span style="color:#388e3c">{cc["enabled"]} enabled</span> · '
            f'{cc["disabled"]} disabled · '
            f'<span style="color:#f57c00">{cc["silent"]} silent</span></p>'
        )

    osc, err = _safe_call(_today_order_submission_count, today_et, default=0)
    nsc, err2 = _safe_call(_today_notify_counts_by_severity, today_et, default={"CRITICAL":0,"WARNING":0,"INFO":0,"DEBUG":0})
    if err or err2:
        parts.append(f'<p>[error: {err or err2}] today counts</p>')
    else:
        parts.append(
            f'<p><strong>Today:</strong> {osc} order submissions · '
            f'{nsc["CRITICAL"]} CRITICAL / {nsc["WARNING"]} WARNING / {nsc["INFO"]} INFO notifications</p>'
        )

    rs, err = _safe_call(_receiver_status, default={"up": False, "ngrok_url": "—"})
    if err:
        parts.append(f'<p>[error: {err}] receiver status</p>')
    else:
        up_str = "up" if rs["up"] else "down"
        parts.append(
            f'<p><strong>Receiver:</strong> {up_str} · '
            f'<strong>ngrok:</strong> <code>{rs["ngrok_url"]}</code></p>'
        )

    positions, err = _safe_call(_open_positions, default=[])
    if err:
        parts.append(f'<p>[error: {err}] open positions</p>')
    else:
        parts.append(f'<p style="margin-top:10px"><strong>Open positions ({len(positions)})</strong></p>')
        if positions:
            rows = "".join(
                f'<tr><td style="border:1px solid #e0e0e0;padding:4px 8px">{p["symbol"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{p["qty"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{p["side"]}</td></tr>'
                for p in positions
            )
            parts.append(
                '<table style="border-collapse:collapse;font-size:12px">\n'
                '<tr style="background:#f7f7f7">'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Symbol</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Qty</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Side</th></tr>'
                f'{rows}\n</table>'
            )

    orders, err = _safe_call(_open_orders, default=[])
    if err:
        parts.append(f'<p>[error: {err}] open orders</p>')
    else:
        parts.append(f'<p style="margin-top:10px"><strong>Open orders ({len(orders)})</strong></p>')
        if orders:
            rows = "".join(
                f'<tr><td style="border:1px solid #e0e0e0;padding:4px 8px">{o["symbol"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["qty"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["side"]}</td>'
                f'<td style="border:1px solid #e0e0e0;padding:4px 8px">{o["status"]}</td></tr>'
                for o in orders
            )
            parts.append(
                '<table style="border-collapse:collapse;font-size:12px">\n'
                '<tr style="background:#f7f7f7">'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Symbol</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Qty</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Side</th>'
                '<th style="border:1px solid #e0e0e0;padding:4px 8px">Status</th></tr>'
                f'{rows}\n</table>'
            )

    return "\n".join(parts)


# ────────────────────────────────────────────────────────────────────────────
# Render — public render(now) + subject + plaintext fallback
# ────────────────────────────────────────────────────────────────────────────

_SUBJECT_CATEGORIES = [
    # (key, singular_label, plural_label)
    ("panic",    "panic",              "panics"),
    ("block",    "block",              "blocks"),
    ("fail",     "failure",            "failures"),
    ("downtime", "downtime",           "downtimes"),
    ("ngrok",    "ngrok change",       "ngrok changes"),
    ("silent",   "silent transition",  "silent transitions"),
]


def _render_subject(today_str: str, counts: dict[str, int]) -> str:
    """tradelab daily — YYYY-MM-DD — <tail>.
    Tail = 'all clear' if total=0, else top-2 categories by precedence
    (PANIC > BLOCK > FAIL > DOWNTIME > NGROK > SILENT). Pluralized correctly."""
    if sum(counts.values()) == 0:
        return f"tradelab daily — {today_str} — all clear"
    nonzero = [(key, sing, plur, counts[key])
               for key, sing, plur in _SUBJECT_CATEGORIES
               if counts.get(key, 0) > 0]
    top = nonzero[:2]
    parts = []
    for _key, sing, plur, n in top:
        label = sing if n == 1 else plur
        parts.append(f"{n} {label}")
    return f"tradelab daily — {today_str} — {', '.join(parts)}"


def _render_plaintext(html: str) -> str:
    """Strip HTML tags and decode entities for the plaintext alternative MIME part.
    Preserves section text and table cell contents; collapses whitespace."""
    # Replace block-level closers with newlines for readability
    s = re.sub(r"</(h[1-6]|p|li|tr|div)>", "\n", html, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</(td|th)>", "  ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)  # strip remaining tags
    # Decode common entities
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Collapse runs of blank lines and trailing spaces
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def render(now: datetime) -> tuple[str, str]:
    """Render today's digest. Returns (subject, html_body). Pure — no I/O writes."""
    today_et = now.astimezone(_ET).date()
    today_str = today_et.strftime("%Y-%m-%d")

    anomaly_html, counts = _render_anomaly_section(today_et)
    snapshot_html = _render_snapshot_section(today_et)
    subject = _render_subject(today_str, counts)

    body = (
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:13px;color:#1a1a1a;line-height:1.5">\n'
        f'<div style="font-weight:600;border-bottom:1px solid #eee;padding-bottom:8px;margin-bottom:12px;font-size:14px">{subject}</div>\n'
        f'{anomaly_html}\n'
        f'{snapshot_html}\n'
        f'<p {_META} style="margin-top:14px">tradelab · end of summary</p>\n'
        f'</div>'
    )
    return subject, body
