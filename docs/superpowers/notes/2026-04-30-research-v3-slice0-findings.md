# Research Tab v3 — Slice 0 Findings

**Date:** 2026-04-30
**Purpose:** Gate-check before Slice 4 (activation backend). Avoid duplicating `approve_strategy.py`.

---

## 1. approve_strategy.py survey

**File:** `tradelab/src/tradelab/web/approve_strategy.py`

### What it exposes

Two pure functions (no HTTP, no global singletons — handlers in `handlers.py` own routing):

**`score_csv(...) -> dict`** (lines 77–134)
- Parses a TradingView CSV, scores it, writes a report folder, records an audit row.
- Returns: `verdict`, `signals`, `dsr_probability`, `scoring_run_id`, `report_folder`, `n_trades`, `start_date`, `end_date`, `metrics`, `pine_lints`.
- Does **not** write to `cards.json`.

**`accept_scored(...) -> dict`** (lines 145–254)
- Promotes a scored report folder to an immutable card + pine_archive record.
- Writes to:
  1. `pine_archive/<card_id>/strategy.pine` (copy from report folder)
  2. `pine_archive/<card_id>/tv_trades.csv` (copy)
  3. `pine_archive/<card_id>/returns.csv` (derived daily-return series)
  4. `pine_archive/<card_id>/verdict.json` (snapshot of scoring metadata)
  5. **`cards.json`** — via `registry.create(card_id, card)` (line 244)
- The card written to `cards.json` has these fields: `card_id`, `secret`, `symbol`, `status="disabled"`, `quantity=None`, `created_at`, `base_name`, `version`, `timeframe`, `verdict`, `dsr_probability`, `report_folder`, `pine_archive_path`, `scoring_run_id`.
- **No robustness gate** — it writes the card regardless of verdict ("ROBUST", "INCONCLUSIVE", or "FRAGILE"). The verdict string is recorded but not used as a gate.
- Has `exist_ok=False` on the pine archive mkdir → raises `FileExistsError` on duplicate (HTTP 409 in handler).
- Has rollback: if `registry.create` fails, it removes the pine archive dir.

### Routes in handlers.py

- `POST /tradelab/score` (line 893) → calls `score_csv()`
- `POST /tradelab/accept` (line 920) → calls `accept_scored()`

### Current callers in the UI

`command_center.html` is served from `C:/TradingScripts/` (the parent repo), not from within `tradelab/src/`. There is no `command_center.html` inside the tradelab repo. The `/tradelab/score` and `/tradelab/accept` routes are called by the **Research tab** of `command_center.html` (the Option H Score/Accept modal flow). Verified by grepping `command_center.html` in `C:/TradingScripts/` — the `accept_scored` flow there triggers `/tradelab/accept`. The dashboard's Research tab (v1, merged 2026-04-22) calls these two endpoints.

### What accept_scored does vs. what "Activate" needs to do

`accept_scored` = **Score → Accept** (the existing v1 flow). It:
1. Promotes a scored run to a versioned card entry in `cards.json`.
2. Sets `status = "disabled"` by default.

Research v3 "Activate" = promote a **researched run directly to an enabled card** with `status = "enabled"`. This is a different operation but shares the same write target (`cards.json` via `CardRegistry`).

---

## 2. cards_view.py survey

**File:** `tradelab/src/tradelab/web/cards_view.py`

### Purpose

Pure-function aggregator for the Live Trading tab. Does **not** write to `cards.json`. Only reads.

### Schema of card entries in cards.json

Inferred from `accept_scored` write (confirmed against live `tradelab/live/cards.json`):

| Field | Type | Notes |
|---|---|---|
| `card_id` | str | `{base_name}-v{n}` |
| `secret` | str | 32-char url-safe token |
| `symbol` | str | e.g. "AMZN" |
| `status` | str | `"enabled"` or `"disabled"` |
| `quantity` | int or null | null until manually set |
| `created_at` | ISO-8601 str | UTC |
| `base_name` | str | strategy family name |
| `version` | int | monotone per base_name |
| `timeframe` | str | e.g. "1H" |
| `verdict` | str | scoring verdict at accept time |
| `dsr_probability` | float or null | |
| `report_folder` | str | path to scoring report |
| `pine_archive_path` | str | path to immutable pine archive |
| `scoring_run_id` | str | audit row ID |

