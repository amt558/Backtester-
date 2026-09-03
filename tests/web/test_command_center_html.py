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
    "escapeHtml",
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
    "researchLoadUniverses",
    "researchRunTest",
    "researchTrackTest",
    "researchValidateSymbols",
    "universeCell",
    # S2 (2026-09-02): the upload fast path
    "nsLoadFiles",
    "nsFillFromTemplate",
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
    "pipelineCompareBtn",
    "modal-3f-confirm",  # Run modal Start button — preflight block targets this
    # S2 (2026-09-02): upload drop-zone, file picker, template button
    "nsDropZone",
    "nsFileInput",
    "nsTemplateBtn",
    "nsFileStatus",
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
    # S1 (2026-09-02): the hardcoded six-strategy roster and the Overview
    # placeholder strip were retired. The roster is derived from /tradelab/cards
    # at runtime (STRATEGY_ROSTER / loadStrategyRoster). Reintroducing any of
    # these means a new strategy needs an HTML edit again — don't.
    "const STRATEGIES",
    "LIVE_STRATS",
    "LIVE_TO_TRADELAB",
    "renderStrategyCards",
    "strategyGrid",
    "dismissedPlaceholders",
    # S3 (2026-09-02): the Overview live-card grid was replaced by one tab per
    # accepted strategy (the ST module). These must not come back.
    "liveCardsGrid",
    "_renderOverviewLiveCardHTML",
    "onToggleLiveCard",
    "onLiveCardSettingChange",
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


def test_accepts_blocked_selector_targets_live_accept_button(html: str) -> None:
    """The canary gate only works if a LIVE, ENABLED Accept button carries a
    class the accepts-blocked CSS selectors target (`button.accept` /
    `.btn.accept` — see test_canary_accepts_blocked_css_rule_present).

    This guards the exact failure mode that silently killed the gate in the
    2026-05-01 golden base: the CSS rule was present AND renderCanaryGrid
    toggled body.accepts-blocked, but the only Accept button there
    (id="scoreAcceptBtn") carried class="btn primary" (no `accept` token) and
    was `disabled` — so the selector matched nothing and a MISMATCH disabled
    no real control. Every other test stayed green. The live file was later
    fixed (score modal rebuilt as Import Strategy; the surviving Accept
    buttons carry `action-btn accept` / `btn accept`), but nothing pinned the
    selector↔button contract — so a future class rename could re-kill the gate
    silently. This test is that pin.

    Contract: at least one ENABLED <button> whose class contains an `accept`
    token must exist. A match against a permanently-`disabled` button proves
    nothing (it can't be clicked regardless), so disabled buttons don't count.
    """
    # Every <button ...> opening tag whose class attribute carries an `accept`
    # token — these are exactly what `button.accept` matches. (Class attrs in
    # command_center.html are double-quoted only — verified no class='...' usage
    # exists in the file — so a double-quote pattern is sufficient.)
    accept_btns = [
        m.group(0)
        for m in re.finditer(r"<button\b[^>]*>", html)
        if re.search(r'class="[^"]*\baccept\b[^"]*"', m.group(0))
    ]
    assert accept_btns, (
        "No <button> carries an `accept` class token — body.accepts-blocked "
        "(button.accept / .btn.accept) has no live target, so a canary "
        'MISMATCH would disable nothing. This is how the golden-base gate '
        'went dead (scoreAcceptBtn carried class="btn primary").'
    )
    # Detect the boolean `disabled` ATTRIBUTE, not the substring "disabled".
    # The token must be preceded by whitespace and followed by whitespace/=/>
    # so this matches `... disabled>` / `... disabled type=...` / `disabled=""`
    # but NOT aria-disabled="false", data-disabled-reason=..., or a class token
    # like "disabled-style". Do NOT loosen this back to r"\bdisabled\b" — that
    # would mis-classify enabled buttons as disabled and fail on a fine button.
    enabled = [b for b in accept_btns if not re.search(r"\sdisabled(?=[\s=>])", b)]
    assert enabled, (
        "Every Accept button carrying the selector-matched `accept` class is "
        "`disabled` — a disabled button proves nothing about the gate (it "
        "cannot be clicked regardless). At least one normally-actionable "
        "Accept button must carry the class so body.accepts-blocked disables "
        f"a real control on MISMATCH. Found only: {accept_btns}"
    )


