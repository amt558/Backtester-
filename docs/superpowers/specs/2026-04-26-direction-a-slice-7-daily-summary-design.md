# Direction A — Slice 7 — Daily Email Summary + Polish + Docs — Design

**Date:** 2026-04-26
**Author:** Brainstormed with Amit (active full-time trader, ~10 concurrent strategies)
**Status:** Spec — awaiting user review before implementation plan
**Parent spec:** `2026-04-25-direction-a-card-management-v1-design.md` (§13 closing slice)
**Predecessor:** `2026-04-26-DIRECTION-A-SLICE-6-COMPLETE.md`

---

## 1. One-liner

Close out Direction A v1 with: a daily 16:00 ET HTML email summarizing today's anomalies (panics, blocks, silent transitions, failures) and current system snapshot (cards, positions, open orders, receiver health); a dashboard preview surface so the format can be tested without waiting for market close; bundled cleanup of two carry-over architectural follow-ups (receiver guardrail Alpaca exception wrapping, JSONL rotation utility); and a `TRADELAB_MANUAL.html` rewrite covering Slices 1-7.

## 2. Scope

### In scope
- New `tradelab/live/daily_summary.py` — render + tick + start/stop, mirroring `silence_checker` shape.
- New `tradelab/live/jsonl_rotation.py` — generic rotation helper for the three append-only logs.
- New `tradelab/live/digest_state.json` — single-line state for idempotent same-day re-fire protection.
- Two new dashboard endpoints: `GET /tradelab/live/digest/preview` (renders today's HTML), `GET /tradelab/live/digest/state` (returns last-sent metadata).
- Settings panel additions in `command_center.html`: enabled toggle wire-up, send-time input, recipient display, [Refresh] preview button + inline iframe, "Last sent" status line.
- **Slice 5 follow-up #3 / Slice 4 follow-up #8** — wrap `build_alpaca_state()` in `receiver.py` with `try/except APIError`; on failure, reject the order with `reason="alpaca_unreachable"` and fire CRITICAL notify.
- **Slice 4 follow-up #1 / Slice 5 follow-up #10 / Slice 6 follow-up #2** — JSONL rotation utility applied to `alerts.jsonl`, `notify_events.jsonl`, `panic_events.jsonl` once per day after digest send.
- `TRADELAB_MANUAL.html` rewrite — six new sections covering Slices 1-6 + Slice 7 section + §3 architecture diagram refresh + §11 troubleshooting additions.
- Launcher wiring: boot `daily_summary` daemon thread alongside `notify_dispatcher` and `silence_checker`; atexit cleanup.
- Monday RTH smoke fixes (if any) for Slices 5+6 fold here.

### Out of scope (deferred)
- **P&L attribution per card.** Parent spec §3 non-goal — deferred to "Phase A.7".
- **Account-level P&L** (would need `alpaca_client.get_account()` wrapper). Tied to the same Phase A.7 deferral.
- **Per-strategy aggregates** in the digest. No clean definition of "strategy" beyond `card_id` exists yet.
- **Multi-day comparison / week-over-week trend reports.** This is a *daily* digest, not a weekly review.
- **Sent-digest history list / archive UI in dashboard** (Q5 option C). Deferred — inbox is the de-facto archive.
- **"Send now" button** in settings panel. Risks accidental sends + state-tracking complexity; the `POST /tradelab/live/config/test-notification` endpoint already proves the email channel works end-to-end.
- **Configurable `as_of` query param** on `/digest/preview`. v1 always renders for `now()`. Add `?as_of=YYYY-MM-DDTHH:MM:SSZ` later if "preview yesterday" becomes useful.
- **Catch-up email for missed send windows** (dispatcher down at 16:00 ET). Silent skip — if launcher was down at 16:00 ET, missed digest is the smallest of your problems.
- **Refactor silence_checker into a generic periodic_task framework.** YAGNI for two daemon threads; revisit at five.
- **Routing the digest through `notify(SEVERITY, ...)`.** Avoided to prevent recursive logging into `notify_events.jsonl` (digest content tallies that file). Direct `notify_channels.email.send()` instead.
- **Slice 6 follow-up #1** (panic POST envelope drift). Defer to a "unify envelope shape" pass when the next POST endpoint lands.
- **Slice 6 follow-up #4** (banner re-enable per-card PATCH loop). Works fine at 10-card scale.
- **Slice 6 follow-up #5** (L3 auto-abort countdown is wall-clock not data-driven). Not reported as confusing.
- **Headless-browser FE testing** (Slice 6 follow-up #6). FE contract tests remain static-pin only.

## 3. Architecture

### 3.1 Process placement

`daily_summary` runs in the **launcher process** (port 8877) — same process as `silence_checker` and `notify_dispatcher`. This is the natural home because:
- The launcher already imports the email channel module; the receiver does not need to.
- Idempotency state lives next to other launcher-owned state (`live_config.json`, `digest_state.json` in the same dir).
- Launcher is the long-lived process; receiver restarts more often.

The receiver process (port 8878) is untouched by the digest logic. F1 is the only receiver-side change in this slice.

### 3.2 Daemon thread lifecycle

Mirrors `silence_checker`:

```
daily_summary._thread (daemon)
  └─ _run_loop():
       while not _stop_evt.is_set():
           try: tick(datetime.now(ET))
           except Exception as e:
               print(f"[daily_summary] tick raised: {type(e).__name__}: {e}", file=sys.stderr)
           if _stop_evt.wait(TICK_SECONDS):  # interruptible 60s sleep
               break
```

`TICK_SECONDS = 60`. Most ticks are guard-skips (not trading day, before send time, already sent today, config disabled) — cheap. The one tick per trading day that actually fires the email is the only one that does work.

### 3.3 Send path — deliberately bypasses `notify()`

```
daily_summary.tick()
  └─ render(now)               -> (subject, html_body)   # pure
  └─ notify_channels.email.send(subject, html_body, to)  # direct
  └─ append INFO line to notify_events.jsonl directly    # audit, NO dispatcher
  └─ _persist_state({"last_sent_date": today_str})       # idempotency lock
```

Direct send is intentional — see §2 deferrals for why `notify(DIGEST, ...)` was rejected.

### 3.4 Idempotency state

`tradelab/live/digest_state.json`:
```json
{
  "last_sent_date": "2026-04-27",
  "last_sent_failed": false,
  "last_attempted_at": "2026-04-27T20:00:14.221+00:00",
  "attempts_today": 0
}
```

- `last_sent_date` is the only field that gates re-fire; the other three are diagnostic + retry tracking.
- `attempts_today` increments on each failed send attempt for today's window; reset to 0 once a different `last_sent_date` is being recorded (i.e., a new trading day).
- Atomic write via `os.replace()` (same pattern as `live_config._persist()`).
- Read fresh on every `tick()` — no in-memory cache (caching would complicate restart semantics).
- Gitignored. New file. No rotation needed (overwritten, never appended).
- On corrupt-file read: log to stderr, treat `last_sent_date` as missing → today's tick will fire (acceptable: re-sending an idempotency-corrupt-day digest is a tolerable failure mode).

### 3.5 Send-failure retry policy

When `notify_channels.email.send()` raises (SMTP unreachable, auth failure, network error):

1. Catch the exception. Do NOT update `last_sent_date` (so today's window remains "not sent").
2. Increment `attempts_today` and persist (with `last_sent_failed: true`, `last_attempted_at: now`).
3. Fire `notify(WARNING, "daily digest send failed", "<exception>", attempt=N)` so the user sees something in real-time.
4. Next tick (60s later) will retry — the gating logic only checks `last_sent_date == today`, not `attempts_today`.
5. **Retry cap:** when `attempts_today >= 5`, set `last_sent_date = today` anyway and write `last_sent_failed: true`. This breaks the retry loop for the day. The next 60s tick sees today is already "sent" and skips. Tomorrow starts fresh.
6. The retry-cap WARNING includes a "no further retries today" suffix in the body so the user knows manual intervention is needed.

This bounds the retry burst to 5 minutes of attempts (5 ticks × 60s) per day. Trades aggressive recovery against not spamming the SMTP relay during sustained outages.

## 4. Data sources for `render()`

All read-only, all paths exist:

| Source | Extracted | Read pattern |
|---|---|---|
| `panic_events.jsonl` | All entries with `ts` matching today's ET date | tail-read with skip-corrupt-trailing-line (Slice 6 T8 pattern) |
| `notify_events.jsonl` | Today's entries grouped by severity; silence-WARNING entries broken out separately | same tail-read |
| `alerts.jsonl` | Today's entries by `status`: `order_submitted`, `order_failed`, `guardrail_blocked` | same tail-read |
| `cards.json` | Total / enabled / disabled counts | `CardRegistry.list_all()` |
| `silence_checker._silent_cards` | Currently silent set | module-level read (same process) |
| `alpaca_client.list_positions()` | Open positions (symbol, qty, side) | wrapped `try/except APIError` → empty list on failure |
| `alpaca_client.list_open_orders()` | Open orders (symbol, qty, side, status) | wrapped `try/except APIError` → empty list on failure |
| `live_config.notifications.smtp.to_address` | Recipient email | `live_config.get()` |
| `live_config.email_digest.send_time` | Render-time threshold check | `live_config.get()` |

"Today" = midnight-to-now in `America/New_York`, computed from `now`. NOT UTC. `trading_calendar.is_trading_day()` (shipped in Slice 5) determines whether to skip.

## 5. Render contract

### 5.1 Subject line

Pattern:
- All-clear: `"tradelab daily — 2026-04-27 — all clear"`
- With anomalies: `"tradelab daily — 2026-04-27 — 1 panic, 3 blocks"` (most-severe-first, top 2 categories)

### 5.2 HTML body structure

```html
<div class="tradelab-digest">
  <div class="subj">tradelab daily — YYYY-MM-DD — <subject_tail></div>

  <h4>⚠ Anomalies (N)</h4>             [render only if N > 0]
    <ul>
      <li><span class="badge badge-crit">PANIC L1</span> 14:22 ET — 8 cards disabled</li>
      <li><span class="badge badge-crit">BLOCK</span> 3 guardrail blocks: <code>card-id</code> ×N (reason)</li>
      <li><span class="badge badge-warn">SILENT</span> 1 silent transition: <code>card-id</code></li>
      ...
    </ul>
    <p class="meta">No order failures · no receiver downtime · no ngrok URL changes</p>

  <h4>📊 Health snapshot (now)</h4>
    <p><strong>Cards:</strong> 12 total · 8 enabled · 3 disabled · 1 silent</p>
    <p><strong>Today:</strong> 14 order submissions · 4 CRITICAL / 2 WARNING / 11 INFO notifications</p>
    <p><strong>Receiver:</strong> up, 8h 22m · <strong>ngrok:</strong> abc123.ngrok-free.app</p>

    <p><strong>Open positions (N)</strong></p>
    <table>...</table>                    [empty-state line if N=0]

    <p><strong>Open orders (N)</strong></p>
    <table>...</table>                    [empty-state line if N=0]

  <p class="meta">tradelab · end of summary</p>
</div>
```

**Note on the snippet above:** the `class="badge badge-crit"` and similar attributes are shown for readability. Actual generated HTML uses **inline `style="..."` attributes** on each element — no `<style>` block, no class-to-style mapping, no external CSS. This is required for email-client compatibility (Gmail strips `<style>` blocks that aren't in `<head>`; Outlook ignores classes in many contexts).

Color palette used in inline styles: `#d32f2f` (crit), `#f57c00` (warn), `#388e3c` (ok), `#1a1a1a` (text), `#888` (meta), `#f7f7f7` (table-header bg).

### 5.3 Plaintext fallback

Multipart MIME message: HTML body as primary, plaintext rendering as alternative part. Plaintext is a deterministic transformation of the HTML (strip tags, replace `<table>` rows with column-aligned text, keep section headers). Renders identically to the Approach A "plaintext" mockup shown during brainstorming.

### 5.4 "All clear" rendering

If anomaly count = 0, the Anomalies section header line reads `<h4 style="color:#388e3c">✓ No anomalies today</h4>` followed directly by the Health snapshot. No empty-bullets section.

### 5.5 Section-level error handling

Each of the 6 anomaly types and 7 snapshot fields is rendered in a `try` block. On failure: that field renders as `[error: <type>]` placeholder; the rest of the email continues. Error is logged to stderr and counted in a per-render `errors_caught` int that, if non-zero, appends a footer line `⚠ N section(s) failed to render — check stderr`.

## 6. New endpoints

Both live in `tradelab/web/handlers.py`, registered under `/tradelab/live/digest/*`.

| Method | Path | Returns | Side effects |
|---|---|---|---|
| GET | `/tradelab/live/digest/preview` | `Content-Type: text/html` — full rendered body from `render(datetime.now(ET))` | None. Pure render. Does not send, does not write state, does not log. |
| GET | `/tradelab/live/digest/state` | JSON `{"error": null, "data": {"last_sent_date": ..., "last_sent_failed": ..., "last_attempted_at": ...}}` | None. Reads `digest_state.json`. |

Both use the standard envelope helper (`_ok()`) for the JSON endpoint. `/preview` returns raw HTML (200 on success, 500 with error body on render failure).

Auth: none, matching other `/tradelab/live/*` endpoints (dashboard same-origin).

## 7. Frontend — settings panel additions

### 7.1 Layout

The Email Digest section in the settings panel already exists from Slice 4 (with `enabled` toggle and `send_time` input scaffolded). Slice 7 wires those to PATCH `/tradelab/live/config` and adds:

```
┌── Email Digest ─────────────────────────────────────────┐
│  ☐ Enabled                                               │
│  Send time:  [16:00]  ET                                 │
│  Recipient:  aaasharma@gmail.com  (read-only, from SMTP) │
│                                                          │
│  [ 🔄 Refresh preview ]                                  │
│  ┌──────────────────────────────────────────────────┐   │
│  │  <iframe srcdoc="<rendered html>" 480px tall>    │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  Last sent: 2026-04-27 16:00 ET (state file: OK)        │
└──────────────────────────────────────────────────────────┘
```

### 7.2 JS functions added (vanilla, in existing settings-panel IIFE)

- `loadDigestPreview()` — fetches `/tradelab/live/digest/preview`, sets `iframe.srcdoc = response.text`. On HTTP error: shows "Preview failed: <status>" inline.
- `loadDigestState()` — fetches `/tradelab/live/digest/state`, updates "Last sent" label. Called on settings-panel open + after manual digest fires (out of scope — only called once on panel open in v1).
- Wire-ups for the existing `enabled` toggle + `send_time` input → PATCH `/tradelab/live/config` with the appropriate sub-block.

### 7.3 No auto-refresh

The `[Refresh preview]` button is the only path that loads preview HTML. Initial state: empty iframe with placeholder text "Click [Refresh preview] to load." Reasoning: each preview triggers two Alpaca API calls (positions + orders); auto-loading on settings-panel open would burn quota on every panel toggle.

## 8. Backwards compatibility

### 8.1 `live_config.json`

The `email_digest` block already exists from Slice 4 (`{enabled: false, send_time: "16:00"}`). Slice 7 reads it as-is — no migration needed.

The new optional `jsonl_rotation` block is read with explicit defaults:
```python
max_size_mb   = live_config.get("jsonl_rotation.max_size_mb", 50)
keep_archives = live_config.get("jsonl_rotation.keep_archives", 5)
```
Existing `live_config.json` files without the block work transparently. Settings panel does NOT expose these — they're advanced knobs.

### 8.2 `digest_state.json`

New file. Missing-file case treated identically to corrupt-file case — `last_sent_date` is None → today's tick fires. No migration needed; first run on a trading day creates the file.

### 8.3 No existing endpoint contracts changed

`/tradelab/live/digest/preview` and `/tradelab/live/digest/state` are new paths. F1's receiver change adds a new rejection reason (`alpaca_unreachable`) but doesn't alter the existing rejection envelope shape.

## 9. Bundled architectural follow-ups

### 9.1 F1 — Receiver guardrail Alpaca exception wrapping

**Source:** Slice 4 follow-up #8 → Slice 5 follow-up #3 → carried forward to Slice 6 (which only wrapped `panic.py`).

**File:** `tradelab/live/receiver.py` — wrap `build_alpaca_state()` (or whichever helper constructs `alpaca_state` for `check_guardrails()`).

**Behavior:**
```python
try:
    alpaca_state = build_alpaca_state()
except APIError as e:
    notify(CRITICAL, "alpaca state fetch failed",
           f"card={card_id} action={action}: {e}",
           card_id=card_id)
    return _reject(card_id, "alpaca_unreachable", str(e))
```

**Fail mode:** fail-closed. The trading path's safety stance is "if we can't read state, we don't trade." A new rejection reason `alpaca_unreachable` joins the existing set (`cooldown_active`, `daily_limit_exceeded`, `symbol_collision`, `no_position_to_sell`, `insufficient_buying_power`).

### 9.2 F2 — JSONL rotation utility

**Source:** Slice 4 follow-up #1 → Slice 5 follow-up #10 → Slice 6 follow-up #2.

**Module:** `tradelab/live/jsonl_rotation.py`

**API:**
```python
def rotate_if_needed(path: Path, max_size_mb: int = 50, keep_archives: int = 5) -> Optional[Path]:
    """If path exceeds max_size_mb, rename to path.YYYY-MM-DD.N.jsonl.gz and start fresh.
    Keep at most `keep_archives` rotated files; delete oldest.
    No-op if file is missing or under threshold. Returns rotated archive path or None.
    Best-effort: catches OSError, logs to stderr, never raises."""

def rotate_all() -> dict[str, Optional[Path]]:
    """Calls rotate_if_needed on alerts.jsonl, notify_events.jsonl, panic_events.jsonl.
    Returns map of name -> result for logging."""
```

**Compression:** rotated files are gzipped (`.jsonl.gz`). Stdlib `gzip.open()` for read-back. ~10× size reduction on text logs.

**Cadence:** `daily_summary.tick()` calls `rotate_all()` once per day, after a successful email send. Re-uses the daily_summary daemon thread — avoids a third periodic-task thread.

**Naming:** `<basename>.YYYY-MM-DD.N.jsonl.gz` where N is 0 for the first rotation in a given day, 1 for second, etc. Date is the rotation date in ET. The N suffix protects against multiple rotations in the same day (corner case if multiple log floods happen).

**Archive cap:** when rotation makes the count exceed `keep_archives`, the oldest archive (by mtime) is deleted. Best-effort delete.

**Reading rotated files:** existing tail-read helpers (used by digest render) operate on the live `.jsonl` only — they don't sift through archives. This is intentional: the digest reports on TODAY, and TODAY's events are always in the live file (rotation only happens after digest send).

## 10. Manual update — `TRADELAB_MANUAL.html`

### 10.1 Insertion structure

Current manual: §1-9 + §10 TradingView Alerts + §11 Troubleshooting + Glossary.

New structure: §1-9 + **NEW §10-16 Live Trading & Operations group** + renumbered §17 TradingView Alerts + §18 Troubleshooting + Glossary.

### 10.2 New sections

| § | Title | Source slice | Source done doc |
|---|---|---|---|
| 10 | Live Trading tab | Slice 1 | `2026-04-25-DIRECTION-A-SLICE-1-COMPLETE.md` |
| 11 | Card mutations from UI | Slice 2 | `2026-04-25-DIRECTION-A-SLICE-2-COMPLETE.md` |
| 12 | Position guardrails | Slice 3 | `2026-04-25-DIRECTION-A-SLICE-3-COMPLETE.md` |
| 13 | Notification system | Slice 4 | `2026-04-25-DIRECTION-A-SLICE-4-COMPLETE.md` |
| 14 | Silence detection | Slice 5 | `2026-04-25-DIRECTION-A-SLICE-5-COMPLETE.md` |
| 15 | Panic Panel | Slice 6 | `2026-04-26-DIRECTION-A-SLICE-6-COMPLETE.md` |
| 16 | Daily Email Summary | Slice 7 (this slice) | done doc written after Slice 7 ships |

### 10.3 Updates to existing sections

- **§3 Architecture** — refresh diagram to include the Live tab, new endpoints, and the launcher daemon threads (notify_dispatcher, silence_checker, daily_summary).
- **§18 Troubleshooting** — append ~5 entries from Slices 1-6 known gotchas:
  - silence multipliers null → silent no-op
  - panic POST envelope shape (mention as known minor inconsistency)
  - banner localStorage dismissal sticks across page refresh (intentional)
  - PowerShell UTF-8 BOM gotcha (already-known reference memory)
  - `digest_state.json` permission errors → silent skip with stderr log

### 10.4 Style

Match existing manual voice: practical, "you" address, code blocks for commands, troubleshooting style for §18 entries. No marketing fluff. Each new section follows the existing `<h2 id="...">` + `<h3>` pattern.

## 11. Testing strategy

### 11.1 New test files

| File | Coverage | Approx tests |
|---|---|---|
| `tests/live/test_daily_summary_render.py` | `render()` pure function: subject formatting (all-clear vs with-anomalies), all 6 anomaly types, snapshot section, error-section degradation, ET timezone correctness, malformed jsonl handling | 12-15 |
| `tests/live/test_daily_summary_tick.py` | `tick()` gating: not-trading-day skip, before-send-time skip, disabled-config skip, idempotency (already-sent today), retry-after-failure, retry-cap (5 attempts/day max) | 8-10 |
| `tests/live/test_daily_summary_state.py` | State file: atomic write, read-on-startup, corrupt-file recovery, restart idempotency | 4-5 |
| `tests/live/test_jsonl_rotation.py` | Rotation: under-threshold no-op, over-threshold rotates with .gz, archive cap (oldest deleted), OSError swallowed, missing-file no-op, three-file `rotate_all` integration, naming collision (multiple rotations same day) | 8-10 |
| `tests/live/test_receiver_alpaca_wrap.py` | F1: APIError on `build_alpaca_state` → reject + notify CRITICAL; happy path unchanged; reason envelope shape | 2-3 |
| `tests/web/test_digest_handlers.py` | GET /preview returns HTML 200 with expected markers, GET /state returns expected JSON envelope, render-error → 500 envelope, missing state file → JSON `data: null` | 4-6 |
| `tests/web/test_digest_fe_contract.py` | FE contract: `loadDigestPreview` JS function present in served HTML, settings-panel iframe markup present, [Refresh preview] button present, "Last sent" status line container present | 4-5 |

**Net new tests: ~42-54.**

### 11.2 Pytest baseline target

- Pre-Slice-7: 709 passed / 0 failed (Slice 6 closing baseline)
- Post-Slice-7 target: **~755 passed / 0 failed** (+45 net new, allowing ~10 new tests to refactor or add assertions to existing files without net-new file growth)

### 11.3 Live smoke (deferred to next trading day after Slice 7 ships)

- Enable digest in settings, set send_time to ~5min from now
- Wait for fire → check inbox → verify HTML renders correctly in Gmail web AND Gmail mobile
- Verify `digest_state.json` contains today's date
- Restart launcher within same day → verify NO duplicate email (state file gates re-fire)
- Force render error (corrupt one jsonl) → verify section degrades to `[error: ...]`, email still ships
- Verify rotation: artificially grow `notify_events.jsonl` past 50MB → next digest tick rotates → archive `.gz` exists → tail-read still works on fresh empty file
- Verify F1: temporarily break Alpaca paper creds → fire a webhook → receiver returns `alpaca_unreachable` rejection + CRITICAL notify

## 12. Files modified or added

| File | Change |
|---|---|
| `tradelab/live/daily_summary.py` | NEW — render + tick + start/stop + send + state-persist |
| `tradelab/live/jsonl_rotation.py` | NEW — rotate_if_needed + rotate_all + .gz handling |
| `tradelab/live/digest_state.json` | NEW (gitignored) — `{last_sent_date, last_sent_failed, last_attempted_at}` |
| `tradelab/live/receiver.py` | F1 — wrap `build_alpaca_state()` Alpaca call, add `alpaca_unreachable` rejection |
| `tradelab/web/handlers.py` | NEW endpoints: GET /digest/preview + GET /digest/state |
| `launch_dashboard.py` (parent repo) | Boot `daily_summary.start()` + `atexit.register(daily_summary.stop)` |
| `command_center.html` (parent repo) | Email Digest section: enabled toggle wire-up, send-time input wire-up, recipient display, [Refresh preview] button, iframe, "Last sent" line, JS functions `loadDigestPreview()` + `loadDigestState()` |
| `live_config.json` | Optional `jsonl_rotation` block (defaults work without it; not exposed in settings panel) |
| `TRADELAB_MANUAL.html` (parent repo) | 7 new sections (§10-16) + §3/§18 updates |
| `tests/live/test_daily_summary_render.py` | NEW |
| `tests/live/test_daily_summary_tick.py` | NEW |
| `tests/live/test_daily_summary_state.py` | NEW |
| `tests/live/test_jsonl_rotation.py` | NEW |
| `tests/live/test_receiver_alpaca_wrap.py` | NEW |
| `tests/web/test_digest_handlers.py` | NEW |
| `tests/web/test_digest_fe_contract.py` | NEW |
| `.gitignore` (tradelab) | Add `digest_state.json` to `live/` ignore list (alongside `live_config.json`) |

## 13. Estimated effort

| Work | Hours |
|---|---|
| daily_summary core (render + tick + state + send) | 4-6 |
| Preview + state endpoints | 1-2 |
| FE preview wire-up + iframe | 2-3 |
| F1 receiver Alpaca wrap | 1-2 |
| F2 jsonl rotation utility | 3-4 |
| Manual update | 4-6 |
| Tests across all of above | 4-6 |
| **Total** | **~19-29 hr (realistic 2-3 trading days)** |

Slightly over parent spec's "1-2 days" estimate; the bundled F1+F2 add ~5-7 hours but they're the last natural touch-points before v1 freeze.

## 14. Rollout

### 14.1 Launcher wiring

`launch_dashboard.py` boots three daemons after the receiver health probe:
```python
notify_dispatcher.start()      # existing (Slice 4)
silence_checker.start()        # existing (Slice 5)
daily_summary.start()          # NEW

atexit.register(notify_dispatcher.stop)
atexit.register(silence_checker.stop)
atexit.register(daily_summary.stop)   # NEW
```

Boot order doesn't matter; all three are idempotent and isolated.

### 14.2 Default-off

`live_config.json` ships with `email_digest.enabled = false`. Slice 7 does NOT change this. The user must enable explicitly via the settings panel after verifying SMTP creds work (via the existing `POST /tradelab/live/config/test-notification` flow).

### 14.3 No data migration

All Slice 7 changes are additive. Existing `live_config.json`, `cards.json`, and the three jsonl files work unchanged.

## 15. Open questions for the implementation phase

Tactical, will get resolved when writing the plan:

1. **Plaintext fallback structure** — generate from HTML via a tiny tag-stripper, or maintain a parallel template? (Plan can choose; tag-stripper is simpler if it preserves table column alignment.)
2. **Iframe height** — 480px static (mockup default) vs auto-resize via `postMessage` from the iframe. Static is fine for v1; auto-resize is polish.
3. **F2 rotation date format** — `YYYY-MM-DD` vs `YYYYMMDD` in archive filenames. Plan picks one; either works.
4. **F2 first-rotation race** — if launcher boots and `rotate_all()` runs same day as a previous rotation, the N suffix needs to look at existing archives to compute next N. Detail for the plan.
5. **F1 — exact `build_alpaca_state` location** — receiver code structure may require introducing the helper if it doesn't exist yet (current receiver may inline these calls). Plan to confirm.
6. **Subject-line ordering precedence when ≥3 anomaly types are present** — §5.1 says "top 2 categories most-severe-first" but doesn't define severity ordering across the 6 anomaly types. Plan picks one (suggested: PANIC > BLOCK > FAIL > DOWNTIME > NGROK > SILENT).
7. **Notify-event audit row schema** — §3.3 says digest sends append an INFO line directly to `notify_events.jsonl`. Plan defines the exact schema (e.g., `{"ts": ..., "severity": "INFO", "title": "daily_digest_sent", "body": "...", "event_type": "daily_digest_sent"}`).

These are not blockers for the spec but will need answers when writing the plan.

---

**End of Slice 7 spec.**
