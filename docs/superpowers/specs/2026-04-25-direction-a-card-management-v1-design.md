# Direction A — Card Management v1 (Live Trading Tab) — Design

**Date:** 2026-04-25
**Author:** Brainstormed with Amit (active full-time trader, ~10 concurrent strategies)
**Status:** Spec — awaiting user review before implementation plan
**Predecessor:** `2026-04-25-RESEARCH_TAB_SLIDE_PANE_COMPLETE.md`, `2026-04-25-CLEANUP_AND_UPGRADES_COMPLETE.md`

---

## 1. One-liner

Replace the hand-edit-`cards.json` + manually-restart-receiver ritual with a dashboard-driven Live Trading tab that exposes card lifecycle (toggle, edit quantity, delete), groups cards by `base_name`, surfaces last-fired status per card, applies receiver-side position guardrails before each Alpaca submit, detects silence per cadence, sends notifications via browser/Windows toast/audible/ntfy.sh/email, and provides a three-level panic panel.

## 2. Goals

- **Eliminate the JSON-edit ritual.** Every Score → Accept currently requires opening cards.json, setting `quantity`, flipping `status`, saving, restarting the receiver. v1 makes all of those one-click.
- **Make 10 concurrent strategies operationally feasible.** Group by `base_name`, bulk enable/disable, last-fired-at visible per row, receiver-up indicator.
- **Push anomalies to the trader.** When you're not watching the dashboard, browser/Windows/audible/ntfy.sh/email reach you depending on severity.
- **Refuse unsafe orders at the receiver.** Five guardrails (collision, naked-short, buying-power, daily limit, cooldown) ON by default with per-card overrides.
- **Provide a panic panel.** Three escalating levels (Pause / Pause+Cancel / Pause+Cancel+Flatten) with confirm gates appropriate to each.

## 3. Non-goals (explicitly deferred to later phases)

- **P&L attribution per card** — own design pass; deferred to "Phase A.7" because half-baked P&L is worse than none.
- **Sector/correlation caps, risk-per-trade caps, time-of-day windows on the receiver side.**
- **Promote-to-Live for Python strategies** — Direction B; depends on this work.
- **Auto-panic on N consecutive guardrail blocks** — v1 panic is human-pulled.
- **"Re-enable from snapshot" / undo-panic** — defer.
- **Rotate-secret UI** — delete + re-Accept already works; lowest value/effort in the bucket.
- **Sector classification, currency, dividends, fees** — out of scope for v1.

## 4. Architecture

### 4.1 Hot-reload mechanism: file watcher

The receiver gains a `watchdog`-based observer on `cards.json`. On change → 100ms debounce → `mtime` re-check → `CardRegistry.reload()`. Atomic `os.replace()` in the existing `_persist()` already gives us a single clean event per write.

- **All mutations write the file.** Dashboard launcher (`launch_dashboard.py`) writes via the existing `CardRegistry`.
- **Receiver passively reloads.** No admin-write endpoints on the receiver. Receiver remains "card lookup + secret check + Alpaca submit + guardrails."
- **If receiver is down when dashboard mutates, the file is consistent.** Receiver picks up on next startup.

This preserves the invariant that `cards.json` is the canonical state — same invariant Score/Accept already relies on.

### 4.2 Process boundaries

| Process | Port | Responsibilities |
|---|---|---|
| Dashboard launcher | 8877 | Serves `command_center.html`. Writes cards.json. Writes `live_config.json`. Calls Alpaca for panic L2/L3. Polls receiver `/health` for status chip. Writes `panic_events.jsonl`. Runs the silence-check periodic task. |
| Receiver | 8878 | Receives webhooks. Hot-reloads cards.json. Applies guardrails. Calls Alpaca for order submit. Writes `alerts.jsonl`. |

Dashboard and receiver remain independent processes. Neither requires the other to be up to do its core job.

### 4.3 Files modified or added

