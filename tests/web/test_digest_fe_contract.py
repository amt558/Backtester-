"""DOM/JS contract tests for the Slice 7a Email Digest section in command_center.html."""
from pathlib import Path

import pytest

CC = Path("C:/TradingScripts/command_center.html")


@pytest.fixture(scope="module")
def html_text():
    return CC.read_text(encoding="utf-8")


# ─── T11: section markup ────────────────────────────────────────────────

def test_email_digest_enabled_uses_data_config(html_text):
    """The enabled toggle uses data-config, NOT a per-field id (existing convention)."""
    assert 'data-config="email_digest.enabled"' in html_text


def test_email_digest_send_time_uses_data_config(html_text):
    assert 'data-config="email_digest.send_time"' in html_text


def test_email_digest_recipient_display_present(html_text):
    """A read-only Recipient line with id email-digest-recipient is present."""
    assert 'id="email-digest-recipient"' in html_text
    assert 'Recipient' in html_text


def test_email_digest_preview_iframe_present(html_text):
    assert 'id="email-digest-preview"' in html_text
    assert '<iframe' in html_text  # very broad — pin that an iframe exists somewhere


def test_email_digest_last_sent_line_present(html_text):
    assert 'id="email-digest-last-sent"' in html_text


def test_email_digest_refresh_button_present(html_text):
    assert 'id="email-digest-refresh-btn"' in html_text


# ─── T12: JS function contracts ─────────────────────────────────────────

def test_loadDigestPreview_function_defined(html_text):
    assert "async function loadDigestPreview" in html_text


def test_loadDigestState_function_defined(html_text):
    assert "async function loadDigestState" in html_text


def test_LT_module_exports_digest_helpers(html_text):
    """Both helpers must be exported from the LT IIFE return object literal.

    Strict pin: both names must appear in a single return-object literal.
    A loose `or` fallback (both names anywhere in the file) would pass even
    if the exports were removed but the function definitions remained, so
    we don't accept that — the contract is the export, not the definition.
    """
    assert "loadDigestPreview, loadDigestState" in html_text, (
        "expected 'loadDigestPreview, loadDigestState' in the LT IIFE return literal"
    )


def test_refresh_button_wired_to_LT_loadDigestPreview(html_text):
    """The DOMContentLoaded boot block binds the Refresh button to LT.loadDigestPreview()."""
    assert "LT.loadDigestPreview" in html_text


def test_loadDigestPreview_uses_correct_endpoint(html_text):
    assert "/tradelab/live/digest/preview" in html_text


def test_loadDigestState_uses_correct_endpoint(html_text):
    assert "/tradelab/live/digest/state" in html_text
