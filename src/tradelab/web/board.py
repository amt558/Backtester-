"""The strategy board (S4): one row per registered strategy, in exactly one
promotion state, with exactly one next action.

    Candidate → Tried (verdict + route) → Accepted (Off | Paper) → Paper-qualified (S7) → Live (S9)
                                                └──────────── Retired

Nothing here is stored. Every state is derived from data that already
exists — the registry (tradelab.yaml), the audit DB's runs, the run folder's
backtest_result.json (for the promotion route, computed the same way Accept
computes it so the board can never disagree with Accept), cards.json, the
retired-cards log, and the job manager for in-flight work.

`derive_state` and `build_board` are pure over plain dicts; the handler
gathers the inputs and injects them.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

STATE_CANDIDATE = "candidate"
STATE_TRIED = "tried"
STATE_ACCEPTED = "accepted"
STATE_PAPER_QUALIFIED = "paper_qualified"   # dropped 2026-09-03 — never emitted; kept so counts stay stable
STATE_LIVE = "live"                          # S9: a card whose mode is "live" (Off or On)
STATE_RETIRED = "retired"

# Spine order for grouping on the board.
STATE_ORDER = [
    STATE_CANDIDATE, STATE_TRIED, STATE_ACCEPTED,
    STATE_PAPER_QUALIFIED, STATE_LIVE, STATE_RETIRED,
]

ROUTE_CLEAR, ROUTE_ADVISORY, ROUTE_BLOCKED = "CLEAR", "ADVISORY", "BLOCKED"


def _iso_key(s: Optional[str]) -> str:
    """Comparable key for ISO-8601 stamps that may differ in suffix ("Z" vs
    "+00:00") or precision; "" when unparsable so a bad stamp sorts oldest."""
    if not s:
        return ""
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    except (ValueError, TypeError):
        return ""


def pick_representative_run(rows_newest_first: list[dict], *, full_ok) -> Optional[dict]:
    """S5: the run that represents a strategy on the board.

    - a plain ``run`` (tier basic) never counts as a trial;
    - the newest Full trial that still passes the gate (``full_ok(row)``)
      wins over any later Trial — a diagnostic robustness run must not knock
      a strategy off its accept-able rung;
    - otherwise the newest Trial, or a legacy row with no tier (a robustness
      run from before the ladder existed).
    """
    trials = [r for r in rows_newest_first if (r.get("tier") or "trial") != "basic"]
    for r in trials:
        if r.get("tier") == "full":
            try:
                if full_ok(r):
                    return r
            except Exception as e:  # noqa: BLE001 — unscorable full row: fall through, loudly
                import logging
                logging.getLogger(__name__).warning(
                    "full-trial check failed for run %s: %s: %s", r.get("run_id"), type(e).__name__, e)
    return trials[0] if trials else None


def _is_active_override(card: dict) -> bool:
    from datetime import datetime, timezone
    from tradelab import override as _ov
    return _ov.is_active(card, datetime.now(timezone.utc))


def _action(kind: str, label: str, enabled: bool = True, reason: Optional[str] = None) -> dict:
    return {"kind": kind, "label": label, "enabled": enabled, "reason": reason}


def derive_state(
    *,
    latest_run: Optional[dict],
    route: Optional[str],
    blockers: Optional[list],
    card: Optional[dict],
    retired: Optional[dict],
    busy: Optional[dict] = None,
    full_trial: Optional[dict] = None,
    override_ok: Optional[dict] = None,
) -> tuple[str, dict]:
    """Return (state, next_action) for one strategy.

    latest_run: the newest audit row for the strategy (or None) — needs
        ``verdict`` to count as a trial; a run with no verdict is not a trial.
    route / blockers: promotion route for that run (None when the run folder
        cannot be scored — treated as not-yet-tried, fail closed).
    card: the strategy's current card in cards.json, or None.
    retired: the most recent retired-cards log entry for it, or None.
    busy: an in-flight job dict, or None. A busy row keeps its state but its
        action becomes the running job.
    full_trial: S5 gate result {ok, code, reason} for the latest run. When it
        is not ok, a CLEAR Tried row's action is "Full trial" (or "Full trial
        again" for a stale one) instead of Accept — Accept is only ever
        offered from a Full trial of the current code and thresholds.
    override_ok: S6 — {"ok": bool, "reason": str|None} saying whether an
        override could be granted right now (budget, canary). None = unknown
        → the override action is offered disabled.
    """
    # A retirement is newer than the run it was accepted from: the strategy
    # is Retired until a FRESH trial (newer than the retirement) exists.
    run_at = _iso_key((latest_run or {}).get("timestamp_utc"))
    retired_after_run = bool(
        retired is not None and latest_run is not None and (
            _iso_key(retired.get("retired_at")) > run_at
            or (retired.get("card") or {}).get("scoring_run_id") == latest_run.get("run_id")
        )
    )
    if card is not None:
        status = (card.get("status") or "disabled").lower()
        live = str(card.get("mode") or "").lower() == "live"
        state = STATE_LIVE if live else STATE_ACCEPTED
        if status == "enabled" and retired is None and card.get("override") and not _is_active_override(card):
            action = _action("open_tab", "Open tab · halted (override expired)")
        elif live:
            action = _action("open_tab", "Open tab · Live · Off" if status == "disabled" else "Open tab · LIVE")
        else:
            action = _action("open_tab", "Open tab" if status == "disabled" else "Open tab · Paper")
    elif latest_run is not None and latest_run.get("verdict") and route and not retired_after_run:
        state = STATE_TRIED
        ft = full_trial or {"ok": False, "code": "no_gate", "reason": "full-trial gate unavailable"}
        if route == ROUTE_CLEAR and ft.get("ok"):
            action = _action("accept", "Accept")
        elif route == ROUTE_CLEAR:
            stale = ft.get("code") in ("code_changed", "thresholds_changed")
            if ft.get("code") == "canary_mismatch":
                action = _action("accept", "Accept", enabled=False, reason=ft.get("reason"))
            else:
                action = _action("full_trial", "Full trial again" if stale else "Full trial",
                                 enabled=True, reason=ft.get("reason"))
        elif route == ROUTE_ADVISORY:
            # An override (S6) will itself require a Full trial, and a Full
            # trial can come out differently from a Trial — so the one action
            # on an ADVISORY strategy without a current Full trial is the
            # Full trial; with one, the (disabled until S6) override.
            if ft.get("ok") or ft.get("code") == "canary_mismatch":
                oo = override_ok or {"ok": False, "reason": "override availability unknown"}
                can = bool(ft.get("ok")) and bool(oo.get("ok"))
                action = _action(
                    "accept_override", "Accept with override", enabled=can,
                    reason=(ft.get("reason") if not ft.get("ok") else oo.get("reason")) if not can
                    else "ADVISORY route — accepting needs a typed confirmation and a written reason; "
                         "the card trades at a capped size and its override expires.",
                )
            else:
                stale = ft.get("code") in ("code_changed", "thresholds_changed")
                action = _action("full_trial", "Full trial again" if stale else "Full trial", enabled=True,
                                 reason="ADVISORY on this rung — " + (ft.get("reason") or "run a Full trial")
                                        + ". The override (S6) will need a Full trial too.")
        else:
            action = _action(
                "retrial", "Re-trial", enabled=True,
                reason="BLOCKED by hard disqualifiers: " + ", ".join(blockers or []),
            )
    elif retired is not None:
        state = STATE_RETIRED
        action = _action("trial", "Trial again")
    else:
        state = STATE_CANDIDATE
        action = _action("trial", "Trial")

    if busy:
        action = _action(
            "busy", f"Running {busy.get('command') or 'job'}…", enabled=False,
            reason=busy.get("summary") or None,
        )
    return state, action


def build_board(
    *,
    registered: Iterable[str],
    latest_runs: dict[str, dict],
    route_for_run: Callable[[dict], tuple[Optional[str], list]],
    cards: dict[str, dict],
    retired: Iterable[dict],
    jobs: Iterable[dict],
    symbols_for: Callable[[str], list[str]],
    excluded: Optional[dict[str, str]] = None,
    data_end_for: Optional[Callable[[dict], Optional[str]]] = None,
    full_trial_for: Optional[Callable[[str, Optional[dict]], dict]] = None,
    signals_for: Optional[Callable[[dict], dict]] = None,
    newer_trials: Optional[dict[str, dict]] = None,
    override_ok: Optional[dict] = None,
    now=None,
) -> dict:
    """Assemble the board.

    registered: strategy names from the registry.
    excluded: {name: reason} for registered names that are NOT strategies to
        promote — the canaries (engine-integrity probes, shown in their own
        panel; a canary must never be offered an Accept) and abstract bases
        (SimpleStrategy itself registered by mistake). They are reported, not
        silently dropped.
    latest_runs: {strategy_name: newest audit row}.
    route_for_run: run row → (route, blockers); (None, []) when unscorable.
    cards: cards.json contents ({card_id: card}); a card belongs to the
        strategy named by its ``strategy`` field (falling back to base_name).
    retired: retired-cards log entries, newest last.
    jobs: job manager dicts; only queued/running ones count as busy.
    symbols_for: strategy name → declared tickers (may raise → []).
    """
    card_by_strategy: dict[str, dict] = {}
    for c in cards.values():
        name = c.get("strategy") or c.get("base_name")
        if not name:
            continue
        prev = card_by_strategy.get(name)
        # Prefer the highest version if several cards exist for one strategy.
        if prev is None or (c.get("version") or 0) > (prev.get("version") or 0):
            card_by_strategy[name] = c

    retired_by_strategy: dict[str, dict] = {}
    for r in retired:
        c = r.get("card") or {}
        name = c.get("strategy") or c.get("base_name")
        if name:
            retired_by_strategy[name] = r  # newest last wins

    busy_by_strategy: dict[str, dict] = {}
    newest_job: dict[str, dict] = {}
    for j in jobs:
        name = j.get("strategy")
        if not name:
            continue
        if j.get("status") in ("queued", "running"):
            busy_by_strategy.setdefault(name, j)
        prev = newest_job.get(name)
        if prev is None or _iso_key(j.get("started_at")) > _iso_key(prev.get("started_at")):
            newest_job[name] = j

    excluded = excluded or {}
    registered_set = set(registered)
    # Orphan cards: the daemon can trade a card whose strategy is no longer in
    # tradelab.yaml. Such a card must still be ON the board, flagged.
    orphan_names = sorted(n for n in card_by_strategy if n not in registered_set and n not in excluded)
    rows = []
    for name in sorted(registered_set) + orphan_names:
        if name in excluded:
            continue
        run = latest_runs.get(name)
        route, blockers = (None, [])
        if run is not None and run.get("verdict"):
            try:
                route, blockers = route_for_run(run)
            except Exception:  # noqa: BLE001 — unscorable folder = not tried
                route, blockers = None, []
        card = card_by_strategy.get(name)
        ret = retired_by_strategy.get(name)
        busy = busy_by_strategy.get(name)
        ft = None
        if run is not None and full_trial_for is not None:
            try:
                ft = full_trial_for(name, run)
            except Exception:  # noqa: BLE001 — fail closed
                ft = {"ok": False, "code": "no_gate", "reason": "full-trial gate unavailable"}
        state, action = derive_state(
            latest_run=run, route=route, blockers=blockers, card=card, retired=ret, busy=busy,
            full_trial=ft, override_ok=override_ok,
        )
        from tradelab import override as _ov
        from datetime import datetime as _dt, timezone as _tz
        receipt = _ov.receipt(card, now or _dt.now(_tz.utc)) if card is not None else None
        # S6: an enabled card whose override has expired is HALTED — the engine
        # sizes it at 0 — even if the daemon has not switched it Off yet.
        effective_status = (card or {}).get("status")
        if receipt and receipt.get("expired") and effective_status == "enabled":
            effective_status = "halted"
        sig = {"score": None, "gating": [], "read_anyway": [], "hard_override": []}
        if run is not None and signals_for is not None:
            try:
                sig = signals_for(run)
            except Exception:  # noqa: BLE001
                pass
        try:
            symbols = list(symbols_for(name))
        except Exception:  # noqa: BLE001
            symbols = []
        # A failed job newer than the latest audit run is the freshest fact
        # about this strategy — say so on the card instead of leaving the
        # trader to dig through the Runs table.
        last_failure = None
        nj = newest_job.get(name)
        if nj and nj.get("status") == "failed" and not busy:
            job_at = nj.get("started_at") or ""
            if not run or _iso_key(job_at) > _iso_key(run.get("timestamp_utc")):
                last_failure = {"job_id": nj.get("id"), "command": nj.get("command"), "at": job_at,
                                "hint": nj.get("failure_hint") or "exited with an error"}
        # A trial newer than the card's own scoring run that routes worse than
        # the card was accepted on is the freshest fact — surface it.
        newer_trial = None
        if card is not None and run is not None and route:
            if run.get("run_id") != card.get("scoring_run_id") and _iso_key(run.get("timestamp_utc")) > _iso_key(card.get("created_at")):
                card_route = (card.get("promotion_route") or "").upper() or None
                newer_trial = {"run_id": run.get("run_id"), "run_at": run.get("timestamp_utc"), "route": route,
                               "verdict": run.get("verdict"), "worse": route != "CLEAR" and route != card_route}
        # S5: on a Tried row the representative run may be an older valid
        # Full trial; a NEWER Trial that routes worse is surfaced the same way.
        nt = (newer_trials or {}).get(name)
        if newer_trial is None and card is None and run is not None and nt is not None and nt.get("verdict"):
            try:
                nt_route, _nb = route_for_run(nt)
            except Exception:  # noqa: BLE001
                nt_route = None
            if nt_route:
                worse = ["CLEAR", "ADVISORY", "BLOCKED"].index(nt_route) > ["CLEAR", "ADVISORY", "BLOCKED"].index(route or "CLEAR")
                newer_trial = {"run_id": nt.get("run_id"), "run_at": nt.get("timestamp_utc"), "route": nt_route,
                               "verdict": nt.get("verdict"), "worse": worse}
        data_end = None
        if run is not None and data_end_for is not None:
            try:
                data_end = data_end_for(run)
            except Exception:  # noqa: BLE001
                data_end = None
        rows.append({
            "strategy": name,
            "state": state,
            "unregistered": name not in registered_set,
            "newer_trial": newer_trial,
            "data_end": data_end,
            "tier": (run or {}).get("tier"),
            "full_trial": ft,
            "override": receipt,
            "effective_status": effective_status,
            "mode": (card or {}).get("mode"),
            "live": (card or {}).get("live"),
            "score": sig.get("score"),
            "signals": {"gating": sig.get("gating", []), "read_anyway": sig.get("read_anyway", []),
                        "hard_override": sig.get("hard_override", [])},
            "next_action": action,
            "verdict": (run or {}).get("verdict"),
            "route": route,
            "blockers": blockers,
            "dsr": (run or {}).get("dsr_probability"),
            "run_id": (run or {}).get("run_id"),
            "run_at": (run or {}).get("timestamp_utc"),
            "universe": (run or {}).get("universe"),
            "report_folder": (run or {}).get("report_card_html_path"),
            "symbols": symbols,
            "card_id": (card or {}).get("card_id"),
            "card_status": (card or {}).get("status"),
            "allocation_usd": (card or {}).get("allocation_usd"),
            "retired_at": (ret or {}).get("retired_at"),
            "last_failure": last_failure,
            "busy": {"job_id": busy.get("id"), "command": busy.get("command"),
                     "started_at": busy.get("started_at")} if busy else None,
        })

    rows.sort(key=lambda r: (STATE_ORDER.index(r["state"]), r["strategy"]))
    counts = {s: 0 for s in STATE_ORDER}
    for r in rows:
        counts[r["state"]] += 1
    return {
        "rows": rows,
        "counts": counts,
        "excluded": [{"strategy": n, "reason": r} for n, r in sorted(excluded.items()) if n in set(registered)],
    }
