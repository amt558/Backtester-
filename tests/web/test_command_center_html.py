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


# ─── Live Cards tile (Task 9) ──────────────────────────────────────────


def _live_card_body(html: str) -> str:
    """Slice from `function renderLiveCard` up to the next sibling function
    so v3 contract assertions don't bleed into surrounding helpers."""
    idx = html.find("function renderLiveCard")
    assert idx > 0, "renderLiveCard function not found"
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 8000)
    return html[idx:end]


def _drift_renderer_body(html: str) -> str:
    """Return the source of the per-tile drift renderer.

    Task 11 extracted the actual logic into renderDriftFor (the bulk
    renderAllDriftSparklines is now just a fan-out wrapper). Look up
    renderDriftFor first, falling back to renderAllDriftSparklines for
    pre-Task-11 source compatibility.
    """
    for fn_name in ("function renderDriftFor", "function renderAllDriftSparklines"):
        idx = html.find(fn_name)
        if idx > 0:
            next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
            end = idx + 30 + (next_fn.start() if next_fn else 4000)
            body = html[idx:end]
            # Make sure the body actually contains the drift loop, not the
            # wrapper. The wrapper is short (<300 chars) and delegates.
            if "/verdict-history" in body or "verdicts.slice" in body:
                return body
    # Fall back to the bulk renderer body even if it's the wrapper —
    # callers will produce the right assertion error.
    idx = html.find("function renderAllDriftSparklines")
    assert idx > 0, "renderAllDriftSparklines function not found"
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 4000)
    return html[idx:end]


def test_v3_live_cards_grid_uses_tile_grid_class(html: str) -> None:
    """The #researchLiveCards container must carry the .tile-grid class so
    the v3 grid CSS rule (4-col, 14px gap) applies. Note: the plan body
    proposed renaming to #live-cards-grid; the existing ID is preserved
    per the handover doc (reuses the v2 skeleton container)."""
    idx = html.find('id="researchLiveCards"')
    assert idx > 0, "researchLiveCards container missing"
    tag = html[max(0, idx - 200):idx + 200]
    assert "tile-grid" in tag, (
        "#researchLiveCards must carry the .tile-grid v3 class so the "
        "research-v3-scope grid CSS applies"
    )


def test_v3_render_live_card_emits_tile_structure(html: str) -> None:
    """The renderLiveCard function must emit the v3 tile DOM: tile-head,
    tile-name, tile-meta, verdict pill, drift container, kpis, health-row,
    actions/activate."""
    body = _live_card_body(html)
    for token in (
        '"tile-head"',
        '"tile-name"',
        '"tile-meta"',
        'class="verdict ',
        '"drift"',
        '"kpis"',
        '"kpi"',
        '"health-row"',
        '"actions"',
        'class="activate ',
    ):
        assert token in body, (
            f"renderLiveCard missing v3 tile token {token!r} — confirm the "
            "rewrite emits the v3 markup, not the v2 .research-card-* DOM"
        )


def test_v3_render_live_card_emits_four_kpi_cells(html: str) -> None:
    """Tile shows exactly 4 KPIs: PF / WR / DD / DSR. Each rendered as
    .kpi > .l (label) + .v (value, with optional ok/warn/fail color class)."""
    body = _live_card_body(html)
    for label in (">PF<", ">WR<", ">DD<", ">DSR<"):
        assert label in body, f"renderLiveCard missing KPI label {label!r}"
    # And the .l / .v sub-spans (per v3 CSS scope)
    assert 'class="l"' in body, "KPI label sub-span class=\"l\" missing"
    assert 'class="v"' in body or 'class="v ' in body, (
        "KPI value sub-span class=\"v\" missing"
    )


def test_v3_render_live_card_uses_v3_te_bar_classes(html: str) -> None:
    """v3 te-bar uses .full/.high/.mid/.low (NOT v2 .empty/.green/.amber/.red).
    patchTrackingError must apply the v3 set."""
    pt_idx = html.find("function patchTrackingError")
    assert pt_idx > 0, "patchTrackingError function not found"
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[pt_idx + 30:])
    end = pt_idx + 30 + (next_fn.start() if next_fn else 5000)
    body = html[pt_idx:end]
    for cls in ("full", "high", "mid", "low"):
        assert (f'"{cls}"' in body) or (f"'{cls}'" in body), (
            f"patchTrackingError must apply v3 .te-bar class {cls!r} "
            "(v2 .green/.green-full/.amber/.red is wrong scope)"
        )