**No existing `activated_*` fields** in the schema. The v3 plan adds `activated_verdict` and `activated_at` — these will be net-new fields.

### Read paths

- `list_cards_view(cards, alerts_log)` (line 146) — used by `GET /tradelab/cards`; enriches cards with `last_status` and `fires_24h` from `alerts.jsonl`.
- `group_by_base_name(cards)` (line 88) — groups cards by family for display.
- `derive_last_status`, `derive_fire_counts`, `tail_alerts_for_card` — all read-only from `alerts.jsonl`.

### No write paths in cards_view.py

`cards_view.py` is purely a read/derivation module. Safe to ignore for write-path collision analysis.

---

## 3. Class B (S2/S4/S7/S8/S10/S12) enable-list

### File location

**`C:/TradingScripts/alpaca_config.json`** (gitignored in the parent `C:/TradingScripts/` repo)

This is a single JSON file shared between:
- `alpaca_trading_bot.py` (reads at startup, re-reads `kill_switch` on each daily scan at line 636)
- `launch_dashboard.py` `/config` handler (reads + writes via `write_config()` at line 375)
- `tradelab/src/tradelab/live/alpaca_client.py` (hardcoded path `CONFIG_PATH = Path("C:/TradingScripts/alpaca_config.json")`)
- `tradelab/src/tradelab/regime/banner.py` (reads once, cached)

### Schema (strategies array)

```json
{
  "strategies": [
    {
      "name": "S4_InsideDayBreakout",
      "module": "s4_inside_day_breakout",
      "enabled": true,
      "capital_allocation": 25000,
      "allocation_pct": 25,
      "max_positions": 5,
      "role": "core_alpha"
    }
  ],
  "disabled_strategies": []
}
```

**Enable flag:** Two overlapping mechanisms:

1. `strategies[i].enabled` — read by `AlpacaBotConfig.strategies` property and filtered in `load_all_strategies()` (`alpaca_trading_bot.py` line 368): `if strat_cfg.get('enabled', True)`.
2. `disabled_strategies` array — checked per-signal at execution time (line 788): `if strategy in disabled`. This is the mechanism the dashboard Overview tab uses via `POST /config` with `{disabled_strategies: [...]}` (written by `launch_dashboard.py`).

In practice the dashboard only writes `disabled_strategies`; it does not toggle `strategies[i].enabled`. The `enabled` field is set manually.

### Reload mechanism

The bot (`alpaca_trading_bot.py`) is a **one-shot script** — it does not poll or watchdog `alpaca_config.json`. It reads config once at `__init__` (line 38) and only re-reads `kill_switch` on each `run_daily_scan()` call (line 636). Strategy `disabled_strategies` is re-read on each `_execute_entries()` call (line 788) by directly reading `self.config.data` which was loaded at init.

**Important:** `self.config.data` is the in-memory dict from startup. The `disabled_strategies` check reads the **in-memory** dict, not the file. The bot must be restarted to pick up `strategies[i].enabled` changes. The `disabled_strategies` path also only works if the bot re-reads the file — looking at the code more carefully, line 788 does `self.config.data.get('disabled_strategies', [])` which is the in-memory dict. **Conclusion: the bot reads `alpaca_config.json` once at startup; there is no watchdog or hot-reload for the strategies list.** A restart is required for changes to take effect.

The `launch_dashboard.py` write at line 408 is a plain `open(path, "w") + json.dump()` — **not atomic** (no write-then-rename). This is an existing gap but out of scope for this task.

---

## 4. Activation routing decision

**Class A (Pine cards):**

