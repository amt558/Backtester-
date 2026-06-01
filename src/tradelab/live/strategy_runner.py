"""Paper-locked desired-state execution engine for Python cards.

Pure decision core + a thin daemon (added in later tasks). EVERY Alpaca
interaction is an injected callable so tests never touch a real account.
Paper-only until an explicit config flip enables live (out of scope here)."""
from __future__ import annotations

import logging
import math
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tradelab.live.strategy_runner")


def desired_position(latest_bar: dict) -> str:
    """Map a strategy's latest-bar signals to a desired position.
    sell_signal (explicit exit) wins over buy_signal. Neither -> 'hold'
    (leave the current position untouched; the engine never invents an exit)."""
    if bool(latest_bar.get("sell_signal")):
        return "flat"
    if bool(latest_bar.get("buy_signal")):
        return "long"
    return "hold"


def size_qty(allocation_usd: Optional[float], price: Optional[float]) -> int:
    """Whole-share qty from a card's dollar allocation. 0 on any invalid input."""
    try:
        a = float(allocation_usd)
        p = float(price)
    except (TypeError, ValueError):
        return 0
    if a <= 0 or p <= 0:
        return 0
    return int(math.floor(a / p))


def safety_block_reason(config: dict, *, daily_pnl: float, is_entry: bool) -> Optional[str]:
    """Return a human reason to BLOCK an order, or None to allow.
    Hard gates: paper_trading must be True; kill_switch halts everything; a
    breached daily_loss_limit halts new ENTRIES (exits still allowed)."""
    alpaca = config.get("alpaca", {}) or {}
    trading = config.get("trading", {}) or {}
    # Fail CLOSED: anything that is not the bool True (missing key, False, None,
    # 1, "true") blocks. A missing/garbage paper flag must never fire orders.
    if alpaca.get("paper_trading") is not True:
        return "paper_trading is not True (missing/non-True blocks all orders)"
    if bool(trading.get("kill_switch", False)):
        return "kill_switch is engaged"
    limit = trading.get("daily_loss_limit")
    if is_entry and limit is not None:
        try:
            if float(daily_pnl) <= float(limit):
                return f"daily loss {daily_pnl:.0f} breached limit {float(limit):.0f}"
        except (TypeError, ValueError):
            # Fail CLOSED on an unreadable P&L: block new entries rather than
            # risk opening into an unknown loss state (exits stay allowed).
            return f"daily P&L unreadable ({daily_pnl!r}) — blocking entry"
    return None


def reconcile_card(*, card: dict, desired: str, actual_qty: int, price: float,
                   bar_date: str, submit_fn) -> dict:
    """Reconcile one card's desired position with its actual Alpaca position by
    placing at most ONE market order via submit_fn. Idempotent: a card already
    in its desired state is a no-op. submit_fn(symbol, side, quantity,
    client_order_id) is injected (real or mock)."""
    symbol = card["symbol"]
    cid = card["card_id"]
    if desired == "long" and actual_qty <= 0:
        qty = size_qty(card.get("allocation_usd"), price)
        if qty <= 0:
            return {"action": "skip", "reason": "allocation/price yields 0 shares"}
        submit_fn(symbol, "buy", qty, client_order_id=f"{cid}-{bar_date}-buy")
        return {"action": "buy", "qty": qty}
    if desired == "flat" and actual_qty > 0:
        submit_fn(symbol, "sell", actual_qty, client_order_id=f"{cid}-{bar_date}-sell")
        return {"action": "sell", "qty": actual_qty}
    return {"action": "none"}


def run_once(cards: dict, *, deps: dict, bar_date: str) -> dict:
    """Process all enabled paper-python cards once, reconciling desired vs actual.

    Each card is processed independently (one failure never stops the rest).
    Cards that are skipped (disabled / non-python / non-paper) are omitted from
    the result dict.  All Alpaca/data access is via injected callables in deps:
      load_latest_bar(strategy, symbol, timeframe) -> bar dict
      get_positions() -> {symbol: qty}
      get_price(symbol) -> float
      get_daily_pnl() -> float
      get_config() -> config dict
      submit_fn(symbol, side, quantity, *, client_order_id) -> None
    Returns {card_id: result_dict} for all processed cards."""
    results: dict = {}

    for card_id, card in cards.items():
        # Step 1 – skip ineligible cards silently
        if (card.get("status") != "enabled"
                or card.get("source") != "python"
                or card.get("mode") != "paper"):
            continue

        try:
            # Step 2 – fetch config
            config = deps["get_config"]()

            # Step 3 – bar + desired position
            bar = deps["load_latest_bar"](card["strategy"], card["symbol"], card["timeframe"])
            desired = desired_position(bar)

            # Step 4 – actual held qty
            actual_qty = int(deps["get_positions"]().get(card["symbol"], 0) or 0)

            # Step 5 – is this a new entry?
            is_entry = (desired == "long" and actual_qty <= 0)

            # Step 6 – safety gates
            # Hard block: paper_trading=False or kill_switch engaged — stops BOTH entries and exits.
            # Isolate these two gates by zeroing out the daily_loss_limit so it can't fire.
            hard_config = {
                **config,
                "trading": {**config.get("trading", {}), "daily_loss_limit": None},
            }
            hard = safety_block_reason(hard_config, daily_pnl=0.0, is_entry=True)
            if hard is not None:
                results[card_id] = {"action": "blocked", "reason": hard}
                continue

            # Soft block: daily-loss limit only blocks new entries, not exits.
            reason = safety_block_reason(config, daily_pnl=deps["get_daily_pnl"](), is_entry=is_entry)
            if is_entry and reason:
                results[card_id] = {"action": "blocked", "reason": reason}
                continue

            # Step 7 – reconcile
            price = deps["get_price"](card["symbol"])
            result = reconcile_card(
                card=card,
                desired=desired,
                actual_qty=actual_qty,
                price=price,
                bar_date=bar_date,
                submit_fn=deps["submit_fn"],
            )
            results[card_id] = result

        except Exception as e:  # Step 8 – isolate per-card failures
            results[card_id] = {"action": "error", "reason": f"{type(e).__name__}: {e}"}

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Live dependency wiring
# ─────────────────────────────────────────────────────────────────────────────