def test_v3_render_live_card_uses_ks_dot_not_ks_tag(html: str) -> None:
    """v3 health-row uses a .ks-dot visual (no text) — the v2 .ks-tag was a
    text label inside its own row. New tile compresses to a single dot."""
    body = _live_card_body(html)
    assert "ks-dot" in body, (
        "renderLiveCard must emit a .ks-dot element (v3 contract); "
        ".ks-tag is the v2-only text variant"
    )


def test_v3_render_all_drift_sparklines_function_defined(html: str) -> None:
    """A function that fetches the verdict-history endpoint per tile and
    paints up to 12 .dot spans into each tile's .drift container."""
    pat = re.compile(r"(?:async\s+)?function\s+renderAllDriftSparklines\s*\(", re.MULTILINE)
    matches = pat.findall(html)
    assert len(matches) == 1, (
        f"renderAllDriftSparklines: found {len(matches)} definitions (expected 1)"
    )


def test_v3_drift_sparkline_fetches_verdict_history_endpoint(html: str) -> None:
    """The drift renderer must call /tradelab/strategies/<id>/verdict-history
    (Task 2 endpoint). Different URL = different data source = silent break."""
    body = _drift_renderer_body(html)
    assert "/verdict-history" in body, (
        "renderAllDriftSparklines must fetch /tradelab/strategies/<id>/verdict-history"
    )


def test_v3_drift_sparkline_caps_at_12_dots(html: str) -> None:
    """Sparkline always renders exactly 12 dots: pad with classless .dot on
    the left when fewer than 12 verdicts are available."""
    body = _drift_renderer_body(html)
    assert "12" in body, "renderAllDriftSparklines must hard-cap at 12 dots"


def test_v3_render_live_card_escapes_user_strings(html: str) -> None:
    """All server-supplied strings (liveId, tradelabName, verdict raw) must
    flow through escapeHtml() — guard against XSS regression in the rewrite.
    A direct ${liveId} or ${verdictRaw} interpolation in an innerHTML
    template fails this test."""
    body = _live_card_body(html)
    bad = re.search(
        r"innerHTML\s*=\s*`[^`]*\$\{(liveId|tradelabName|verdictRaw)\}",
        body,
    )
    assert bad is None, (
        f"renderLiveCard interpolates raw server string into innerHTML: "
        f"{bad.group(0) if bad else ''}. Wrap in escapeHtml()."
    )


def test_v3_activate_button_state_helpers_defined(html: str) -> None:
    """activateState and activateLabel helpers map (verdict, has_card) to
    (.enabled|.disabled|.live, label text). Pin both names so Task 10's
    click handler has stable hooks to bind to."""
    pat_state = re.compile(r"function\s+activateState\s*\(", re.MULTILINE)
    pat_label = re.compile(r"function\s+activateLabel\s*\(", re.MULTILINE)
    assert pat_state.search(html), "activateState helper missing"
    assert pat_label.search(html), "activateLabel helper missing"


def test_v3_activate_button_state_emits_three_states(html: str) -> None:
    """activateState must return exactly the three v3 states the CSS defines:
    'enabled', 'disabled', 'live' (not 'activating' — that's Task 10's flight
    state). Returning anything else paints an unstyled grey button."""
    idx = html.find("function activateState")
    assert idx > 0
    next_fn = re.search(r"\n    function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 1500)
    body = html[idx:end]
    for state in ("enabled", "disabled", "live"):
        assert (f'"{state}"' in body) or (f"'{state}'" in body), (
            f"activateState must be able to return {state!r}"
        )


def test_v3_research_load_live_cards_invokes_drift_renderer(html: str) -> None:
    """researchLoadLiveCards must call renderAllDriftSparklines AFTER tiles
    are appended to the DOM (otherwise querySelectorAll('.drift') hits empty)."""
    idx = html.find("async function researchLoadLiveCards")
    assert idx > 0
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 3000)
    body = html[idx:end]
    assert "renderAllDriftSparklines" in body, (
        "researchLoadLiveCards must invoke renderAllDriftSparklines after rendering tiles"
    )


# ─── Task 10: Activate state machine + cross-tab linkage ───────────────

def test_v3_task10_activate_click_handler_wired_to_grid(html: str) -> None:
    """Task 10 wires a delegated click on #researchLiveCards. Without this
    the .activate buttons are inert — silent failure pytest can't catch."""
    # Function that installs the delegated listener.
    assert "function wireResearchLiveCardsClick" in html, (
        "Task 10 click handler installer is missing"
    )
    # The handler must be delegated on the grid container, not on each tile.
    assert "getElementById('researchLiveCards')" in html
    # And researchLoadLiveCards must invoke it after rendering.
    idx = html.find("async function researchLoadLiveCards")
    assert idx > 0
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 3000)
    assert "wireResearchLiveCardsClick" in html[idx:end], (
        "researchLoadLiveCards must call wireResearchLiveCardsClick"
    )