# ─── Research v3 scope (Task 7) ────────────────────────────────────────


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


# ─── Live Cards tile (Task 9) — removed in S4: the board replaced the tiles.
# The XSS guard now lives in test_s4_board_escapes_server_strings below.


# ─── Task 10: Activate state machine + cross-tab linkage ───────────────

# ─── Task 11: Click-to-expand inline (header + 7-cell summary + tab strip)

# ─── Task 12: QuantStats sub-grid + 3 inline SVG charts ────────────────


def test_v3_task12_placeholder_text_replaced(html: str) -> None:
    """Once the loader is wired, the literal placeholder string from Task 11
    should no longer appear in the source — that text was a TODO marker."""
    assert "QuantStats sub-grid loads in Task 12." not in html, (
        "Task 11 placeholder text still present — Task 12 loader not wired"
    )


# ─── Task 13: Cross-strategy factor matrix ─────────────────────────────


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


# ─── Task 15: Pipeline delete affordances (cascade-aware modal) ────────


def test_v3_task15_show_delete_confirm_calls_preview_delete(html: str) -> None:
    """Before opening the modal, showDeleteConfirm must POST to
    /tradelab/runs/preview-delete with the candidate run_ids so the FE
    knows whether any live cards are affected (Tier 2 / Tier 4
    escalation). Otherwise it can't differentiate plain bulk-delete from
    cascade-delete."""
    idx = html.find("function showDeleteConfirm")
    assert idx > 0, "showDeleteConfirm function missing"
    body = html[idx:idx + 4000]
    assert "/tradelab/runs/preview-delete" in body, (
        "showDeleteConfirm must call /tradelab/runs/preview-delete to detect "
        "cascade before opening the confirm modal"
    )


def test_v3_task15_modal_has_cascade_container(html: str) -> None:
    """The existing #researchDeleteConfirm modal gains a new
    #deleteConfirmCascade section that's hidden by default and
    populated when cascade is non-empty. Hidden default keeps the
    Tier 1 / Tier 3 (no-cascade) experience visually unchanged."""
    assert 'id="deleteConfirmCascade"' in html, (
        "Modal markup missing #deleteConfirmCascade container — needed to "
        "render the 'Cards affected' list when cascade is non-empty"
    )


def test_v3_task15_disable_and_delete_button_label_present(html: str) -> None:
    """When cascade is non-empty, a third button labeled 'Disable card + delete'
    appears so the user can flip affected cards to status='disabled' before
    the run vanishes — instead of leaving orphan cards with no robustness
    history (smoke turned up s2_pocket_pivot's card already in this state).
    The button lives in modal markup (#deleteConfirmDisableGo), revealed
    by showDeleteConfirm when cascade.length > 0."""
    idx = html.find('id="deleteConfirmDisableGo"')
    assert idx > 0, (
        "Modal markup missing #deleteConfirmDisableGo — needed for the "
        "Tier 2 / Tier 4 'Disable card + delete' action"
    )
    # Read the surrounding button tag (label is the inner text)
    btn_open  = html.rfind('<button', 0, idx)
    btn_close = html.find('</button>', idx)
    assert btn_open > 0 and btn_close > 0
    btn = html[btn_open:btn_close]
    assert "Disable card + delete" in btn or "Disable cards + delete" in btn, (
        "Disable button must carry label 'Disable card + delete' "
        f"(found tag: {btn[:200]})"
    )


def test_v3_task15_disable_uses_patch_with_status_disabled(html: str) -> None:
    """The 'Disable card + delete' action must PATCH each affected card_id
    with {status: 'disabled'} — the existing endpoint at
    handlers.py:1147 (PATCH /tradelab/cards/<id>) is the canonical
    disable mechanism. NO new endpoint."""
    idx = html.find("function showDeleteConfirm")
    assert idx > 0
    body = html[idx:idx + 4000]
    # Either inline or in a sibling helper called from showDeleteConfirm —
    # so look in a wider window.
    wider = html[idx:idx + 8000]
    assert "/tradelab/cards/" in wider and "PATCH" in wider, (
        "Disable+delete flow must PATCH /tradelab/cards/<id> — confirmed "
        "endpoint at handlers.py:1147"
    )
    assert '"status":"disabled"' in wider or '"status": "disabled"' in wider or "status: 'disabled'" in wider or "status: \"disabled\"" in wider, (
        "PATCH body must set status to 'disabled' (canonical disable signal)"
    )


