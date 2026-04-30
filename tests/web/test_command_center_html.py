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
    "patchCard",
    "bindRowActions",
    "bindQuantityEdit",
    "openDeleteModal",
    "renderOverridesDrawer",
    "saveOverrides",
    "loadSettings",
    "saveSettings",
    "testChannel",
    "subscribeBrowserToasts",
    "fetchSilenceStatus",
    "refreshSilentPills",
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


def test_lt_delete_modal_uses_show_class_pattern(html: str) -> None:
    """openDeleteModal/closeDeleteModal must toggle the .show class.

    Regression: T12 originally used dialog.hidden = false/true which was
    silently overridden by the existing .dialog{display:none} CSS rule.
    The dialog stayed invisible even when "opened" — every trash click
    ran the handler but produced no visible UI, and the user had no way
    to confirm or cancel a delete. Other dialogs (flattenDialog,
    emergencyDialog) use classList.add('show') / .remove('show'); the
    delete modal must follow the same pattern.
    """
    open_idx = html.index("function openDeleteModal")
    close_idx = html.index("function closeDeleteModal", open_idx)
    open_body = html[open_idx:close_idx]

    next_fn = re.search(r"function\s+\w+\s*\(", html[close_idx + 25:])
    close_body = html[close_idx:close_idx + 25 + (next_fn.start() if next_fn else 200)]

    assert "classList.add('show')" in open_body, (
        "openDeleteModal must use classList.add('show') — bare .hidden=false "
        "is overridden by .dialog{display:none} CSS"
    )
    assert "ltDeleteDialog').hidden = false" not in open_body, (
        "openDeleteModal must not toggle the [hidden] attribute on the dialog"
    )
    assert "classList.remove('show')" in close_body, (
        "closeDeleteModal must use classList.remove('show')"
    )
    assert "ltDeleteDialog').hidden = true" not in close_body, (
        "closeDeleteModal must not toggle the [hidden] attribute on the dialog"
    )


def test_overrides_drawer_has_all_four_fields(html: str) -> None:
    """The 4 fields the PATCH endpoint accepts must each be bound by
    data-field=. A silent rename in renderOverridesDrawer breaks PATCH
    silently; pin the contract."""
    for field in ("allow_collision", "allow_naked_short",
                  "daily_limit", "cooldown_seconds"):
        assert f'data-field="{field}"' in html, \
            f"renderOverridesDrawer missing data-field={field!r}"


def test_overrides_drawer_uses_open_class_pattern(html: str) -> None:
    """saveOverrides toggles the .open class — same pattern as the
    delete modal's .show class. Pin that the CSS rule + the toggle
    name still agree (regression on Slice 2 modal-CSS bug)."""
    assert ".lt-overrides-drawer.open" in html, \
        "lt-overrides-drawer.open CSS rule missing"
    assert "classList.toggle('open')" in html, \
        "drawer toggle handler not using .open class"


def test_lt_settings_block_present_with_required_sections(html: str) -> None:
    """Settings panel block + 4 sections render in the markup."""
    assert 'id="lt-settings"' in html
    for section in ("notifications", "silence", "guardrails", "email_digest"):
        assert f'data-section="{section}"' in html


def test_lt_settings_has_test_button_per_channel(html: str) -> None:
    for channel in ("browser", "windows_toast", "audible", "ntfy", "email"):
        assert f'data-channel="{channel}"' in html


def test_lt_settings_severity_matrix_complete(html: str) -> None:
    """3 severities × 5 channels = 15 routing checkboxes."""
    import re
    matches = re.findall(r'data-config="notifications\.severity_routing\.(critical|warning|info)" value="(\w+)"', html)
    assert len(matches) == 15
    by_sev = {}
    for sev, chan in matches:
        by_sev.setdefault(sev, set()).add(chan)
    assert by_sev["critical"] == {"browser", "windows_toast", "audible", "ntfy", "email"}
    assert by_sev["warning"] == {"browser", "windows_toast", "audible", "ntfy", "email"}
    assert by_sev["info"] == {"browser", "windows_toast", "audible", "ntfy", "email"}


def test_lt_settings_save_button_present(html: str) -> None:
    assert 'id="lt-settings-save"' in html
    assert 'id="lt-settings-status"' in html


def test_lt_toast_container_styles_present(html: str) -> None:
    """CSS for #lt-toast-container + .lt-toast severity variants must be in the embedded <style>."""
    assert "#lt-toast-container" in html
    assert ".lt-toast.critical" in html
    assert ".lt-toast.warning" in html
    assert ".lt-toast.info" in html


