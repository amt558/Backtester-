# Direction A — Slice 6 — Panic Panel — Design

**Date:** 2026-04-26
**Author:** Brainstormed with Amit (active full-time trader, ~10 concurrent strategies)
**Status:** Spec — awaiting user review before implementation plan
**Parent spec:** `2026-04-25-direction-a-card-management-v1-design.md` (§10 expanded here)
**Predecessor:** `2026-04-25-DIRECTION-A-SLICE-5-COMPLETE.md`

---

## 1. One-liner

Replace "panic = open a terminal and `pkill receiver`" with a three-button panic panel pinned to the top of the Live Trading tab: L1 disables all cards, L2 also cancels open tradelab orders, L3 also flattens every Alpaca position — each gated by a typed confirm word, L3 by an additional 3-second armed countdown — and every event is audited to `panic_events.jsonl` and notified at `CRITICAL` severity.

## 2. Scope

### In scope
- Spec §10 (Panic Panel) in full.
- **Slice 5 follow-up #8** — wrap all Alpaca calls in the panic handler with `try/except APIError` (and broader `Exception`). Failures are recorded per-action; the panic continues. Carries the same gap flagged in Slice 4 follow-up #8.
- **Slice 5 follow-up #11** — fix `silence_checker.stop()` lock asymmetry (acquire `_start_lock` before reading/writing `_thread`).
- **Slice 5 follow-up #9** — delete unused `.lt-pill--silent` dead CSS class from `command_center.html`.
- New post-panic re-arm UX: dismissible banner + scoped re-enable using `before_state_snapshot`.

