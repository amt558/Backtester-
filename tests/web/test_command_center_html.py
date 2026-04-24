"""Static assertions over C:/TradingScripts/command_center.html.

Defense against the class of bugs that pytest can't see: the Research
tab's JavaScript / DOM contract between the HTML file and the tradelab
web endpoints. Plan drift (wrong selector, renamed function) or dead-
code deletion (accidentally dropping a function the backend still
references) slip past the backend suite because the backend doesn't
render HTML.

These are static checks — no browser, no JSDOM, no network. The tests
open the HTML file as text and assert structural invariants:

  1. Required JS functions exist exactly once (defense against double-
     paste or silent deletion).
  2. Required DOM IDs / classes are present (defense against "renamed
     by one side of the contract").
  3. Intentionally-removed identifiers stay absent (guards against a
     future session restoring `fragileReasons` or similar without
     noticing it duplicates engine logic).
  4. XSS smell check: no `innerHTML = \\`...${server_field}...\\``
     pattern against fields known to hold user/server strings.

If command_center.html is not at the expected path (e.g. test run in a
CI container without the parent repo), the module skips cleanly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _find_command_center_html() -> Path | None:
    """Walk up from cwd looking for command_center.html.

    Expected layout:
      C:/TradingScripts/
        command_center.html       ← target
        tradelab/                 ← we run tests from here
          tests/web/test_command_center_html.py
    """
    start = Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "command_center.html"
        if candidate.exists():
            return candidate
    return None


HTML_PATH = _find_command_center_html()


pytestmark = pytest.mark.skipif(
    HTML_PATH is None,
    reason="command_center.html not found (expected at parent of tradelab/)",
)


@pytest.fixture(scope="module")
def html() -> str:
    assert HTML_PATH is not None
    return HTML_PATH.read_text(encoding="utf-8")


# ── Required JS functions (must exist exactly once) ────────────────
REQUIRED_JS_FUNCTIONS = [
    "researchLoadPreflight",
    "renderPreflightInModal",
    "verdictHeatClass",
    "renderSparkline",
    "getSparklineRuns",
    "updateCompareButton",
    "renderLiveCard",
    "escapeHtml",
    "researchLoadLiveCards",
    "researchLoadPipeline",
]


@pytest.mark.parametrize("fn_name", REQUIRED_JS_FUNCTIONS)
def test_required_js_function_defined_exactly_once(html: str, fn_name: str) -> None:
    # Match either `function X(` or `async function X(`. Single regex with
    # optional `async` prefix avoids the double-count trap of running two
    # patterns (async function matches both plain and async variants).
    pattern = re.compile(rf"(?:async\s+)?function\s+{re.escape(fn_name)}\s*\(", re.MULTILINE)
    matches = pattern.findall(html)
    assert len(matches) == 1, f"{fn_name}: found {len(matches)} definitions (expected exactly 1)"


# ── Required DOM contracts (ID/class references the backend or plan
#    assumes will exist) ────────────────────────────────────────────
REQUIRED_DOM_IDS = [
    "preflight-universe",
    "preflight-cache",
    "preflight-strategy",
    "preflight-tdapi",
    "preflight-chips",
    "researchPipelineTable",
    "researchPipelineBody",
    "researchLiveCards",
    "pipelineCompareBtn",
    "modal-3f-confirm",  # Run modal Start button — preflight block targets this
]


@pytest.mark.parametrize("dom_id", REQUIRED_DOM_IDS)
def test_required_dom_id_present(html: str, dom_id: str) -> None:
    assert f'id="{dom_id}"' in html, f'required DOM id="{dom_id}" missing from command_center.html'


REQUIRED_CSS_CLASSES = [
    "preflight-chip",
    "preflight-ok",
    "preflight-warn",
    "preflight-red",
    "verdict-pill",
    "research-card",
    "modal-preflight",
    "btn-ghost",  # Added post-review 2026-04-23 — don't let it disappear silently
]


@pytest.mark.parametrize("css_class", REQUIRED_CSS_CLASSES)
def test_required_css_class_defined(html: str, css_class: str) -> None:
    # Either `.foo{...}` or `.btn.foo{...}` or class="... foo ..." usage.
    # Match either a CSS selector (`.foo` followed by `{`, space, `:`, `.`)
    # or a `class="..."` attribute containing the token.
    selector_re = re.compile(rf"\.{re.escape(css_class)}(?=[\s\{{:\.,])")
    attr_re = re.compile(rf'class="[^"]*\b{re.escape(css_class)}\b[^"]*"')
    assert selector_re.search(html) or attr_re.search(html), (
        f"CSS class '.{css_class}' has no selector definition and no class= usage"
    )


# ── Intentionally-removed identifiers (post-review 2026-04-23) ─────
FORBIDDEN_IDENTIFIERS = [
    # Removed because it duplicated + drifted from engine verdict thresholds.
    # If a future session reintroduces client-side fragility heuristics, this
    # test fails and forces them to either update the test (acknowledging the
    # architectural decision) or rethink.
    "fragileReasons",
    # Removed because it was a display:none placeholder with no handler wired.
    # The per-row `.rowSelectCheckbox` elements remain and drive Compare.
    "pipelineSelectAll",
]


@pytest.mark.parametrize("ident", FORBIDDEN_IDENTIFIERS)
def test_forbidden_identifier_absent(html: str, ident: str) -> None:
    assert ident not in html, (
        f"'{ident}' was intentionally removed 2026-04-23 post-review. "
        f"If you're reintroducing it, update tests/web/test_command_center_html.py's "
        f"FORBIDDEN_IDENTIFIERS list and explain why in the commit."
    )


# ── XSS smell check ────────────────────────────────────────────────
# The plan originally prescribed several raw-interpolation innerHTML
# snippets against server-supplied strings. All were rewritten to use
# textContent / createTextNode / escapeHtml during the v2 ship. If a
# future change reintroduces `${r.label}` / `${r.detail}` directly in
# an innerHTML template, we want to know.
def test_no_raw_interpolation_of_server_strings_into_innerhtml(html: str) -> None:
    # Pattern: innerHTML = `...${field}...` where field is a known
    # server-sourced value. False positives are OK — if the match is
    # legitimately safe (e.g. already-escaped), the offending line can
    # be moved out of innerHTML or an allowlist added.
    risky_fields = ["r.label", "r.detail", "latest.run_id", "r.strategy_name", "tradelabName"]
    pat = re.compile(
        r"\.innerHTML\s*=\s*`[^`]*\$\{(" + "|".join(re.escape(f) for f in risky_fields) + r")\}",
        re.DOTALL,
    )
    matches = pat.findall(html)
    # Known-safe exceptions (escapeHtml-wrapped). If you match one of these,
    # verify the surrounding code really does escape.
    # Currently: none — v2 ship removed them all.
    assert not matches, (
        f"Raw server-string interpolation into innerHTML detected for: {matches}. "
        f"Use textContent or escapeHtml()."
    )


# ── PREFLIGHT_KEYS constant used by both JS iteration and HTML chips ──
def test_preflight_keys_constant_defined_and_used(html: str) -> None:
    decl = re.search(r"const\s+PREFLIGHT_KEYS\s*=\s*\[", html)
    usage = re.search(r"for\s*\(\s*const\s+\w+\s+of\s+PREFLIGHT_KEYS\s*\)", html)
    assert decl, "PREFLIGHT_KEYS constant declaration missing"
    assert usage, "PREFLIGHT_KEYS constant declared but not iterated over"