# ── Slice 5: silence detection FE contracts ────────────────────────


def test_lt_row_template_injects_data_silent_attribute(html: str) -> None:
    """Slice 5 T9: outer .lt-row must inject data-silent dynamically from silentSet
    so the amber pill CSS rule has an anchor to attach to."""
    assert 'data-silent="${silentSet.has(card.card_id) ? \'true\' : \'false\'}"' in html, (
        ".lt-row template must inject data-silent dynamically from silentSet "
        "(both 'true' and 'false' cases) — Slice 5 T9 contract"
    )


def test_amber_silent_pill_css_targets_lt_pill_descendant(html: str) -> None:
    """Slice 5 T9 + T9-fix: CSS rule must anchor on .lt-pill descendant inside
    the silent row, not on the .lt-row itself (the row is a 12-col CSS grid;
    pseudo-element on the row container becomes a phantom 13th grid item)."""
    assert '.lt-row[data-silent="true"] .lt-pill::after' in html, (
        "amber pill CSS rule must target .lt-row[data-silent='true'] .lt-pill::after "
        "(NOT .lt-row[data-silent='true']::after — that would create a phantom grid item)"
    )


def test_subscribe_browser_toasts_calls_refresh_silent_pills(html: str) -> None:
    """Slice 5 T9-fix: SSE notify handler must call refreshSilentPills (diff-update),
    NOT fetchAndRender (full innerHTML rebuild that destroys inline-edit state)."""
    idx = html.find("function subscribeBrowserToasts")
    assert idx >= 0, "subscribeBrowserToasts function not found"
    # Look at the function body (next ~3000 chars).
    chunk = html[idx:idx + 3000]
    assert "refreshSilentPills()" in chunk, (
        "subscribeBrowserToasts SSE handler must call refreshSilentPills() to "
        "diff-update silent pills without rebuilding the LT row list"
    )


def test_fetch_and_render_calls_silence_status_first(html: str) -> None:
    """Slice 5 T9: fetchAndRender must call fetchSilenceStatus() BEFORE the
    /tradelab/cards fetch so silentSet is fresh when renderRow reads it."""
    idx = html.find("async function fetchAndRender")
    assert idx >= 0, "fetchAndRender function not found"
    # Examine the function body — first ~1500 chars cover the body
    chunk = html[idx:idx + 1500]
    silence_pos = chunk.find("fetchSilenceStatus()")
    cards_pos = chunk.find("/tradelab/cards")
    assert silence_pos >= 0, "fetchAndRender must call fetchSilenceStatus()"
    assert cards_pos >= 0, "fetchAndRender must fetch /tradelab/cards"
    assert silence_pos < cards_pos, (
        "fetchAndRender must call fetchSilenceStatus() BEFORE fetching /tradelab/cards "
        "so silentSet is fresh when renderRow reads it"
    )


def test_amber_silent_pill_css_has_visible_content(html: str) -> None:
    """The ::after content must produce visible text — an empty or missing
    content would make the pill invisible without breaking the selector test."""
    assert 'content: "● silent"' in html or "content: '● silent'" in html, (
        "amber pill ::after must set content to '● silent' (otherwise pill renders empty)"
    )


# ── Slice 0.5: canary integrity panel + accept-block ───────────────


def test_canary_panel_dom_present(html: str) -> None:
    """The Research tab must contain the canary panel container so the
    JS has a render target to mount the 4 cells into."""
    assert 'id="canary-panel"' in html, (
        "Slice 0.5 canary panel container missing — researchLoadAll() will "
        "have nowhere to render run_canary_check() output."
    )
    assert 'id="canary-grid"' in html, (
        "Slice 0.5 canary-grid render target missing — renderCanaryGrid() "
        "needs this element to inject the 4 canary cells into."
    )


def test_canary_accepts_blocked_css_rule_present(html: str) -> None:
    """body.accepts-blocked must disable every .accept button. This is the
    actual safety mechanism — if any canary is MISMATCH the user must NOT
    be able to push a freshly-evaluated strategy live until the engine is
    investigated. Visually-only opacity isn't enough; pointer-events:none
    is what stops the click from firing."""
    assert "body.accepts-blocked" in html, (
        "Slice 0.5 accepts-blocked CSS rule missing — without it, a "
        "MISMATCH canary won't actually disable Accept buttons; the panel "
        "will go red but the safety gate is open."
    )
    # Both opacity and pointer-events must be in the rule body or its block.
    # Match the rule and require pointer-events:none somewhere in its body.
    m = re.search(
        r"body\.accepts-blocked[^{]*\{[^}]*pointer-events\s*:\s*none[^}]*\}",
        html,
        re.DOTALL,
    )
    assert m, (
        "body.accepts-blocked must set pointer-events:none on accept buttons "
        "(opacity alone leaves them clickable)."
    )