| File | Change |
|---|---|
| `tradelab/live/cards.json` | New per-card fields: `cadence`, `last_fired_at`, `last_attempted_at`, `enabled_at`, `daily_limit`, `cooldown_seconds`, `allow_collision`, `allow_naked_short` |
| `tradelab/live/cards.py` | Add `update`, `delete`, `set_status`, `set_quantity`, `set_cadence`, `set_overrides` methods. Drop the Session 3a guardrail in `create()` (line 71-75). |
| `tradelab/live/receiver.py` | Add watchdog observer. Add guardrail check between secret-check and order-submit. Update `last_fired_at` on accepted orders. |
| `tradelab/live/guardrails.py` | NEW — `check_guardrails(card, alert, alpaca_state) -> Optional[BlockReason]` |
| `tradelab/live/notify.py` | NEW — `notify(severity, title, body, **kwargs)` with channel routing |
| `tradelab/live/silence_checker.py` | NEW — periodic task; runs in dashboard launcher process |
| `tradelab/live/panic.py` | NEW — `pause_all`, `pause_and_cancel`, `pause_cancel_and_flatten` |
| `tradelab/web/handlers.py` | New endpoints (see §6) |
| `tradelab/live/live_config.json` | NEW (gitignored) — channel toggles, ntfy.sh topic, SMTP creds, severity routing, global guardrail thresholds, silence-multiplier sliders |
| `tradelab/live/panic_events.jsonl` | NEW — append-only audit log |
| `command_center.html` | New "Live Trading" tab; settings panel; panic panel; per-card row UI |

## 5. Live Trading tab UI

### 5.1 Layout (top to bottom)

1. **Status strip** — receiver-up chip (✓ :8878 up · uptime XhXm / ⚠ :8878 down) · ngrok-up chip (read from `127.0.0.1:4040/api/tunnels`) · global "Cards enabled / total" counter
2. **Panic panel** — three buttons: `[Pause All]` `[Pause + Cancel Orders]` `[Pause + Cancel + Flatten]` (each with type-to-confirm + L3 has 3s countdown)
3. **Bulk action strip** — appears when ≥1 card is checkbox-selected: `[Enable Selected]` `[Disable Selected]` `[Delete Selected]`
4. **Card list** — grouped by `base_name`, currently-enabled `-vN` pinned to top of group, older versions collapsed under "Show N archived versions" disclosure
5. **Settings panel** (collapsed by default) — bottom of tab: notification config + global guardrail/silence sliders

### 5.2 Card row content

| Column | Source | Notes |
|---|---|---|
| ☐ | n/a | Selection checkbox for bulk actions |
| `card_id` | cards.json key | e.g. `viprasol-amzn-v2` |
| Status pill | cards.json `status` | `enabled` (green) · `disabled` (grey) · `silent` (amber, derived) |
| Symbol | cards.json `symbol` | e.g. `AMZN` |
| Quantity | cards.json `quantity` | Inline editable (click to edit) |
| Cadence | cards.json `cadence` | Dropdown: `intraday` / `daily` / `weekly` / `manual` |
| Last fired | cards.json `last_fired_at` | Human-relative: "3m ago" / "yesterday" / "—" |
| Last status | derived from alerts.jsonl tail | `order_submitted` (green) / `order_failed` (red) / `guardrail_blocked` (amber) / `—` |
| 24h fires | derived | Count from alerts.jsonl |
| Actions | inline | `[Toggle]` `[⚙ Overrides]` `[🗑 Delete]` |

### 5.3 Click row → detail panel

Right-side slide-pane reusing the same component as the Research tab's slide-pane. Only one slide-pane open at any time across the dashboard (opening one closes the other). Tabs:

- **Recent Alerts** — last 50 entries from `alerts.jsonl` filtered by card_id
- **Pine Archive** — `verdict.json` + `strategy.pine` from `pine_archive/<card_id>/` rendered inline
- **Overrides** — per-card guardrail overrides (allow_collision, allow_naked_short, daily_limit, cooldown_seconds)

### 5.4 Grouping by base_name

