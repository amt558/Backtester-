"""DOM/CSS/JS contract tests for the Slice 6 panic panel.

These tests use static greps against C:/TradingScripts/command_center.html.
They pin selectors, attribute names, function names, and CSS literals so
that a refactor that breaks the contract gets caught at pytest time.

Mirrors the Slice 5 contract-test pattern (test_silence_status_handler.py
style) — text greps with explicit error messages.
"""
from pathlib import Path
import re

import pytest

CC = Path("C:/TradingScripts/command_center.html")


@pytest.fixture(scope="module")
def html_text():
    return CC.read_text(encoding="utf-8")


# ─── Panel strip ────────────────────────────────────────────────────────

def test_panic_strip_is_first_child_of_live_trading(html_text):
    """Panic strip must appear before the existing lt-status-strip."""
    panic_idx = html_text.find('id="lt-panic-strip"')
    status_idx = html_text.find('id="lt-status-strip"')
    assert panic_idx > 0, "lt-panic-strip not found in command_center.html"
    # If lt-status-strip is wrapped without an id, fall back to the class
    if status_idx < 0:
        status_idx = html_text.find('class="lt-status-strip"')
    assert status_idx > 0, "lt-status-strip not found"
    assert panic_idx < status_idx, "panic strip must precede status strip in DOM"


def test_panic_strip_buttons_present(html_text):
    for label in ("Pause All", "Pause + Cancel Orders", "Pause + Cancel + Flatten Positions"):
        assert label in html_text, f"missing button label: {label!r}"


def test_panic_strip_emoji_title(html_text):
    assert "🚨 PANIC" in html_text


def test_panic_strip_sticky_css(html_text):
    """panic strip CSS uses position: sticky."""
    block = html_text[html_text.find(".lt-panic-strip"):html_text.find(".lt-panic-strip") + 1500]
    assert "position: sticky" in block or "position:sticky" in block


# ─── JS toggles + state pins ────────────────────────────────────────────

def test_panic_toggle_function_pinned(html_text):
    assert "togglePanicStrip" in html_text


def test_panic_strip_collapsed_by_default(html_text):
    # data-expanded="false" or hidden attribute on the buttons container
    assert 'data-expanded="false"' in html_text or 'data-panic-expanded="false"' in html_text