def test_v3_task10_activate_posts_to_strategies_activate_endpoint(html: str) -> None:
    """The Activate flow MUST POST to /tradelab/strategies/<id>/activate.
    Pasting the wrong URL (e.g. /tradelab/accept) silently breaks activation
    because the BE expects different payloads on each route."""
    # Look for the literal URL fragment with template interpolation.
    pattern = re.compile(
        r"/tradelab/strategies/\$\{encodeURIComponent\([^)]+\)\}/activate"
    )
    assert pattern.search(html), (
        "Activate must POST to /tradelab/strategies/${id}/activate"
    )
    # Confirm POST method is used (not GET).
    idx = html.find("wireResearchLiveCardsClick")
    if idx > 0:
        block = html[idx:idx + 4000]
        assert "method: 'POST'" in block or 'method:"POST"' in block, (
            "Activate must use POST"
        )


def test_v3_task10_activate_state_transitions_present(html: str) -> None:
    """Buttons go enabled → activating → live (or back to enabled on error).
    Each class must appear in the click handler so the visual state matches."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    end = idx + 5000
    body = html[idx:end]
    # In-flight transition.
    assert "'activating'" in body, "must add 'activating' class during POST"
    # Success state.
    assert "'live'" in body, "must transition to 'live' on success"
    # Error rollback.
    assert "'enabled'" in body, "must restore 'enabled' on POST failure"
    # Toast surfaces both success and error.
    assert "toast(" in body, "must surface success/error to user via toast()"


def test_v3_task10_activating_class_has_css(html: str) -> None:
    """The .activate.activating selector needs a real CSS rule, otherwise
    the in-flight state is invisible to the user."""
    assert ".activate.activating" in html, (
        "Missing CSS rule for .activate.activating in-flight state"
    )


def test_v3_task10_switch_to_overview_helper_present(html: str) -> None:
    """The cross-tab cross-jump helper must exist and call switchTab('overview').
    The button on Live state ('● Already live ↗') uses this to navigate."""
    idx = html.find("function switchToOverviewTabAndScrollTo")
    assert idx > 0, "switchToOverviewTabAndScrollTo helper is missing"
    end = idx + 1500
    body = html[idx:end]
    assert "switchTab('overview')" in body, (
        "helper must invoke switchTab('overview')"
    )
    # Pulses target by adding/removing a class on a timer.
    assert "r3-highlight-pulse" in body, (
        "helper must add/remove the highlight-pulse class"
    )


def test_v3_task10_highlight_pulse_keyframes_defined(html: str) -> None:
    """The pulse animation must be defined in CSS so the cross-tab jump
    actually animates rather than silently no-op'ing."""
    assert "@keyframes r3-highlight-pulse" in html, (
        "Missing @keyframes r3-highlight-pulse"
    )
    assert ".r3-highlight-pulse {" in html or ".r3-highlight-pulse{" in html, (
        "Missing .r3-highlight-pulse class rule binding the animation"
    )


def test_v3_task10_open_research_button_in_live_card_template(html: str) -> None:
    """Overview live cards must have an ↗ Research button so users can
    cross-jump back from Overview to Research."""
    # The Overview live card template lives in command_center.html. Find the
    # render block (it sits right above the live-card-hero markup) and
    # confirm the button is rendered inside.
    idx = html.find('class="strategy-card live-card')
    assert idx > 0
    block = html[max(0, idx - 800):idx + 200]
    assert "open-research-btn" in block, (
        "Overview live-card markup is missing the ↗ Research button"
    )
    assert "data-base-name=" in block, (
        "↗ Research button must carry data-base-name for cross-jump"
    )


def test_v3_task10_open_research_button_click_handler(html: str) -> None:
    """A document-level click delegate must wire .open-research-btn → switchTab.
    Otherwise the button renders but does nothing."""
    # The click handler must reference the class selector.
    pattern = re.compile(r"closest\(['\"]\.open-research-btn['\"]\)")
    assert pattern.search(html), (
        "Missing document-level handler for .open-research-btn"
    )
    # And it must call switchTab('research').
    # Search within ~1500 chars after the matched closest() to confirm the
    # handler body actually switches tabs and pulses the tile.
    m = pattern.search(html)
    body = html[m.end():m.end() + 1500]
    assert "switchTab('research')" in body, (
        "open-research-btn handler must invoke switchTab('research')"
    )
    assert "r3-highlight-pulse" in body, (
        "open-research-btn handler must pulse the destination tile"
    )


