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


def test_timestamp_with_seconds_raises_parse_error():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-05-01 09:30:15,100.00,10,,,,,,,,\n"
        "1,Exit long,Exit,2024-05-03 09:30:15,105.00,10,50.00,5.00,50.00,0.05,60.00,6.00,-2.00,-0.20\n"
    )
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(csv, symbol="MU")
    msg = str(exc.value).lower()
    assert "trade #1" in msg
    assert "date/time" in msg or "format" in msg


def test_fractional_contracts_rounded_to_nearest_integer():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-05-01 09:30,100.00,6.7236,,,,,,,,\n"
        "1,Exit long,Exit,2024-05-03 09:30,105.00,6.7236,33.62,5.00,33.62,0.03,40.00,6.00,-2.00,-0.20\n"
        "2,Entry long,Long,2024-05-10 09:30,100.00,0.6,,,,,,,,\n"
        "2,Exit long,Exit,2024-05-12 09:30,110.00,0.6,6.00,10.00,39.62,0.04,7.00,12.00,-1.00,-1.00\n"
    )
    parsed = parse_tv_trades_csv(csv, symbol="X")
    assert parsed.trades[0].shares == 7   # 6.7236 rounds to 7
    assert parsed.trades[1].shares == 1   # 0.6 rounds to 1


def test_malformed_price_includes_trade_number_in_error():
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,"
        "Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-05-01 09:30,not-a-number,10,,,,,,,,\n"
        "1,Exit long,Exit,2024-05-03 09:30,105.00,10,50.00,5.00,50.00,0.05,60.00,6.00,-2.00,-0.20\n"
    )
    with pytest.raises(TVCSVParseError) as exc:
        parse_tv_trades_csv(csv, symbol="MU")
    assert "trade #1" in str(exc.value).lower()


def test_modern_tv_schema_with_renamed_columns_parses():
    # As of TV 2025+ the Strategy Tester export renamed several columns:
    #   Date/Time          -> "Date and time"
    #   Contracts          -> "Size (qty)"
    #   Profit USD/%       -> "Net P&L USD" / "Net P&L %"
    #   Run-up %           -> "Favorable excursion %"
    #   Drawdown %         -> "Adverse excursion %"
    # Also the row order is Exit-then-Entry per trade. Parser must accept both.
    csv = (
        "Trade #,Type,Date and time,Signal,Price USD,Size (qty),Size (value),"
        "Net P&L USD,Net P&L %,Favorable excursion USD,Favorable excursion %,"
        "Adverse excursion USD,Adverse excursion %,Cumulative P&L USD,Cumulative P&L %\n"
        "1,Exit long,2024-01-13 13:30,Time Exit,19.7,4740,94989.6,"
        "-1611.6,-1.70,711,0.75,-1753.8,-1.85,-1611.6,-1.61\n"
        "1,Entry long,2024-01-09 09:30,Long,20.04,4740,94989.6,"
        "-1611.6,-1.70,711,0.75,-1753.8,-1.85,-1611.6,-1.61\n"
    )
    parsed = parse_tv_trades_csv(csv, symbol="AMZN")
    assert len(parsed.trades) == 1
    t = parsed.trades[0]
    assert t.entry_date == "2024-01-09"
    assert t.exit_date == "2024-01-13"
    assert t.entry_price == 20.04
    assert t.exit_price == 19.7
    assert t.shares == 4740
    assert t.pnl == -1611.6
    assert t.pnl_pct == -1.70
    assert t.exit_reason == "Time Exit"
    assert t.mfe_pct == 0.75
    assert t.mae_pct == -1.85
