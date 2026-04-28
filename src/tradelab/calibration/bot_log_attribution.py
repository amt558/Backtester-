"""Parses alpaca_trading_bot.log for `Position added: SYMBOL (STRATEGY)` lines.

Used by Slice -1 to attribute Alpaca fills to strategies for the historical 12mo
window. Pre-Slice-0.5 the bot did not tag client_order_id, so this log-parsing
fallback is needed for fills that pre-date the tagging change.

Future fills (post Slice -0.5) carry strategy in client_order_id natively and
won't need this parser.
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


_LINE_PATTERN = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r".*Position added: (?P<symbol>[A-Z]+) \((?P<strategy>[A-Za-z0-9_]+)\)"
    r" - (?P<qty>\d+)@\$(?P<price>[\d.]+)"
)


def parse_position_added_lines(log_path: Path) -> list[dict]:
    """Read bot log; return one entry per `Position added` line.

    Raises FileNotFoundError if the log file doesn't exist.
    """
    text = log_path.read_text(errors="ignore")
    entries: list[dict] = []
    for line in text.splitlines():
        m = _LINE_PATTERN.search(line)
        if m:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            entries.append({
                "ts": ts, "symbol": m.group("symbol"),
                "strategy": m.group("strategy"),
                "qty": int(m.group("qty")),
                "entry_price": float(m.group("price")),
            })
    return entries


def attribute_trade(
    trade: dict, log_entries: list[dict], *, window_hours: int = 24,
) -> Optional[str]:
    """Find the bot.log Position added entry matching this trade's symbol within window.

    Returns the strategy name, or None if no match within window_hours.
    Picks the nearest-in-time entry when multiple match.
    """
    trade_ts = datetime.fromisoformat(trade["entry_ts"].replace("Z", "+00:00"))
    candidates = [
        e for e in log_entries
        if e["symbol"] == trade["symbol"]
        and abs(e["ts"] - trade_ts) <= timedelta(hours=window_hours)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda e: abs(e["ts"] - trade_ts))
    return candidates[0]["strategy"]