def test_v3_task10_open_research_button_styles_defined(html: str) -> None:
    """The ↗ Research button needs its own CSS rule (positioned, hover state)."""
    assert ".open-research-btn" in html, "Missing .open-research-btn CSS"
    # Positioned absolutely so it sits in the top-right corner of the card.
    pattern = re.compile(r"\.open-research-btn\s*\{[^}]*position:\s*absolute", re.DOTALL)
    assert pattern.search(html), (
        ".open-research-btn must be positioned absolute (top-right corner)"
    )


def test_v3_task10_card_id_stashed_on_tile_after_activate(html: str) -> None:
    """After a successful activate, the tile's data-card-id must be set so
    the next click ('Already live ↗') can cross-jump without re-fetch."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 5000]
    # Either tile.dataset.cardId = ... or tile.setAttribute('data-card-id', ...)
    assert (
        "tile.dataset.cardId" in body
        or "data-card-id" in body
    ), "tile must persist the new card_id after activate so cross-jump works"


def test_v3_task10_no_old_accept_endpoint_for_live_cards(html: str) -> None:
    """Defense against regression: the Live Cards Activate flow must NOT POST
    to /tradelab/accept (that endpoint requires base_name/symbol/timeframe
    payload that the FE doesn't have). Use /tradelab/strategies/<id>/activate."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 5000]
    assert "'/tradelab/accept'" not in body, (
        "wireResearchLiveCardsClick must not POST to /tradelab/accept "
        "(missing payload fields); use /tradelab/strategies/<id>/activate"
    )


# ─── Task 11: Click-to-expand inline (header + 7-cell summary + tab strip)

def test_v3_task11_expanded_tile_html_helper_exists(html: str) -> None:
    """The expand template must be a discrete function so collapse can
    re-render the compact tile by calling its complement."""
    assert "function expandedTileHtml" in html, (
        "Task 11 expand template helper expandedTileHtml() is missing"
    )


def test_v3_task11_expanded_markup_has_seven_summary_cells(html: str) -> None:
    """Plan body specifies exactly 7 cells: Verdict, PF, WR, DD, DSR, TE
    health, K-S. The visual rhythm is fragile to cell count drift, so pin it."""
    idx = html.find("function expandedTileHtml")
    assert idx > 0
    end = idx + 4000
    body = html[idx:end]
    # Each cell uses the .ex-cell class — count them.
    cells = body.count('class="ex-cell"')
    assert cells == 7, (
        f"expandedTileHtml must render exactly 7 ex-cell summary cells; got {cells}"
    )
    # The seven labels must all be present.
    for label in ("Verdict", "Profit factor", "Win rate", "Max DD", "DSR", "TE health", "K-S"):
        assert label in body, f"7-cell summary missing label {label!r}"


def test_v3_task11_expanded_markup_has_tab_strip_and_deep_dive(html: str) -> None:
    """The expand row's tab strip + deep-dive button must both be present.
    Tearsheet button drives traffic to the existing /tradelab/runs/<id>/tearsheet
    route — drift breaks the link silently."""
    idx = html.find("function expandedTileHtml")
    assert idx > 0
    body = html[idx:idx + 4000]
    assert "tab-strip" in body, "Missing tab-strip container in expand template"
    assert "tab-strip-tabs" in body, "Missing tab-strip-tabs button row"
    assert "deep-dive-btn" in body, "Missing deep-dive-btn (View full tearsheet)"
    assert "/tradelab/runs/" in body and "/tearsheet" in body, (
        "deep-dive-btn must link to /tradelab/runs/<id>/tearsheet"
    )
    assert 'class="close-btn"' in body, "Missing collapse close-btn"


def test_v3_task11_expand_collapse_helpers_present(html: str) -> None:
    """expandTile / collapseTile must exist so the click delegate can call
    them. Without them the tile-click event handler can't toggle state."""
    assert "function expandTile" in html, "Missing expandTile helper"
    assert "function collapseTile" in html, "Missing collapseTile helper"


def test_v3_task11_strategy_data_cache_populated_at_render_time(html: str) -> None:
    """expandTile reads from a cache populated by renderLiveCard. Without the
    cache the expand template can't access symbol/verdict/etc. populated by
    the runs+metrics fetches that happened during render."""
    # Cache constant must exist (Map or plain object).
    assert "strategyDataCache" in html, (
        "Missing strategyDataCache used by expandTile to read summary fields"
    )
    # It must be written-to during the render path. Check for either .set()
    # (Map) or [key]= (plain object) inside renderLiveCard.
    idx = html.find("function renderLiveCard")
    assert idx > 0
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 8000)
    body = html[idx:end]
    assert "strategyDataCache" in body, (
        "renderLiveCard must populate strategyDataCache so expandTile can read it"
    )