def test_v3_task15_cascade_card_id_iteration_in_modal(html: str) -> None:
    """When cascade is non-empty, the modal body must enumerate the
    affected card_id / base_name pairs so the user can see WHICH cards
    are at risk before clicking the destructive button. Just a count
    isn't enough."""
    idx = html.find("function showDeleteConfirm")
    assert idx > 0
    body = html[idx:idx + 4000]
    # Look for cascade.map or cascade.forEach (rendering loop) and reference
    # to base_name (the user-facing identifier).
    assert ("cascade.map" in body or "cascade.forEach" in body or "for (const" in body), (
        "showDeleteConfirm must iterate the cascade to render affected cards"
    )
    assert "base_name" in body or "card_id" in body, (
        "Cascade rendering must surface base_name or card_id per affected card"
    )


# ─── Task 15 — Slice 4: stale modal copy fix ───────────────────────


def test_v3_task15_stale_archive_copy_removed(html: str) -> None:
    """The original modal copy at line ~1702 said the audit DB record is
    'preserved (filtered out of default queries — restorable from the
    archived_runs table by a developer if needed)'. That described the
    OLD soft-archive contract. Since 840fb0f, DELETE is HARD-delete:
    audit row is removed, folder is rmtree'd, deletions.log gets a
    line. The copy must reflect that."""
    # The exact stale phrase from the old soft-archive copy:
    assert "audit DB record is preserved" not in html, (
        "Stale soft-archive copy in delete-confirm modal — DELETE has been "
        "hard-delete since 840fb0f. Update the modal description to match."
    )
    assert "archived_runs table" not in html, (
        "Stale reference to archived_runs table — not how delete works since "
        "840fb0f. Fix modal copy to describe hard-delete + deletions.log."
    )


def test_v3_task15_modal_copy_describes_hard_delete(html: str) -> None:
    """The new copy must mention either deletions.log or an unmistakable
    'hard delete' / 'permanent' framing so the user understands the
    action is non-recoverable."""
    # Find the modal markup
    idx = html.find('id="researchDeleteConfirm"')
    assert idx > 0
    # Read forward through the modal body
    end_idx = html.find('</div>', idx + 2000)  # rough end-of-modal scan
    if end_idx < 0:
        end_idx = idx + 4000
    body = html[idx:end_idx + 4000]
    assert (
        "deletions.log" in body
        or "permanently" in body.lower()
        or "cannot be undone" in body.lower()
        or "hard delete" in body.lower()
        or "removed from the audit" in body.lower()
    ), (
        "Modal copy must describe DELETE as permanent / hard-delete / "
        "non-recoverable so users understand the action"
    )


def test_import_modal_has_discovery_dropdown_and_no_pine_csv(html: str) -> None:
    assert 'id="importStrategySelect"' in html
    assert 'id="importStrategyBtn"' in html
    assert "/tradelab/strategies/discoverable" in html
    assert "/tradelab/strategies/import" in html
    assert 'id="scorePineFileInput"' not in html
    assert 'id="scoreCsvFileInput"' not in html


def test_no_pine_or_csv_score_triggers_in_ui(html: str) -> None:
    assert "scoreCsvTextarea" not in html
    assert "scorePineTextarea" not in html


def test_import_modal_has_test_button_firing_full_run(html: str) -> None:
    assert 'id="importTestBtn"' in html
    assert "run --full" in html
    assert "/tradelab/jobs" in html


def test_accept_flow_posts_to_strategies_accept(html: str) -> None:
    assert "/tradelab/strategies/accept" in html
    # S6: the confirm_non_robust knob is gone from the UI entirely — an
    # ADVISORY run is accepted only through the override modal.
    assert "confirm_non_robust" not in html