`accept_scored` in `approve_strategy.py` is the existing "Score → Accept" path: it writes a disabled card to `cards.json`. The v3 "Activate" button must do something different in degree, not in kind — it should either (a) call `accept_scored` then immediately PATCH the card to `status="enabled"`, or (b) extend `accept_scored` with an optional `activate=True` flag that sets `status="enabled"` and stamps `activated_at`/`activated_verdict` fields directly in the create call. **Recommendation: extend `approve_strategy.accept_scored`** rather than writing a separate `activation.py`. The plan's Slice 4 task should be renamed from "write `activation.py`" to "extend `accept_scored` with activation path." Specifically: add an `activate: bool = False` parameter; when `True`, set `status="enabled"` and include `activated_at` (ISO-8601 UTC) and `activated_verdict` (snapshot of verdict at activation time) in the card dict. Add a duplicate-card 409 check — this already exists implicitly via `CardExistsError` from `registry.create`, but Slice 4 should confirm the handler surfaces it cleanly. There is no verdict gate in the current code; whether to add one (e.g., refuse activation of FRAGILE) should be decided in the Slice 4 spec, not assumed.

**Class B (bot strategies):**

Write target: **`C:/TradingScripts/alpaca_config.json`**, `strategies[i].enabled` field (and/or `disabled_strategies` array). Because the bot is a one-shot script with no watchdog, writing to `alpaca_config.json` will take effect only at the **next bot startup** — this is acceptable and should be documented in the UI. The existing `launch_dashboard.py` write path (`write_config()` at line 375) already handles `disabled_strategies` writes; Slice 18 should route Class B activation through a new tradelab endpoint that calls the same logic (or delegates to `launch_dashboard.py`'s `/config` POST). The write is currently non-atomic (plain overwrite); for Slice 18, use a write-then-rename pattern to avoid a torn file if the bot happens to be reading concurrently. Since the bot re-reads only `kill_switch` during a scan (not `strategies`), the race window is small but not zero.

---

## 5. Plan amendments

**Slice 4 rename:** Change "write `activation.py` from scratch" to "extend `approve_strategy.accept_scored`." The new parameter signature should be:

```python
def accept_scored(
    *,
    base_name: str,
    symbol: str,
    timeframe: str,
    report_folder: str,
    verdict: str,
    dsr_probability: Optional[float],
    scoring_run_id: str,
    registry: CardRegistry,
    pine_archive_root: Path = Path("pine_archive"),
    reports_root: Path = Path("reports"),
    activate: bool = False,          # NEW — if True, status="enabled" + stamps activated_* fields
) -> dict:
```

When `activate=True`, the card dict written to `cards.json` (currently assembled at lines 228–243) gains two new fields: `activated_at` (same timestamp as `created_at`) and `activated_verdict` (same as `verdict`), and `status` is set to `"enabled"` instead of `"disabled"`. The return dict (lines 250–254) should include `activated_at` so the frontend can render confirmation.

**Slice 4 handler:** `POST /tradelab/accept` in `handlers.py` (line 920) needs a new `activate` boolean in the validated payload (`_validate_accept_payload` at line 1435) — default `False` for backward compat.

**Slice 4 tests:** `test_approve_strategy.py` already tests `accept_scored` happy path (card lands as `disabled`). Slice 4 must add a test for `activate=True` that asserts `status=="enabled"`, `activated_at` is present, and `activated_verdict` matches `verdict`.

**Slice 18 (Class B):** Write target is `C:/TradingScripts/alpaca_config.json`. The enable-list field to toggle is `strategies[i].enabled` (not just `disabled_strategies`). Use write-then-rename for atomicity. Document in the UI that changes take effect at next bot startup (no hot-reload). Consider whether to expose this as a new endpoint in tradelab handlers or proxy through `launch_dashboard.py`'s existing `/config` POST — the latter avoids duplicate write paths to `alpaca_config.json` but couples tradelab to the parent dashboard's HTTP server.

**No `activation.py` should be created.** If the plan document references `activation.py` as a new file, that reference should be removed; the correct home for all Class A activation logic is `approve_strategy.py`.