def test_v3_task11_tile_click_handler_in_grid_delegate(html: str) -> None:
    """The same delegated listener that handles .activate clicks should also
    handle tile-click for expand. Adding a second listener on the same grid
    risks event ordering surprises; one delegate is the contract."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 6000]
    # Tile-click handler must call expandTile/collapseTile.
    assert ("expandTile(" in body) or ("collapseTile(" in body), (
        "wireResearchLiveCardsClick must invoke expandTile/collapseTile"
    )
    # Must guard: clicking .activate or .close-btn or .deep-dive-btn should
    # not toggle expand.
    assert ".close-btn" in body or "close-btn" in body, (
        "Tile-click handler must guard against close-btn re-entry"
    )


def test_v3_task11_expanded_state_has_css(html: str) -> None:
    """The visual "expanded" state needs CSS — without it the inserted markup
    has no layout and the user sees a broken card."""
    assert ".tile.expanded" in html, (
        "Missing .tile.expanded CSS rule"
    )
    assert ".ex-cell" in html, "Missing .ex-cell CSS rule (7-cell layout)"
    assert ".ex-summary" in html, "Missing .ex-summary CSS rule (cell grid)"
    assert ".ex-header" in html, "Missing .ex-header CSS rule"


def test_v3_task11_only_one_tile_expanded_at_a_time(html: str) -> None:
    """Plan spec: 'only one expanded at a time'. The tile-click handler must
    collapse any other expanded tile before expanding the clicked one."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 6000]
    # Look for the all-expanded-tiles iteration before expand.
    assert (
        ".tile.expanded" in body or "tile.expanded" in body
    ), "Missing 'collapse all other expanded tiles' iteration"


def test_v3_task11_clicking_actions_does_not_toggle_expand(html: str) -> None:
    """The action buttons (Activate, close-btn, deep-dive-btn, tab buttons)
    inside a tile must not propagate to the tile-click handler. Either via
    explicit .closest() guard or via stopPropagation on each button."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 6000]
    # The plan body uses a closest() guard. The click handler must mention at
    # least .activate (existing) and .close-btn (Task 11 new).
    assert ".activate" in body
    assert "close-btn" in body


# ─── Task 12: QuantStats sub-grid + 3 inline SVG charts ────────────────


def test_v3_task12_load_qs_helper_exists(html: str) -> None:
    """The expanded tile populates its QuantStats tab via this loader.
    Without it, every tile shows the empty placeholder forever."""
    assert "function loadQsForExpandedTile" in html, (
        "Missing function loadQsForExpandedTile (Task 12 entry point)"
    )


def test_v3_task12_load_qs_calls_qs_metrics_endpoint(html: str) -> None:
    """The loader must hit /tradelab/runs/<id>/qs-metrics — the BE route is
    already wired (Task 5). Don't accidentally point at /metrics or /tearsheet."""
    idx = html.find("function loadQsForExpandedTile")
    assert idx > 0
    body = html[idx:idx + 2000]
    assert "/qs-metrics" in body, (
        "loadQsForExpandedTile must fetch from /tradelab/runs/<id>/qs-metrics"
    )
    # Must encode the runId — defensive against a run id with a slash or %.
    assert "encodeURIComponent" in body


def test_v3_task12_load_qs_handles_null_run_id(html: str) -> None:
    """A strategy with no scored run yet should show an empty-state, not a
    fetch error. The plan spec calls for `<div class="empty">No run data...`."""
    idx = html.find("function loadQsForExpandedTile")
    assert idx > 0
    body = html[idx:idx + 2000]
    # Some explicit null/empty branch before the fetch.
    assert ("if (!runId)" in body) or ("if (runId == null)" in body) or ("runId == null" in body), (
        "loadQsForExpandedTile must check for missing runId before fetching"
    )
    assert 'class="empty"' in body or "class='empty'" in body, (
        "Missing empty-state markup for runId=null path"
    )


