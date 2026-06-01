import math
import pytest
from tradelab.live.strategy_runner import desired_position, size_qty, safety_block_reason


def test_desired_position_from_signals():
    assert desired_position({"buy_signal": True,  "sell_signal": False}) == "long"
    assert desired_position({"buy_signal": False, "sell_signal": True})  == "flat"
    assert desired_position({"buy_signal": False, "sell_signal": False}) == "hold"
    assert desired_position({"buy_signal": True,  "sell_signal": True})  == "flat"


def test_size_qty_floors_and_guards():
    assert size_qty(1000.0, 100.0) == 10
    assert size_qty(1050.0, 100.0) == 10
    assert size_qty(50.0, 100.0) == 0
    assert size_qty(None, 100.0) == 0
    assert size_qty(1000.0, 0.0) == 0
    assert size_qty(-5.0, 100.0) == 0


def test_safety_block_reason():
    base = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": False, "daily_loss_limit": -5000}}
    assert safety_block_reason(base, daily_pnl=-100.0, is_entry=True) is None
    off = {"alpaca": {"paper_trading": False}, "trading": {}}
    assert "paper" in safety_block_reason(off, daily_pnl=0.0, is_entry=True).lower()
    ks = {"alpaca": {"paper_trading": True}, "trading": {"kill_switch": True}}
    assert "kill" in safety_block_reason(ks, daily_pnl=0.0, is_entry=True).lower()
    dl = {"alpaca": {"paper_trading": True}, "trading": {"daily_loss_limit": -5000}}
    assert safety_block_reason(dl, daily_pnl=-6000.0, is_entry=True) is not None
    assert safety_block_reason(dl, daily_pnl=-6000.0, is_entry=False) is None
