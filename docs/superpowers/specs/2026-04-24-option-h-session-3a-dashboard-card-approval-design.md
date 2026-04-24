# Option H — Session 3a: Dashboard Card Approval (Design)

**Date:** 2026-04-24
**Scope:** Session 3a of the Option H rollout. Authoring-only path — paste a TradingView CSV + Pine into the dashboard, score it, and create an immutable `disabled` card in the registry.
**Out of scope (deferred to Session 3b):** card list UI, ON/OFF toggle, delete, flatten, receiver hot-reload, Live Strategies strip sourcing from `cards.json`.
**Out of scope (deferred to Session 4):** Cloudflare Tunnel migration, old-bot retirement, Windows service wrapping, reconciliation job.

---

## 1. Context

Session 2 shipped `tradelab score-from-trades` as a CLI that turns a TradingView "List of trades" CSV into a verdict + report folder + audit row (see `OPTION_H_SESSION_2_COMPLETE_2026-04-24.md`). Session 3 was scoped in that handoff as one 14-hour block that bundles authoring and lifecycle UI together. This spec splits it:

- **3a (this spec)** — authoring: Score → Accept → card lands in `cards.json` with `status="disabled"`. User hand-edits status to flip ON until 3b ships.
- **3b (future spec)** — lifecycle: list cards, toggle ON/OFF, delete, flatten, receiver hot-reload.