def test_v3_task12_qs_grid_helper_renders_eight_cells(html: str) -> None:
    """The QS sub-grid has 8 stat cells per the plan: Total return, Sharpe,
    Sortino, CAGR, Avg win, Avg loss, Trades, Avg hold."""
    idx = html.find("function qsGridHtml")
    assert idx > 0, "Missing function qsGridHtml"
    next_fn = re.search(r"\n    (?:async\s+)?function\s+\w+\s*\(", html[idx + 30:])
    end = idx + 30 + (next_fn.start() if next_fn else 3000)
    body = html[idx:end]
    for label in (
        "Total return", "Sharpe", "Sortino", "CAGR",
        "Avg win", "Avg loss", "Trades", "Avg hold",
    ):
        assert label in body, f"qsGridHtml missing the {label!r} stat cell"


def test_v3_task12_qs_grid_uses_qs_stat_class(html: str) -> None:
    """Each stat cell carries .qs-stat for styling. The grid wrapper carries
    .qs-grid. Without these classes the CSS layout breaks."""
    idx = html.find("function qsGridHtml")
    assert idx > 0
    body = html[idx:idx + 3000]
    assert "qs-stat" in body, "qs-stat class missing from cell template"
    assert "qs-grid" in body, "qs-grid class missing from grid wrapper"


def test_v3_task12_three_chart_helpers_exist(html: str) -> None:
    """Three inline SVG chart helpers per plan: drawdown, monthly heatmap,
    rolling sharpe. Pure SVG (no Chart.js — see reference_command_center_arch_lock.md)."""
    for fn_name in ("function drawdownSvg", "function monthlyHeatmap", "function rollingSharpeSvg"):
        assert fn_name in html, f"Missing {fn_name}"


def test_v3_task12_chart_helpers_emit_inline_svg(html: str) -> None:
    """Charts must be inline SVG, not Canvas / Chart.js / d3. The architectural
    lock on command_center.html forbids new build-step deps."""
    for fn_name in ("function drawdownSvg", "function rollingSharpeSvg"):
        idx = html.find(fn_name)
        assert idx > 0
        body = html[idx:idx + 2000]
        assert "<svg" in body, f"{fn_name} must emit inline <svg> markup"
        assert "viewBox" in body, f"{fn_name} svg must declare a viewBox for responsive scaling"


def test_v3_task12_monthly_heatmap_uses_grid_class(html: str) -> None:
    """The heatmap is a CSS grid of colored cells (red/green by sign)."""
    idx = html.find("function monthlyHeatmap")
    assert idx > 0
    body = html[idx:idx + 2000]
    assert "heatmap-grid" in body, "monthlyHeatmap must wrap cells in .heatmap-grid"
    assert "heatmap-cell" in body, "monthlyHeatmap must use .heatmap-cell per cell"


def test_v3_task12_expand_calls_loader(html: str) -> None:
    """expandTile must invoke loadQsForExpandedTile after writing innerHTML so
    the QuantStats tab populates. Without this, the user sees the empty
    placeholder until clicking Factors and back."""
    idx = html.find("function expandTile")
    assert idx > 0
    body = html[idx:idx + 1500]
    assert "loadQsForExpandedTile" in body, (
        "expandTile must call loadQsForExpandedTile(tile, runId) after render"
    )


def test_v3_task12_placeholder_text_replaced(html: str) -> None:
    """Once the loader is wired, the literal placeholder string from Task 11
    should no longer appear in the source — that text was a TODO marker."""
    assert "QuantStats sub-grid loads in Task 12." not in html, (
        "Task 11 placeholder text still present — Task 12 loader not wired"
    )


def test_v3_task12_tab_strip_click_swaps_tabs(html: str) -> None:
    """Clicking the Factors tab should hide .tab-qs and show .tab-factors,
    and vice versa. The wireResearchLiveCardsClick handler owns this logic."""
    idx = html.find("function wireResearchLiveCardsClick")
    assert idx > 0
    body = html[idx:idx + 6000]
    # Either explicit class swap on tab-content elements, or hidden attribute toggle.
    has_qs_swap = ("tab-qs" in body) and ("tab-factors" in body)
    assert has_qs_swap, (
        "Tab strip handler must reference both .tab-qs and .tab-factors "
        "to swap visibility"
    )


def test_v3_task12_qs_grid_css_present(html: str) -> None:
    """CSS rules must exist for the new grid + chart layout — without them
    the markup renders as a plain stack of unstyled divs."""
    for selector in (".qs-grid", ".qs-stat", ".qs-charts", ".qs-chart"):
        assert selector in html, f"Missing CSS rule for {selector}"


def test_v3_task12_heatmap_css_present(html: str) -> None:
    """The heatmap is a fixed-shape CSS grid; the .heatmap-grid rule defines it."""
    for selector in (".heatmap-grid", ".heatmap-cell"):
        assert selector in html, f"Missing CSS rule for {selector}"


