# Research Tab v2 — Silent-Failure Audit

**Date:** 2026-04-23 (post-review follow-up)
**Scope:** `C:/TradingScripts/command_center.html` — Research tab JavaScript only (`renderPipelineRows`, `renderLiveCard`, `getSparklineRuns`, `researchLoad*`, preflight handlers, Compare wiring).
**Why:** The external code review surfaced one silent bug (`renderLiveCard` metrics never populated for a full version). This audit checks whether the same pattern class exists elsewhere in the tab.

## Audit method

1. Grep every `fetchJSON(...).then(...)` and `innerHTML = \`...\`` in the file.
2. For each, trace whether the callback's target element could be replaced, detached, or re-rendered between fetch start and fetch resolve.
3. Grep `addEventListener` and `onclick` for handlers attached to elements that could be wiped by a later `innerHTML` overwrite.
4. Grep `${...}` interpolations inside template strings for server/user-supplied values not wrapped in `escapeHtml`.
5. Grep `setInterval`/`setTimeout` for uncleared timers.

## Findings

### B1 — `renderPipelineRows` orphan-fetch race [MEDIUM, live]

**Location:** `command_center.html:2553-2625`

`renderPipelineRows(runs, replace)` with `replace=true` clears `tbody.innerHTML = ''`, then appends new `<tr>` elements. For each row it kicks off two async fetches: metrics (line 2603) and sparkline (line 2621). Both callbacks call `tr.querySelector(...)` — but `tr` is already detached if the user triggered another `replace` render before the fetch resolved.

Unlike `renderLiveCard` (which is guarded by `researchState.loaded` and runs once per session), `renderPipelineRows(replace=true)` fires on:
- Filter change (strategy / verdict / since)
- Sort change
- Clicking a pipeline column header

A user rapidly toggling filters will see empty `…` placeholders in metric cells that never fill.

**Fix sketch:** either (a) attach an AbortController per render and cancel outstanding fetches on next `replace`, or (b) tag each render with a monotonic `renderId` and have the callback check `if (tr.dataset.renderId !== currentRenderId) return` before writing. (a) is cleaner; (b) is simpler if AbortController support is a concern.

### B2 — Sparkline cache never invalidated [LOW, staleness]

**Location:** `command_center.html:2541-2550`

`getSparklineRuns(strategy)` memoizes results in `researchState.sparklineCache[strategy]` indefinitely. After a user runs a new backtest for a strategy, the sparkline won't reflect the new run until a full page reload.

**Fix sketch:** invalidate the cache entry when a job of type `run*` completes for that strategy (existing job-tracking infrastructure already emits completion events).

### B3 — `data-strategy` attribute XSS via template composition [HIGH, fixed in this pass]

**Was at:** `command_center.html:2569` (fixed 2026-04-23)

`runCell` template interpolated `r.strategy_name` into `data-strategy="${...}"` without `escapeHtml`. The composition `tr.innerHTML = \`...${runCell}...\`` then landed the unescaped value in live HTML. Escaped.

The static HTML test (`test_command_center_html.py::test_no_raw_interpolation_of_server_strings_into_innerhtml`) did NOT catch this because its regex looks for `${field}` literally inside `innerHTML = \`...\``; nested template composition hid the interpolation site. Strengthened test recommendation in B9.

### B4 — Inline `onclick="event.stopPropagation()"` style inconsistency [LOW]

**Location:** `command_center.html:2569`

The file's default style is `addEventListener` attached after appending. This one inline `onclick` is out of sync. Functionally fine (no user data in the handler), but if a future CSP policy tightens, inline handlers break first.

**Fix sketch:** move to an `addEventListener('click', e => e.stopPropagation())` after `appendChild`.

### B5 — `tr.onclick =` overwrites any prior handler [NONE]

**Location:** `command_center.html:2595`

`tr` is `document.createElement('tr')` freshly each iteration, so no prior handler exists. Safe today. Change to `addEventListener` for consistency if a pass through this code happens anyway.

### B6 — `cell.innerHTML = renderSparkline(runs)` assumes safe SVG string [LOW]

**Location:** `command_center.html:2623`

`renderSparkline` constructs an SVG string with interpolated `${stroke}`, `${pts}`, `${verdict}`. `stroke` and `pts` come from a closed set (verdict-driven color) and numeric formatting (no injection surface). `verdict` is server-supplied but constrained to `{ROBUST, MARGINAL, FRAGILE, INCONCLUSIVE}`. Injection would require an engine compromise that would already be game-over.

If you want defense-in-depth, wrap the `<polyline>` construction in `document.createElementNS('http://www.w3.org/2000/svg', 'polyline')` instead of string concat.

### B7 — Modal click-outside closes only if target is the backdrop [NONE]

**Location:** `command_center.html:2936, 2959`

`modal.addEventListener('click', e => { if (e.target === modal) ... })`. Correct behavior; noted for completeness.

### B8 — No cleanup of `countdownInterval` in Strategies tab [out of scope]

**Location:** `command_center.html:2233`

`setInterval` assignment; audit scope is Research tab only. Flagging the pattern but not investigating.

### B9 — Static test regex blind to nested template composition [MEDIUM, test gap]

`test_no_raw_interpolation_of_server_strings_into_innerhtml` in `tests/web/test_command_center_html.py` missed B3 because its regex assumes `${field}` is directly inside an `innerHTML = \`...\`` template. When a sub-template (`runCell`) interpolates a risky field and then gets composed into the outer `innerHTML` assignment, the pattern doesn't match.

**Fix sketch:** either (a) broaden the regex to match `${r.strategy_name}` anywhere in a `` ` `` ...``  `` block that ends up in `innerHTML`/`outerHTML`/`insertAdjacentHTML`, or (b) parse the JS with a proper tokenizer (overkill for one file). (a) is cheap — `r'`[^`]*\$\{(r\.strategy_name|...)\}'` globally, then manually allowlist the already-escaped call sites.

## Severity summary

| ID | Severity | Status |
|---|---|---|
| B1 | Medium | Open — document-level fix in v2.1 (AbortController pattern) |
| B2 | Low | Open — invalidate on job completion |
| B3 | High | **Fixed 2026-04-23** |
| B4 | Low | Open (style) |
| B5 | None | — |
| B6 | Low | Open (defense-in-depth) |
| B7 | None | — |
| B8 | Out of scope | — |
| B9 | Medium | Open (test gap) |

**Net:** one real XSS fixed inline. Four open items worth picking up as a v2.1 batch if there's appetite — none urgent, none blocking.