- Cards in `cards.json` parsed for `<base_name>-v<N>` pattern
- Group header shows `base_name` + "{N enabled} / {M versions}"
- Within group: ALL enabled versions pinned top (sorted by version desc); disabled `-vN` collapsed under disclosure
- "Show N disabled versions" toggles the rest
- **If multiple `-vN` versions of the same base_name are enabled simultaneously**, render a yellow group-header warning ("⚠ N versions of viprasol-amzn are enabled — symbol collision guardrail will reject conflicting orders"). This is intentional non-blocking — the guardrail in §9 handles correctness; the UI surfaces the situation.

## 6. New endpoints (all on dashboard launcher :8877)

| Method | Path | Body | Effect |
|---|---|---|---|
| GET | `/tradelab/cards` | — | List all cards with derived fields (last_fired_at, last_status, 24h fires, base_name group) |
| GET | `/tradelab/cards/<id>` | — | Single card detail incl. recent alerts |
| GET | `/tradelab/cards/<id>/alerts?limit=50` | — | Tail of alerts.jsonl filtered by card_id |
| GET | `/tradelab/cards/<id>/archive` | — | verdict.json + strategy.pine for card |
| PATCH | `/tradelab/cards/<id>` | `{status?, quantity?, cadence?, daily_limit?, cooldown_seconds?, allow_collision?, allow_naked_short?}` | Mutate one or more card fields. Validates. Persists via CardRegistry. |
| DELETE | `/tradelab/cards/<id>` | `{confirm: "DELETE"}` | Remove card. Pine archive untouched. |
| POST | `/tradelab/cards/bulk-toggle` | `{ids: [...], status: "enabled"\|"disabled"}` | Bulk state change |
| POST | `/tradelab/cards/bulk-delete` | `{ids: [...], confirm: "DELETE"}` | Bulk delete |
| POST | `/tradelab/panic/pause` | `{confirm: "DISABLE"}` | Disable all enabled cards |
| POST | `/tradelab/panic/pause-cancel` | `{confirm: "PANIC"}` | Disable + Alpaca cancel_all_orders |
| POST | `/tradelab/panic/pause-flatten` | `{confirm: "FLATTEN", armed_at: <ts>}` | Disable + cancel + flatten positions. Server checks armed_at is ≥3s old. |
| GET | `/tradelab/receiver/status` | — | Probes `:8878/health` and `:4040/api/tunnels`; returns `{receiver_up, ngrok_up, receiver_uptime, ngrok_url}` |
| GET | `/tradelab/live/config` | — | Returns `live_config.json` (passwords masked) |
| PATCH | `/tradelab/live/config` | partial config | Updates `live_config.json`; triggers reload of in-memory config in launcher |
| POST | `/tradelab/live/config/test-notification` | `{channel, severity}` | Fires a synthetic notification to verify channel works |

## 7. Notification system

### 7.1 Severity → channel routing (defaults, configurable)

| Severity | Browser toast | Windows toast | Audible | ntfy.sh | Email |
|---|---|---|---|---|---|
| CRITICAL | ✓ | ✓ | ✓ | ✓ | ✓ |
| WARNING | ✓ | ✓ | ✓ | — | — |
| INFO | ✓ | — | — | — | — |
| Daily summary (separate) | — | — | — | — | ✓ (4pm ET) |

### 7.2 What triggers what

| Event | Severity |
|---|---|
| Receiver process down (health probe fails) | CRITICAL |
| ngrok tunnel down (probe fails or URL changed) | CRITICAL |
| Alpaca order submission failed | CRITICAL |
| Guardrail blocked an order | CRITICAL (because by definition signal disagreed with portfolio reality) |
| Panic button activated (any level) | CRITICAL |
| Card silent past expected cadence × multiplier | WARNING (first transition only; suppress until next fire) |
| Card fired and order submitted successfully | INFO |
| Daily 4pm ET market-close summary | (separate email path) |

### 7.3 Implementation