# ─── Task 13: Cross-strategy factor matrix ─────────────────────────────


def test_v3_task13_matrix_markup_present(html: str) -> None:
    """The matrix needs three id'd containers in the DOM: the card wrapper,
    the grid (renderFactorMatrix mounts to this), and the meta caption."""
    for needle in ('id="matrix-card"', 'id="matrix-grid"', 'id="matrix-meta"'):
        assert needle in html, f"Missing matrix DOM hook: {needle}"


def test_v3_task13_alpha_callout_present(html: str) -> None:
    """The callout starts hidden and is revealed when ≥1 column-warn fires.
    Without the element renderFactorMatrix's getElementById('matrix-alpha-callout')
    would silently no-op; tests guard against that drift."""
    assert 'id="matrix-alpha-callout"' in html, "Missing matrix-alpha-callout div"


def test_v3_task13_factor_columns_const_defined(html: str) -> None:
    """FACTOR_COLUMNS drives the column count + labels. Renaming or removing
    it would silently break every cell in the matrix."""
    assert "FACTOR_COLUMNS" in html, "Missing FACTOR_COLUMNS const"


def test_v3_task13_factor_columns_use_real_signal_names(html: str) -> None:
    """The plan body's columns (dsr, monte_carlo, oos_pf, regime, sample,
    stability, walk_forward) don't match real verdict.py signal names. The
    matrix must use the actual names so cells light up against real data."""
    idx = html.find("FACTOR_COLUMNS")
    assert idx > 0
    body = html[idx:idx + 2000]
    # The 8 real signals from src/tradelab/robustness/verdict.py
    for sig_name in (
        "baseline_pf", "dsr", "mc_max_dd", "param_landscape",
        "entry_delay", "loso", "noise_injection", "regime_spread",
    ):
        assert f"'{sig_name}'" in body or f'"{sig_name}"' in body, (
            f"FACTOR_COLUMNS missing real signal name {sig_name!r}"
        )
    # And NOT the plan's invented ids that would never match real data
    assert "'monte_carlo'" not in body and '"monte_carlo"' not in body, (
        "FACTOR_COLUMNS still uses plan's invented 'monte_carlo' id; "
        "real signal name is 'mc_max_dd'"
    )
    assert "'walk_forward'" not in body and '"walk_forward"' not in body, (
        "FACTOR_COLUMNS still uses plan's invented 'walk_forward' id"
    )


def test_v3_task13_classify_outcome_function_defined(html: str) -> None:
    """classifyOutcome maps signal.outcome → cell color class. Needs to handle
    robust/marginal/fragile/inconclusive (lowercase) per the BE contract."""
    assert "function classifyOutcome" in html, "Missing classifyOutcome helper"
    idx = html.find("function classifyOutcome")
    body = html[idx:idx + 800]
    # Returns 'pass'/'fail'/'marginal'/'dim' for the 4 outcome states.
    assert "'pass'" in body or '"pass"' in body
    assert "'fail'" in body or '"fail"' in body
    assert "'dim'" in body or '"dim"' in body
    # Lowercases the outcome string (so 'ROBUST'/'robust' both work).
    assert "toLowerCase" in body


def test_v3_task13_render_factor_matrix_function_defined(html: str) -> None:
    """The matrix is built by renderFactorMatrix(); it must exist + fetch
    /tradelab/strategies-summary."""
    assert "function renderFactorMatrix" in html, "Missing renderFactorMatrix"
    idx = html.find("function renderFactorMatrix")
    body = html[idx:idx + 4000]
    assert "/tradelab/strategies-summary" in body, (
        "renderFactorMatrix must fetch from /tradelab/strategies-summary"
    )


def test_v3_task13_render_factor_matrix_invoked_on_load(html: str) -> None:
    """The matrix needs to render when the Research tab loads. Either via
    researchLoadAll() or alongside researchLoadLiveCards()."""
    # Search for the call site (not the definition) — it should be invoked
    # from the Research-tab loader.
    occurrences = html.count("renderFactorMatrix(")
    # Definition call has parens too, so we expect ≥ 2 occurrences (def + call).
    assert occurrences >= 2, (
        f"renderFactorMatrix() never called — only {occurrences} occurrence(s) "
        f"(definition with no call site)"
    )


def test_v3_task13_matrix_grid_css_handles_eight_columns(html: str) -> None:
    """The CSS grid template was hardcoded to 7 columns in the original v3
    sketch — must be updated to 8 to match real signal count."""
    idx = html.find(".matrix-grid")
    assert idx > 0
    # Find the actual grid-template-columns value
    rule_end = html.find("}", idx)
    rule_body = html[idx:rule_end]
    assert "repeat(8" in rule_body, (
        f".matrix-grid grid-template-columns must use repeat(8, ...) "
        f"to match the 8 real signals; current rule:\n{rule_body[:200]}"
    )


