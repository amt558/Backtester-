# Phase 4 — Python Strategy Paper-Execution Engine — Design Spec

**Date:** 2026-05-31
**Status:** Approved (design)
**Branch:** `feat/research-tab-v3`

## Goal

A daemon that makes **enabled Python cards actually trade — on paper** — by reconciling each strategy's desired position against the live Alpaca account. Paper-locked until the user explicitly flips to live.

## Confirmed decisions (user, 2026-05-31)

1. **Sizing = card-level dollar allocation.** The user sets `allocation_usd` per strategy on the card. Order qty = `floor(allocation_usd / latest_price)`. No %-of-capital, no global sizing.
2. **Exits = authored in the Python strategy code.** The engine does NOT implement a trailing-stop state machine. The strategy's `generate_signals` expresses both entry and exit; the engine just executes the desired position.
3. **Safety = the existing Command Center controls.** Reuse the **$5k max daily drawdown** (`daily_loss_limit` in `alpaca_config.json`) + `kill_switch`. Do not build a parallel safety system.
4. **Cadence = the strategy's `timeframe`.** The Python strategy declares its timeframe; the engine schedules each card on that bar-close cadence.

## Architecture — desired-state reconciler

A new daemon `tradelab/live/strategy_runner.py` (started by `launch_dashboard.py` alongside `receiver`/`notify_dispatcher`/`silence_checker`, with `start()`/`stop()`), loops on a tick. Each tick, for every **enabled, `source:"python"`, `mode:"paper"`** card whose `timeframe` bar has just closed:

1. **Refresh data** for the card's `symbol` at its `timeframe` via the Twelve Data → parquet cache (`marketdata.download_symbols`, cache-only constraint; refresh so the latest closed bar is present).
2. **Run the strategy:** `instantiate_strategy(card["strategy"])`, `enrich`, `generate_signals` → take the **latest closed bar**.
3. **Compute desired position** for `card["symbol"]` from that bar (the live contract, below).
4. **Read actual position** from Alpaca (`TradingClient.get_open_position` / positions).
5. **Reconcile** (idempotent): desired long & flat → BUY `qty`; desired flat & long → SELL to close. Already-in-desired-state → no-op (never double-fire).
6. **Record** the attempt/fire (reuse the `CardRuntimeState` + `alerts.jsonl` pattern from `receiver.py`).

### Live signal contract (how Python code "handles exits")

The engine reads the latest closed bar's columns from `generate_signals`:
- `buy_signal == True` → desired = **long**.
- `sell_signal == True` (or `exit_signal == True`) → desired = **flat**.
- Neither → **hold** (no change to current position).
This puts entry AND exit fully in the strategy's Python code. A strategy intended for live use SHOULD emit `sell_signal`; if it never emits an exit, the position is held until the strategy says to exit (the engine will not invent one). `entry_stop`, if present, MAY additionally be submitted as a protective stop order (follow-up; v1 is market-in/market-out on signals).

## Order primitive

`tradelab/live/alpaca_client.submit_market_order(client, symbol, qty, side, client_order_id)` with `get_client()` (which already honors `alpaca.paper_trading`). `client_order_id` = deterministic `{card_id}-{bar_date}-{side}` for idempotency/dedup at the broker.

## Safety gates (checked before EVERY order; any failure → skip, log, do not trade)

1. **Paper-lock:** refuse to place ANY order unless `alpaca_config.json::alpaca.paper_trading == True`. (Hard stop until the user explicitly goes live — a separate, deliberate flip.)
2. **Kill switch:** `trading.kill_switch == True` → halt all trading.
3. **Max daily drawdown:** if today's realized P&L ≤ `trading.daily_loss_limit` (−5000) → halt all new entries (exits still allowed to de-risk).
4. **Per-card guard:** reuse the existing cadence/cooldown/daily-limit `CardRuntimeState` so one card can't spam orders.
5. **Card validation:** skip cards missing `allocation_usd` (or ≤ 0), missing `strategy`/`symbol`, or whose `strategy` isn't in the registry — log and continue.

## Card schema additions

`accept_python_run` (Phase 3a) already stamps `mode:"paper"`, `source:"python"`, `strategy`, `symbol`, `timeframe`. Phase 4 adds:
- `allocation_usd: float | null` — user-set $ allocation; the engine sizes from it (null/0 → card does not trade).
A small Overview-card input lets the user set it (`PATCH`/update via the existing card-update path).

## Out of scope (follow-ups)

- Live trading (real money) — a separate explicit flip of `paper_trading` + a go-live confirmation; NOT this phase.
- Trailing-stop / bracket parity, partial fills, multi-symbol portfolio strategies (one card = one symbol for v1).
- Backfilling positions opened outside the engine.

## Testing

- Unit: desired-position computation from a synthetic latest bar (long/flat/hold); reconciliation logic (buy-to-open, sell-to-close, no-op) with a **mocked** Alpaca client (NO real orders in tests); qty sizing from `allocation_usd`; every safety gate (paper-off, kill-switch, daily-loss, missing allocation) blocks an order.
- The Alpaca client is injected/mocked in all tests — tests must NEVER place a real or paper order.

## Open items for the plan

1. Exact daily-realized-P&L source from Alpaca (account activities vs positions) for the drawdown gate.
2. The tick scheduler: how "bar just closed" is detected per timeframe (market-calendar vs simple time check).
3. Where engine runtime state (open positions per card, last-fired bar) persists across restarts.