The split is deliberate. 3a is a self-contained capability that can be reviewed, shipped, and soak-tested independently. 3b is a pure UX layer on top. Bundling them created a review surface large enough to defer real defects into live-testing (Session 2's experience).

---

## 2. Decisions locked in brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| Backtest length source of truth | TradingView Strategy Tester (status quo) | Preserves Option H invariant: TV is SOT. No dashboard override. No preflight length guardrail in 3a. |
| Verdict gate on Accept | Soft gate — FRAGILE requires type-the-word confirm; INCONCLUSIVE and ROBUST click through | CSV verdict ceiling is INCONCLUSIVE (only 3 signals). Hard-blocking FRAGILE would make the real production path unreachable. Soft confirm is cheap friction at the one moment muscle memory is dangerous. |
| `card_id` naming | Always `{base_name}-v{n}`, first approval is `-v1` | Matches observed manual convention in Session 2 smoke runs and the "cards immutable, iteration = delete+recreate" invariant: every accept is a new version by definition. |
| Per-card secret | Auto-generate (`secrets.token_urlsafe(24)`), always retrievable in card detail and inline after approval | `cards.json` sits next to `alpaca_config.json` which already has live creds; "show once" hygiene doesn't improve the real threat model, and it creates a recovery trap (lost copy = must delete+rescore). |
| Approval form fields | V1 minimal: CSV paste, Pine paste, Symbol, Base name, Timeframe. Starting equity (100000) and MC sims (500) hardcoded. Card `quantity` left null (TV-driven). | Dashboard's job is the common-path fast-lane. CLI already exists for power users who need non-default params. |
| Score vs Accept | Two-step — Score writes report folder + audit row + returns verdict; Accept creates card + promotes Pine archive | User wants to see the verdict before committing a card. Orphan report folders from unacclepted scores are fine — they look exactly like unused `tradelab run` output. |
| Pine archive location | Two locations — `reports/.../strategy.pine` stays transient; Accept copies Pine + CSV + verdict.json into `pine_archive/{card_id}/` as the permanent record | Cards are immutable; their Pine should outlive any report folder. |
| Modal placement | "Score New Strategy" button at top of Research tab → opens a modal | Approval is a deliberate action worth one extra click. CSV and Pine textareas need the viewport a modal gives them. Matches existing New Strategy modal pattern. |

---

## 3. Architecture

### 3.1 Two-endpoint design

```
          ┌────────────── Research tab ──────────────┐
          │                                          │
          │  [ Score New Strategy ]  ← button        │
          │          │                               │
          │          ▼                               │
          │  ┌── Modal ────────────────────────┐     │
          │  │  CSV textarea                   │     │
          │  │  Pine textarea                  │     │
          │  │  Symbol | Base name | Timeframe │     │
          │  │                                 │     │
          │  │    [ Score ]  ──────────────────┼──POST /tradelab/score
          │  │                                 │     │
          │  │    ── verdict result panel ──   │     │
          │  │                                 │     │
          │  │    [ Accept ]  ─────────────────┼──POST /tradelab/accept
          │  │                                 │     │
          │  │    ── success panel ──          │     │
          │  │    card_id, secret, TV template │     │
          │  └─────────────────────────────────┘     │
          └──────────────────────────────────────────┘
```

### 3.2 State ownership

Frontend is the only holder of state between Score and Accept. After a successful Score response it stashes `researchState.scoreSession = { report_folder, scoring_run_id, verdict, metrics, dsr_probability, n_trades, start_date, end_date, base_name, symbol, timeframe }`, and passes `{base_name, symbol, timeframe, report_folder}` back in the Accept POST. Server is stateless across the two requests.

### 3.3 Invariants

- **Every new card is `disabled`.** 3a has no code path that writes `"enabled"`. Enforced by an assertion in `CardRegistry.create`.
- **`card_id` always matches `^{base_name}-v\d+$`.** Enforced by always deriving `card_id` from `next_version_for(base_name)`; the approval form does not let the user override.
- **`pine_archive/{card_id}/` is the legal record.** `reports/` is considered transient.
- **Receiver's in-memory card view is stale in 3a.** Safe because all new cards are disabled, and disabled cards are rejected at `live/receiver.py:88` regardless of whether the receiver knows about them.

---

## 4. Components

### 4.1 Backend

**`src/tradelab/live/cards.py` — extended**

Adds (no breaking changes to existing read methods):

- `class CardExistsError(Exception)` — raised by `create` on duplicate.
- `def next_version_for(self, base_name: str) -> int` — scans `self._cards` keys, returns `max(n for {base_name}-v{n} in keys) + 1`, or `1` if none.
- `def create(self, card_id: str, data: dict) -> None`:
  - Asserts `data.get("status") == "disabled"` (raises `ValueError` if not — 3a safety).
  - Under `self._lock`: raises `CardExistsError` if `card_id in self._cards`; else adds the entry and persists via atomic write (`cards.json.tmp` → `os.replace(cards.json)`).
  - Rollback on mid-write exception: if the tmp write succeeds but `os.replace` fails, leaves the old `cards.json` intact (the whole point of tmp+replace).

**`src/tradelab/web/approve_strategy.py` — new module**

Pattern: mirrors `web/new_strategy.py` structure (pure functions returning dicts, raising only well-typed errors the handler can map to HTTP codes).

```python
def score_csv(
    csv_text: str, pine_source: str | None,
    symbol: str, base_name: str, timeframe: str,
    *, reports_root: Path = Path("reports"),
    db_path: Path | None = None,  # defaults to tradelab.audit.history.DEFAULT_DB_PATH
) -> dict:
    """Parse → score → write report folder with audit.
    Raises TVCSVParseError, ValueError, or wraps csv_scoring errors.
    Returns: {verdict, metrics: {...}, report_folder, scoring_run_id,
              dsr_probability, n_trades, start_date, end_date}
    """

def accept_scored(
    base_name: str, symbol: str, timeframe: str, report_folder: str,
    *, registry: CardRegistry,
    pine_archive_root: Path = Path("pine_archive"),
    reports_root: Path = Path("reports"),
) -> dict:
    """Validate report_folder is under reports/, compute card_id,
    generate secret, copy strategy.pine + tv_trades.csv to
    pine_archive/{card_id}/, write verdict.json, call registry.create.
    Rolls back pine_archive dir on registry failure.
    Returns: {card_id, secret, pine_archive_path}
    """
```

Both are pure functions: no HTTP, no global state, directly testable.

**Implementation note for the plan:** `csv_scoring.write_report_folder` currently calls `audit.record_run` but discards its return value; `audit.history.record_run` returns a `str` run_id (`src/tradelab/audit/history.py:91`). The plan must extend `write_report_folder` to surface this id — either by changing its return type to a small dataclass `(folder, audit_run_id)` or by adding a second return value. The existing CLI caller (`cli_score.py`) must be updated in the same commit. No other call sites.

**`src/tradelab/web/handlers.py` — extended**

Two new route branches in `handle_post_with_status` (placed before the `handle_post` fallback):

```
POST /tradelab/score    → approve_strategy.score_csv(...)
POST /tradelab/accept   → approve_strategy.accept_scored(...)
```

HTTP code mapping per §5 below. Uses the existing `_ok`/`_err` envelope and the existing audit DB path helper `_db_path()`. Registry is instantiated fresh per request (cheap — it just reads `cards.json`) so concurrent writes from two tabs go through the registry's RLock.

**`pine_archive/` — new top-level dir**

- Created on first Accept.
- Gitignored (runtime data, mirrors `live/cards.json`, `live/alerts.jsonl`).
- Layout: `pine_archive/{card_id}/{strategy.pine, tv_trades.csv, verdict.json}`.
- `verdict.json` is a JSON snapshot: `{card_id, base_name, version, symbol, timeframe, verdict, dsr_probability, n_trades, start_date, end_date, created_at, scoring_run_id}`.

### 4.2 Card schema (v1)

Keys written to `cards.json` by `CardRegistry.create`:

```json
{
  "viprasol-amzn-v1": {
    "card_id":           "viprasol-amzn-v1",
    "secret":            "<32-char url-safe>",
    "symbol":            "AMZN",
    "status":            "disabled",
    "quantity":          null,
    "created_at":        "2026-04-24T15:13:23Z",
    "base_name":         "viprasol-amzn",
    "version":           1,
    "timeframe":         "1H",
    "verdict":           "FRAGILE",
    "dsr_probability":   0.883,
    "report_folder":     "reports/viprasol-amzn-v1_2026-04-24_151323",
    "pine_archive_path": "pine_archive/viprasol-amzn-v1",
    "scoring_run_id":    "<audit row id>"
  }
}
```

Existing receiver fields (`card_id`, `secret`, `symbol`, `status`, `quantity`) are preserved in their current semantics. New fields (`base_name`, `version`, etc.) are ignored by the current receiver — no migration needed.

### 4.3 Frontend

**Single file edited:** `C:/TradingScripts/command_center.html`.

**Additions:**

- New button `#scoreNewStrategyBtn` in the existing chip row at the top of the Research tab.
- New modal `#modal-score-strategy` following the `#modal-3f-*` pattern from Research v2 (backdrop click + ESC to dismiss).
- New JS state: `researchState.scoreSession` (null or the scored-state dict).
- New functions inside the existing IIFE: `openScoreModal`, `closeScoreModal`, `researchHandleScore`, `researchHandleAccept`, plus event wiring via delegation on the modal container (no `onclick=` attributes — same XSS discipline as Research v2).
- Verdict panel reuses `verdictHeatClass()` and `fragileReasons()` (already present in the file).
- Success panel shows `card_id`, `secret` (with copy button), and a TV Alert Message JSON template block with a copy button:
  ```json
  {"card_id":"viprasol-amzn-v1","secret":"<secret>","action":"{{strategy.order.action}}","symbol":"{{ticker}}","contracts":"{{strategy.order.contracts}}"}
  ```

**XSS discipline:** every interpolation of user-supplied or server-returned text uses `textContent` / `escapeHtml()` / `document.createElement` / `dataset` — no raw `innerHTML` with template literals containing `${...}` of dynamic data. This is the pattern established by Research v2 commits `8ef29ed`, `2380635`, `9e7e4ef`.

**Live Strategies strip untouched in 3a.** `renderLiveCard()` continues reading from `alpaca_config.json`. New cards from 3a appear only in `cards.json` and are invisible to the strip until 3b ships `GET /tradelab/cards`.

**Backup sidecar.** Before editing, create `command_center.html.bak-2026-04-24-option-h-3a` per the v2 convention.

---

## 5. Data flow

### 5.1 Score flow

1. User fills form, clicks **Score**.
2. Frontend disables Score button, posts `{csv_text, pine_source, symbol, base_name, timeframe}` to `/tradelab/score`.
3. Handler validates field shapes (see §6 error table).
4. Handler calls `approve_strategy.score_csv`:
   - `parse_tv_trades_csv(csv_text, symbol=symbol)` → `ParsedTradesCSV`.
   - `csv_scoring.score_trades(parsed, strategy_name=base_name, symbol=symbol, timeframe=timeframe)` → `CSVScoringOutput`.
   - `csv_scoring.write_report_folder(output, base_name=base_name, pine_source=pine_source, csv_text=csv_text, record_audit=True)` → report folder path.
5. Handler returns `{verdict, metrics: {net_pnl, profit_factor, total_trades, max_drawdown_pct, ...}, report_folder, scoring_run_id, dsr_probability, n_trades, start_date, end_date}`.
6. Frontend renders verdict panel, stashes response in `researchState.scoreSession`, enables Accept button.

### 5.2 Accept flow

1. User clicks **Accept**.
2. If `scoreSession.verdict === "FRAGILE"`: `window.prompt("Type FRAGILE to confirm approval")`. If result !== `"FRAGILE"`, abort — do not POST.
3. Frontend disables Accept button, posts `{base_name, symbol, timeframe, report_folder}` to `/tradelab/accept`.
4. Handler validates `report_folder` is under `reports/` (paranoid prefix check against directory traversal).
5. Handler calls `approve_strategy.accept_scored`:
   - `registry = CardRegistry(CARDS_PATH)` (fresh load).
   - `version = registry.next_version_for(base_name)`; `card_id = f"{base_name}-v{version}"`.
   - `secret = secrets.token_urlsafe(24)` (32 chars).
   - `archive_dir = pine_archive / card_id`; `mkdir(parents=True, exist_ok=False)` (raises if already exists).
   - Copy `strategy.pine` and `tv_trades.csv` from `report_folder` into `archive_dir`. If `strategy.pine` is missing, raise `ValueError("report folder has no strategy.pine")` and `shutil.rmtree(archive_dir)`.
   - Write `verdict.json` into `archive_dir` from the audit row + score metadata.
   - Build card dict (per §4.2), call `registry.create(card_id, card)`. On any `CardRegistry.create` exception, `shutil.rmtree(archive_dir, ignore_errors=True)` and re-raise.
6. Handler returns `{card_id, secret, pine_archive_path}`.
7. Frontend shows success panel with copy buttons. User closes the modal manually.

---

## 6. Error handling

### 6.1 `POST /tradelab/score` error table

| Condition | HTTP | Body `error` |
|---|---|---|
| Missing `csv_text`, `symbol`, `base_name`, or `timeframe` | 400 | `missing field: <name>` |
| `base_name` fails `^[a-z0-9][a-z0-9-]{1,47}$` | 400 | `base_name must be lowercase alphanumeric with hyphens, 2–48 chars` |
| `symbol` fails `^[A-Z]{1,10}$` | 400 | `symbol must be 1–10 uppercase letters` |
| `timeframe` not in `{1m,5m,15m,30m,1H,4H,1D,1W}` | 400 | `unknown timeframe: <x>` |
| `TVCSVParseError` | 400 | `str(exc)` (parser message is already user-facing) |
| CSV has 0 closed trades | 400 | `csv contained no closed trades` |
| `csv_scoring` unexpected | 500 | `scoring failed: <type>: <msg>` (traceback to stderr) |
| Success | 200 | — |

### 6.2 `POST /tradelab/accept` error table

| Condition | HTTP | Body `error` |
|---|---|---|
| Missing `base_name`, `symbol`, `timeframe`, or `report_folder` | 400 | `missing field: <name>` |
| `report_folder` not under `reports/` or missing on disk | 404 | `report folder not found` |
| `report_folder` has no `strategy.pine` | 400 | `report folder has no strategy.pine — re-score with Pine source` |
| `pine_archive/{card_id}/` already exists (stale dir) | 409 | `pine archive already exists for {card_id}` |
| `CardExistsError` (race) | 409 | `card_id {card_id} already registered` |
| Registry/atomic write failure | 500 | `failed to persist card: <msg>`; pine_archive rolled back |
| Success | 200 | — |

### 6.3 Partial-failure semantics

Accept's order of writes is deliberate:

1. Create `pine_archive/{card_id}/` and copy files.
2. `CardRegistry.create` (atomic tmp+replace).

If (2) fails after (1) succeeded, the handler `shutil.rmtree`s the pine_archive dir and surfaces 500. If the rmtree itself fails (rare — Windows file lock), the error message includes the orphan path for manual cleanup. This is the "prefer orphan pine_archive over ghost card" tradeoff: a card entry pointing at nothing would break the receiver's Pine-lookup in 3b; an orphan dir is inert.

If the registry's atomic write partially fails (tmp written, rename fails), the on-disk `cards.json` is untouched — this is the whole point of `os.replace`.

### 6.4 Concurrency

Two browser tabs clicking Accept at the same base name both land in the same `launch_dashboard.py` process. `CardRegistry._lock` serializes them; second request sees first's write and raises `CardExistsError` → 409. Frontend surfaces the conflict and a retry re-computes `-v{n+1}`.

### 6.5 Frontend-side cheap validation (before POST)

- Empty CSV textarea → inline `"paste the CSV first"`, no request.
- Empty Pine textarea → warning `"no Pine source — archive will be incomplete. Continue?"`, user confirms to proceed.
- Empty Symbol or Base name → inline error, no request.

---

## 7. Testing

### 7.1 Automated (pytest)

| File | Tests |
|---|---|
| `tests/live/test_cards_create.py` (new) | `create` happy path; duplicate `card_id` raises `CardExistsError`; `next_version_for` returns 1/2/3 across seeded states; `create` with `status != "disabled"` raises `ValueError`; atomic write behavior — assert `cards.json.tmp` absent after success, and old `cards.json` untouched when `os.replace` is monkeypatched to raise |
| `tests/web/test_approve_strategy.py` (new) | `score_csv` happy path using `tests/io/fixtures/tv_export_amzn_smoke.csv`; `score_csv` with empty CSV raises `TVCSVParseError`; `score_csv` with 0 closed trades; `accept_scored` happy path against a freshly-scored fixture; two sequential accepts produce `-v1` and `-v2`; `accept_scored` refuses a report_folder without `strategy.pine`; `accept_scored` rolls back pine_archive dir on registry failure (monkeypatch) |
| `tests/web/test_handlers_approve.py` (new) | `POST /tradelab/score`: 200 happy, 400 on each malformed input, 500 on forced internal error; `POST /tradelab/accept`: 200 happy, 404 missing report_folder, 409 on `CardExistsError`, 400 on missing Pine |

### 7.2 Regression

```powershell
cd C:\TradingScripts\tradelab
$env:PYTHONPATH = "src"; $env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/ -q
```

Baseline before this work: `339 passed, 3 pre-existing failures` on master `f390da0`. Post-3a expected: baseline + ~20 new passes, zero new failures. Plan writer snapshots `pytest --collect-only` at start to distinguish pre-existing from regressions.

### 7.3 Manual smoke (before calling 3a done)

1. Receiver, dashboard, ngrok all up per the handoff §5 procedure.
2. Research tab → **Score New Strategy** → modal opens.
3. Paste `tests/io/fixtures/tv_export_amzn_smoke.csv` content + any Pine string → Symbol `AMZN`, Base name `smoke-amzn`, Timeframe `1H` → **Score**. Expect: verdict panel renders; Accept button enabled.
4. **Accept** → (no FRAGILE confirm on the smoke fixture) → success panel shows `card_id: smoke-amzn-v1`, secret, TV alert template. Copy buttons work.
5. Check `tradelab/live/cards.json` contains `smoke-amzn-v1` with `status: "disabled"`.
6. Check `tradelab/pine_archive/smoke-amzn-v1/` contains `strategy.pine`, `tv_trades.csv`, `verdict.json`.
7. Re-run steps 2–4 with the same inputs → expect `card_id: smoke-amzn-v2`.
8. POST `/webhook` (using `curl` or TV sandbox alert) with `card_id: smoke-amzn-v1` → expect `card_disabled` response from the receiver.
9. Cleanup: delete `smoke-amzn-v*` entries from `cards.json`, `rm -rf pine_archive/smoke-amzn-v*`.

### 7.4 Deliberately not tested in 3a

- Receiver hot-reload (3b).
- Toggle / delete / flatten (3b).
- Live Strategies strip reading from `cards.json` (3b).
- End-to-end TV → Alpaca fill for a dashboard-approved card (requires 3b toggle).

---

## 8. References

- `docs/superpowers/OPTION_H_HANDOFF_2026-04-24.md` — Option H rationale + architecture.
- `docs/superpowers/OPTION_H_SESSION_2_COMPLETE_2026-04-24.md` — Session 2 deliverable + Session 3 task decomposition (from which 3a is extracted).
- `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md` — current dashboard architecture, modal patterns, XSS discipline.
- `docs/superpowers/plans/2026-04-24-csv-scoring-adapter.md` — Session 2 plan (template for 3a's implementation plan).
- `src/tradelab/csv_scoring.py` — orchestrator wrapped by `score_csv`.
- `src/tradelab/live/cards.py` — registry being extended.
- `src/tradelab/live/receiver.py` — consumer of the resulting cards (untouched in 3a).
- `src/tradelab/web/new_strategy.py` — structural template for `approve_strategy.py`.
- `C:/TradingScripts/command_center.html` — only frontend file modified.

---

## 9. Out-of-scope — defer to 3b

Explicitly called out here so a future Claude session picking up 3a does not scope-creep into lifecycle management:

- `GET /tradelab/cards` — list endpoint.
- `PUT /tradelab/cards/{id}` — toggle ON/OFF.
- `DELETE /tradelab/cards/{id}` — with type-the-name confirm + "must be OFF and no open positions" guard.
- `POST /tradelab/cards/{id}/flatten` — close open Alpaca positions for a card.
- `POST /internal/reload` on the receiver — hot-pick new cards from `cards.json`.
- `renderLiveCard()` rewrite to source from `/tradelab/cards`.
- `alpaca_client` extension for `close_position(symbol)` / `close_all_positions()`.
- Card detail view (secret retrieval, verdict reminder).
- Auto-disable in `CardRegistry.create` assertion — will be relaxed when the toggle endpoint ships.

---

## 10. Success criteria for 3a

Amit can, end-to-end, in one dashboard session:

1. Open the Research tab.
2. Click **Score New Strategy**.
3. Paste a TradingView "List of trades" CSV and the matching Pine source.
4. Enter Symbol, Base name, Timeframe.
5. Click **Score** and read the verdict.
6. Click **Accept** (with soft confirm on FRAGILE).
7. See a `card_id`, a secret, and a TV Alert Message template — all copyable.
8. Confirm (by inspecting `cards.json`) that the card is `disabled`.

After that, hand-editing `cards.json` to flip `status: "enabled"` + restarting the receiver, and firing a TV alert, should result in an Alpaca fill — same as the Session 1 smoke. That last step is not itself part of 3a's done-definition; it's the bridge to 3b.
