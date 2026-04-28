"""Derive daily-returns series from tv_trades.csv exports.

Used at Accept time (and via backfill script) to persist a per-card
returns series at pine_archive/<card_id>/returns.csv, which feeds the
correlation engine and tracking-error engine.

Returns are aggregated by trade-EXIT date. Multi-trade days net out.

This module has its own minimal CSV reader so it only requires the columns
it actually needs (Type, Date/Time, Profit %) — it does NOT require the
full column set that parse_tv_trades_csv demands (run-up, drawdown, etc.).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable

# Column name aliases for the columns we care about.
_DATE_COLS = ("Date/Time", "Date and time")
_PROFIT_PCT_COLS = ("Profit %", "Net P&L %", "P&L %")
_TYPE_COL = "Type"


def _find_col(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate present in fieldnames, or None."""
    for c in candidates:
        if c in fieldnames:
            return c
    return None


def _parse_date(stamp: str) -> str:
    """Extract YYYY-MM-DD from 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'."""
    s = stamp.strip()
    if len(s) >= 10:
        return s[:10]
    return s


def derive_daily_returns(tv_trades_csv: Path) -> list[dict]:
    """Return [{date: 'YYYY-MM-DD', return_pct: float}, ...] sorted by date.

    Groups exits by trade-exit date; sums their Profit % values per day.
    Entry rows (no profit value) are ignored.
    Returns an empty list if the file contains no closed trades.
    """
    text = tv_trades_csv.read_text(encoding="utf-8-sig")  # handle BOM from PS-written files
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []

    fieldnames = list(reader.fieldnames)
    date_col = _find_col(fieldnames, _DATE_COLS)
    profit_col = _find_col(fieldnames, _PROFIT_PCT_COLS)
    type_col = _TYPE_COL if _TYPE_COL in fieldnames else None

    if date_col is None or profit_col is None or type_col is None:
        return []

    by_date: dict[str, float] = {}
    for row in reader:
        row_type = (row.get(type_col) or "").strip()
        # Only Exit rows carry a Profit % value.
        if not row_type.startswith("Exit"):
            continue
        profit_raw = (row.get(profit_col) or "").strip()
        if not profit_raw:
            continue
        try:
            profit_pct = float(profit_raw)
        except ValueError:
            continue
        date_raw = (row.get(date_col) or "").strip()
        if not date_raw:
            continue
        key = _parse_date(date_raw)
        by_date[key] = by_date.get(key, 0.0) + profit_pct

    return [{"date": d, "return_pct": round(by_date[d], 4)} for d in sorted(by_date)]


def write_returns_csv(out_path: Path, rows: Iterable[dict]) -> None:
    """Write [{date, return_pct}] rows as 2-column CSV with header."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "return_pct"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "date": row["date"],
                "return_pct": f"{float(row['return_pct']):.2f}",
            })
