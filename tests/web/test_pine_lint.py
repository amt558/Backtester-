"""Tests for the Pine source linter (UPGRADES #2-A)."""
from __future__ import annotations

from tradelab.web.approve_strategy import lint_pine_source


def test_lint_empty_source_returns_empty():
    assert lint_pine_source(None) == []
    assert lint_pine_source("") == []


def test_lint_clean_source_returns_empty():
    src = """//@version=5
strategy("clean", overlay=true)
if close > open
    strategy.entry("L", strategy.long)
"""
    assert lint_pine_source(src) == []


def test_lint_catches_process_orders_on_close():
    src = '//@version=5\nstrategy("opt", process_orders_on_close = true)\n'
    findings = lint_pine_source(src)
    flags = [f["flag"] for f in findings]
    assert "process_orders_on_close" in flags
    assert all(f["level"] in ("warning", "error") for f in findings)


def test_lint_catches_lookahead_on():
    src = 'x = request.security(syminfo.ticker, "1H", close, lookahead = barmerge.lookahead_on)\n'
    findings = lint_pine_source(src)
    assert any(f["flag"] == "lookahead_on" and f["level"] == "error" for f in findings)


def test_lint_catches_multiple_flags():
    src = """//@version=5
strategy("bad", process_orders_on_close=true, calc_on_every_tick=true)
"""
    flags = [f["flag"] for f in lint_pine_source(src)]
    assert "process_orders_on_close" in flags
    assert "calc_on_every_tick" in flags


def test_lint_case_insensitive():
    src = 'strategy("up", PROCESS_ORDERS_ON_CLOSE = TRUE)\n'
    flags = [f["flag"] for f in lint_pine_source(src)]
    assert "process_orders_on_close" in flags
