"""TradingView Strategy Tester 'List of trades' CSV parser.

Pure: reads CSV text, returns domain objects, no I/O. The orchestrator
(csv_scoring.py) is responsible for reading bytes off disk and feeding them
in. Keep this module free of pandas / numpy so it stays cheap to test.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from ..results import Trade


# Canonical name -> list of header strings TradingView has used at various
# points. The newer Strategy Tester (2025+) renamed several columns; the
# parser accepts either form so a CSV exported from any vintage works.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "Trade #":     ("Trade #",),
    "Type":        ("Type",),
    "Signal":      ("Signal",),
    "Date/Time":   ("Date/Time", "Date and time"),
    "Price USD":   ("Price USD",),
    "Contracts":   ("Contracts", "Size (qty)"),
    "Profit USD":  ("Profit USD", "Net P&L USD", "P&L USD"),
    "Profit %":    ("Profit %",   "Net P&L %",   "P&L %"),
    "Run-up %":    ("Run-up %",   "Favorable excursion %"),
    "Drawdown %":  ("Drawdown %", "Adverse excursion %"),
}

# Backwards-compat alias (some external code / tests may import this).
REQUIRED_COLUMNS = set(COLUMN_ALIASES.keys())


class TVCSVParseError(ValueError):
    """Raised when the CSV is unreadable, malformed, or contains no closed trades."""


def _resolve_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Build canonical-name -> actual-CSV-column-name. Raises on missing columns."""
    fields = set(fieldnames)
    out: dict[str, str] = {}
    missing: list[str] = []
    for canonical, candidates in COLUMN_ALIASES.items():
        match = next((c for c in candidates if c in fields), None)
        if match is None:
            missing.append(canonical)
        else:
            out[canonical] = match
    if missing:
        raise TVCSVParseError(f"missing column(s): {sorted(missing)}")
    return out


@dataclass(frozen=True)
class ParsedTradesCSV:
    trades: list[Trade]
    start_date: str  # ISO YYYY-MM-DD of earliest entry
    end_date: str    # ISO YYYY-MM-DD of latest exit


def _date_only(stamp: str) -> str:
    """Convert TV's 'YYYY-MM-DD HH:MM' to 'YYYY-MM-DD'."""
    try:
        return datetime.strptime(stamp.strip(), "%Y-%m-%d %H:%M").strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        # Some TV exports drop the time when the bar is daily.
        return datetime.strptime(stamp.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise TVCSVParseError(f"unrecognised Date/Time format: {stamp!r}")


def _bars_between(entry: str, exit_: str) -> int:
    a = datetime.strptime(entry, "%Y-%m-%d")
    b = datetime.strptime(exit_, "%Y-%m-%d")
    return max(int((b - a).days), 0)


def _f(row: dict, key: str, default: float = 0.0) -> float:
    v = (row.get(key) or "").strip()
    if not v:
        return default
    return float(v)


def parse_tv_trades_csv(csv_text: str, *, symbol: str) -> ParsedTradesCSV:
    if not csv_text or not csv_text.strip():
        raise TVCSVParseError("CSV is empty")

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise TVCSVParseError("CSV has no header row")

    H = _resolve_header_map(reader.fieldnames)

    rows_by_trade: dict[str, list[dict]] = {}
    for row in reader:
        tnum = (row.get(H["Trade #"]) or "").strip()
        if not tnum:
            continue
        rows_by_trade.setdefault(tnum, []).append(row)

    trades: list[Trade] = []
    for tnum in sorted(rows_by_trade.keys(), key=lambda s: int(s)):
        rows = rows_by_trade[tnum]
        entry = next((r for r in rows if r[H["Type"]].startswith("Entry")), None)
        exit_ = next((r for r in rows if r[H["Type"]].startswith("Exit")), None)
        if entry is None or exit_ is None:
            # Open trade — drop silently.
            continue

        try:
            entry_date = _date_only(entry[H["Date/Time"]])
            exit_date = _date_only(exit_[H["Date/Time"]])
            trades.append(Trade(
                ticker=symbol,
                entry_date=entry_date,
                exit_date=exit_date,
                entry_price=_f(entry, H["Price USD"]),
                exit_price=_f(exit_, H["Price USD"]),
                shares=int(round(_f(entry, H["Contracts"]))),
                pnl=_f(exit_, H["Profit USD"]),
                pnl_pct=_f(exit_, H["Profit %"]),
                bars_held=_bars_between(entry_date, exit_date),
                exit_reason=(exit_.get(H["Signal"]) or "tv_csv").strip() or "tv_csv",
                mae_pct=_f(exit_, H["Drawdown %"]),
                mfe_pct=_f(exit_, H["Run-up %"]),
            ))
        except (ValueError, TVCSVParseError) as e:
            raise TVCSVParseError(f"trade #{tnum}: {e}") from e

    if not trades:
        raise TVCSVParseError("no closed trades found in CSV")

    return ParsedTradesCSV(
        trades=trades,
        start_date=min(t.entry_date for t in trades),
        end_date=max(t.exit_date for t in trades),
    )
