"""Static assertions over command_center.html for the New Strategy live
pipeline (Task E), review-before-accept (Task G), and advisory threshold
(Task F) front-end contracts. Mirrors test_command_center_html.py's
text-based approach (no browser) and skips cleanly if the file is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _find_html() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "command_center.html"
        if candidate.exists():
            return candidate
    return None


HTML_PATH = _find_html()
pytestmark = pytest.mark.skipif(HTML_PATH is None, reason="command_center.html not found")


@pytest.fixture(scope="module")
def html() -> str:
    assert HTML_PATH is not None
    return HTML_PATH.read_text(encoding="utf-8")


# ── Task E: live pipeline tracker ────────────────────────────────────

def test_pipeline_stage_list_present(html: str):
    assert "NS_PIPELINE_STAGES" in html
    for stage in ("'register'", "'enrich'", "'backtest'", "'robustness'", "'quantstats'", "'done'"):
        assert stage in html, f"pipeline stage {stage} missing"


def test_pipeline_tracking_function_present(html: str):
    assert "function nsStartPipelineTracking" in html
    assert "function nsStageFromJob" in html
    assert "function nsRenderPipeline" in html


def test_register_polls_job_endpoint_instead_of_blind_alert(html: str):
    # The new flow polls the Task D job-status endpoint...
    assert "/tradelab/new-strategy/job/" in html
    # ...and the old blind New-Strategy alert (which closed the modal) is gone.
    assert "table will update when complete" not in html


def test_pipeline_escapes_server_strings(html: str):
    # log_tail / error / stage come from the server — must be escaped (XSS).
    assert "escapeHtml(String(job.log_tail))" in html
    assert "escapeHtml(String(name))" in html or "escapeHtml(name)" in html


# ── Task G: review-before-accept ─────────────────────────────────────

def test_review_controls_and_accept_present(html: str):
    assert "window.nsRenderReviewControls" in html
    assert "window.onNsAccept" in html
    # Both review artifacts are reachable.
    assert "robustness_tearsheet.html" in html
    assert "quantstats_tearsheet.html" in html


def test_candidate_accept_button_is_canary_gated(html: str):
    # The canary gate disables `.btn.accept` on a MISMATCH. The new candidate
    # Accept button must carry class "accept" so it is actually covered.
    assert 'class="btn accept"' in html
    # And the gate CSS still targets that class.
    assert "body.accepts-blocked .btn.accept" in html


def test_candidate_accept_creates_paper_disabled_unfunded_card(html: str):
    # activate:false → disabled; no allocation_usd in payload → unfunded; paper mode.
    assert "activate: false" in html
    assert "mode: 'paper'" in html
    payload = _ns_accept_payload(html)
    assert payload, "could not locate onNsAccept payload literal"
    assert "allocation_usd" not in payload, "candidate accept must not fund the card"
    assert "/tradelab/strategies/accept" in html


# ── Task F: advisory threshold control ───────────────────────────────

def test_advisory_control_present(html: str):
    assert "window.onNsAdvisory" in html
    assert "/tradelab/new-strategy/advisory-verdict" in html
    assert 'id="nsAdvPfRobust"' in html
    # The display-only framing must be explicit.
    assert "advisory only" in html
    assert "canonical verdict = " in html


def _ns_accept_payload(html: str) -> str:
    """The `const payload = { ... }` object literal inside onNsAccept, so the
    assertions check what is actually SENT (not surrounding comments)."""
    anchor = html.find("window.onNsAccept")
    start = html.find("const payload = {", anchor)
    end = html.find("};", start)
    return html[start:end] if start >= 0 and end > start else ""