`tradelab.live.notify` module:
- `notify(severity: Severity, title: str, body: str, channels: Optional[set] = None)` — uses default routing if `channels` not set
- Channel modules: `notify.browser` (writes to a SSE stream consumed by the dashboard for in-page toasts), `notify.windows_toast` (via `plyer`), `notify.audible` (via `winsound.PlaySound` of a bundled .wav), `notify.ntfy` (single `requests.post` to `https://ntfy.sh/<topic>`), `notify.email` (SMTP via `smtplib`)
- All channels are best-effort and isolated — one channel failure does not block the others
- Test-notification endpoint exists per channel for the user to verify config

### 7.4 Settings panel — fillable fields

Located at the bottom of the Live Trading tab, collapsed by default ("⚙ Notification & Safety Settings").

**Notifications section:**
- ntfy.sh topic (text field; e.g. `tradelab-amit-7g3k2x`)
- ntfy.sh server URL (text; default `https://ntfy.sh`)
- Email — SMTP host, port, user, password, from-address, to-address
- Per-channel enable toggles (browser/windows/audible/ntfy/email)
- Per-severity routing matrix (checkboxes)
- "Test [channel]" buttons per channel
- Audible volume + sound-file picker (defaults to a bundled `panic.wav`)

**Silence detection section:**
- Multiplier sliders per cadence band (intraday / daily / weekly)
- Default values: intraday × 2 trading days, daily × 5 trading days, weekly × 21 calendar days

**Position guardrails section:**
- Max in-flight exposure as % of buying power (slider 50/75/90/95/100; default 90)
- Default per-card daily order limit (number; default 5)
- Default per-card cooldown seconds (number; default 30)
- Per-card overrides happen on the per-card row, not here

**Email digest section:**
- Daily summary enabled toggle
- Send time (default 16:00 ET)

## 8. Silence detection

### 8.1 Cadence model

- Per-card `cadence` field: `"intraday" | "daily" | "weekly" | "manual"`
- Default for new cards (created via Score/Accept) and existing cards (migration): `"daily"`
- `"manual"` opts out of silence detection entirely

### 8.2 Threshold

`threshold = base_unit × multiplier` where:

| Cadence | Base unit | Default multiplier | Default threshold |
|---|---|---|---|
| intraday | 1 trading day | 2 | 2 trading days |
| daily | 1 trading day | 5 | 5 trading days |
| weekly | 1 calendar day | 21 | 21 calendar days |
| manual | — | — | (no detection) |

Trading-day calculation: simple — exclude Saturday, Sunday, and US market holidays (use the existing `pandas_market_calendars` if already a tradelab dep, else hardcode the 9 US holidays).

### 8.3 Checker

- Runs in launcher process (one place, easy to stop/start)
- Cron: every 30 minutes during market hours (9:30am–4pm ET, Mon-Fri)
- For each enabled card: compute `now - last_fired_at` against threshold
- If exceeded AND not already in silent state: `notify(WARNING)` + flip a derived `silent: true` flag (in-memory, not in cards.json)
- On next fire: silent flag clears, no further notification
- One notification per silence transition — never repeat-fire while silent

## 9. Position guardrails (receiver-side)

### 9.1 The five checks

Run between secret-check and Alpaca submit, in this order (cheapest first, fail-fast):

1. **Cooldown check** — `now - card.last_attempted_at < card.cooldown_seconds`? Reject `cooldown_active`. Uses `last_attempted_at` (written on every webhook receipt regardless of outcome) NOT `last_fired_at` (written only on success) — so a flood of attempts gets debounced even if all are blocking.
2. **Daily limit check** — count `order_submitted` entries in alerts.jsonl for this card_id since today's market open. ≥ `card.daily_limit`? Reject `daily_limit_exceeded`.
3. **Symbol collision check** — scan `alerts.jsonl` tail for any OTHER enabled card with the same symbol that produced `order_submitted` in last 30s. Unless `allow_collision`, reject `symbol_collision`.
4. **Naked-short check** — `action == "sell"` AND no open position for symbol in `alpaca_state.positions` AND not `allow_naked_short`? Reject `no_position_to_sell`.
5. **Buying-power check** — `(working_orders_notional + this_order_notional) > buying_power × max_exposure_pct`? Reject `insufficient_buying_power`. `working_orders_notional` = sum over `alpaca_state.open_orders` of `qty × limit_price_or_last_price`.