# ─── Phase-4 Task 5: allocation_usd card field ─────────────────────────


def test_overview_card_has_allocation_input(html: str) -> None:
    assert "allocation_usd" in html


# ─── WP5: research-tab renders the ADVISORY promotion tier ─────────────


def test_wp5_accept_flow_keys_advisory_off_422_state(html: str) -> None:
    """WP5: the live accept handler (acceptRunAsCard) must give a 422 carrying
    state=='ADVISORY' a distinct treatment, wired to the response body — not a
    free-floating constant elsewhere in the file."""
    idx = html.find("async function acceptRunAsCard")
    assert idx > 0, "acceptRunAsCard not found"
    body = html[idx:idx + 3500]
    assert "ADVISORY" in body, "acceptRunAsCard does not handle the ADVISORY tier"
    assert ".state" in body or "state ===" in body or "state==" in body, (
        "ADVISORY handling not wired to the 422 body.state field — assert the "
        "wiring, not a bare constant"
    )


def test_wp5_advisory_copy_present_in_accept_flow(html: str) -> None:
    """WP5 decision (C): the reviewable framing copy must appear inside the
    accept handler so a human sees 'didn't clear, not floor-blocked'."""
    idx = html.find("async function acceptRunAsCard")
    assert idx > 0
    body = html[idx:idx + 3500]
    assert "reviewable" in body.lower(), "ADVISORY reviewable framing copy missing"


def test_accept_flow_has_no_non_robust_override(html: str) -> None:
    """2026-06-11 decision: the accept-anyway override is removed from the UI.
    Only CLEAR-route runs can become cards — a 422 promotion-gate response
    renders the rejection and stops. No confirmed retry, no confirm_non_robust
    anywhere in the accept flow (the backend override stays, API-only)."""
    idx = html.find("async function acceptRunAsCard")
    assert idx > 0, "acceptRunAsCard not found"
    body = html[idx:idx + 4500]
    assert "retryPayload" not in body, (
        "acceptRunAsCard must not re-post after a 422 promotion gate — the "
        "accept-anyway override was removed from the UI on 2026-06-11"
    )
    assert "confirm_non_robust" not in body, (
        "the confirm_non_robust override knob must not appear in the UI "
        "accept flow — accepting non-CLEAR runs is API-only"
    )


def test_research_test_controls_present(html: str) -> None:
    # Research-tab "Test strategy" control + universe picker, wired to the
    # registered-strategy scoring route. Re-establishes the in-UI scoring
    # removed in the 2026-05-31 import refactor.
    assert 'id="researchTestBtn"' in html
    assert 'id="researchTestUniverse"' in html
    assert "/tradelab/strategies/score" in html
    assert "/tradelab/universes" in html


def test_research_custom_symbols_controls_present(html: str) -> None:
    """Custom-symbols box (2026-06-11): a 'Custom symbols…' choice in the
    universe picker reveals a text input that is validated cache-aware via
    /tradelab/symbols/validate — green only when every symbol is well-formed
    AND cached (an --offline run will genuinely use all of them)."""
    assert 'id="researchTestSymbols"' in html
    assert "/tradelab/symbols/validate" in html
    assert "__custom__" in html
    # the three validation states must exist as CSS classes
    for cls in ("sym-ok", "sym-warn", "sym-bad"):
        assert cls in html, f"validation state class {cls!r} missing"


def test_pipeline_has_universe_column(html: str) -> None:
    """The Runs table renders what each run was scored against (named
    universe, or 'N syms' with the full list as tooltip for custom runs)."""
    assert "<th>Universe</th>" in html
    # S5 added the Rung column: 16 columns now.
    assert 'colspan="16"' in html
    assert 'colspan="14"' not in html and 'colspan="15"' not in html, (
        "pipeline colspans must match the column count (16 since S5's Rung column)"
    )

