"""Desired-state execution engine for Python cards.

Pure decision core + a thin daemon. EVERY Alpaca interaction is an injected
callable so tests never touch a real account.

S9: a card's ``mode`` is its account. Paper cards run against ``deps`` exactly
as before (paper_trading must be True, kill switch, daily loss limit). Live
cards run against ``deps["live"]`` — present only when live keys exist — and
through ``live_block_reason``; with no live deps, a live card is blocked,
never silently routed to paper. Multi-ticker (PORTFOLIO) cards trade each
declared ticker from ONE signal pass, allocation split equally."""
from __future__ import annotations

import logging
import math
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradelab import override as _override

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


def live_block_reason(config: dict, *, live_config: Optional[dict], daily_pnl, is_entry: bool,
                      card: Optional[dict] = None, live_ready: bool = False,
                      receipt_ok: Optional[bool] = None) -> Optional[str]:
    """Return a reason to BLOCK a LIVE order, or None to allow. Fail CLOSED.

    kill_switch (alpaca_config.json) halts everything, live and paper alike;
    live keys must be present (``live_ready``); a live card needs its go-live
    receipt AND that receipt must verify against the audit ledger
    (``receipt_ok`` — None/False blocks: a hand-edited cards.json cannot arm
    real money); the live daily loss limit (tradelab.yaml
    `live.daily_loss_limit_usd`) stops ENTRIES only."""
    trading = (config or {}).get("trading", {}) or {}
    if bool(trading.get("kill_switch", False)):
        return "kill_switch is engaged"
    if not live_ready:
        return "live keys not configured (ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY) — no live orders"
    if card is not None and not isinstance(card.get("live"), dict):
        return "card carries no go-live receipt — refused (only POST /tradelab/cards/{id}/live arms live)"
    if card is not None and receipt_ok is not True:
        return "go-live receipt does not verify against the audit ledger — refused (re-arm through the tab)"
    if is_entry:
        try:
            limit = float((live_config or {}).get("daily_loss_limit_usd", 1000.0))
            pnl = float(daily_pnl)
        except (TypeError, ValueError):
            return f"live daily P&L unreadable ({daily_pnl!r}) — blocking entry"
        if limit > 0 and pnl <= -limit:
            return f"live daily loss {pnl:.0f} breached limit -{limit:.0f} — entries stopped for today"
    return None


def card_symbols(card: dict, declared_symbols=None) -> list[str]:
    """Tickers a card trades. Its own symbol, unless it is a PORTFOLIO card —
    then the strategy's declared tickers (S2), via the injected
    ``declared_symbols(strategy) -> list[str]``. Empty list = cannot trade."""
    sym = str(card.get("symbol") or "").upper()
    if sym and sym != "PORTFOLIO":
        return [sym]
    if declared_symbols is None:
        return []
    try:
        out = [str(x).upper() for x in (declared_symbols(card.get("strategy") or card.get("base_name") or "") or [])]
    except Exception:  # noqa: BLE001
        return []
    seen: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.append(x)
    return seen


def reconcile_symbol(*, card: dict, symbol: str, desired: str, actual_qty: int, price: float,
                     bar_date: str, submit_fn, now: Optional[datetime] = None,
                     share: float = 1.0, stamp_symbol: bool = False) -> dict:
    """Reconcile ONE ticker of a card. ``share`` is this ticker's fraction of
    the card's effective allocation (1/n for a PORTFOLIO card); ``stamp_symbol``
    appends ``-SYM`` to the client_order_id so multi-ticker fills attribute."""
    cid = card["card_id"]
    # Stamps may only carry [A-Z0-9.]: a class-B style ticker is stamped in
    # its dotted form so card_activity's regex keeps attributing its fills.
    suffix = f"-{symbol.replace('-', '.')}" if stamp_symbol else ""
    if desired == "long" and actual_qty <= 0:
        alloc = _override.effective_allocation(card, now or datetime.now(timezone.utc))
        try:
            alloc = float(alloc) * float(share) if alloc is not None else None
        except (TypeError, ValueError):
            alloc = None
        qty = size_qty(alloc, price)
        if qty <= 0:
            if card.get("override") and not _override.is_active(card, now or datetime.now(timezone.utc)):
                return {"action": "skip", "reason": "override expired — no new entries"}
            return {"action": "skip", "reason": "allocation/price yields 0 shares"}
        submit_fn(symbol, "buy", qty, client_order_id=f"{cid}-{bar_date}-buy{suffix}")
        return {"action": "buy", "qty": qty}
    if desired == "flat" and actual_qty > 0:
        submit_fn(symbol, "sell", actual_qty, client_order_id=f"{cid}-{bar_date}-sell{suffix}")
        return {"action": "sell", "qty": actual_qty}
    return {"action": "none"}


