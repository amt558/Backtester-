"""TradingView 'List of trades' CSV parser tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.io.tv_csv import (
    ParsedTradesCSV,
    TVCSVParseError,
    parse_tv_trades_csv,
)


FIXTURE = Path(__file__).parent / "fixtures" / "tv_export_amzn_smoke.csv"


def test_parses_six_closed_trades_and_drops_open_trade():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    assert isinstance(parsed, ParsedTradesCSV)
    assert len(parsed.trades) == 6  # trade #7 is open and must be dropped


def test_window_dates_span_first_entry_to_last_exit():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    assert parsed.start_date == "2024-01-08"
    assert parsed.end_date == "2024-03-22"


def test_first_trade_round_trip_preserves_prices_pnl_and_pct():
    parsed = parse_tv_trades_csv(FIXTURE.read_text(encoding="utf-8"), symbol="AMZN")
    t = parsed.trades[0]
    assert t.ticker == "AMZN"
    assert t.entry_date == "2024-01-08"
    assert t.exit_date == "2024-01-12"
    assert t.entry_price == 150.00
    assert t.exit_price == 156.00
    assert t.shares == 10
    assert t.pnl == 60.00
    assert t.pnl_pct == 4.00
    assert t.exit_reason == "Exit"          # from Signal column on exit row
    assert t.mfe_pct == 5.33
    assert t.mae_pct == -1.33
    assert t.bars_held == 4                 # calendar days between entry/exit


def test_short_trade_pnl_uses_csv_value_not_recomputed():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry short,Short,2024-05-01 09:30,100.00,5,,,,,,,,\n"
        "1,Exit short,Cover,2024-05-03 09:30,95.00,5,25.00,5.00,25.00,0.03,30.00,6.00,-2.00,-0.40\n"
    )
    parsed = parse_tv_trades_csv(csv, symbol="MU")
    t = parsed.trades[0]
    # Short profit: entry 100 -> exit 95 -> +5 per share x 5 shares = 25 (matches CSV).
    assert t.pnl == 25.00
    assert t.exit_reason == "Cover"


def test_missing_required_column_raises():
    bad = "Foo,Bar\n1,2\n"
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(bad, symbol="AMZN")
    assert "missing column" in str(exc.value).lower()


def test_empty_csv_raises():
    with pytest.raises(TVCSVParseError):
        parse_tv_trades_csv("", symbol="AMZN")


def test_no_closed_trades_raises():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-01-01 09:30,100,10,,,,,,,,\n"
    )
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(csv, symbol="AMZN")
    assert "no closed trades" in str(exc.value).lower()