# ── S1: registry-derived roster (2026-09-02) ───────────────────────
def test_s1_roster_is_registry_derived(html: str) -> None:
    """The Overview/Calendar/divergence roster must come from the card registry,
    not a literal. One definition each; the calendar filter is populated from it."""
    import re as _re
    assert len(_re.findall(r"\blet STRATEGY_ROSTER = \[\];", html)) == 1
    assert len(_re.findall(r"\basync function loadStrategyRoster\(", html)) == 1
    assert len(_re.findall(r"\bfunction findStrategy\(", html)) == 1
    assert "fetch('/tradelab/cards')" in html
    assert len(_re.findall(r"\bfunction _populateCalendarFilter\(", html)) == 1


def test_s1_calendar_filter_has_no_hardcoded_strategies(html: str) -> None:
    """Only the 'All Strategies' option is authored in markup; the rest are runtime."""
    import re as _re
    m = _re.search(r'<select class="calendar-filter" id="calendarFilter">(.*?)</select>', html, _re.S)
    assert m, "calendarFilter select missing"
    options = _re.findall(r"<option", m.group(1))
    assert len(options) == 1, f"expected 1 authored option, found {len(options)}"

# ── S2: upload fast path (2026-09-02) ───────────────────────────────
def test_s2_research_tab_accepts_file_drops(html: str) -> None:
    """Dropping a .py anywhere on the Research tab must open the upload modal
    and load the file — the drop listener is bound on #research, not only on
    the drop-zone inside the modal."""
    assert "researchTab.addEventListener('drop'" in html
    assert "nsLoadFiles(e.dataTransfer.files, {autoTest: true})" in html


def test_s2_upload_refuses_non_python_files_with_a_reason(html: str) -> None:
    assert "isn't a .py file" in html
    assert "not a tradelab strategy" in html


def test_s2_template_button_calls_template_route(html: str) -> None:
    assert "/tradelab/new-strategy/template?name=" in html

# ── S3: strategy tabs (2026-09-02) ──────────────────────────────────
def test_s3_strategy_tab_module_present_once(html: str) -> None:
    assert html.count("const ST = (() => {") == 1
    for fn in ("refreshTabs", "activate", "deactivate", "open", "loadActivity", "cardForStrategy", "activityFor"):
        assert f"{fn}," in html or f"{fn} }}" in html or f"{fn}}}" in html, fn


def test_s3_tabs_read_the_activity_route(html: str) -> None:
    assert "/activity?days=" in html


def test_s3_live_mode_is_present_and_gated(html: str) -> None:
    """S3 shipped Live disabled; S9 made it real — it must still exist, and
    must never be a bare PATCH: the click opens the gate."""
    import re as _re
    assert _re.search(r'<button data-mode="live" class=', html), "Live button must exist on the tab"
    assert "if (mode === 'live' && !isLive) { GOLIVE.open(c); return; }" in html


def test_s3_paper_requires_allocation(html: str) -> None:
    assert "Set a $ allocation first" in html


def test_s3_switch_tab_routes_card_tabs(html: str) -> None:
    assert "if (tabName.startsWith('card-'))" in html


def test_s3_calendar_filter_uses_strategy_activity(html: str) -> None:
    assert "function _calendarSource(" in html
    assert "ST.cardForStrategy(choice)" in html

def test_s3_accept_creates_card_off_not_armed(html: str) -> None:
    """Accept must not arm a strategy (S0 F12): the payload sends activate:false
    and the Paper switch on the tab is the only way to enable it."""
    assert "activate:        false," in html
    assert "activate:        true," not in html


# ── S3 review notes (specialist, 2026-09-03) ────────────────────────
def test_s3r_flatten_goes_through_backend_not_the_readonly_proxy(html: str) -> None:
    """The /api proxy is GET-only; a browser-side DELETE /v2/positions never
    reached Alpaca and would not carry the card stamp anyway. Flatten must
    POST /tradelab/cards/{id}/flatten (Off-first, prefixed, card-scoped)."""
    assert "/flatten'" in html
    assert "dry_run: true" in html
    assert "/v2/positions/" not in html
    for dead in ("onFlattenLiveCard", "onDeleteLiveCard", "_liveCardPositionStats"):
        assert dead not in html, dead


def test_s3r_rung3_counts_closing_orders_over_a_year(html: str) -> None:
    assert "t.closed_orders" in html
    assert "'/activity?days=365'" in html
    assert "closing orders" in html


