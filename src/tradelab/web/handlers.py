"""HTTP request handlers for /tradelab/* routes.

Pure dispatch — no HTTP server framework. launch_dashboard.py's
SimpleHTTPRequestHandler calls into these functions and writes the
returned JSON body with the returned status code.

Response envelope: {"error": null|str, "data": <payload>}.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from tradelab.audit import archive
from tradelab.canaries.runtime import run_canary_check
from tradelab.web import audit_reader, cards_view, freshness, new_strategy, ranges, whatif


# Allowed (strategy-agnostic) commands the web tracker can launch.
# Maps "run --robustness" → ["run", "--robustness"] argv tail.
_ALLOWED_COMMANDS = {
    "optimize":         ["optimize"],
    "wf":               ["wf"],
    "run":              ["run"],
    "run --robustness": ["run", "--robustness"],
    "run --full":       ["run", "--full"],
}


def _resolve_active_universe() -> str:
    """Return the universe name the web dashboard should pass to tradelab CLI.

    Same precedence the PowerShell launcher uses:
    1. .cache/launcher-state.json::activeUniverse (the launcher's last selection,
       shared state so CLI and web agree on what's active)
    2. First universe in tradelab.yaml (alphabetical) as a final fallback
    3. Empty string if nothing is defined — caller treats as "no --universe flag"
    """
    try:
        state_path = Path(".cache") / "launcher-state.json"
        if state_path.exists():
            # PowerShell writes JSON with a UTF-8 BOM; utf-8-sig strips it.
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            active = state.get("activeUniverse")
            if active:
                return str(active)
    except Exception as e:
        print(
            f"[resolver] launcher-state.json read failed "
            f"({type(e).__name__}: {e}); falling back to tradelab.yaml",
            file=sys.stderr,
        )
    try:
        from tradelab.config import get_config
        cfg = get_config()
        if cfg.universes:
            return sorted(cfg.universes.keys())[0]
    except Exception as e:
        print(
            f"[resolver] tradelab.yaml universe load failed "
            f"({type(e).__name__}: {e}); no universe will be passed to CLI",
            file=sys.stderr,
        )
    return ""


def _build_tradelab_argv(strategy: str, command: str) -> Optional[list]:
    """Build the subprocess argv for a (strategy, command) pair.

    Returns None if the command is not in _ALLOWED_COMMANDS.
    Strategy must match a-z0-9_ pattern (no shell metacharacters).

    Injects --universe from launcher-state.json so the CLI has data to
    operate on (mirrors what the PowerShell launcher does via $activeUniverse).
    Without this, run/optimize/wf exit 2 with "No symbols provided".
    """
    if command not in _ALLOWED_COMMANDS:
        return None
    if not re.match(r"^[a-z0-9_]+$", strategy):
        return None
    cmd_argv = _ALLOWED_COMMANDS[command]
    universe_args: list = []
    universe = _resolve_active_universe()
    if universe:
        universe_args = ["--universe", universe]
    # tradelab CLI is `python -m tradelab.cli <subcommand> <strategy> [flags]`
    return [sys.executable, "-m", "tradelab.cli", cmd_argv[0], strategy, *cmd_argv[1:], *universe_args]


# ─── Configurable roots (monkeypatched in tests) ─────────────────────


def _db_path() -> Path:
    return Path("data") / "tradelab_history.db"


def _cache_root() -> Path:
    return Path(".cache") / "ohlcv" / "1D"


def _src_root() -> Path:
    return Path("src")


def _staging_root() -> Path:
    return Path(".cache") / "new_strategy_staging"


def _reports_root() -> Path:
    return Path("reports")


def _pine_archive_root() -> Path:
    return Path("pine_archive")


def _cards_path() -> Path:
    return Path("live/cards.json")


def _alerts_log_path() -> Path:
    return Path("live") / "alerts.jsonl"


def _receiver_health_url() -> str:
    return "http://127.0.0.1:8878/health"


def _ngrok_api_url() -> str:
    return "http://127.0.0.1:4040/api/tunnels"


def _probe_json(url: str, timeout: float = 1.5) -> dict:
    """Tiny GET-and-parse-JSON helper used by /receiver/status. Returns
    parsed JSON dict on success; raises on any error so the caller can
    use a single try/except to mark the probe as down."""
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_receiver_status() -> dict:
    """Probe receiver (port 8878) and ngrok directly. Returns the dict that
    /tradelab/receiver/status wraps in an envelope. Used by the route handler
    AND by daily_summary's daemon (which lives in the launcher process and
    must not HTTP-call itself).

    Performs up to two outbound HTTP requests (1.5s timeout each, worst-case
    ~3s). Named `probe_*` rather than `compute_*` to make the I/O cost
    explicit at every call site.
    """
    receiver_up = False
    cards_loaded = None
    try:
        health = _probe_json(_receiver_health_url(), timeout=1.5)
        receiver_up = health.get("status") == "ok"
        cards_loaded = health.get("cards_loaded")
    except Exception:
        pass

    ngrok_up = False
    ngrok_url = None
    try:
        tunnels = _probe_json(_ngrok_api_url(), timeout=1.5)
        for t in tunnels.get("tunnels", []):
            if t.get("proto") == "https":
                ngrok_url = t.get("public_url")
                ngrok_up = bool(ngrok_url)
                break
    except Exception:
        pass

    return {
        "receiver_up": receiver_up,
        "ngrok_up": ngrok_up,
        "ngrok_url": ngrok_url,
        "cards_loaded": cards_loaded,
    }


def _yaml_path() -> Path:
    return Path("tradelab.yaml")


def _get_job_manager():
    """Indirection to allow monkeypatching in tests."""
    from tradelab.web import get_job_manager
    return get_job_manager()


# ─── Public entry points ─────────────────────────────────────────────


def handle_get(path_with_query: str) -> str:
    """GET dispatcher. Returns JSON body. Status is 200 except 404s (see _with_status)."""
    body, _ = handle_get_with_status(path_with_query)
    return body


def handle_get_with_status(path_with_query: str) -> Tuple[str, int]:
    """GET dispatcher with explicit status code."""
    parsed = urlparse(path_with_query)
    path = parsed.path
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    if path == "/tradelab/runs":
        strategy_q = q.get("strategy") or None
        verdicts_q = [v for v in q.get("verdict", "").split(",") if v] or None
        since_q = q.get("since") or None
        try:
            limit = int(q.get("limit", "50"))
        except (ValueError, TypeError):
            limit = 50
        include_archived = (q.get("include_archived", "false").lower() == "true")

        # Audit DB rows
        audit_rows = audit_reader.list_runs(
            strategy=strategy_q,
            verdicts=verdicts_q,
            since=since_q,
            limit=limit,
            db_path=_db_path(),
            exclude_archived=not include_archived,
        )
        # When include_archived is on, the FE needs to know which rows are
        # archived to render them dim + show the unarchive button. Otherwise
        # archived rows are filtered out and the flag is always False.
        archived_set: set[str] = (
            archive.list_archived_run_ids(db_path=_db_path())
            if include_archived else set()
        )
        for r in audit_rows:
            r["source"] = "audit"
            r["status"] = "done"  # all audit rows are completed by definition
            r["archived"] = r.get("run_id") in archived_set

        # In-flight jobs
        jm = _get_job_manager()
        all_jobs = [j.to_dict() for j in jm.list_jobs()]
        # Only include non-terminal job statuses; done/failed/cancelled live in audit DB
        IN_FLIGHT = {"queued", "running"}
        inflight = [j for j in all_jobs if j.get("status") in IN_FLIGHT]
        # Apply strategy filter to jobs too
        if strategy_q:
            inflight = [j for j in inflight if j.get("strategy") == strategy_q]
        for j in inflight:
            j["source"] = "job"
            j["run_id"] = j["id"]  # uniform key

        # Order: running → queued → audit-by-date-desc
        inflight.sort(key=lambda j: (0 if j["status"] == "running" else 1,
                                     j.get("started_at") or ""))

        # `total` is the unpaginated count (in-flight matching strategy filter
        # + all audit rows matching all filters). Used by Pipeline pagination
        # to render "Showing X of Y" — without it the UI shows X of X.
        audit_total = audit_reader.count_runs(
            strategy=strategy_q,
            verdicts=verdicts_q,
            since=since_q,
            db_path=_db_path(),
            exclude_archived=not include_archived,
        )
        total = len(inflight) + audit_total
        return json.dumps({"runs": inflight + audit_rows, "total": total}), 200

    m = re.match(r"^/tradelab/runs/([^/]+)/metrics$", path)
    if m:
        return _ok(audit_reader.get_run_metrics(m.group(1), db_path=_db_path())), 200

    m = re.match(r"^/tradelab/runs/([^/]+)/folder$", path)
    if m:
        lookup = audit_reader.resolve_run_folder(m.group(1), db_path=_db_path())
        if lookup.status == "no_run":
            return _err("run not found"), 404
        if lookup.status == "no_folder":
            return _err("run has no report folder"), 404
        # Return path relative to tradelab root (used as iframe prefix)
        return _ok({"folder": str(lookup.folder).replace("\\", "/")}), 200

    m = re.match(r"^/tradelab/runs/([^/]+)/robustness$", path)
    if m:
        run_id = m.group(1)
        lookup = audit_reader.resolve_run_folder(run_id, db_path=_db_path())
        if lookup.status == "no_run":
            return _err("run not found"), 404
        # Empty payload (200) for runs that exist but lack robustness data —
        # CLI runs without --report (no folder) or runs predating T4 (no
        # robustness_result.json). FE renders "—" silently; 200 prevents
        # devtools from logging an error for an expected miss.
        empty = {
            "run_id": run_id,
            "strategy": None,
            "verdict": None,
            "signals": [],
            "dsr_probability": None,
        }
        if lookup.status == "no_folder":
            return _ok(empty), 200
        rob_path = Path(lookup.folder) / "robustness_result.json"
        if not rob_path.exists():
            return _ok(empty), 200
        try:
            # utf-8-sig handles a stray BOM if any tooling injected one.
            data = json.loads(rob_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            return _err(f"robustness_result.json parse failed: {e}"), 500
        # Keep payload tight: signals + verdict + the strategy name.
        # The full RobustnessSuiteResult is bigger than the FE needs.
        verdict = data.get("verdict") or {}
        return _ok({
            "run_id": run_id,
            "strategy": data.get("strategy"),
            "verdict": verdict.get("verdict"),
            "signals": verdict.get("signals", []),
            "dsr_probability": data.get("dsr_probability"),
        }), 200

    # Validation Suite — parallel, REPORT-ONLY layer (no verdict by design).
    # Reads validation.json (written by `tradelab run --validation`). 200 with an
    # empty signals[] for runs that exist but predate / didn't run validation, so
    # the panel renders "—" silently instead of logging a devtools error.
    m = re.match(r"^/tradelab/runs/([^/]+)/validation$", path)
    if m:
        run_id = m.group(1)
        lookup = audit_reader.resolve_run_folder(run_id, db_path=_db_path())
        if lookup.status == "no_run":
            return _err("run not found"), 404
        empty = {"run_id": run_id, "strategy": None, "suite_version": None, "signals": []}
        if lookup.status == "no_folder":
            return _ok(empty), 200
        val_path = Path(lookup.folder) / "validation.json"
        if not val_path.exists():
            return _ok(empty), 200
        try:
            data = json.loads(val_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            return _err(f"validation.json parse failed: {e}"), 500
        return _ok({
            "run_id": run_id,
            "strategy": data.get("strategy"),
            "suite_version": data.get("suite_version"),
            "signals": data.get("signals", []),
        }), 200

    if path == "/tradelab/data-freshness":
        return _ok(freshness.get_freshness(cache_root=_cache_root())), 200

    m = re.match(r"^/tradelab/ranges/([^/]+)$", path)
    if m:
        r = ranges.get_ranges(m.group(1), src_root=_src_root())
        if r is None:
            return _ok({"ranges": None}), 200
        return _ok({"ranges": r}), 200

    if path == "/tradelab/jobs":
        jm = _get_job_manager()
        return _ok({
            "jobs": [j.to_dict() for j in jm.list_jobs()],
            "running_id": jm._running_id,
            "queue": list(jm._queue),
        }), 200

    if path == "/tradelab/strategies":
        from tradelab.registry import list_registered_strategies
        try:
            strategies = list(list_registered_strategies().keys())
        except Exception as e:
            return _err(f"registry error: {e}"), 200
        return _ok({"strategies": strategies}), 200

    if path == "/tradelab/strategies/discoverable":
        from ..web.new_strategy import discover_unregistered_strategies
        try:
            return _ok({"strategies": discover_unregistered_strategies()}), 200
        except Exception as e:
            return _err(f"discovery failed: {type(e).__name__}: {e}"), 500

    if path == "/tradelab/preflight":
        from tradelab.web.preflight import compute_preflight
        return _ok(compute_preflight()), 200

    m = re.match(r"^/tradelab/strategies/([^/]+)/history$", path)
    if m:
        strategy = m.group(1)
        try:
            limit = int(q.get("limit", "10"))
        except (TypeError, ValueError):
            limit = 10
        runs = audit_reader.history_for_strategy(
            strategy, limit=limit, db_path=_db_path()
        )
        return json.dumps({"runs": runs}), 200

    if path == "/tradelab/cards":
        cards_path = _cards_path()
        if not cards_path.exists():
            return _ok({"groups": [], "total_cards": 0, "total_enabled": 0}), 200
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        view = cards_view.list_cards_view(
            reg.all_hydrated(),
            _alerts_log_path(),
        )
        return _ok(view), 200

    if path == "/tradelab/baselines":
        # Latest backtest metrics per strategy, fed to Command Center's
        # Strategy Divergence KPI so it compares against fresh OOS values
        # instead of frozen const fields. Strategies with no usable run
        # are absent from the dict — frontend keeps its baked-in fallback.
        baselines = audit_reader.baselines_for_all_strategies(db_path=_db_path())
        return _ok({"baselines": baselines}), 200

    m = re.match(r"^/tradelab/cards/([^/]+)/alerts$", path)
    if m:
        try:
            limit = int(q.get("limit", "50"))
        except (TypeError, ValueError):
            limit = 50
        alerts = cards_view.tail_alerts_for_card(
            m.group(1), _alerts_log_path(), limit=limit
        )
        return _ok({"alerts": alerts}), 200

    m = re.match(r"^/tradelab/cards/([^/]+)/archive$", path)
    if m:
        card_id = m.group(1)
        archive_dir = _pine_archive_root() / card_id
        # Lenient by design:
        # - Missing archive_dir → 404 (the card never had a Score/Accept frozen archive)
        # - Empty archive_dir → 200 with {} (something else removed files, that's OK)
        # - Partial archive (only one of pine/verdict) → 200 with what's there
        # - Malformed verdict.json → 200 with {"verdict": {"error": "..."}} (frontend can render what succeeded)
        # We return HTTP 200 instead of 4xx for partial/malformed data so the
        # frontend can render whatever IS valid alongside an inline error indicator.
        if not archive_dir.exists():
            return _err("archive not found"), 404
        pine_path = archive_dir / "strategy.pine"
        verdict_path = archive_dir / "verdict.json"
        out: dict = {}
        if pine_path.exists():
            out["pine_source"] = pine_path.read_text(encoding="utf-8")
        if verdict_path.exists():
            try:
                out["verdict"] = json.loads(
                    verdict_path.read_text(encoding="utf-8-sig")
                )
            except json.JSONDecodeError as e:
                out["verdict"] = {"error": f"verdict.json parse failed: {e}"}
        return _ok(out), 200

    m = re.match(r"^/tradelab/cards/([^/]+)/tracking-error$", path)
    if m:
        from ..live.tracking_error import compute_tracking_error, load_live_returns_for_card
        card_id = m.group(1)
        archive_root = _pine_archive_root()
        backtest_csv = archive_root / card_id / "tv_trades.csv"
        if not backtest_csv.exists():
            # Expected for non-Pine cards (e.g. legacy tradelab strategies in
            # the Research-tab health grid). 200 + insufficient lets the FE
            # render the same "n=0" placeholder it renders for empty live
            # returns, without filling devtools with 404s.
            return _ok({
                "status": "insufficient",
                "n_live_trades": 0,
                "n_backtest_trades": 0,
                "te": None,
                "decay_series": None,
                "ks_p_value": None,
                "ks_outcome": None,
            }), 200
        try:
            live_returns = load_live_returns_for_card(card_id)
            result = compute_tracking_error(backtest_csv, live_returns)
            return _ok(result.model_dump()), 200
        except Exception as e:
            return _err(f"tracking-error compute failed: {e}"), 500

    if path == "/tradelab/portfolio-health":
        from ..robustness.correlation import compute_pairwise_correlations
        from ..live.cards import CardRegistry
        archive_root = _pine_archive_root()
        try:
            cards_path = _cards_path()
            if not cards_path.exists():
                return _ok({"pairs": [], "max_return_rho": 0.0, "max_dd_rho": 0.0, "max_entry_overlap": 0.0}), 200
            reg = CardRegistry(cards_path)
            all_cards = reg.all_hydrated()
            enabled = [cid for cid, c in all_cards.items() if c.get("status") == "enabled"]
            result = compute_pairwise_correlations(archive_root, enabled)
            return _ok(result.model_dump()), 200
        except Exception as e:
            return _err(f"portfolio-health compute failed: {e}"), 500

    if path == "/tradelab/calibration-summary":
        from ..calibration.summary import summarize_calibration
        from ..live.cards import CardRegistry
        from ..live.tracking_error import compute_tracking_error, load_live_returns_for_card
        cards = list(CardRegistry(_cards_path()).all_hydrated().values())
        archive_root = _pine_archive_root()
        def _te_loader(card_id: str) -> dict:
            csv_path = archive_root / card_id / "tv_trades.csv"
            if not csv_path.exists():
                return {"status": "insufficient", "decay_series": None}
            try:
                live = load_live_returns_for_card(card_id)
                return compute_tracking_error(csv_path, live).model_dump()
            except Exception:
                return {"status": "insufficient", "decay_series": None}
        try:
            result = summarize_calibration(cards=cards, te_loader=_te_loader)
            return _ok(result.model_dump()), 200
        except Exception as e:
            return _err(f"calibration-summary failed: {e}"), 500

    if path == "/tradelab/regime":
        from ..regime.banner import fetch_regime
        unknown_payload = {
            "vol": "UNKNOWN", "trend": "UNKNOWN", "breadth": "UNKNOWN",
            "vix": None, "realized_vol_30d": None,
            "adx": None, "breadth_pct_above_50d": None,
            "last_shift_date": None, "days_stable": None,
        }
        try:
            result = fetch_regime()
            return _ok(result.model_dump()), 200
        except NotImplementedError:
            # Legacy fallback for when fetch_regime was a stub.
            return _ok(unknown_payload), 200
        except ValueError as e:
            # Insufficient SPY history (Alpaca data plan limit) or malformed
            # bars. Render UNKNOWN rather than 500 — the banner is a hint,
            # not a hard requirement, and a 500 would flood the console.
            return _ok({**unknown_payload, "_note": str(e)}), 200
        except Exception as e:
            return _err(f"regime fetch failed: {e}"), 500

    m = re.match(r"^/tradelab/correlation/([^/]+)$", path)
    if m:
        from ..robustness.correlation import compute_candidate_vs_cohort
        from ..live.cards import CardRegistry
        from ..io.returns import derive_daily_returns
        run_id = m.group(1)
        try:
            lookup = audit_reader.resolve_run_folder(run_id, db_path=_db_path())
        except Exception as e:
            return _err(f"audit lookup failed: {e}"), 500
        if lookup.status == "no_run":
            return _err("run not found"), 404
        # Empty result (200) for runs that exist but lack a tv_trades.csv —
        # CLI runs without --report (no folder) or pre-T6 runs that never
        # auto-froze a backtest CSV. FE renders Corr column as "—".
        empty = {
            "pairs": [], "max_return_rho": 0.0,
            "max_dd_rho": 0.0, "max_entry_overlap": 0.0,
        }
        if lookup.status == "no_folder":
            return _ok(empty), 200
        run_folder = lookup.folder
        tv_csv = run_folder / "tv_trades.csv"
        if not tv_csv.exists():
            return _ok(empty), 200
        try:
            candidate_returns_rows = derive_daily_returns(tv_csv)
            candidate_pairs = [(r["date"], r["return_pct"]) for r in candidate_returns_rows]
            archive_root = _pine_archive_root()
            cards_path = _cards_path()
            candidate_card_id: str | None = None
            if cards_path.exists():
                reg = CardRegistry(cards_path)
                all_cards = reg.all_hydrated()
                enabled = [cid for cid, c in all_cards.items() if c.get("status") == "enabled"]
                # If this run was previously accepted, its card_id is embedded as
                # scoring_run_id on the card. Filter it out to prevent self-correlation
                # producing a spurious rho=1.0 that would false-positive block T6's gate.
                for cid, card in all_cards.items():
                    if card.get("scoring_run_id") == run_id:
                        candidate_card_id = cid
                        break
            else:
                enabled = []
            result = compute_candidate_vs_cohort(
                archive_root, candidate_pairs, enabled,
                exclude_card_id=candidate_card_id,
            )
            return _ok(result.model_dump()), 200
        except Exception as e:
            return _err(f"correlation compute failed: {e}"), 500

    m = re.match(r"^/tradelab/relative-context/([^/]+)$", path)
    if m:
        # T6: rank a candidate's PF / DSR / DD against the cohort of currently
        # enabled live cards. Per-card PF and DD live in the audit DB sibling
        # `backtest_result.json` (via audit_reader.get_run_metrics(scoring_run_id))
        # since pine_archive/<card_id>/verdict.json only stores DSR + verdict.
        from ..live.cards import CardRegistry
        run_id = m.group(1)
        try:
            lookup = audit_reader.resolve_run_folder(run_id, db_path=_db_path())
        except Exception as e:
            return _err(f"audit lookup failed: {e}"), 500
        if lookup.status == "no_run":
            return _err("run not found"), 404
        if lookup.status == "no_folder":
            # Run exists but has no report folder (CLI run sans --report).
            # Return empty candidate/ranks with cohort_size=0 so the FE
            # renders "cohort sparse" rather than logging a 404.
            return _ok({
                "candidate": {"pf": None, "dsr": None, "dd": None},
                "pf": None, "dsr": None, "dd": None,
                "cohort_size": 0,
            }), 200
        run_folder = lookup.folder
        cand_metrics = audit_reader.get_run_metrics(run_id, db_path=_db_path()) or {}
        cand_pf = cand_metrics.get("profit_factor")
        cand_dd = cand_metrics.get("max_drawdown_pct")
        # DSR lives in the candidate's robustness_result.json (top-level).
        cand_dsr = None
        rob_file = run_folder / "robustness_result.json"
        if rob_file.exists():
            try:
                cand_dsr = json.loads(rob_file.read_text(encoding="utf-8")).get("dsr_probability")
            except Exception:
                cand_dsr = None

        archive_root = _pine_archive_root()
        cohort: list[dict] = []
        try:
            cards_path = _cards_path()
            if cards_path.exists():
                reg = CardRegistry(cards_path)
                all_cards = reg.all_hydrated()
                for cid, card in all_cards.items():
                    if card.get("status") != "enabled":
                        continue
                    # Skip the candidate's own card (if it's already accepted) so
                    # the rank doesn't compare it against itself.
                    if card.get("scoring_run_id") == run_id:
                        continue
                    pf = dd = None
                    sid = card.get("scoring_run_id")
                    if sid:
                        cm = audit_reader.get_run_metrics(sid, db_path=_db_path()) or {}
                        pf = cm.get("profit_factor")
                        dd = cm.get("max_drawdown_pct")
                    dsr = None
                    vfile = archive_root / cid / "verdict.json"
                    if vfile.exists():
                        try:
                            dsr = json.loads(vfile.read_text(encoding="utf-8")).get("dsr_probability")
                        except Exception:
                            dsr = None
                    cohort.append({
                        "card_id": cid,
                        "pf": pf,
                        "dsr": dsr,
                        "dd": dd,
                    })
        except Exception as e:
            return _err(f"cohort load failed: {e}"), 500

        def _rank(value, key, higher_is_better=True):
            """Return (rank, n_with_data, median, worst). rank is 1-based.
            None when value or all cohort values are missing."""
            if value is None:
                return None
            vals = [c[key] for c in cohort if c.get(key) is not None]
            n = len(vals)
            if n == 0:
                return {"rank": None, "n": 0, "median": None, "worst": None}
            if higher_is_better:
                better = sum(1 for v in vals if v > value)
                worst = min(vals)
            else:
                # DD is negative or expressed as % drawdown; "higher is worse".
                # We rank by abs() so smaller drawdown is better.
                better = sum(1 for v in vals if abs(v) < abs(value))
                worst = max(vals, key=lambda x: abs(x))
            sorted_vals = sorted(vals)
            mid = n // 2
            median = (sorted_vals[mid] if n % 2 else
                      (sorted_vals[mid - 1] + sorted_vals[mid]) / 2)
            # rank = how many cohort members the candidate beats + 1
            return {"rank": better + 1, "n": n + 1, "median": median, "worst": worst}

        return _ok({
            "candidate": {"pf": cand_pf, "dsr": cand_dsr, "dd": cand_dd},
            "pf": _rank(cand_pf, "pf", higher_is_better=True),
            "dsr": _rank(cand_dsr, "dsr", higher_is_better=True),
            "dd": _rank(cand_dd, "dd", higher_is_better=False),
            "cohort_size": len(cohort),
        }), 200

    if path == "/tradelab/receiver/status":
        return _ok(probe_receiver_status()), 200

    if path == "/tradelab/live/config":
        return handle_live_config_get()

    if path == "/tradelab/live/silence-status":
        return handle_silence_status_get()

    if path == "/tradelab/live/panic/last-event":
        return handle_panic_last_event_get()

    if path == "/tradelab/live/digest/preview":
        return handle_digest_preview_get()

    if path == "/tradelab/live/digest/state":
        return handle_digest_state_get()

    if path == "/tradelab/canary-status":
        # Engine integrity status query — reads latest verdict per canary
        # from the audit DB. Unenveloped shape (matches /tradelab/runs):
        # {"all_match": bool, "canaries": [...], "last_run_at": iso}.
        status = run_canary_check(db_path=_db_path())
        return json.dumps(status.to_dict()), 200

    # ─── Research v3 routes ────────────────────────────────────────────
    m = re.match(r"^/tradelab/runs/([^/]+)/qs-metrics$", path)
    if m:
        run_id = m.group(1)
        lookup = audit_reader.resolve_run_folder(run_id, db_path=_db_path())
        if lookup.status != "ok" or lookup.folder is None:
            return _err("run not found"), 404
        return _qs_metrics_response(run_id, lookup.folder)

    m = re.match(r"^/tradelab/strategies/([^/]+)/verdict-history$", path)
    if m:
        from tradelab.web import verdict_history
        verdicts = verdict_history.get_recent_verdicts(
            m.group(1), n=12, db_path=_db_path()
        )
        return json.dumps({"verdicts": verdicts}), 200

    if path == "/tradelab/strategies-summary":
        # Task 13: powers the cross-strategy factor matrix. Returns latest
        # signals[] per strategy from each run's robustness_result.json
        # so the FE can color cells by signal outcome and detect column-
        # wide weakness across the universe.
        from tradelab.web import strategies_summary
        strategies = strategies_summary.get_summaries(db_path=_db_path())
        return json.dumps({"strategies": strategies}), 200

    return _err("not found"), 404


def handle_post(path: str, body: bytes) -> str:
    """POST dispatcher. All POSTs return 200 with envelope (error may be set)."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body")

    if path == "/tradelab/whatif":
        try:
            result = whatif.run_whatif(
                strategy_name=payload["strategy"],
                symbol=payload["symbol"],
                params=payload.get("params") or {},
                start=payload.get("start"),
                end=payload.get("end"),
            )
            return _ok(result)
        except whatif.WhatIfError as e:
            return _err(str(e))
        except KeyError as e:
            return _err(f"missing required field: {e}")

    if path == "/tradelab/new-strategy":
        action = payload.get("action", "test")
        name = payload.get("name", "")

        if action == "test":
            code = payload.get("code", "")
            result = new_strategy.validate_and_stage(
                name=name,
                code=code,
                staging_root=_staging_root(),
                src_root=_src_root(),
            )
            # result already contains error/stage or success metrics
            if result.get("error"):
                return _err(result["error"], data={"stage": result.get("stage"), "traceback": result.get("traceback")})
            return _ok({
                "metrics": result.get("metrics", {}),
                "equity_curves_by_symbol": result.get("equity_curves_by_symbol", {}),
                "class_name": result.get("class_name"),
                "canonical_name": result.get("canonical_name"),
            })

        if action == "register":
            class_name = payload.get("class_name", "")
            reg = new_strategy.register_strategy(
                name=name,
                class_name=class_name,
                staging_root=_staging_root(),
                src_root=_src_root(),
                yaml_path=_yaml_path(),
            )
            if reg.get("error"):
                return _err(reg["error"])
            # Kick off background robustness run; don't wait.
            # Use the normalized canonical form so the CLI can find the strategy.
            canonical = new_strategy._normalize_name(name)
            subprocess.Popen(
                [sys.executable, "-m", "tradelab.cli", "run", canonical, "--robustness"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _ok({
                "final_path": reg["final_path"],
                "robustness_started": True,
                "canonical_name": canonical,
            })

        if action == "discard":
            new_strategy.discard_staging(name, staging_root=_staging_root())
            return _ok({"discarded": name})

        return _err(f"unknown action: {action}")

    if path == "/tradelab/save-variant":
        try:
            base = payload["base_strategy"]
            new_name = payload["new_name"]
            new_params = payload.get("params") or {}
        except KeyError as e:
            return _err(f"missing field: {e}")
        from tradelab.registry import get_strategy_entry, list_registered_strategies
        if new_name in list_registered_strategies():
            return _err(f"name '{new_name}' already registered")
        try:
            entry = get_strategy_entry(base)
        except Exception as e:
            return _err(f"base strategy not registered: {e}")
        module_path = entry.module.replace("tradelab.strategies.", "")
        src_file = _src_root() / "tradelab" / "strategies" / f"{module_path}.py"
        if not src_file.exists():
            return _err(f"base strategy file missing: {src_file}")
        # Read the original source, then write it with the new default params injected
        code = src_file.read_text()
        code = _inject_default_params(code, new_params)
        result = new_strategy.validate_and_stage(
            name=new_name,
            code=code,
            staging_root=_staging_root(),
            src_root=_src_root(),
        )
        if result["error"]:
            return _err(result["error"], data={"stage": result.get("stage")})
        reg = new_strategy.register_strategy(
            name=new_name,
            class_name=result["class_name"],
            staging_root=_staging_root(),
            src_root=_src_root(),
            yaml_path=_yaml_path(),
        )
        if reg["error"]:
            return _err(reg["error"])
        subprocess.Popen(
            [sys.executable, "-m", "tradelab.cli", "run", new_name, "--robustness"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return _ok({"final_path": reg["final_path"]})

    if path == "/tradelab/refresh-data":
        # Fire-and-forget: launcher polls /tradelab/data-freshness afterward
        try:
            from tradelab.marketdata import download_symbols
            from tradelab.config import get_config
            cfg = get_config()
            # DefaultsConfig has no `universe` field. Resolve from payload,
            # then launcher-state.json, then the first universe in tradelab.yaml.
            universe_name = payload.get("universe") or _resolve_active_universe()
            if not universe_name:
                return _err("no universe selected and no default available")
            if universe_name not in cfg.universes:
                return _err(f"unknown universe: {universe_name!r}")
            symbols = cfg.universes[universe_name]
            download_symbols(symbols)
            return _ok({"refreshed": len(symbols), "universe": universe_name})
        except Exception as e:
            return _err(f"refresh failed: {e}")

    return _err("not found")


def handle_post_with_status(path: str, body: bytes) -> Tuple[str, int]:
    """POST dispatcher with explicit status. Mirrors handle_get_with_status.

    Routes that need explicit status codes (201/400/409/410) live here.
    Other POSTs delegate to the legacy handle_post() for backward compat.
    """
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    m = re.match(r"^/tradelab/runs/([^/]+)/unarchive$", path)
    if m:
        run_id = m.group(1)
        archive.unarchive_run(run_id, db_path=_db_path())
        # Idempotent: succeed regardless of whether a row was actually removed.
        return "", 204

    if path == "/tradelab/runs/bulk-delete":
        run_ids = payload.get("run_ids")
        if run_ids is None:
            return _err("missing run_ids field"), 400
        if not isinstance(run_ids, list):
            return _err("run_ids must be a list"), 400

        deleted: list[str] = []
        failed: list[dict] = []
        for run_id in run_ids:
            del_body, status = _delete_run(str(run_id))
            if status == 204:
                deleted.append(str(run_id))
            else:
                try:
                    msg = json.loads(del_body).get("error", "unknown error")
                except (json.JSONDecodeError, AttributeError):
                    msg = "unknown error"
                failed.append({"id": str(run_id), "reason": msg})

        return json.dumps({"deleted": deleted, "failed": failed}), 200

    if path == "/tradelab/runs/preview-delete":
        # Task 15: read-only cascade detection for the FE delete-confirm
        # modal. Given a list of run_ids, returns each live card whose
        # scoring_run_id is in the set so the FE can escalate to a
        # card-aware confirm (Tier 2 / Tier 4).
        run_ids = payload.get("run_ids")
        if run_ids is None:
            return _err("missing run_ids field"), 400
        if not isinstance(run_ids, list):
            return _err("run_ids must be a list"), 400

        from tradelab.web import run_cascade
        cards_path = _cards_path()
        if not cards_path.exists():
            return json.dumps({"cascade": []}), 200
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        cascade = run_cascade.cards_powered_by_runs(
            {str(r) for r in run_ids},
            reg.all_hydrated().values(),
        )
        return json.dumps({"cascade": cascade}), 200

    if path == "/tradelab/jobs":
        return _post_job(payload)

    if path.startswith("/tradelab/jobs/") and path.endswith("/cancel"):
        job_id = path[len("/tradelab/jobs/"):-len("/cancel")]
        return _cancel_job(job_id)

    if path == "/tradelab/compare":
        from tradelab.web.compare import run_compare
        body_dict, status = run_compare(
            run_ids=payload.get("run_ids") or [],
            benchmark=payload.get("benchmark") or "SPY",
        )
        return json.dumps(body_dict), status

    if path == "/tradelab/score":
        from tradelab.io.tv_csv import TVCSVParseError
        from tradelab.web import approve_strategy

        err = _validate_score_payload(payload)
        if err:
            return _err(err), 400
        try:
            data = approve_strategy.score_csv(
                csv_text=payload["csv_text"],
                pine_source=payload.get("pine_source") or None,
                symbol=payload["symbol"],
                base_name=payload["base_name"],
                timeframe=payload["timeframe"],
                reports_root=_reports_root(),
                db_path=_db_path(),
            )
            return _ok(data), 200
        except TVCSVParseError as e:
            return _err(str(e)), 400
        except ValueError as e:
            return _err(str(e)), 400
        except Exception as e:
            print(f"[handlers] /tradelab/score unexpected: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return _err("scoring failed: internal error"), 500

    if path == "/tradelab/accept":
        from tradelab.live.cards import CardExistsError, CardRegistry
        from tradelab.web import approve_strategy

        err = _validate_accept_payload(payload)
        if err:
            return _err(err), 400
        try:
            registry = CardRegistry(_cards_path())
            data = approve_strategy.accept_scored(
                base_name=payload["base_name"],
                symbol=payload["symbol"],
                timeframe=payload["timeframe"],
                report_folder=payload["report_folder"],
                verdict=payload.get("verdict", "INCONCLUSIVE"),
                dsr_probability=payload.get("dsr_probability"),
                scoring_run_id=payload.get("scoring_run_id", ""),
                registry=registry,
                pine_archive_root=_pine_archive_root(),
                reports_root=_reports_root(),
                activate=bool(payload.get("activate", False)),
            )
            if payload.get("activate"):
                # Notify FE listeners (Task 16 wires the dispatch on the FE side).
                try:
                    from tradelab.web import get_broadcaster
                    get_broadcaster().broadcast({
                        "type": "card_activated",
                        "card_id": data["card_id"],
                    })
                except Exception:
                    pass
            return _ok(data), 200
        except approve_strategy.ActivationGateFailed as e:
            return _err(str(e)), 422
        except FileNotFoundError as e:
            print(f"[handlers] /tradelab/accept report folder missing: {e}", file=sys.stderr)
            return _err("report folder not found"), 404
        except FileExistsError as e:
            return _err(f"pine archive already exists: {e}"), 409
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except ValueError as e:
            return _err(str(e)), 400
        except Exception as e:
            print(f"[handlers] /tradelab/accept unexpected: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return _err("accept failed: internal error"), 500

    if path == "/tradelab/strategies/accept":
        from tradelab.live.cards import CardExistsError, CardRegistry
        from tradelab.web import approve_strategy
        required = ("base_name", "symbol", "timeframe", "report_folder", "strategy")
        missing = [k for k in required if not (payload.get(k) or "").strip()]
        if missing:
            return _err(f"missing required fields: {', '.join(missing)}"), 400
        try:
            card = approve_strategy.accept_python_run(
                base_name=payload["base_name"], symbol=payload["symbol"],
                timeframe=payload["timeframe"], report_folder=payload["report_folder"],
                verdict=payload.get("verdict", "INCONCLUSIVE"),
                dsr_probability=payload.get("dsr_probability"),
                scoring_run_id=payload.get("scoring_run_id", ""),
                strategy=payload["strategy"],
                registry=CardRegistry(_cards_path()),
                reports_root=_reports_root(),
                activate=bool(payload.get("activate", False)),
                confirm_non_robust=bool(payload.get("confirm_non_robust", False)),
            )
            return _ok(card), 200
        except approve_strategy.ActivationGateFailed as e:
            return _err(str(e)), 422
        except FileNotFoundError:
            return _err("report folder not found"), 404
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except Exception as e:
            return _err(f"accept failed: {type(e).__name__}: {e}"), 500

    # Task 10: one-click activate. Looks up the strategy's latest run, derives
    # symbol/timeframe from its backtest_result.json, and forwards to
    # accept_scored(activate=True). Reuses every gate, side effect, and SSE
    # broadcast from the /tradelab/accept code path.
    m = re.match(r"^/tradelab/strategies/([^/]+)/activate$", path)
    if m:
        strategy_id = m.group(1)
        from tradelab.live.cards import CardExistsError, CardRegistry
        from tradelab.web import approve_strategy

        # 1. Latest audit row for this strategy.
        runs = audit_reader.list_runs(
            strategy=strategy_id, limit=1, db_path=_db_path()
        )
        if not runs:
            return _err(f"no runs found for strategy {strategy_id!r}"), 422
        latest = runs[0]

        # 2. Resolve the report folder. no_run shouldn't happen (we just read
        # the row from the same DB), but no_folder is a real failure mode for
        # CLI runs invoked without --report.
        lookup = audit_reader.resolve_run_folder(
            latest["run_id"], db_path=_db_path()
        )
        if lookup.status != "ok" or lookup.folder is None:
            return _err(
                f"latest run {latest['run_id']} has no report folder"
            ), 422

        # 3. Read symbol/timeframe from backtest_result.json (the report
        # folder's metadata file written by csv_scoring.write_report_folder).
        bt_json_path = lookup.folder / "backtest_result.json"
        if not bt_json_path.exists():
            return _err(
                f"backtest_result.json missing in {lookup.folder}"
            ), 422
        try:
            bt_json = json.loads(bt_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return _err(f"backtest_result.json unreadable: {e}"), 422

        symbol = bt_json.get("symbol")
        timeframe = bt_json.get("timeframe")
        if not symbol or not timeframe:
            return _err(
                "backtest_result.json missing symbol/timeframe"
            ), 422

        # 4. Forward to accept_scored with activate=True.
        registry = CardRegistry(_cards_path())

        # Defensive guard: if any enabled card already exists for this
        # base_name, refuse rather than auto-bumping to -v2. The FE button
        # state machine ("● Already live ↗") prevents this from the UI, but
        # a duplicate POST should fail loudly so the FE can react.
        for cid, card in registry.all().items():
            if (
                card.get("base_name") == latest["strategy_name"]
                and card.get("status") == "enabled"
            ):
                return _err(
                    f"strategy {latest['strategy_name']!r} already activated as "
                    f"{cid}; deactivate it first to re-activate"
                ), 409
        try:
            data = approve_strategy.accept_scored(
                base_name=latest["strategy_name"],
                symbol=symbol,
                timeframe=timeframe,
                report_folder=str(lookup.folder),
                verdict=latest["verdict"] or "INCONCLUSIVE",
                dsr_probability=latest["dsr_probability"],
                scoring_run_id=latest["run_id"],
                registry=registry,
                pine_archive_root=_pine_archive_root(),
                reports_root=_reports_root(),
                activate=True,
            )
            # Notify FE listeners (Task 16 wires SSE listener on the FE side).
            try:
                from tradelab.web import get_broadcaster
                get_broadcaster().broadcast({
                    "type": "card_activated",
                    "card_id": data["card_id"],
                })
            except Exception:
                pass
            return _ok(data), 200
        except approve_strategy.ActivationGateFailed as e:
            return _err(str(e)), 422
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except FileNotFoundError as e:
            return _err(f"report folder unavailable: {e}"), 422
        except ValueError as e:
            return _err(str(e)), 400
        except Exception as e:
            print(
                f"[handlers] /tradelab/strategies/{strategy_id}/activate "
                f"unexpected: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            return _err("activate failed: internal error"), 500

    if path == "/tradelab/cards/bulk-toggle":
        ids = payload.get("ids")
        status_val = payload.get("status")
        if not isinstance(ids, list) or not ids:
            return _err("ids must be a non-empty list"), 400
        if status_val not in _ALLOWED_STATUSES:
            return _err(f"status must be one of {sorted(_ALLOWED_STATUSES)}"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("no cards.json"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        updated, failed = reg.bulk_update_status(
            [str(cid) for cid in ids], status_val
        )
        return _ok({"updated": updated, "failed": failed}), 200

    if path == "/tradelab/cards/bulk-delete":
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids:
            return _err("ids must be a non-empty list"), 400
        if payload.get("confirm") != "DELETE":
            return _err("missing confirm: 'DELETE' to bulk-delete cards"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("no cards.json"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        deleted, failed = reg.bulk_delete([str(cid) for cid in ids])
        return _ok({"deleted": deleted, "failed": failed}), 200

    if path == "/tradelab/live/config/test-notification":
        return handle_test_notification(payload)

    if path == "/tradelab/live/panic":
        return handle_panic_post(payload)

    if path == "/tradelab/strategies/import":
        from ..web.new_strategy import import_discovered
        name = (payload.get("name") or "").strip()
        class_name = (payload.get("class_name") or "").strip()
        if not name or not class_name:
            return _err("name and class_name are required"), 400
        try:
            res = import_discovered(name, class_name)
        except Exception as e:
            return _err(f"import failed: {type(e).__name__}: {e}"), 500
        if res.get("error"):
            return _err(res["error"]), 409
        return _ok(res), 200

    # Fallback to legacy POST dispatcher for everything else
    return handle_post(path, body), 200


def handle_patch_with_status(path: str, body: bytes) -> Tuple[str, int]:
    """PATCH dispatcher with explicit status."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    m = re.match(r"^/tradelab/cards/([^/]+)$", path)
    if m:
        card_id = m.group(1)
        err = _validate_patch_card_payload(payload)
        if err:
            return _err(err), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("card not found"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        try:
            reg.update(card_id, payload)
        except KeyError:
            return _err("card not found"), 404
        return _ok({"updated": card_id}), 200

    if path == "/tradelab/live/config":
        return handle_live_config_patch(payload)

    return _err("not found"), 404


def _post_job(payload: dict) -> Tuple[str, int]:
    import tradelab.web as web_pkg
    from tradelab.web import get_job_manager
    from tradelab.web import jobs as jobs_mod

    if not web_pkg.supports_progress_log():
        return _err(
            "this tradelab build is missing --progress-log; rebuild from current master"
        ), 503

    strategy = payload.get("strategy", "")
    command = payload.get("command", "")
    if not strategy or not command:
        return _err("strategy and command required"), 400

    argv = _build_tradelab_argv(strategy, command)
    if argv is None:
        return _err(f"invalid command or strategy name: {command!r} / {strategy!r}"), 400

    jm = get_job_manager()
    try:
        job_id, status = jm.submit(strategy, command, argv)
    except jobs_mod.DuplicateJobError as e:
        return _err("job already in flight",
                    data={"existing_job_id": e.existing_job_id}), 409

    return _ok({
        "job_id": job_id,
        "status": status.value,
    }), 201


def handle_sse(wfile) -> None:
    """SSE endpoint for /tradelab/jobs/stream.

    Called by launch_dashboard.py's do_GET branch directly. Subscribes the
    connection to the broadcaster and blocks until the client disconnects.

    The caller (HTTP server) is responsible for sending the response headers
    (200 OK, Content-Type: text/event-stream, Cache-Control: no-cache,
    Connection: keep-alive) before invoking this.
    """
    from tradelab.web import get_broadcaster, get_job_manager

    bc = get_broadcaster()
    jm = get_job_manager()

    # Build the initial-state replay: one synthetic event per active job
    initial_state = []
    for j in jm.list_jobs():
        if j.status.value in ("running", "queued"):
            initial_state.append({
                "job_id": j.id,
                "event": {
                    "type": "state",
                    "status": j.status.value,
                    "summary": j.last_event_summary or "",
                    "strategy": j.strategy,
                    "command": j.command,
                },
            })

    token = bc.subscribe(wfile, initial_state=initial_state)
    # Block until the broadcaster prunes our token (broken-pipe on a write
    # detected during a broadcast removes the client from the registry).
    # Poll once per second; the actual disconnect detection happens inside
    # broadcast(), this loop just waits for it.
    try:
        import time
        while bc.is_subscribed(token):
            time.sleep(1.0)
    finally:
        bc.unsubscribe(token)


def handle_notify_sse(wfile) -> None:
    """SSE endpoint for /tradelab/live/notify-stream.

    Subscribes to the notify broadcaster (separate from the job-tracker
    broadcaster). No initial-state replay — notifications are ephemeral;
    a new browser tab only sees events emitted after subscription.
    """
    from tradelab.web import get_notify_broadcaster

    bc = get_notify_broadcaster()
    # Pass an empty list (not None) so the spec §6.3 retry hint is sent
    token = bc.subscribe(wfile, initial_state=[])
    try:
        import time
        while bc.is_subscribed(token):
            time.sleep(1.0)
    finally:
        bc.unsubscribe(token)


def _cancel_job(job_id: str) -> Tuple[str, int]:
    from tradelab.web import get_job_manager
    jm = get_job_manager()
    job = jm.get(job_id)
    if job is None:
        return _err("job not found"), 404
    if job.status.value not in ("queued", "running"):
        return _err(f"job is in terminal state {job.status.value!r}"), 410
    jm.cancel(job_id)
    return _ok({"job_id": job_id, "status": "cancelled"}), 200


# ─── Envelope helpers ────────────────────────────────────────────────


def _ok(data) -> str:
    return json.dumps({"error": None, "data": data})


def _err(msg: str, data=None) -> str:
    return json.dumps({"error": msg, "data": data})


# ─── Misc helpers ────────────────────────────────────────────────────


def _inject_default_params(code: str, new_defaults: dict) -> str:
    """Rewrite the `default_params = {...}` class attribute with new_defaults.

    Naive replacement — expects a single `default_params = {` line in the file.
    Falls back to inserting a new class-level assignment after the class
    declaration if not found.
    """
    import re as _re
    if not new_defaults:
        return code
    literal = repr(new_defaults)
    pattern = _re.compile(r"default_params\s*=\s*\{[^}]*\}", _re.MULTILINE | _re.DOTALL)
    if pattern.search(code):
        return pattern.sub(f"default_params = {literal}", code, count=1)
    # fallback: insert after first class definition line
    cls = _re.compile(r"(class \w+\([^)]*Strategy[^)]*\):\s*\n)")
    m = cls.search(code)
    if m:
        insertion = m.group(0) + f"    default_params = {literal}\n"
        return cls.sub(insertion, code, count=1)
    return code


# ─── Validation for PATCH /tradelab/cards/<id> ───────────────────────

_ALLOWED_PATCH_FIELDS = {
    "status", "quantity", "cadence", "daily_limit",
    "cooldown_seconds", "allow_collision", "allow_naked_short",
    "capital", "max_positions",
}
_ALLOWED_STATUSES = {"enabled", "disabled"}
_ALLOWED_CADENCES = {"intraday", "daily", "weekly", "manual"}


def _validate_patch_card_payload(payload: dict) -> Optional[str]:
    """Returns error message string or None if valid."""
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    if not payload:
        return "no fields to update"
    unknown = set(payload.keys()) - _ALLOWED_PATCH_FIELDS
    if unknown:
        return f"unknown field: {sorted(unknown)[0]}"

    if "status" in payload and payload["status"] not in _ALLOWED_STATUSES:
        return f"status must be one of {sorted(_ALLOWED_STATUSES)}"
    if "quantity" in payload:
        q = payload["quantity"]
        if q is not None and (not isinstance(q, int) or isinstance(q, bool) or q < 1):
            return "quantity must be a positive int or null"
    if "cadence" in payload and payload["cadence"] not in _ALLOWED_CADENCES:
        return f"cadence must be one of {sorted(_ALLOWED_CADENCES)}"
    for k in ("daily_limit", "cooldown_seconds"):
        if k in payload:
            v = payload[k]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                return f"{k} must be a non-negative int"
    if "capital" in payload:
        v = payload["capital"]
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
            return "capital must be a non-negative number or null"
    if "max_positions" in payload:
        v = payload["max_positions"]
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            return "max_positions must be a non-negative int or null"
    for k in ("allow_collision", "allow_naked_short"):
        if k in payload and not isinstance(payload[k], bool):
            return f"{k} must be a bool"
    return None


# ─── Validation for PATCH /tradelab/live/config ──────────────────────

_ALLOWED_LIVE_CONFIG_TOP_LEVEL = {
    "schema_version", "notifications", "guardrails", "silence", "email_digest",
}
_ALLOWED_NOTIFICATIONS_KEYS = {
    "enabled_channels", "severity_routing", "ntfy", "smtp", "audible",
}
_ALLOWED_CHANNELS = {"browser", "windows_toast", "audible", "ntfy", "email"}
_ALLOWED_SEVERITIES = {"critical", "warning", "info"}


def _validate_live_config_payload(payload) -> Optional[str]:
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    unknown = set(payload.keys()) - _ALLOWED_LIVE_CONFIG_TOP_LEVEL
    if unknown:
        return f"unknown top-level field: {sorted(unknown)[0]}"
    notif = payload.get("notifications", {})
    if not isinstance(notif, dict):
        return "notifications must be an object"
    unknown = set(notif.keys()) - _ALLOWED_NOTIFICATIONS_KEYS
    if unknown:
        return f"unknown notifications field: {sorted(unknown)[0]}"
    if "enabled_channels" in notif:
        ec = notif["enabled_channels"]
        if not isinstance(ec, list) or any(c not in _ALLOWED_CHANNELS for c in ec):
            return f"enabled_channels must be a subset of {sorted(_ALLOWED_CHANNELS)}"
    if "severity_routing" in notif:
        sr = notif["severity_routing"]
        if not isinstance(sr, dict):
            return "severity_routing must be an object"
        for sev, chans in sr.items():
            if sev not in _ALLOWED_SEVERITIES:
                return f"unknown severity: {sev}"
            if not isinstance(chans, list) or any(c not in _ALLOWED_CHANNELS for c in chans):
                return f"severity_routing[{sev}] must be a list of channel names"
    if "guardrails" in payload:
        g = payload["guardrails"]
        if not isinstance(g, dict):
            return "guardrails must be an object"
        if "max_exposure_pct" in g:
            v = g["max_exposure_pct"]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0.0 < v <= 1.0):
                return "max_exposure_pct must be a number in (0, 1]"
    return None


def handle_live_config_get() -> Tuple[str, int]:
    from tradelab.live import live_config
    return _ok(live_config.mask_passwords(live_config.get())), 200


def handle_live_config_patch(payload) -> Tuple[str, int]:
    err = _validate_live_config_payload(payload)
    if err is not None:
        return _err(err), 400
    # Strip masked passwords (treat "******" as no-change)
    if isinstance(payload, dict):
        smtp = payload.get("notifications", {}).get("smtp", {})
        if isinstance(smtp, dict) and smtp.get("password") == "******":
            smtp.pop("password")
    from tradelab.live import live_config
    live_config.update(payload)
    return _ok(live_config.mask_passwords(live_config.get())), 200


def handle_test_notification(payload) -> Tuple[str, int]:
    if not isinstance(payload, dict):
        return _err("payload must be a JSON object"), 400
    channel = payload.get("channel")
    severity_str = payload.get("severity", "info")
    if channel not in _ALLOWED_CHANNELS:
        return _err(f"channel must be one of {sorted(_ALLOWED_CHANNELS)}"), 400
    if severity_str not in _ALLOWED_SEVERITIES:
        return _err(f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}"), 400
    from tradelab.live import notify
    from tradelab.live.notify import Severity
    notify.notify(
        Severity(severity_str),
        f"Test notification ({channel})",
        f"Synthetic {severity_str} event from settings panel",
        channels={channel},
    )
    return _ok({"channel": channel, "severity": severity_str}), 200


def handle_silence_status_get() -> Tuple[str, int]:
    """Return current silent-card set as {<card_id>: true} envelope."""
    from tradelab.live import silence_checker
    return _ok({cid: True for cid in silence_checker.silent_set()}), 200


def handle_digest_preview_get() -> Tuple[str, int]:
    """GET /tradelab/live/digest/preview — render today's digest as HTML.

    Pure render. Does not send, does not write state, does not log.
    Returns 200 with the rendered HTML body on success, or 500 with the
    standard JSON error envelope (`{"error": ..., "data": null}`) on render
    failure.

    Note: the launcher's HTTP dispatcher hardcodes Content-Type to
    application/json regardless of body type — this 200 response will
    technically arrive at the browser as application/json. The FE in T12
    does `await resp.text(); el.innerHTML = body`, so the wrong content-type
    is cosmetic, not functional. Filed as a follow-up if it ever matters.
    """
    from datetime import datetime
    from tradelab.live import daily_summary
    try:
        _, html_body = daily_summary.render(datetime.now(daily_summary._ET))
        return html_body, 200
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}"), 500


def handle_digest_state_get() -> Tuple[str, int]:
    """GET /tradelab/live/digest/state — return the current digest state dict.

    Pure read. Does not write state. Returns 200 with the parsed state
    dict, or 200 with data=null when the state file is missing, empty,
    or unparseable — `_read_state()` returns {} for all those cases and
    we surface that as null to the FE (missing state is not an error).
    """
    from tradelab.live import daily_summary
    state = daily_summary._read_state()
    # _read_state() returns {} for both missing-file and unparseable-file
    # cases (corrupt JSON is logged to stderr there and squashed to {}).
    # We intentionally collapse both into data=null at this layer for v1 —
    # the FE just needs "have we sent today or not?" and corrupt-state is
    # rare given the atomic-replace writer. Revisit if duplicate-send
    # incidents surface (would need a `state_health` field in the envelope).
    if not state:
        return _ok(None), 200
    return _ok(state), 200


def handle_panic_last_event_get() -> Tuple[str, int]:
    """GET /tradelab/live/panic/last-event — return most recent panic event
    as JSON, or null if no events exist (or file is empty/corrupt at tail)."""
    from tradelab.live import panic
    if not panic.PANIC_LOG_PATH.exists():
        return _ok(None), 200
    try:
        text = panic.PANIC_LOG_PATH.read_text(encoding="utf-8")
    except Exception:
        return _ok(None), 200

    # Iterate non-empty lines from the bottom up; return first parseable one.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return _ok(json.loads(ln)), 200
        except json.JSONDecodeError:
            continue
    return _ok(None), 200


_PANIC_CONFIRM_WORDS = {"L1": "DISABLE", "L2": "PANIC", "L3": "FLATTEN"}


def handle_panic_post(payload: dict) -> Tuple[str, int]:
    """POST /tradelab/live/panic — execute panic at the given level.

    Body: {level: "L1"|"L2"|"L3", confirm: "DISABLE"|"PANIC"|"FLATTEN",
           also_cancel_nontradelab?: bool}
    Server-side confirm-word check is defense in depth — FE also enforces.
    """
    level = payload.get("level")
    confirm = payload.get("confirm")
    if level not in _PANIC_CONFIRM_WORDS:
        return json.dumps({"ok": False, "error": f"invalid or missing level (got {level!r}); expected L1/L2/L3", "data": None}), 400
    if confirm != _PANIC_CONFIRM_WORDS[level]:
        return json.dumps({"ok": False, "error": f"confirm word mismatch for {level} (expected {_PANIC_CONFIRM_WORDS[level]!r})", "data": None}), 400

    also_cancel = bool(payload.get("also_cancel_nontradelab", False))
    # L1 has no Alpaca calls; the flag is meaningless. Force-False for safety.
    if level == "L1":
        also_cancel = False

    from tradelab.live import panic
    try:
        result = panic.execute_panic(level, also_cancel_nontradelab=also_cancel)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"panic execution raised: {type(e).__name__}: {e}", "data": None}), 500

    from dataclasses import asdict
    return json.dumps({"ok": True, "error": None, "data": asdict(result)}), 200


# ─── Validation for /tradelab/score + /tradelab/accept (Option H 3a) ──

import re as _re_mod

_BASE_NAME_RE = _re_mod.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
# Symbol: 1-5 uppercase letters (typical US ticker). Plan text says 1-10 but
# the Step-1 test explicitly rejects the 10-char "TOOLONGSYM", so the tighter
# bound is what the tests (ground truth) require.
_SYMBOL_RE = _re_mod.compile(r"^[A-Z]{1,5}$")
_ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W"}


def _validate_score_payload(payload: dict) -> Optional[str]:
    """Returns error message string or None if valid."""
    for key in ("csv_text", "symbol", "base_name", "timeframe"):
        if not payload.get(key):
            return f"missing field: {key}"
    if not _BASE_NAME_RE.match(payload["base_name"]):
        return "base_name must be lowercase alphanumeric with hyphens, 2–48 chars"
    if not _SYMBOL_RE.match(payload["symbol"]):
        return "symbol must be 1–5 uppercase letters"
    if payload["timeframe"] not in _ALLOWED_TIMEFRAMES:
        return f"unknown timeframe: {payload['timeframe']!r}"
    return None


def _validate_accept_payload(payload: dict) -> Optional[str]:
    """Returns error message string or None if valid."""
    for key in ("base_name", "symbol", "timeframe", "report_folder"):
        if not payload.get(key):
            return f"missing field: {key}"
    if not _BASE_NAME_RE.match(payload["base_name"]):
        return "base_name must be lowercase alphanumeric with hyphens, 2–48 chars"
    if not _SYMBOL_RE.match(payload["symbol"]):
        return "symbol must be 1–5 uppercase letters"
    if payload["timeframe"] not in _ALLOWED_TIMEFRAMES:
        return f"unknown timeframe: {payload['timeframe']!r}"
    if "activate" in payload and not isinstance(payload["activate"], bool):
        return "activate must be a boolean"
    return None


def handle_delete_with_status(path: str) -> tuple[str, int]:
    """DELETE dispatcher with explicit status."""
    m = re.match(r"^/tradelab/runs/([^/]+)$", path)
    if m:
        run_id = m.group(1)
        return _delete_run(run_id)

    return _err("not found"), 404


def handle_delete_with_status_with_body(path: str, body: bytes) -> Tuple[str, int]:
    """DELETE dispatcher that also accepts a body. Routes that need body
    confirmation (cards) call this; legacy DELETE (runs) keep using
    handle_delete_with_status."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    m = re.match(r"^/tradelab/cards/([^/]+)$", path)
    if m:
        card_id = m.group(1)
        if payload.get("confirm") != "DELETE":
            return _err("missing confirm: 'DELETE' to delete card"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("card not found"), 404
        from tradelab.live.cards import CardRegistry
        reg = CardRegistry(cards_path)
        try:
            reg.delete(card_id)
        except KeyError:
            return _err("card not found"), 404
        return _ok({"deleted": card_id}), 200

    # Fall through to body-less variant for legacy routes
    return handle_delete_with_status(path)


def _load_daily_returns_for_run(folder: Path):
    """Build a pd.Series of daily returns from the run's backtest_result.json.

    Returns an empty Series if the file is missing or has no equity_curve.
    Pandas is imported lazily so cold-path callers don't pay the import cost.
    """
    import pandas as pd  # lazy
    bt_file = folder / "backtest_result.json"
    if not bt_file.exists():
        return pd.Series(dtype=float)
    try:
        data = json.loads(bt_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return pd.Series(dtype=float)
    ec = data.get("equity_curve") or []
    if not ec:
        return pd.Series(dtype=float)
    try:
        dates = pd.to_datetime([p["date"] for p in ec])
        equities = [float(p["equity"]) for p in ec]
    except (KeyError, ValueError, TypeError):
        return pd.Series(dtype=float)
    s = pd.Series(equities, index=pd.DatetimeIndex(dates), dtype=float)
    return s.pct_change().dropna()


def _qs_metrics_response(run_id: str, folder: Path) -> tuple[str, int]:
    """Compute QuantStats sub-grid metrics for one run. Unenveloped JSON."""
    from tradelab.web import qs_metrics
    returns = _load_daily_returns_for_run(folder)
    if len(returns) == 0:
        return _err("no equity curve for run"), 404

    monthly = qs_metrics.monthly_returns_matrix(returns).fillna(0.0).values.tolist()
    rolling = qs_metrics.rolling_sharpe(returns).dropna().tolist()
    drawdown = qs_metrics.drawdown_series(returns).tolist()
    metrics = audit_reader.get_run_metrics(run_id, db_path=_db_path()) or {}
    payload = {
        "sharpe":           qs_metrics.sharpe(returns),
        "sortino":          qs_metrics.sortino(returns),
        "cagr":             qs_metrics.cagr(returns),
        "max_drawdown":     qs_metrics.max_drawdown(returns),
        "monthly_returns":  monthly,
        "rolling_sharpe":   rolling,
        "drawdown_series":  drawdown,
        "total_return":     float((1.0 + returns).prod() - 1.0),
        "trades":           metrics.get("total_trades", metrics.get("trades", 0)),
        "win_rate":         metrics.get("win_rate", 0.0),
        "profit_factor":    metrics.get("profit_factor", 0.0),
        "avg_win_pct":      metrics.get("avg_win_pct", 0.0),
        "avg_loss_pct":     metrics.get("avg_loss_pct", 0.0),
        "avg_bars_held":    metrics.get("avg_bars_held", 0.0),
    }
    return json.dumps(payload), 200


def _delete_run(run_id: str) -> tuple[str, int]:
    """Hard-delete a run: DB row + report folder + JSONL audit log entry.

    Idempotent: if the run is already gone (or the DB hasn't been created
    yet) returns 204 — callers shouldn't have to distinguish "deleted now"
    from "already deleted" for stale FE state. On success, broadcasts a
    run_deleted SSE event for FE pipeline reconciliation (Task 16 dispatches
    on event.type).

    Behavior change (2026-04-30, Research v3): replaced the prior
    soft-archive flow (which kept the runs row and inserted into
    archived_runs). The /unarchive route + archive primitives still exist
    for any legacy archived rows; nothing new lands there.
    """
    db = _db_path()
    if not db.exists():
        return "", 204  # idempotent: nothing to delete

    from tradelab.web import run_deletion
    try:
        manifest = run_deletion.delete_run_atomic(run_id, db_path=db)
    except run_deletion.RunNotFound:
        return "", 204  # idempotent
    except OSError as e:
        return _err(f"folder removal failed: {e}"), 409
    except Exception as e:
        print(f"[handlers] _delete_run({run_id}): "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return _err("delete failed: internal error"), 500

    try:
        from tradelab.web import get_broadcaster
        get_broadcaster().broadcast({
            "type":     "run_deleted",
            "run_id":   manifest["run_id"],
            "strategy": manifest["strategy"],
        })
    except Exception:
        pass

    return "", 204