### 9.2 Defaults

| Override field | Default if missing | Notes |
|---|---|---|
| `cooldown_seconds` | 30 | Per-card override |
| `daily_limit` | 5 | Per-card override (scalpers may need 50+) |
| `allow_collision` | false | Per-card override (hedge pairs) |
| `allow_naked_short` | false | Per-card override (short strategies) |
| `max_exposure_pct` (global) | 0.90 | Settings panel slider |

### 9.3 Alpaca state caching

`alpaca_state` is a small wrapper exposing `positions`, `open_orders`, `account` (buying_power, equity). Each batched with a 2-second cache so 10 cards firing close together don't slam the Alpaca API. Cache invalidated on every successful order submit so the next guardrail check sees the new position immediately.

### 9.4 Rejected orders

- Append to `alerts.jsonl` with `status: "guardrail_blocked"` + `reason: "<check_name>"`
- Fire `notify(CRITICAL, ...)` with: card_id, reason, the action attempted, current portfolio state at the time of block

## 10. Panic panel

### 10.1 Three buttons

```
🚨 PANIC
[ Pause All ]   [ Pause + Cancel Orders ]   [ Pause + Cancel + Flatten Positions ]
   (DISABLE)         (PANIC)                    (FLATTEN, 3s arm)
```

### 10.2 Confirm gates

| Level | Confirm word | Extra gate |
|---|---|---|
| L1 — Pause | "DISABLE" | none |
| L2 — Pause + Cancel | "PANIC" | none |
| L3 — Pause + Cancel + Flatten | "FLATTEN" | 3-second armed countdown after typing; button must be re-clicked after countdown |

### 10.3 Effects

| Level | Effect |
|---|---|
| L1 | All cards with `status: enabled` flipped to `disabled`. Receiver picks up via watcher. |
| L2 | L1 + iterate `list_orders(status='open')`, filter to those whose `client_order_id` starts with a known tradelab card_id, cancel each. Default behavior: tradelab-only cancellation. UI exposes a checkbox "Also cancel non-tradelab open orders" (default OFF) for the rare full-account-panic case. |
| L3 | L2 + iterate `list_positions()` and submit market sell orders to flatten each. Affects the WHOLE Alpaca account regardless of tradelab origin — there is no way to attribute positions to specific cards. UI tooltip makes this explicit. |

### 10.4 Audit + notification

Every panic event:
- Append to `panic_events.jsonl`: `{ts, level, before_state_snapshot, actions_taken, alpaca_responses}`
- Fire `notify(CRITICAL)` summarizing: cards disabled (count + ids), orders cancelled (count + ids), positions flattened (count + symbols + qty)

### 10.5 Re-arm

After panic: all cards are disabled. Re-enabling is the normal flow (toggle per card or bulk-enable). No magical "undo panic" in v1.

## 11. Backwards compatibility

### 11.1 Existing cards.json migration

Existing cards lack `cadence`, `last_fired_at`, `enabled_at`, `daily_limit`, `cooldown_seconds`, `allow_collision`, `allow_naked_short`. Receiver and launcher must default-fill missing fields:

```python
def _hydrate_card(card: dict) -> dict:
    return {
        "cadence": "daily",
        "last_fired_at": None,
        "last_attempted_at": None,
        "enabled_at": None,
        "daily_limit": 5,
        "cooldown_seconds": 30,
        "allow_collision": False,
        "allow_naked_short": False,
        **card,  # existing fields override defaults
    }
```

Apply on read. Persist back the hydrated form on next write (so existing cards gradually grow the new fields).

### 11.2 Drop the Session 3a safety guardrail