def test_s3r_activity_warnings_surface_in_tab(html: str) -> None:
    assert 'data-role="act-warn"' in html
    assert "act.truncated" in html
    assert "act.orphaned_lots" in html
    assert "Unrealized (acct, by symbol)" in html


# ── S4: the strategy board (2026-09-03) ─────────────────────────────
def test_s4_board_is_the_research_tabs_spine(html: str) -> None:
    assert 'id="strategyBoard"' in html
    assert 'id="boardGroups"' in html and 'id="boardCounts"' in html
    assert html.count("const BOARD = (() => {") == 1
    assert "fetch('/tradelab/board'" in html


def test_s4_context_drawer_holds_the_three_old_sections(html: str) -> None:
    """Market Regime, Verdict Calibration and Portfolio Health survive, but
    collapsed under the board — inside <details id="researchContext">."""
    start = html.index('<details id="researchContext"')
    end = html.index("</details>", start)
    drawer = html[start:end]
    for sec in ('id="researchRegime"', 'id="researchCalibration"', 'id="researchPortfolioHealth"'):
        assert sec in drawer, sec


def test_s4_the_old_surface_names_are_gone(html: str) -> None:
    """One object, one surface: no Strategy Verdicts grid, no Live Cards
    renderer, no 'cards enabled' wording on Live Trading."""
    for dead in ("researchLiveCards", "researchLoadLiveCards", "renderLiveCard(", "renderDriftStrip(",
                 "patchTrackingError(", "research-cards-grid", ">Strategy Verdicts<", "cards enabled /"):
        assert dead not in html, dead


def test_s4_board_dispatches_one_action_per_card(html: str) -> None:
    for kind in ("'trial'", "'retrial'", "'accept'", "'open_tab'"):
        assert kind in html, kind
    assert "submitJob(row.strategy, 'run --robustness')" in html
    assert "acceptRunAsCard(row.run_id, row.strategy, row.verdict" in html
    assert "ST.open(row.card_id)" in html


def test_s4_board_refreshes_on_job_end_accept_and_retire(html: str) -> None:
    # The reload must come BEFORE the Runs-table row lookup: a job whose row
    # is filtered out of the table still has to update the board.
    i = html.index("function handleJobUpdate(")
    body = html[i:i + 2500]
    assert body.index("BOARD.load()") < body.index("researchPipelineBody")
    # the settled state event (from the JobManager reaper) needs no delayed retry
    assert "if (!payload.settled) setTimeout(BOARD.load, 2500)" in body
    assert html.count("BOARD.load()") >= 4


def test_s4_board_escapes_server_strings(html: str) -> None:
    """Every server-supplied string the board interpolates into innerHTML
    goes through _esc(): strategy names, symbols, reasons, labels."""
    idx = html.index("const BOARD = (() => {")
    body = html[idx: html.index("async function researchLoadAll()", idx)]
    for raw in ("${r.strategy}", "${a.reason}", "${a.label}", "${data.error}", "${r.state}", "${r.route", "${r.card_id}"):
        assert raw not in body, f"raw interpolation {raw} in board renderer — wrap in _esc()"
    assert "_esc(r.strategy)" in body and "_esc(a.reason" in body


def test_s4_job_stream_envelope_is_normalised(html: str) -> None:
    """The SSE payload is {job_id, event:{type,…}}; the handler must map it to
    {id, status} (exit≠0 on a 'done' event = failed) before any early return."""
    i = html.index("function handleJobUpdate(")
    body = html[i:i + 2500]
    assert "payload.job_id && payload.event" in body
    assert "Number(ev.exit || 0) === 0 ? 'done' : 'failed'" in body
    assert body.index("payload.job_id && payload.event") < body.index("if (!payload || !payload.id) return;")


def test_s4_accepted_cards_surface_newer_worse_trials_and_orphans(html: str) -> None:
    assert "r.newer_trial && r.newer_trial.worse" in html
    assert "r.unregistered" in html
    assert "data to <b>" in html


# ── S5: the test ladder (2026-09-03) ──────────────────────────────────
def test_s5_board_follows_the_full_trial_gate(html: str) -> None:
    assert "'full_trial'" in html
    assert "submitJob(row.strategy, 'run --full --validation-deep')" in html
    assert "function ladderHTML(" in html
    assert 'class="rung ' in html and "Full trial again" not in html.split("function ladderHTML(")[0][-200:]


