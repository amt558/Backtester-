# Frontend test strategy — Playwright vs. lighter alternatives

**Date:** 2026-04-23
**Status:** Decision doc — awaits user sign-off
**Context:** Code review flagged "413-line frontend diff with zero automated tests" as a structural gap. Original suggestion: Playwright. This doc evaluates that against cheaper alternatives now that a static-HTML smoke test (see `tests/web/test_command_center_html.py`, 32 assertions) is already in place.

## 1. The bug classes we care about

From the v2.0 ship + post-review audit:

| Bug class | Example | Would a browser test catch it? | Would a static test catch it? |
|---|---|---|---|
| Wrong DOM selector | `[data-action="start"]` vs `#modal-3f-confirm` | ✅ only if test clicks Run and asserts Start is disabled | ❌ |
| Deleted helper function | `fragileReasons` removed, call site orphaned | ✅ if test exercises the code path | ✅ — static test asserts called-identifier is defined |
| Missing DOM ID | Backend endpoint expects `#preflight-universe`, HTML has `#preflight-univ` | ✅ | ✅ |
| Raw innerHTML XSS | `${r.strategy_name}` unescaped in innerHTML template | ❌ (browser happily renders) | ✅ — regex over the source |
| Dead feature flag flipping | `localStorage.researchLayoutLegacy=1` shows old layout | ✅ only if test toggles the flag and diffs | ❌ |
| Orphan-fetch race | `renderPipelineRows` filter re-entry | ✅ with careful async scripting | ❌ |
| CSS regression (heat colors invisible) | `.heat-3` typo renders transparent | ✅ with screenshot diff | ❌ |
| Metric cells stuck at "…" | Backend endpoint 500s, UI shows placeholder forever | ✅ with mocked/intercepted response | ❌ |

**Summary:** static tests cover the cheap, pattern-based bugs (selectors, deletions, XSS). Browser tests cover interaction bugs, CSS regressions, and timing races.

## 2. Options evaluated

### Option A — Static HTML tests only (status quo post-today)

Already in place: `tests/web/test_command_center_html.py`, 32 assertions, runs in 0.06s, no new dependencies. Caught 1 real XSS on first run (r.strategy_name).

**Pros:**
- Zero new deps.
- Runs in the existing pytest suite.
- Fast enough to run in pre-commit hook.
- Covers identifier presence/absence (the bug class that burned us on v2.0).

**Cons:**
- Cannot test interaction (clicking Run, toggling flags).
- Cannot test CSS rendering.
- Cannot test async races.

**Cost:** already paid.

### Option B — Option A plus a small Playwright pack

Install Playwright for Python, add ~5 tests for critical flows:
- `test_run_modal_start_disabled_when_preflight_red`
- `test_compare_selected_button_appears_after_two_checkboxes`
- `test_fragile_pill_tooltip_contains_generic_text` (would catch regression of today's fix)
- `test_feature_flag_toggle_renders_legacy_layout`
- `test_pipeline_filter_change_repopulates_metrics` (would catch audit finding B1)

**Pros:**
- Covers the bug classes static tests miss.
- Industry-standard for this kind of testing.
- Works with the same pytest harness.

**Cons:**
- Playwright wheel: 40MB. Browser binaries: 600MB+ per browser (Chromium/Firefox/WebKit). `playwright install chromium` alone is 300MB.
- Adds first-run-setup pain for new contributors (install browsers).
- Tests are slower (~5-15s per test), so moves the pytest suite from 2min to 3-4min.
- Local-only CI (no remote CI configured for this project), so the cost is borne entirely at dev-time.
- Flakier than static tests — real browsers have timing variance.

**Cost:** ~3 hours to add the initial pack (install, config, 5 tests). ~300MB of disk. Ongoing cost: +2min to each pytest run that includes them.

### Option C — JSDOM (jest-dom-style, Node-based)

Parse the HTML, simulate DOM, run the JS via a headless DOM library. Doesn't need real browsers.

**Pros:**
- Smaller (~40MB vs. 600MB).
- Faster (sub-second per test).
- No browser binary.

**Cons:**
- Introduces Node.js as a second test runtime (currently pure-Python).
- JSDOM has known gaps vs. real browsers (no layout engine, no CSS rendering, async quirks).
- Mixing Python+JS test infra adds maintenance burden.
- The bugs most likely to slip are exactly the ones JSDOM doesn't catch well (CSS regressions, real-browser async timing).

**Cost:** ~4 hours to stand up. Ongoing Node toolchain maintenance.

### Option D — Hand-written e2e smoke script in Python using requests + regex

Exists as a concept — could formalize the ad-hoc smoke Ilike I ran today into a proper `tests/smoke/test_dashboard_e2e.py` that:
- Boots the dashboard as a subprocess
- Hits endpoints via requests
- Parses the served HTML for expected identifiers
- Doesn't simulate clicks but asserts the "static contract" between server and page

**Pros:**
- No new deps.
- Catches backend-to-frontend contract drift (endpoint returns field X, frontend looks for field Y).
- Works with existing pytest harness.

**Cons:**
- Doesn't execute JS.
- Can't test interaction flows.

**Cost:** ~1.5 hours. No disk / no new runtime.

## 3. Recommendation

**Ship Option A (done today) + Option D (1.5h next session). Defer Option B until a bug surfaces that neither A nor D would have caught.**

Rationale:
- The bugs that bit v2.0 (wrong selector, deleted helper, lying tooltip) were all static-test-coverable or contract-test-coverable. None required a real browser.
- Option D adds minimal cost and closes the backend↔frontend contract gap.
- Playwright's 300MB of browsers is a real tax on a project with no remote CI — bears it all at dev-machine level, including laptop disk, `.claude/worktrees/*` copies, and backup copies.
- If v2.2+ grows new interaction flows (drag-drop reorder, multi-select panels, rich modal composition), revisit Option B at that time with specific bugs in mind.

## 4. If you disagree

The decision hinges on blast radius. If you think:
- "I want to catch CSS regressions" → Option B (Playwright) with `expect(page).toHaveScreenshot()`.
- "I want to test the feature flag toggle before removing it" → Option B, one-off.
- "I care more about backend↔frontend contract than UI interaction" → Option D is the sweet spot.
- "I want something today" → you have Option A already; Option D is the cheapest next step.

Say which you want and I'll implement.

## 5. Non-decision — what I'm NOT going to do without you

- Install Playwright or any new dep.
- Touch `package.json` or add Node.js tooling.
- Add a CI pipeline (this project has none; adding one is a separate decision).
- Convert the existing `test_command_center_html.py` to a different framework.