def reconcile_card(*, card: dict, desired: str, actual_qty: int, price: float,
                   bar_date: str, submit_fn, now: Optional[datetime] = None) -> dict:
    """Reconcile one card's desired position with its actual Alpaca position by
    placing at most ONE market order via submit_fn. Idempotent: a card already
    in its desired state is a no-op. submit_fn(symbol, side, quantity,
    client_order_id) is injected (real or mock).

    S6: an overridden card sizes from allocation × cap while its override is
    active and from 0 once it has expired — the policy lives in the engine,
    not in the UI. Exits are never capped."""
    return reconcile_symbol(card=card, symbol=card["symbol"], desired=desired, actual_qty=actual_qty,
                            price=price, bar_date=bar_date, submit_fn=submit_fn, now=now)


def run_once(cards: dict, *, deps: dict, bar_date: str, now: Optional[datetime] = None) -> dict:
    """Process all enabled python cards once, reconciling desired vs actual.

    Each card is processed independently (one failure never stops the rest).
    Cards that are skipped (disabled / non-python / unknown mode) are omitted
    from the result dict. All Alpaca/data access is via injected callables:
      load_latest_bar(strategy, symbol, timeframe) -> bar dict          (single ticker)
      load_latest_bars(strategy, symbols, timeframe) -> {sym: bar dict} (one signal pass; optional)
      declared_symbols(strategy) -> [tickers]                            (PORTFOLIO cards; optional)
      get_positions() -> {symbol: qty}
      get_price(symbol) -> float
      get_daily_pnl() -> float
      get_config() -> config dict
      submit_fn(symbol, side, quantity, *, client_order_id) -> None
      live -> the same get_positions/get_price/get_daily_pnl/submit_fn bound to
              the LIVE account, or None when live keys are absent (optional)
      live_config -> dict of tradelab.yaml `live:` (optional)
    Returns {card_id: result_dict} for all processed cards. A PORTFOLIO card's
    result is {"action": "multi", "symbols": {sym: result}}."""
    results: dict = {}

    for card_id, card in cards.items():
        # Step 1 – skip ineligible cards silently
        mode = card.get("mode")
        if (card.get("status") != "enabled"
                or card.get("source") != "python"
                or mode not in ("paper", "live")):
            continue

        try:
            # Step 2 – config + the account this card trades on
            config = deps["get_config"]()
            receipt_ok = None
            if mode == "live":
                acct = deps.get("live")
                if not acct:
                    results[card_id] = {"action": "blocked", "reason": live_block_reason(
                        config, live_config=deps.get("live_config"), daily_pnl=0.0, is_entry=False,
                        card=card, live_ready=False) or "live deps not configured"}
                    continue
                # The receipt must verify against the ledger every tick; no
                # verifier → not verified. A live card sizes from the LEDGERED
                # allocation on its receipt, never from a hand-edited field.
                verify = deps.get("verify_live_receipt")
                try:
                    receipt_ok = bool(verify(card)) if verify else False
                except Exception:  # noqa: BLE001
                    receipt_ok = False
                if receipt_ok:
                    card = {**card, "allocation_usd": (card.get("live") or {}).get("allocation_usd")}
            else:
                acct = deps

            # Step 3 – tickers + one signal pass
            symbols = card_symbols(card, deps.get("declared_symbols"))
            if not symbols:
                results[card_id] = {"action": "error", "reason": "no tickers declared — declare `symbols` on the strategy class"}
                continue
            multi = len(symbols) > 1 or str(card.get("symbol") or "").upper() == "PORTFOLIO"
            if multi and deps.get("load_latest_bars"):
                bars = deps["load_latest_bars"](card["strategy"], symbols, card["timeframe"])
            else:
                bars = {sym: deps["load_latest_bar"](card["strategy"], sym, card["timeframe"]) for sym in symbols}

            # Step 4 – actual held qty per ticker (one account call)
            held = acct["get_positions"]()

            # Step 5 – gates, evaluated once per card with "is_entry" = any entry wanted
            desired = {sym: desired_position(bars.get(sym) or {}) for sym in symbols}
            actual = {sym: int(held.get(sym, 0) or 0) for sym in symbols}
            any_entry = any(desired[s_] == "long" and actual[s_] <= 0 for s_ in symbols)

            if mode == "live":
                hard = live_block_reason(config, live_config=deps.get("live_config"), daily_pnl=0.0,
                                         is_entry=False, card=card, live_ready=True, receipt_ok=receipt_ok)
                if hard is not None:
                    results[card_id] = {"action": "blocked", "reason": hard}
                    continue
                soft = live_block_reason(config, live_config=deps.get("live_config"),
                                         daily_pnl=acct["get_daily_pnl"](), is_entry=any_entry,
                                         card=card, live_ready=True, receipt_ok=receipt_ok) if any_entry else None
            else:
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
                soft = safety_block_reason(config, daily_pnl=acct["get_daily_pnl"](), is_entry=any_entry) if any_entry else None

            # Step 6 – reconcile each ticker; entries blocked by the soft gate, exits still run
            share = 1.0 / len(symbols)
            per: dict = {}
            for sym in symbols:
                try:
                    if desired[sym] == "long" and actual[sym] <= 0 and soft:
                        per[sym] = {"action": "blocked", "reason": soft}
                        continue
                    price = acct["get_price"](sym)
                    per[sym] = reconcile_symbol(card=card, symbol=sym, desired=desired[sym], actual_qty=actual[sym],
                                                price=price, bar_date=bar_date, submit_fn=acct["submit_fn"],
                                                now=now, share=share, stamp_symbol=multi)
                except Exception as e:  # noqa: BLE001 – one ticker's failure never stops the others
                    per[sym] = {"action": "error", "reason": f"{type(e).__name__}: {e}"}
            if multi:
                results[card_id] = {"action": "multi", "symbols": per}
            else:
                results[card_id] = per[symbols[0]]

        except Exception as e:  # Step 7 – isolate per-card failures
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
        return alpaca_client.account_day_pnl("paper")

    # S9: the live account's deps exist only when live keys are present. A
    # live card with no live deps is BLOCKED by run_once, never sent to paper.
    live_deps = None
    if alpaca_client.live_keys_present():
        live_deps = {
            "get_positions": lambda: {p["symbol"]: int(float(p["qty"])) for p in alpaca_client.list_positions("live")},
            "get_price": _get_price,
            "get_daily_pnl": lambda: alpaca_client.account_day_pnl("live"),
            "submit_fn": lambda symbol, side, quantity, client_order_id=None:
                alpaca_client.submit_market_order(symbol, side, quantity, client_order_id=client_order_id, account="live"),
        }

    def _live_config() -> dict:
        try:
            from tradelab.config import load_config
            lc = load_config().live
            out = {"max_total_allocation_usd": lc.max_total_allocation_usd,
                   "daily_loss_limit_usd": lc.daily_loss_limit_usd,
                   "require_flat_paper": lc.require_flat_paper}
        except Exception:  # noqa: BLE001 – defaults are the policy when the file is unreadable
            out = {"max_total_allocation_usd": 25000.0, "daily_loss_limit_usd": 1000.0, "require_flat_paper": True}
        if not out["daily_loss_limit_usd"] > 0:
            logger.warning("live.daily_loss_limit_usd is %r — the live daily loss limit is DISABLED", out["daily_loss_limit_usd"])
            print(f"[strategy_runner] WARNING live.daily_loss_limit_usd={out['daily_loss_limit_usd']!r}: live daily loss limit disabled", file=sys.stderr)
        return out

    # The audit DB is resolved ONCE, absolute, at deps-build time — the same
    # relative location the web layer uses — and logged, so a cwd mismatch
    # shows up in the log instead of as "receipt does not verify" every tick.
    from tradelab.audit.history import DEFAULT_DB_PATH as _HIST_DB
    _db = _HIST_DB.resolve()
    logger.info("live engine: audit/ledger DB %s (exists=%s); cards %s", _db, _db.exists(), _CARDS_PATH)
    print(f"[strategy_runner] audit DB {_db} (exists={_db.exists()})", file=sys.stderr)

    def _verify_live_receipt(card: dict) -> bool:
        # The receipt must be the card's LATEST live-action ledger row.
        from tradelab.audit.verdict_ledger import get_latest_live_row
        from tradelab.live import golive
        return golive.receipt_matches_ledger(card, get_latest_live_row(card.get("card_id") or "", db_path=_db))

    def _live_evidence_stale(card: dict):
        # The run a live card was armed on must still be a current Full trial:
        # same strategy code on disk, same robustness thresholds. Unknown = stale.
        try:
            from tradelab import ladder
            from tradelab.audit.history import get_run
            from tradelab.config import get_config
            from tradelab.registry import load_strategy_class
            run_id = (card.get("live") or {}).get("scoring_run_id") or card.get("scoring_run_id") or ""
            row = get_run(run_id, db_path=_db) if run_id else None
            if row is None:
                return "the run this card was armed on is not on record"
            code = ladder.code_hash_for_class(load_strategy_class(card.get("strategy") or card.get("base_name") or ""))
            thr = ladder.thresholds_hash(get_config().robustness)
            ft = ladder.full_trial_status({"tier": row.tier, "code_hash": row.code_hash, "thresholds_hash": row.thresholds_hash},
                                          current_code_hash=code, current_thresholds_hash=thr)
            return None if ft.get("ok") else (ft.get("reason") or ft.get("code") or "evidence no longer current")
        except Exception as e:  # noqa: BLE001
            return f"could not verify the evidence ({type(e).__name__})"

    def _declared_symbols(strategy: str) -> list[str]:
        from tradelab.registry import load_strategy_class
        from tradelab.web.new_strategy import declared_symbols
        return declared_symbols(load_strategy_class(strategy))

    def _load_latest_bars(strategy: str, symbols: list, timeframe: str) -> dict:
        # ONE download + ONE generate_signals over the whole ticker list, so a
        # strategy that ranks across its universe (rotation) sees all of it.
        data = download_symbols(list(symbols), timeframe=timeframe)
        enriched = enrich_universe(data)
        strat_obj = instantiate_strategy(strategy)
        signals = strat_obj.generate_signals(enriched)
        out = {}
        for sym in symbols:
            sym_df = signals.get(sym) if isinstance(signals, dict) else enriched.get(sym)
            if sym_df is None or sym_df.empty:
                raise ValueError(f"No signal data returned for {sym} from {strategy}")
            out[sym] = sym_df.iloc[-1].to_dict()
        return out

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
        "load_latest_bars": _load_latest_bars,
        "declared_symbols": _declared_symbols,
        "verify_live_receipt": _verify_live_receipt,
        "live_evidence_stale": _live_evidence_stale,
        "live": live_deps,
        "live_config": _live_config(),
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

    Eligible = status=='enabled', source=='python', mode in ('paper', 'live').
    Cards are grouped by timeframe; each group gets its own bar_date bucket
    (so daily cards get a per-day dedup key and intraday cards get per-hour).

    Returns merged {card_id: result} for all processed cards.
    A top-level exception returns {} and logs — never crashes the daemon.
    """
    try:
        cards = registry.all()

        # S6: an override that has expired switches its card Off on this tick,
        # paper or live (S9: no paper-qualified exemption). Stamped so the tab
        # can say why the card is Off. Fail-open per card: a registry write
        # failure must not stop the tick, and effective_allocation already
        # sizes an expired override at 0.
        for card_id, card in list(cards.items()):
            if card.get("status") == "enabled" and _override.is_expired(card, now) \
                    and not card.get("override_expired_at"):
                try:
                    registry.update(card_id, {"status": "disabled",
                                              "override_expired_at": now.astimezone(timezone.utc).isoformat(timespec="seconds")})
                    logger.warning("card %s: override expired — switched Off", card_id)
                    print(f"[strategy_runner] {card_id}: override expired — switched Off", file=sys.stderr)
                except Exception as e:  # noqa: BLE001
                    logger.error("card %s: could not disable on override expiry: %s", card_id, e)
        cards = registry.all()

        # S9: a LIVE card that is On must, every tick, (a) carry a receipt that
        # verifies against the ledger and (b) still stand on current evidence
        # (strategy code and thresholds unchanged since its Full trial). Either
        # failing switches it Off and stamps why — the same shape as override
        # expiry. Positions stay; Flatten on the tab closes them.
        verify = deps.get("verify_live_receipt")
        stale_fn = deps.get("live_evidence_stale")
        for card_id, card in list(cards.items()):
            if card.get("status") != "enabled" or str(card.get("mode") or "").lower() != "live":
                continue
            why = None
            try:
                if not (verify and verify(card)):
                    why = ("live_receipt_invalid_at", "go-live receipt does not verify against the ledger")
                elif stale_fn is not None:
                    stale = stale_fn(card)
                    if stale:
                        why = ("live_evidence_stale_at", str(stale))
            except Exception as e:  # noqa: BLE001 — unknown = not safe to keep trading
                why = ("live_evidence_stale_at", f"could not verify ({type(e).__name__})")
            if why:
                try:
                    registry.update(card_id, {"status": "disabled", why[0]: now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                                              "live_off_reason": why[1]})
                    logger.warning("card %s: switched Off — %s", card_id, why[1])
                    print(f"[strategy_runner] {card_id}: LIVE switched Off — {why[1]}", file=sys.stderr)
                except Exception as e:  # noqa: BLE001
                    logger.error("card %s: could not disable live card: %s", card_id, e)
        cards = registry.all()

        # Group eligible cards by timeframe.
        groups: dict[str, dict] = {}
        for card_id, card in cards.items():
            if (card.get("status") != "enabled"
                    or card.get("source") != "python"
                    or card.get("mode") not in ("paper", "live")):
                continue
            tf = card.get("timeframe", "1D")
            groups.setdefault(tf, {})[card_id] = card

        results: dict = {}
        for tf, group in groups.items():
            bar_date = _bar_bucket(tf, now)
            group_results = run_once(group, deps=deps, bar_date=bar_date, now=now)
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