### Out of scope (deferred)
- **Orphan-order detection.** L2 default skips open orders whose `client_order_id` doesn't match any current `card_id` (orders from deleted cards). The "Also cancel non-tradelab" checkbox provides the escape hatch. Add `tradelab_order_history.jsonl` only if orphans become a real problem.
- **Auto-panic on N consecutive guardrail blocks.** v1 panic is human-pulled (carries from parent spec §3).
- **Structured per-channel notify rendering.** All five channels receive the same multi-line `body` string; channel-specific HTML/templating is v2.
- **Panic event log rotation.** `panic_events.jsonl` is append-only and unbounded for v1 (carries from Slice 4 follow-up #1 / Slice 5 follow-up #10).
- **"Undo panic" beyond the bulk-re-enable banner.** Per parent spec §10.5: re-enabling individual cards is the normal flow.
- **Ramped-flatten / split-flatten / TWAP-flatten.** L3 issues plain market orders. If you need to be gentle, don't hit L3.

## 3. Architecture

### 3.1 Process boundaries — unchanged

Panic lives entirely in the dashboard launcher process (port 8877). Receiver (port 8878) is the passive consumer of `cards.json` changes — L1 takes effect through the existing watchdog reload. The launcher calls Alpaca directly for L2/L3 (same pattern as guardrails). Receiver is never asked to do anything panic-related.

### 3.2 Files modified or added

| File | Change |
|---|---|
| `tradelab/live/panic.py` | NEW — `execute_panic(level, also_cancel_nontradelab) -> PanicResult` |
| `tradelab/live/alpaca_client.py` | Add `list_open_orders()`, `cancel_order_by_id(order_id)`, `list_positions()` wrappers (alpaca-py SDK calls). Currently only `submit_market_order` exists. |
| `tradelab/live/panic_events.jsonl` | NEW — append-only audit log. Already covered by `.gitignore` rule `/live/*.jsonl`. |
| `tradelab/live/silence_checker.py` | Fix `stop()` lock asymmetry (follow-up #11) |
| `tradelab/web/_handlers.py` | Add `POST /tradelab/live/panic` and `GET /tradelab/live/panic/last-event` |
| `command_center.html` | Add panic strip (collapsed-by-default) + L1/L2/L3 modal flows + post-panic banner. Delete dead `.lt-pill--silent` CSS (follow-up #9). |
| `tests/live/test_panic.py` | NEW — execute_panic effect, partial-failure, audit log |
| `tests/web/test_panic_handlers.py` | NEW — endpoint envelopes, confirm-token validation |
| `tests/web/test_panic_fe_contract.py` | NEW — DOM/CSS/JS contract pins for panic strip + modals + banner |

## 4. UI design

### 4.1 Panic strip placement

The strip is the **first child** of the Live Trading tab content area, above the cards grid. It is a single-row pinned bar:

```
[ 🚨 PANIC ▾ ]                                                  collapsed (default)

[ 🚨 PANIC ▴ ]  [ Pause All ]  [ Pause + Cancel Orders ]  [ Pause + Cancel + Flatten Positions ]   expanded
```

- Collapsed-by-default. Click the title chevron to expand. State is **not** persisted — every page load starts collapsed.
- The strip is `position: sticky; top: 0` within the LT tab so it stays visible during scroll, but only when expanded does it occupy meaningful vertical space.
- Each level button has a tooltip:
  - L1: "Flip every enabled card to disabled. No Alpaca calls."
  - L2: "L1 + cancel open tradelab orders."
  - L3: "L2 + flatten ALL positions in your Alpaca account, regardless of whether tradelab opened them."

### 4.2 L1 — Pause All

1. Click `[ Pause All ]` → modal opens
2. Modal contents:
   - Title: `Pause All Cards`
   - Body: `This will disable every enabled card. Receiver picks up the change immediately. No Alpaca calls. Type DISABLE to confirm.`
   - Text input
   - `[ Cancel ]` `[ Confirm ]` (Confirm disabled until input === "DISABLE")
3. Click Confirm → POST → modal closes → cards refresh → post-panic banner appears

### 4.3 L2 — Pause + Cancel Orders

Same flow as L1, with:
- Confirm word: `PANIC`
- Modal also contains a checkbox **"Also cancel non-tradelab open orders"** — default **OFF**. Tooltip: `Cancels EVERY open order in your Alpaca account. Use only if you have no manual orders you want to keep.`
- Modal warns: `Will cancel open orders whose client_order_id matches a current tradelab card. Orders from deleted cards are NOT cancelled unless the checkbox above is on.`

### 4.4 L3 — Pause + Cancel + Flatten Positions

Modal-owned state machine (no second click outside the modal):

1. Click `[ Pause + Cancel + Flatten Positions ]` → modal opens
2. Modal contents:
   - Title: `🚨 FLATTEN ALL POSITIONS`
   - Body: `This affects your ENTIRE Alpaca account, not just tradelab positions. Type FLATTEN to arm.`
   - Text input
   - `[ Cancel ]` `[ Arm ]` (Arm disabled until input === "FLATTEN")
3. Click Arm → button container swaps to `[ ARMED — Click again in 3s ]` with a 3-second countdown ring on the button
4. After 3s elapsed → button text becomes `[ FIRE FLATTEN NOW ]` and is clickable
5. Click → POST → modal closes → cards refresh → post-panic banner appears
6. **Auto-abort:** if no second click within 10s of arming, modal closes silently. No POST.
7. **Manual abort:** modal close (X button, Esc, outside-click) at any stage = no POST.

The DOM uses `data-armed="true|false"` and `data-countdown="N"` attributes on the modal root so the contract test can pin the state machine without depending on visual styling.

### 4.5 Post-panic banner

At top of LT tab, between the panic strip and the cards grid. Renders when:
- `GET /tradelab/live/panic/last-event` returns non-null AND
- The event's `ts` is not in `localStorage[panicDismissedTs]` (set of dismissed event timestamps)

Banner format:
```
🚨 L2 panic at 14:32:07 ET — 7 cards disabled, 3 orders cancelled.
[ Re-enable just these 7 ]   [ View audit ]   [ Dismiss ]
```

- "Re-enable just these N" — bulk PATCH on the `cards_disabled` `card_id` list (top-level field of the panic event, not nested inside `before_state_snapshot`)
- "View audit" — expands the JSONL entry inline below the banner (collapsible)
- "Dismiss" — adds `ts` to `localStorage[panicDismissedTs]`, banner disappears for this event only

The banner uses `data-panic-banner` and `data-panic-event-ts="..."` attributes for contract pinning.

## 5. Backend design

### 5.1 `panic.py` module

```python
@dataclass
class CancelAction:
    ok: bool
    error: Optional[str]
    order_id: Optional[str]          # Alpaca order id
    client_order_id: Optional[str]
    card_id: Optional[str]           # which tradelab card it belonged to (None = non-tradelab)

@dataclass
class FlattenAction:
    ok: bool
    error: Optional[str]
    symbol: str
    qty: str                         # Alpaca returns qty as string; preserve precision
    side: str                        # "buy" or "sell" — opposite of the held position
    order_id: Optional[str]          # Alpaca id of the close order, if submit succeeded

@dataclass
class PanicResult:
    ts: str  # ISO 8601 with TZ
    level: str  # "L1" | "L2" | "L3"
    before_state_snapshot: list[dict]
    cards_disabled: list[str]  # card_ids
    orders_cancelled: list[CancelAction]
    positions_flattened: list[FlattenAction]

def execute_panic(level: str, also_cancel_nontradelab: bool = False) -> PanicResult:
    """Execute panic at the given level. Always succeeds — partial failures are
    recorded inside the result. Raises only on programmer error (bad level)."""
```

Internal call order:
1. Snapshot current cards.json into `before_state_snapshot`
2. L1 step: flip every `status=enabled` card to `disabled`, atomic write to cards.json
3. L2 step (L2/L3 only): `try/except` around `alpaca_client.list_open_orders()` (wraps `TradingClient.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))`), then per-order `try/except` around `alpaca_client.cancel_order_by_id(order_id)` (wraps `TradingClient.cancel_order_by_id`). Filter rule: `client_order_id.startswith(f"{cid}-")` for any `cid` in current cards.json (or all open orders if `also_cancel_nontradelab=True`). Each result becomes a `PanicAction`.
4. L3 step (L3 only): `try/except` around `alpaca_client.list_positions()` (wraps `TradingClient.get_all_positions()`), then per-position `try/except` around `alpaca_client.submit_market_order(symbol, side, qty)` with `side` opposite to the position. Each result becomes a `PanicAction`.
5. Append `PanicResult` (as JSON) to `panic_events.jsonl`
6. Build the multi-line notification body, call `notify(CRITICAL, title, body)`
7. Return `PanicResult`

### 5.2 Endpoints

**`POST /tradelab/live/panic`** — body:
```json
{
  "level": "L1" | "L2" | "L3",
  "confirm": "DISABLE" | "PANIC" | "FLATTEN",
  "also_cancel_nontradelab": false
}
```

Validation (all 400 on failure):
- `level` ∈ `{L1, L2, L3}`
- `confirm` matches the required word for that level (`L1=DISABLE, L2=PANIC, L3=FLATTEN`)
- `also_cancel_nontradelab` only meaningful for L2/L3; ignored for L1

Response: the full `PanicResult` as JSON.

Server-side confirm-word check is **defense in depth** — the FE also enforces it, but a misbehaving FE / curl test must not bypass it.

**`GET /tradelab/live/panic/last-event`** — response: most recent line of `panic_events.jsonl` parsed as JSON, or `null` if file is empty/missing.

Implementation note: read the file as text, take the last non-empty line, `json.loads` it. Don't load the whole file into memory if it gets large — use a tail-read. (Even at 1KB per event × 1000 panics = 1MB; not urgent. But: cheap to do right.)

### 5.3 Notification body format

Title: `🚨 L{1,2,3} panic — {N} cards disabled`

Body (single multi-line string, same to all 5 channels):
```
L2 panic at 14:32:07 ET

Cards disabled (7): S2_AAPL_LONG, S4_MSFT_SHORT, S7_NVDA_LONG, S8_TSLA_SHORT, S10_SPY_LONG, S12_QQQ_SHORT, S2_GOOG_LONG
Orders cancelled (3): a1b2c3, d4e5f6, g7h8i9
Positions flattened: (none)
```

**Truncation:** any list of card IDs (or order IDs) over 10 items is rendered as the first 10 + `… +N more`. Full list lives in `panic_events.jsonl`.

If a step had errors, append a line: `Errors: 2 of 5 cancellations failed (see audit log).` Don't dump stack traces in the notification body.

## 6. Audit log shape

`panic_events.jsonl` — one JSON object per line, append-only:

```json
{
  "ts": "2026-04-26T14:32:07.123-04:00",
  "level": "L2",
  "before_state_snapshot": [
    {"card_id": "S2_AAPL_LONG_a1b2", "base_name": "S2_AAPL_LONG", "status": "enabled", "qty": 100, "last_fired_at": "2026-04-26T13:18:42-04:00"},
    {"card_id": "S4_MSFT_SHORT_c3d4", "base_name": "S4_MSFT_SHORT", "status": "disabled", "qty": 50, "last_fired_at": null}
  ],
  "cards_disabled": ["S2_AAPL_LONG_a1b2"],
  "orders_cancelled": [
    {"ok": true, "order_id": "alpaca-uuid-1", "client_order_id": "S2_AAPL_LONG_a1b2-1714142887000", "card_id": "S2_AAPL_LONG_a1b2", "error": null}
  ],
  "positions_flattened": []
}
```

`before_state_snapshot` includes **every** card in cards.json at panic time (enabled or disabled), with the per-card minimal fields: `card_id`, `base_name`, `status`, `qty`, `last_fired_at`. Sufficient for the post-panic banner's "re-enable just these N" feature and for forensic "what was running when I hit panic." Not the entire card payload.

## 7. Architectural follow-ups bundled in this slice

### 7.1 Slice 5 follow-up #8 — Alpaca exception wrapping

Every Alpaca call site in `panic.py` wrapped:

```python
try:
    orders = alpaca_client.list_open_orders()
except APIError as e:
    # Whole-step failure: record one synthetic CancelAction noting list call failed; continue to next step
    cancel_actions = [CancelAction(ok=False, error=f"list_open_orders APIError: {e}",
                                   order_id=None, client_order_id=None, card_id=None)]
except Exception as e:
    cancel_actions = [CancelAction(ok=False, error=f"list_open_orders failed: {type(e).__name__}: {e}",
                                   order_id=None, client_order_id=None, card_id=None)]
else:
    cancel_actions = [_try_cancel(o) for o in orders if _is_in_scope(o, also_cancel_nontradelab)]
```

Per-order/per-position calls each get their own `try/except` so one failed cancellation doesn't abort the panic. This same pattern should be retrofitted into the guardrail evaluation path (Slice 4 follow-up #8) — but doing so is **out of scope** for Slice 6 (don't widen the slice; the guardrail path runs in the receiver, this slice is launcher-only).

### 7.2 Slice 5 follow-up #11 — silence_checker.stop() lock fix

Change `silence_checker.stop()` to acquire `_start_lock` before reading/writing `_thread`, mirroring `start()`. One-method patch. Add a unit test (`tests/live/test_silence_checker.py::test_stop_uses_lock`) that mocks the lock and asserts acquisition.

### 7.3 Slice 5 follow-up #9 — drop dead `.lt-pill--silent` CSS

Delete the unused `.lt-pill--silent { ... }` rule block from `command_center.html`. The contract test for the silence pill (`::after`-based) does not depend on this class. Verify with grep before deletion that no JS references it.

## 8. Testing strategy

### 8.1 `tests/live/test_panic.py` — execute_panic core

| Test | Asserts |
|---|---|
| `test_l1_disables_all_enabled_cards` | All `enabled` cards become `disabled`. Disabled cards unchanged. cards.json written exactly once. |
| `test_l1_no_alpaca_calls` | Mock Alpaca client; assert no methods called. |
| `test_l2_cancels_only_tradelab_orders_by_default` | Two open orders: one `client_order_id` matches a card, one doesn't. Only the matching one cancelled. |
| `test_l2_cancels_all_orders_when_flag_on` | Both orders cancelled when `also_cancel_nontradelab=True`. |
| `test_l2_partial_failure_continues` | `cancel_order` raises `APIError` on order #2. Order #1 cancelled, order #2 recorded with `ok=False, error=...`. Panic completes. |
| `test_l3_flattens_all_positions` | `list_positions` returns 3; 3 `submit_market_order` calls with opposite side. |
| `test_l3_flatten_partial_failure` | Position #2 submit raises; result records ok/error per position. |
| `test_audit_log_appended` | After execute, `panic_events.jsonl` has one new line, parses to the expected dict. |
| `test_audit_log_snapshot_shape` | `before_state_snapshot` has the expected fields per card. |
| `test_notify_called_with_critical` | Mock `notify`; assert called with `severity=CRITICAL` and body includes truncation marker for >10 cards. |
| `test_notify_truncation_under_10` | 5 cards → no `… +N more` suffix. |
| `test_notify_truncation_at_11` | 11 cards → first 10 then `… +1 more`. |
| `test_alpaca_list_orders_failure_does_not_crash_panic` | Mock `list_orders` to raise; result records the failure; L1 step still succeeded. |

### 8.2 `tests/web/test_panic_handlers.py` — endpoints

| Test | Asserts |
|---|---|
| `test_post_panic_l1_happy` | Valid body returns 200 with PanicResult. |
| `test_post_panic_wrong_confirm_word_400` | `level=L1, confirm=PANIC` → 400. |
| `test_post_panic_invalid_level_400` | `level=L4` → 400. |
| `test_post_panic_l1_ignores_also_cancel_flag` | `level=L1, also_cancel_nontradelab=True` → flag has no effect; no Alpaca calls. |
| `test_get_last_event_returns_null_when_empty` | No file or empty file → `null`. |
| `test_get_last_event_returns_most_recent` | Two entries written; endpoint returns the second. |
| `test_get_last_event_handles_corrupt_trailing_line` | If the last line is malformed JSON, return the last valid line, not 500. |

### 8.3 `tests/web/test_panic_fe_contract.py` — DOM/CSS/JS pins

Static-text greps against `command_center.html`, mirroring Slice 5's contract-test pattern. Pin:
- The literal strings `🚨 PANIC`, `Pause All`, `Pause + Cancel Orders`, `Pause + Cancel + Flatten Positions`
- The confirm-word literals `DISABLE`, `PANIC`, `FLATTEN` appear in the modal body for their respective levels
- `data-armed`, `data-countdown`, `data-panic-banner`, `data-panic-event-ts` attributes are referenced in JS
- JS function names `executePanic`, `armFlatten`, `disarmFlatten`, `fetchLastPanicEvent`, `dismissPanicBanner`, `reenableFromSnapshot` are pinned
- Sticky-position CSS (`position: sticky`, `top: 0`) on the panic strip selector
- The dead `.lt-pill--silent` class is **not** present (assert grep returns 0 matches — regression guard for follow-up #9)

### 8.4 `tests/live/test_silence_checker.py` — added test

`test_stop_acquires_start_lock` — mock `_start_lock`, call `stop()`, assert `__enter__` was called.

### 8.5 Integration / smoke (manual, deferred to Monday RTH if needed)

L1, L2, L3 each fired once against a paper-trading Alpaca account during RTH:
- L1: verify all enabled cards flip to disabled within 1 sec of POST; receiver log shows reload event
- L2: place a paper order, hit L2, verify order cancelled and notification fires
- L3: open a paper position, hit L3, verify position closed and notification fires
- Banner appears after each, dismiss persists across page reload (per-event ts)
- "Re-enable just these N" restores the correct subset

### 8.6 Pytest baseline target

Maintain `653 passed / 0 failed` baseline. Net-new tests: ~25-30 across `test_panic.py` (~13), `test_panic_handlers.py` (~7), `test_panic_fe_contract.py` (~8), `test_silence_checker.py` (+1). Target: **~680 passed / 0 failed**.

## 9. Rollout

Single slice. Land all changes on `master` branch (no feature flag) in dependency order:
1. Backend (`panic.py`, endpoints, follow-up #11 stop-lock fix)
2. FE (panic strip, modals, banner, follow-up #9 dead-CSS removal)
3. Smoke during Monday RTH
4. Done doc + handoff for Slice 7 (Daily email summary + polish + docs per parent spec §13)

Estimated: ~2 days per parent spec §13.

## 10. Open questions deferred to plan-writing

- Exact `tail-read` strategy for `GET /tradelab/live/panic/last-event` — `seek(-N, 2)` heuristic vs full file read. Pick during plan writing; both work for current scale.
- Whether the post-panic banner `[View audit]` link expands inline or opens a small slide-pane (existing pattern from Research tab). Pick during plan writing — inline is simpler.
- Modal styling — reuse the existing modal CSS from card-edit, or new dedicated panic-modal CSS? Reuse where possible.

---

**End of Slice 6 design spec.**