def test_load_canary_status_function_defined(html: str) -> None:
    """loadCanaryStatus must exist exactly once and must fetch the
    canary-status endpoint. Pin both the function name (researchLoadAll
    references it) and the URL (the backend route it calls)."""
    pattern = re.compile(r"(?:async\s+)?function\s+loadCanaryStatus\s*\(", re.MULTILINE)
    assert len(pattern.findall(html)) == 1, "loadCanaryStatus must be defined exactly once"
    assert "/tradelab/canary-status" in html, (
        "loadCanaryStatus must call the /tradelab/canary-status endpoint"
    )


def test_render_canary_grid_function_defined(html: str) -> None:
    """renderCanaryGrid must exist exactly once and must toggle the
    accepts-blocked class on body. The toggle is the actual safety
    behavior — a silent rename here disables the gate."""
    pattern = re.compile(r"(?:async\s+)?function\s+renderCanaryGrid\s*\(", re.MULTILINE)
    assert len(pattern.findall(html)) == 1, "renderCanaryGrid must be defined exactly once"
    # Make sure the accepts-blocked class is referenced from JS, not just CSS.
    assert "accepts-blocked" in html
    # Must do both add and remove (toggle), otherwise once blocked it stays
    # blocked even after the engine is investigated and canaries return MATCH.
    assert "classList.add('accepts-blocked')" in html or 'classList.add("accepts-blocked")' in html
    assert "classList.remove('accepts-blocked')" in html or 'classList.remove("accepts-blocked")' in html


def test_canary_panel_wired_into_research_load(html: str) -> None:
    """researchLoadAll must call loadCanaryStatus so the panel populates
    when the Research tab activates. Without this wiring the panel renders
    skeleton-only forever and the safety gate never engages."""
    idx = html.find("async function researchLoadAll")
    assert idx >= 0, "researchLoadAll function not found"
    chunk = html[idx:idx + 2000]
    assert "loadCanaryStatus(" in chunk, (
        "researchLoadAll must invoke loadCanaryStatus() so the canary panel "
        "populates when the Research tab activates."
    )


# ─── Research v3 scope (Task 7) ────────────────────────────────────────


def test_v3_google_fonts_link_present(html: str) -> None:
    """Editorial typography requires Fraunces (display), Geist (sans),
    JetBrains Mono. The Google Fonts <link> must be in <head>."""
    head_close = html.find("</head>")
    assert head_close > 0
    head = html[:head_close]
    assert "fonts.googleapis.com" in head, "Google Fonts <link> missing from <head>"
    for family in ("Fraunces", "Geist", "JetBrains+Mono"):
        assert family in head, f"font family {family!r} missing from Google Fonts URL"


def test_v3_scope_style_block_present(html: str) -> None:
    """The research-v3 CSS lives in its own <style id='research-v3-scope'>
    block so future edits don't tangle with the existing dashboard styles."""
    assert 'id="research-v3-scope"' in html, "research-v3-scope <style> block missing"


def test_v3_palette_variables_defined_under_body_scope(html: str) -> None:
    """Variables MUST be scoped to body.research-v3, not :root, so the rest
    of the dashboard's palette is unchanged. Checks a sample of the palette
    + each font-family token."""
    idx = html.find("body.research-v3 {")
    assert idx > 0, "body.research-v3 variable block missing"
    block = html[idx:idx + 3000]
    for token in (
        "--r3-bg:", "--r3-accent:", "--r3-green:", "--r3-red:", "--r3-amber:",
        "--r3-font-display:", "--r3-font-sans:", "--r3-font-mono:",
    ):
        assert token in block, f"palette/font token {token!r} missing from v3 scope"


def test_v3_scope_does_not_leak_root_variable_names(html: str) -> None:
    """Existing dashboard's :root vars (--bg, --green, etc.) MUST NOT be
    redefined by the v3 scope — that would change every other tab's colors.
    All v3 vars are prefixed with --r3-*."""
    idx = html.find('id="research-v3-scope"')
    assert idx > 0
    end = html.find("</style>", idx)
    block = html[idx:end]
    # Anything inside the v3 scope that defines --bg / --green / --red without
    # the r3- prefix would clobber the dashboard. (Comments and selectors
    # mentioning these names elsewhere are fine; we look for declarations.)
    for forbidden in ("--bg:", "--green:", "--red:", "--amber:", "--text:"):
        assert forbidden not in block, (
            f"v3 scope must not redefine global {forbidden!r}; use --r3-* prefix"
        )