`cards.py:71-75` — the `status='disabled'` enforcement on `create()` was self-flagged for removal "when the toggle endpoint ships." Remove it now; PATCH endpoint is the toggle.

### 11.3 Existing receiver behavior unchanged for accepted webhooks

Card resolution + secret check + symbol match + Alpaca submit is unchanged structurally. Guardrails are inserted as a new step. Existing tests for the happy path should continue passing with appropriate guardrail-bypass mocks.

## 12. Testing strategy

### 12.1 Unit tests (pytest, follows existing pattern)

- `tests/live/test_cards_mutations.py` — update / delete / set_status / set_quantity round-trip; concurrency safety
- `tests/live/test_guardrails.py` — each guardrail in isolation (mocked alpaca state); override behavior; ordering of checks
- `tests/live/test_silence_checker.py` — threshold computation per cadence; trading-day arithmetic; one-notification-per-transition semantics
- `tests/live/test_notify.py` — channel isolation (one channel failure doesn't block others); severity routing; mocked transport per channel
- `tests/live/test_panic.py` — L1/L2/L3 effect; audit log written; confirm-token validation
- `tests/web/test_cards_handlers.py` — every new endpoint; auth / validation envelopes consistent with existing pattern
- `tests/web/test_receiver_status.py` — probe handles receiver-down gracefully

### 12.2 Integration tests

- File-watcher round-trip: launcher writes cards.json → receiver picks up reload within 500ms (allow generous slop on Windows)
- End-to-end panic L1 → receiver-side rejection: launcher hits /panic/pause → cards.json written → receiver reload → next webhook returns `card_disabled`

### 12.3 FE smoke (manual, since no FE test harness yet)

Per-card toggle, edit-quantity inline, delete with type-DELETE, bulk-toggle, bulk-delete, settings-panel persistence, panic L1/L2/L3 confirm gates, slide-pane recent alerts + Pine archive view.

### 12.4 Pytest baseline target

Maintain `413 passed / 0 failed` baseline; net-new tests should add roughly 40-60 new tests across the modules above.

## 13. Rollout plan (high-level — actual implementation plan TBD via writing-plans skill)

This is a ~12-15 day v1. Natural slices, dependency-ordered:

1. **Slice 1 — Read-only Live Trading tab + receiver hot-reload.** New tab renders cards.json; file watcher in receiver. No mutations yet. Validates the architecture end-to-end. ~2-3 days.
2. **Slice 2 — Mutations: toggle / quantity / delete (per-card and bulk).** PATCH/DELETE endpoints. Card-row UI active. ~2-3 days.
3. **Slice 3 — Position guardrails.** All five checks in receiver. Per-card override fields + UI. ~2-3 days.
4. **Slice 4 — Notification system + settings panel.** All channels + routing + test buttons + persisted config. ~2-3 days.
5. **Slice 5 — Silence detection.** Cadence picker + checker + threshold sliders. ~1-2 days.
6. **Slice 6 — Panic panel.** Three buttons + confirm gates + audit log + Alpaca cancel/flatten. ~2 days.
7. **Slice 7 — Daily email summary + polish + docs.** Including updating `TRADELAB_MANUAL.html` to reflect Direction A. ~1-2 days.

Each slice should be independently shippable + tested before starting the next.

## 14. Open questions for the implementation phase

These are not blockers for the spec but will need answers when writing the plan:

- Which `watchdog` API specifically — `Observer` polling vs `PollingObserver` for Windows reliability?
- ntfy.sh: pre-fill a default topic suggestion (e.g. `tradelab-<random>`) for the user, or blank field?
- Should the Live Trading tab default to "show enabled only" with a toggle for "show all"? Or always show grouped with disabled collapsed?
- Email digest: bundled HTML template or plaintext? (Plaintext is simpler; HTML lets us color the "X cards healthy" headline.)
- Per-card cooldown override field: 0 = disable cooldown? Or require explicit `cooldown_seconds: null`?

These are tactical and will get resolved in the implementation plan.

---

**End of spec.** Awaiting user review before invoking `writing-plans` skill.