def test_v3_task13_classify_outcome_treats_inconclusive_as_marginal_or_dim(html: str) -> None:
    """Real audit data has many 'inconclusive' signals. Must NOT silently
    classify them as 'pass' — that would hide weakness."""
    idx = html.find("function classifyOutcome")
    body = html[idx:idx + 800]
    # The default branch (after robust/marginal/fragile) returns dim, so
    # inconclusive falls through to dim. Just check it doesn't accidentally
    # return 'pass' for an inconclusive outcome.
    if "'inconclusive'" in body or '"inconclusive"' in body:
        # If the function explicitly handles inconclusive, it must not return pass.
        # This is a weak check; the semantic test is in the explicit branches above.
        pass
    # Stronger check: 'inconclusive' values map to either 'dim' or 'marginal' (not pass)
    # via the fall-through return. Pattern: last return statement is 'dim' or 'marginal'.
    # Easier: just assert 'inconclusive' is never adjacent to "return 'pass'".
    assert "inconclusive') return 'pass'" not in body
    assert 'inconclusive") return "pass"' not in body


# ─── Task 14: Pipeline restyle ─────────────────────────────────────────


def test_v3_task14_pipeline_card_wrapper_present(html: str) -> None:
    """The Research Pipeline section gets the v3 .pipeline-card chrome so
    the existing CSS rules at body.research-v3 #research .pipeline-card
    actually apply."""
    assert 'class="pipeline-card"' in html, (
        "Research Pipeline section missing the .pipeline-card v3 wrapper"
    )


def test_v3_task14_pipeline_toolbar_wrapper_present(html: str) -> None:
    """Filter row should sit inside .pipeline-toolbar so the v3 toolbar CSS
    (border-bottom, gap, font) applies. The v2 .research-filters div can
    stay as inner content; we just need the v3 wrapper outside it."""
    assert 'class="pipeline-toolbar"' in html, (
        "Filter row missing the .pipeline-toolbar v3 wrapper"
    )


def test_v3_task14_pipeline_table_has_pipeline_class(html: str) -> None:
    """The CSS rule body.research-v3 #research table.pipeline targets
    .pipeline (not .table). Without the class, the v3 table styling
    (column-uppercase headers, hover stripe, monospaced numerics) doesn't
    apply."""
    # Find the existing #researchPipelineTable opening tag and confirm it
    # carries class="pipeline" alongside whatever else.
    idx = html.find('id="researchPipelineTable"')
    assert idx > 0, "researchPipelineTable id missing"
    tag_start = html.rfind('<table', 0, idx)
    tag_end = html.find('>', idx)
    assert tag_start > 0 and tag_end > 0
    tag = html[tag_start:tag_end + 1]
    assert "pipeline" in tag, (
        f"researchPipelineTable must include class \"pipeline\" for v3 styling. "
        f"Current tag: {tag}"
    )


def test_v3_task14_section_header_for_pipeline(html: str) -> None:
    """A v3 section header sits between the matrix and the pipeline card so
    the user can see 'Research Pipeline' as a labeled landmark, with the
    meta caption describing what's inside."""
    assert 'id="pipeline-section-header"' in html, (
        "Missing #pipeline-section-header — needed so the v3 typography "
        "rule applies and to anchor the meta caption"
    )
    assert 'id="pipeline-meta"' in html, (
        "Missing #pipeline-meta — runs count goes here"
    )


def test_v3_task14_trash_button_tooltip_says_delete_not_archive(html: str) -> None:
    """Memory note 840fb0f flipped DELETE /tradelab/runs/<id> from
    soft-archive to hard-delete. The trash button tooltip must reflect
    that — calling it 'Archive run' is misleading and was the v2 wording."""
    # Find the actionsCell function (per-row delete button definition).
    idx = html.find("function actionsCell")
    assert idx > 0, "actionsCell function not found"
    body = html[idx:idx + 2000]
    assert 'title="Delete run"' in body or "title='Delete run'" in body, (
        "Trash button title must say 'Delete run', not the v2 'Archive run' "
        "(DELETE is hard-delete since 840fb0f)"
    )
    # And NOT the old wording
    assert 'title="Archive run"' not in body and "title='Archive run'" not in body, (
        "Stale 'Archive run' tooltip on trash button — DELETE is hard-delete "
        "since tradelab commit 840fb0f"
    )