def test_v3_body_class_toggle_in_switch_tab(html: str) -> None:
    """switchTab must add 'research-v3' to the body class only when the
    Research tab is active, and remove it on every other tab."""
    idx = html.find("function switchTab")
    assert idx > 0, "switchTab function not found"
    chunk = html[idx:idx + 4000]
    # The toggle pattern: classList.toggle('research-v3', tabName === 'research')
    assert "research-v3" in chunk, "switchTab does not reference research-v3 class"
    assert "tabName === 'research'" in chunk or "tabName==='research'" in chunk, (
        "switchTab must gate the research-v3 body class on tabName === 'research'"
    )


# ─── Action bar (Task 8) ───────────────────────────────────────────────


def test_action_bar_preserves_protected_button_ids(html: str) -> None:
    """Existing v2 click handlers bind to the camelCase button IDs. Renaming
    them (which the plan body suggested) would break Refresh Data, New
    Strategy, and Score modal triggers. Buttons keep IDs; CSS class flips
    to ab-btn / ab-btn primary."""
    for btn_id in ("preflightRefreshBtn", "preflightNewStrategyBtn", "scoreNewStrategyBtn"):
        assert f'id="{btn_id}"' in html, f"protected button ID {btn_id!r} missing"


def test_action_bar_preserves_preflight_chip_ids(html: str) -> None:
    """Preflight chip IDs are read by researchLoadPreflight() and the
    PREFLIGHT_KEYS table. Note: the plan body wrote preflight-strategies
    (plural) but the actual existing ID is preflight-strategy (singular).
    Singular wins; that's the one the JS handler keys off."""
    for chip_id in (
        "preflight-universe", "preflight-cache", "preflight-strategy", "preflight-tdapi",
    ):
        assert f'id="{chip_id}"' in html, f"protected preflight chip ID {chip_id!r} missing"


def test_action_bar_uses_v3_classes_on_protected_buttons(html: str) -> None:
    """Protected buttons MUST use v3 .ab-btn class so the editorial styling
    applies. Refresh Data is the primary action so it gets .ab-btn.primary."""
    refresh_idx = html.find('id="preflightRefreshBtn"')
    assert refresh_idx > 0
    refresh_tag = html[refresh_idx - 200:refresh_idx + 200]
    assert "ab-btn primary" in refresh_tag, (
        "preflightRefreshBtn must carry the v3 .ab-btn.primary class"
    )
    for btn_id in ("preflightNewStrategyBtn", "scoreNewStrategyBtn"):
        idx = html.find(f'id="{btn_id}"')
        tag = html[idx - 200:idx + 200]
        assert "ab-btn" in tag, f"{btn_id} missing .ab-btn class"


def test_action_bar_has_calibration_trust_chip(html: str) -> None:
    """New chip carrying the 0..1 trust score derived from
    /tradelab/calibration-summary."""
    assert 'id="calibration-trust"' in html
    # Helper that fills the chip must exist.
    assert "function updateCalibrationTrustChip" in html, (
        "updateCalibrationTrustChip function missing — chip never populates"
    )
    # And it must be invoked from loadCalibrationSummary so it actually fires.
    cs_idx = html.find("async function loadCalibrationSummary")
    assert cs_idx > 0
    chunk = html[cs_idx:cs_idx + 2500]
    assert "updateCalibrationTrustChip(" in chunk, (
        "loadCalibrationSummary must invoke updateCalibrationTrustChip"
    )


def test_action_bar_has_canary_status_icon(html: str) -> None:
    """⚠ icon hidden by default; renderCanaryGrid toggles it visible when
    any canary status === 'MISMATCH'. Hidden attribute must be present at
    page load (no flash of warning before data resolves)."""
    icon_idx = html.find('id="canary-status-icon"')
    assert icon_idx > 0
    icon_tag = html[icon_idx - 200:icon_idx + 200]
    assert "hidden" in icon_tag, "canary-status-icon must start hidden"
    assert "canary-icon" in icon_tag, "canary-status-icon must carry .canary-icon class"
    # And renderCanaryGrid must toggle it. Read until the next function so
    # we don't accidentally exclude code at the end of the function.
    rg_idx = html.find("function renderCanaryGrid")
    assert rg_idx > 0
    end = html.find("\n    function ", rg_idx + 30)
    if end < 0:
        end = rg_idx + 6000
    chunk = html[rg_idx:end]
    assert "canary-status-icon" in chunk, (
        "renderCanaryGrid must reference the new icon to toggle visibility"
    )
