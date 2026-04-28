"""Test daily-returns derivation from tv_trades.csv."""
from __future__ import annotations
from pathlib import Path
import csv
import pytest
from tradelab.io.returns import derive_daily_returns, write_returns_csv, MalformedTVCSVError


def _write_tv_trades(tmp_path: Path) -> Path:
    """Two trades on 2026-01-05 (one win, one loss), one on 2026-01-06."""
    p = tmp_path / "tv_trades.csv"
    p.write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00,103.00,10,30.00,3.00\n"
        "2,Entry long,enter,2026-01-05 13:00,105.00,10,,\n"
        "2,Exit long,exit,2026-01-05 14:30,103.00,10,-20.00,-1.90\n"
        "3,Entry long,enter,2026-01-06 09:30,107.00,5,,\n"
        "3,Exit long,exit,2026-01-06 15:00,112.00,5,25.00,4.67\n",
        encoding="utf-8",
    )
    return p


def test_derive_daily_returns_groups_by_exit_date(tmp_path: Path) -> None:
    csv_path = _write_tv_trades(tmp_path)
    rows = derive_daily_returns(csv_path)
    # Two distinct trade-exit dates → two daily rows.
    assert len(rows) == 2
    by_date = {r["date"]: r for r in rows}
    # 2026-01-05 net return: trade 1 (+3.00%) + trade 2 (-1.90%) = +1.10%.
    assert by_date["2026-01-05"]["return_pct"] == pytest.approx(1.10, abs=0.001)
    # 2026-01-06: single trade +4.67%.
    assert by_date["2026-01-06"]["return_pct"] == pytest.approx(4.67, abs=0.001)


def test_derive_daily_returns_handles_alt_column_names(tmp_path: Path) -> None:
    """tv_csv supports both 'Profit USD' and 'Net P&L USD', etc."""
    p = tmp_path / "tv_trades.csv"
    p.write_text(
        "Trade #,Type,Signal,Date and time,Price USD,Size (qty),Net P&L USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    rows = derive_daily_returns(p)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["return_pct"] == pytest.approx(3.00, abs=0.001)


def test_write_returns_csv_emits_two_columns(tmp_path: Path) -> None:
    out = tmp_path / "returns.csv"
    write_returns_csv(out, [
        {"date": "2026-01-05", "return_pct": 1.10},
        {"date": "2026-01-06", "return_pct": 4.67},
    ])
    text = out.read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    assert reader.fieldnames == ["date", "return_pct"]
    assert rows == [
        {"date": "2026-01-05", "return_pct": "1.10"},
        {"date": "2026-01-06", "return_pct": "4.67"},
    ]


def test_derive_returns_empty_csv_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "tv_trades.csv"
    p.write_text("Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n", encoding="utf-8")
    assert derive_daily_returns(p) == []


def test_derive_daily_returns_raises_on_missing_type_column(tmp_path: Path) -> None:
    """Missing Type column → MalformedTVCSVError, not silent []."""
    p = tmp_path / "tv_trades.csv"
    # Valid date + profit columns, but no Type column.
    p.write_text(
        "Trade #,Signal,Date/Time,Price USD,Profit %\n"
        "1,enter,2026-01-05 11:00,103.00,3.00\n",
        encoding="utf-8",
    )
    with pytest.raises(MalformedTVCSVError, match="Type"):
        derive_daily_returns(p)


def test_derive_daily_returns_raises_on_missing_date_column(tmp_path: Path) -> None:
    """Missing date column → MalformedTVCSVError, not silent []."""
    p = tmp_path / "tv_trades.csv"
    # Type and profit columns present, but no recognised date column.
    p.write_text(
        "Trade #,Type,Signal,Timestamp,Price USD,Profit %\n"
        "1,Exit long,exit,2026-01-05 11:00,103.00,3.00\n",
        encoding="utf-8",
    )
    with pytest.raises(MalformedTVCSVError, match="date column"):
        derive_daily_returns(p)


def test_derive_daily_returns_raises_on_missing_profit_column(tmp_path: Path) -> None:
    """Missing profit-pct column → MalformedTVCSVError, not silent []."""
    p = tmp_path / "tv_trades.csv"
    # Type and date columns present, but no recognised profit-pct column.
    p.write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Profit USD\n"
        "1,Exit long,exit,2026-01-05 11:00,103.00,30.00\n",
        encoding="utf-8",
    )
    with pytest.raises(MalformedTVCSVError, match="profit-pct column"):
        derive_daily_returns(p)