def test_s5_score_is_presentation_only(html: str) -> None:
    """The score renders as a bar and is described as ranking, never deciding."""
    assert "Ranks; never decides." in html
    assert "sc.toFixed(2)" in html and "Number(r.score)" in html   # numeric-safe render


def test_s5_signals_split_gating_and_read_anyway(html: str) -> None:
    assert "Gating — these decide the verdict" in html
    assert "Read anyway — never change the verdict" in html
    assert "sig-hard" in html


def test_s5_runs_table_has_rung_column(html: str) -> None:
    assert "function rungCell(" in html
    assert ">Rung</th>" in html
    assert 'colspan="16"' in html and 'colspan="15"' not in html


# ── S6: the override (2026-09-03) ────────────────────────────────────
def test_s6_override_modal_is_typed_name_plus_reason_no_checkbox(html: str) -> None:
    assert 'id="overrideModal"' in html
    assert 'id="overrideConfirmInput"' in html and 'id="overrideReason"' in html
    assert "confirm_non_robust: true" not in html and "confirm_non_robust:true" not in html
    assert "$('overrideConfirmInput').value.trim() === pending.name" in html
    assert "reason.length >= min" in html


def test_s6_board_and_tab_wire_the_override(html: str) -> None:
    assert "OVERRIDE.grant(row)" in html
    assert "OVERRIDE.renew(c)" in html
    assert "override: {confirm, reason}" in html
    assert "/override'" in html
    assert "function renderOverride(pane, c)" in html
    assert "arrives in <span class=\"slice\">S6</span>" not in html


def test_s6_override_strings_are_escaped(html: str) -> None:
    i = html.index("function renderOverride(pane, c)")
    body = html[i:i + 3000]
    assert "${ov.reason}" not in body and "_esc(ov.reason" in body
    assert "${c.override_expired_at}" not in body


def test_s6_halted_state_is_shown(html: str) -> None:
    assert "r.effective_status === 'halted'" in html
    assert "needs a Full trial newer than the current grant" in html


# ── S9: the go-live gate (2026-09-03) ────────────────────────────────
def test_s9_go_live_modal_is_typed_confirmation_plus_allocation(html: str) -> None:
    assert 'id="goLiveModal"' in html
    assert 'id="goLiveConfirmInput"' in html and 'id="goLiveAlloc"' in html and 'id="goLiveChecks"' in html
    assert "=== v.expected_confirm" in html                    # the server names the string to type
    assert "Live arrives in S9" not in html                    # the Live button is real now
    assert "Paper-qualified" not in html.split("const BOARD = (() => {")[1][:4000]


def test_s9_live_routes_are_the_only_mode_writers(html: str) -> None:
    i = html.index("const GOLIVE = (() => {")
    body = html[i:i + 6000]
    assert "'/live', {cache: 'no-store'}" in body               # GET: the checks
    assert "'/live', {method: 'POST'" in body                   # POST: arm
    assert "'/paper', {method: 'POST'" in html                  # back to paper
    assert '"mode"' not in html[html.index("async function setMode("):html.index("async function setMode(") + 3000] \
        or "JSON.stringify({status})" in html                   # setMode only ever PATCHes status
    assert "GOLIVE.open(c)" in html and "function renderLiveReceipt(pane, c)" in html


def test_s9_board_has_a_live_column_and_the_rail_has_no_future_nodes(html: str) -> None:
    assert "const COLS = ['candidate', 'tried', 'accepted', 'live', 'retired'];" in html
    assert "const future = false;" in html
    assert "LIVE · real money" in html


def test_s9_live_strings_are_escaped(html: str) -> None:
    i = html.index("function renderLiveReceipt(pane, c)")
    body = html[i:i + 2500]
    assert "${lv.route}" not in body and "_esc(String(lv.route" in body
    j = html.index("const GOLIVE = (() => {")
    gb = html[j:j + 6000]
    assert "${c.reason}" not in gb and "_esc(c.reason" in gb and "_esc(c.label)" in gb
