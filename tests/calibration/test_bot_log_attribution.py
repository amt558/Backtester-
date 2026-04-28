from pathlib import Path
import pytest
from tradelab.calibration.bot_log_attribution import (
    parse_position_added_lines, attribute_trade,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrospective"


def test_parse_position_added_lines():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    assert len(entries) == 3
    aapl_first = entries[0]
    assert aapl_first["symbol"] == "AAPL"
    assert aapl_first["strategy"] == "S4_InsideDayBreakout"
    assert aapl_first["entry_price"] == pytest.approx(180.10)
    assert aapl_first["qty"] == 100


def test_attribute_trade_within_window():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    trade = {"symbol": "AAPL", "entry_ts": "2026-01-15T14:31:00Z"}
    strategy = attribute_trade(trade, entries, window_hours=24)
    assert strategy == "S4_InsideDayBreakout"


def test_attribute_trade_unattributed_when_no_match():
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    trade = {"symbol": "GOOGL", "entry_ts": "2026-03-01T14:31:00Z"}
    strategy = attribute_trade(trade, entries, window_hours=24)
    assert strategy is None


def test_attribute_picks_nearest_entry_when_multiple_match():
    """Two AAPL Position added lines exist (Jan 15 and Feb 1).
    A trade on Jan 16 should attribute to the Jan 15 entry, not Feb 1."""
    entries = parse_position_added_lines(FIXTURES / "bot_log_sample.log")
    trade = {"symbol": "AAPL", "entry_ts": "2026-01-16T14:31:00Z"}
    strategy = attribute_trade(trade, entries, window_hours=72)
    assert strategy == "S4_InsideDayBreakout"


def test_parse_handles_missing_file_gracefully():
    """If the log doesn't exist, parser should raise FileNotFoundError or
    return empty — pick one and document."""
    nonexistent = FIXTURES / "definitely_not_a_log.log"
    with pytest.raises(FileNotFoundError):
        parse_position_added_lines(nonexistent)
