# v2.1 Spec — Engine-Truth Verdict Tooltip

**Date:** 2026-04-23
**Status:** Draft — awaits user approval before implementation
**Supersedes:** v2 §8 deferred item "Why FRAGILE? tooltip"

## 1. Problem

The v2.0 `fragileReasons()` client-side heuristic was deleted 2026-04-23 because it was a lying tooltip: its thresholds had already drifted from `tradelab.yaml` (DSR 0.30 client vs 0.50 yaml), and three of its five "reasons" (trade count, DD, win rate) were not engine criteria at all — invented UI-side. After deletion, the FRAGILE/MARGINAL pill still colors correctly, but hovering it now reads `"FRAGILE — open Dashboard report for full diagnostics"` with no enumerated reasons.

We want honest, engine-truth reasons without duplicating engine logic client-side.

## 2. Non-goals

- No new SQLite schema column. The `runs` table stays as-is.
- No change to `record_run()` signature.
- No frontend-side threshold configuration.
- No backfill of pre-v2.1 runs that predate the `robustness_result.json` artifact.

## 3. Background — where the signals already live

`src/tradelab/cli_run.py:296-298` writes `robustness_result.model_dump_json()` to `<run_dir>/robustness_result.json` whenever the robustness suite runs. The dumped object contains `verdict: VerdictResult` (`src/tradelab/robustness/verdict.py:39-50`), whose `.signals: list[VerdictSignal]` is a structured array of `{name, outcome, reason}`. Example:

```json
{
  "verdict": {
    "verdict": "FRAGILE",
    "signals": [
      {"name": "dsr", "outcome": "fragile", "reason": "DSR=0.23 below fragile threshold 0.50"},
      {"name": "monte_carlo", "outcome": "inconclusive", "reason": "observed MaxDD at 67th percentile"},
      {"name": "wfe", "outcome": "robust", "reason": "WFE ratio 0.82 above robust threshold 0.75"},
      {"name": "regime_spread", "outcome": "fragile", "reason": "worst/best regime PF ratio 0.31 below 0.40"}
    ]
  }
}
```

This is ground-truth from the verdict engine. No client-side recomputation needed.

## 4. Design

### 4.1 Backend change — extend metrics endpoint

`GET /tradelab/runs/<run_id>/metrics` currently returns:
```json
{"data": {"total_trades": 197, "profit_factor": 1.1, ...}}
```

After v2.1, response shape:
```json
{
  "data": {
    "total_trades": 197, "profit_factor": 1.1, ...,
    "verdict_signals": [
      {"name": "dsr", "outcome": "fragile", "reason": "DSR=0.23 below fragile threshold 0.50"},
      ...
    ]
  }
}
```

The handler at `tradelab/web/handlers.py` locates the run folder from SQLite (`report_card_html_path` column), reads `robustness_result.json` from that folder if present, extracts `verdict.signals`, and includes them on the response. If the file is missing (run predates v2.1, or robustness didn't execute for that run), omit the field — UI falls back to the generic tooltip.

### 4.2 Frontend change — populate tooltip from real signals

`command_center.html` lazy-metrics callback (currently around line 2603) already receives the metrics body. After v2.1, it also receives `verdict_signals`. When verdict ∈ {FRAGILE, MARGINAL}:

- If `verdict_signals` contains ≥1 signal with `outcome === "fragile"`: tooltip text = `"FRAGILE — reasons:\n  · <reason 1>\n  · <reason 2>"` (max 3 shown, truncate rest with `"(and N more)"`).
- If no signals or all are inconclusive/robust: fall back to current `"FRAGILE — open Dashboard report for full diagnostics"` text.

Apply the same logic to `renderLiveCard` pill tooltips once per card (currently the live cards don't have verdict tooltips — add them for consistency).

### 4.3 Test shape

- Unit: `tests/web/test_handlers.py::test_metrics_includes_verdict_signals_when_available` — seed a tmp run folder with a `robustness_result.json`, assert the handler returns the signals.
- Unit: `tests/web/test_handlers.py::test_metrics_omits_verdict_signals_when_file_missing` — don't write the file, assert the field is absent (not null, not empty-array).
- Unit: `tests/web/test_handlers.py::test_metrics_handles_malformed_robustness_json` — write garbage, assert the endpoint still returns metrics without crashing (log warning, omit signals).
- Static: strengthen `test_command_center_html.py::test_no_raw_interpolation_of_server_strings_into_innerhtml` per audit B9 (catch nested template composition). Ensure the new tooltip population uses `textContent` not `innerHTML` — cover via a new assertion that the relevant section of JS references `.title = ` not `.innerHTML = `.

## 5. Implementation sequence

1. **Backend** — extend handler to read and merge signals. Tests first (TDD: write the three test_metrics_* first, red, then implement).
2. **Frontend** — update metrics callback at `command_center.html:2603` to read `verdict_signals` and set `pill.title` with enumerated reasons. Update `renderLiveCard` similarly.
3. **Static test** — add assertion that `fragileReasons` is still absent AND the new `verdict_signals` handling path exists (string presence test).

## 6. Scope boundary

This spec ONLY surfaces engine-truth reasons in the Research tab tooltip. It does NOT:
- Expose signals in the Job Tracker (fix-later if useful).
- Expose signals in Compare reports (already have their own rendering).
- Add a "why FRAGILE" modal panel (deferred to v2.2 if demanded).

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `robustness_result.json` missing for older runs | Handler gracefully omits field; UI falls back to generic text. |
| Malformed JSON on disk | Try/except around read; log + omit. |
| Reason strings contain HTML | Populate via `.title` (attribute) or `.textContent` — never `.innerHTML`. |
| Signal count grows (12+ signals would blow out the tooltip) | Truncate to top-3 fragile signals + `"(and N more)"`. |

## 8. Estimated effort

- Backend handler + 3 tests: ~1.5 hours
- Frontend tooltip population + static test: ~1 hour
- Docs + handoff: ~30 min

**Total: ~3 hours. One session.**

## 9. Open questions for user

- Q1: Show only `outcome === "fragile"` signals in tooltip, or also `inconclusive`? (Proposed: fragile only; inconclusive noise would dilute the signal.)
- Q2: Live cards get the tooltip too? (Proposed: yes, for consistency. Cost: zero — same data already fetched.)
- Q3: After v2.1, do we still want to add a structured `verdict_signals_json` column to the `runs` table — even though we don't need it right now — as a future-proofing step for when we want to query across runs ("show me all strategies that failed the WFE gate")? (Proposed: defer. Current approach works; column can be added when query need actually materializes.)