def _real_deps() -> dict:
    """Build injected callables from real Alpaca + marketdata modules.

    FAIL-SAFE CONTRACT — every failure path results in NO order (fail closed):

    * get_config: reads C:/TradingScripts/alpaca_config.json. If the file is
      unreadable the exception propagates and the whole tick iteration is
      skipped — the daemon's outer try/except catches it and logs without
      placing any orders.  A config lacking paper_trading:True will block all
      orders inside safety_block_reason.

    * get_positions: calls alpaca_client.list_positions(). If Alpaca is
      unreachable the exception propagates; run_once's per-card try/except
      marks every card "error" → no order placed.

    * get_price: reads the last Close from the parquet cache for (symbol, tf).
      If the cache is missing/empty the function raises → per-card error →
      no order placed.

    * get_daily_pnl: fetches account equity from Alpaca. If it raises,
      propagates → per-card error → no order placed. Even if it returned a
      bad value, safety_block_reason blocks entries on unreadable P&L.

    * submit_fn: thin wrapper around alpaca_client.submit_market_order.

    * load_latest_bar: downloads/refreshes cache, enriches, runs strategy
      generate_signals, returns the last row as a plain dict. Any step
      failing raises → per-card error → no order placed.
    """
    from tradelab.live import alpaca_client
    from tradelab.marketdata import download_symbols, enrich_universe
    from tradelab.marketdata import cache as _mcache
    from tradelab.registry import instantiate_strategy

    _CONFIG_PATH = Path("C:/TradingScripts/alpaca_config.json")

    def _get_config() -> dict:
        # utf-8-sig strips BOM; read failure propagates → tick aborted safely.
        import json
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8-sig"))

    def _get_positions() -> dict:
        # {symbol: whole-share int qty}; raises on network failure → fail closed
        return {p["symbol"]: int(float(p["qty"])) for p in alpaca_client.list_positions()}

    def _get_price(symbol: str) -> float:
        # We need a timeframe to pick the cache bucket.  The timeframe is not
        # passed here; we read the latest cached 1D Close (the most broadly
        # available bar) for pricing.  A card's allocation / price → qty
        # calculation only needs a ballpark current price; 1D Close is fine.
        # Raises if cache is missing or empty → no order placed.
        df = _mcache.read(symbol, "1D")
        if df is None or df.empty:
            raise ValueError(f"No cached price data for {symbol}")
        close_col = "Close" if "Close" in df.columns else df.columns[-1]
        val = float(df[close_col].iloc[-1])
        return val

    def _get_daily_pnl() -> float:
        # equity - last_equity; raises on Alpaca failure → fail closed
        acct = alpaca_client.get_client().get_account()
        return float(acct.equity) - float(acct.last_equity)

    def _load_latest_bar(strategy: str, symbol: str, timeframe: str) -> dict:
        # 1. Refresh cache (cache-only source; does not call external APIs
        #    beyond what download_symbols already gates behind its own logic).
        data = download_symbols([symbol], timeframe=timeframe)
        # 2. Enrich with indicators expected by strategies.
        enriched = enrich_universe(data)
        # 3. Run strategy signals.
        strat_obj = instantiate_strategy(strategy)
        signals = strat_obj.generate_signals(enriched)
        # 4. Return last row of this symbol as a plain dict.
        sym_df = signals.get(symbol) if isinstance(signals, dict) else enriched.get(symbol)
        if sym_df is None or sym_df.empty:
            raise ValueError(f"No signal data returned for {symbol} from {strategy}")
        return sym_df.iloc[-1].to_dict()

    return {
        "get_config": _get_config,
        "get_positions": _get_positions,
        "get_price": _get_price,
        "get_daily_pnl": _get_daily_pnl,
        "submit_fn": alpaca_client.submit_market_order,
        "load_latest_bar": _load_latest_bar,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Timeframe bucketing (dedup key for client_order_id)
# ─────────────────────────────────────────────────────────────────────────────

def _bar_bucket(timeframe: str, now: datetime) -> str:
    """Return a dedup bucket string for a given timeframe and wall-clock time.

    Daily timeframes (e.g. '1D', '2D', 'W', 'M') → YYYY-MM-DD
      (one logical order per calendar day).
    Intraday (anything else, e.g. '1H', '5m', '15min') → YYYY-MM-DD-HH
      (one logical order per hour).

    Detection: a timeframe is "daily" if its uppercase form ends with 'D'.
    Everything else is treated as intraday and buckets by hour.
    """
    if timeframe.upper().endswith("D"):
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d-%H")


# ─────────────────────────────────────────────────────────────────────────────
# run_tick — one full reconciliation cycle
# ─────────────────────────────────────────────────────────────────────────────

def run_tick(*, registry, deps: dict, now: datetime) -> dict:
    """Process all eligible cards for the current tick.

    Eligible = status=='enabled', source=='python', mode=='paper'.
    Cards are grouped by timeframe; each group gets its own bar_date bucket
    (so daily cards get a per-day dedup key and intraday cards get per-hour).

    Returns merged {card_id: result} for all processed cards.
    A top-level exception returns {} and logs — never crashes the daemon.
    """
    try:
        cards = registry.all()

        # Group eligible cards by timeframe.
        groups: dict[str, dict] = {}
        for card_id, card in cards.items():
            if (card.get("status") != "enabled"
                    or card.get("source") != "python"
                    or card.get("mode") != "paper"):
                continue
            tf = card.get("timeframe", "1D")
            groups.setdefault(tf, {})[card_id] = card

        results: dict = {}
        for tf, group in groups.items():
            bar_date = _bar_bucket(tf, now)
            group_results = run_once(group, deps=deps, bar_date=bar_date)
            results.update(group_results)

        return results

    except Exception as e:
        logger.error("run_tick raised: %s: %s", type(e).__name__, e)
        print(f"[strategy_runner] run_tick raised: {type(e).__name__}: {e}", file=sys.stderr)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Daemon (start / stop)
# ─────────────────────────────────────────────────────────────────────────────

_CARDS_PATH = Path("C:/TradingScripts/tradelab/live/cards.json")

_thread: Optional[threading.Thread] = None
_stop_evt = threading.Event()
_start_lock = threading.Lock()


def _run_loop(
    *,
    registry,
    deps: dict,
    run_tick_fn,
    tick_seconds: float,
) -> None:
    """Daemon thread body: tick → wait tick_seconds (interruptible) → repeat."""
    while not _stop_evt.is_set():
        try:
            results = run_tick_fn(registry=registry, deps=deps, now=datetime.now(timezone.utc))
            actions = {k: v.get("action", "?") for k, v in results.items()}
            logger.info("strategy_runner tick: %s", actions)
            print(f"[strategy_runner] tick: {actions}", file=sys.stderr, flush=True)
        except Exception as e:
            logger.error("strategy_runner loop error: %s: %s", type(e).__name__, e)
            print(f"[strategy_runner] loop error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        # Interruptible wait: stop() sets the event and this returns immediately.
        if _stop_evt.wait(tick_seconds):
            break


def start(
    *,
    deps: Optional[dict] = None,
    registry=None,
    run_tick_fn=None,
    tick_seconds: float = 300,
) -> None:
    """Start the paper-engine daemon thread. Idempotent — repeated calls are no-ops.

    Injectable parameters are provided so tests can pass fakes and NEVER
    trigger _real_deps() or any network call:
      deps       — if None, built via _real_deps() (real Alpaca wiring)
      registry   — if None, CardRegistry(<_CARDS_PATH>) is used
      run_tick_fn — if None, run_tick is used
      tick_seconds — loop sleep interval in seconds (default 300 = 5 min)
    """
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_evt.clear()

        # Resolve real defaults only when no fake is injected.
        _deps = deps if deps is not None else _real_deps()
        if registry is None:
            from tradelab.live.cards import CardRegistry
            _registry = CardRegistry(_CARDS_PATH)
        else:
            _registry = registry
        _fn = run_tick_fn if run_tick_fn is not None else run_tick

        _thread = threading.Thread(
            target=_run_loop,
            kwargs={
                "registry": _registry,
                "deps": _deps,
                "run_tick_fn": _fn,
                "tick_seconds": tick_seconds,
            },
            daemon=True,
            name="strategy_runner",
        )
        _thread.start()


def stop() -> None:
    """Signal the daemon to stop and join its thread. Safe when not running."""
    global _thread
    _stop_evt.set()
    with _start_lock:
        if _thread is not None:
            _thread.join(timeout=2.0)
            _thread = None
