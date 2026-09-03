"""HTTP request handlers for /tradelab/* routes.

Pure dispatch — no HTTP server framework. launch_dashboard.py's
SimpleHTTPRequestHandler calls into these functions and writes the
returned JSON body with the returned status code.

Response envelope: {"error": null|str, "data": <payload>}.
"""
from __future__ import annotations

import json
import logging
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

_log = logging.getLogger(__name__)


# Allowed (strategy-agnostic) commands the web tracker can launch.
# Maps "run --robustness" → ["run", "--robustness"] argv tail.
_ALLOWED_COMMANDS = {
    "optimize":         ["optimize"],
    "wf":               ["wf"],
    "run":              ["run"],
    "run --robustness": ["run", "--robustness"],
    "run --full":       ["run", "--full"],
    # S5: Rung 2, the only run that entitles a strategy to be accepted.
    "run --full --validation-deep": ["run", "--full", "--validation-deep"],
}


def _card_symbols(card: dict) -> list[str]:
    """Tickers a card trades: its own symbol unless it is a PORTFOLIO card, in
    which case the strategy class's declared symbols (S2). Empty when neither
    is known — positions are then unattributable and the tab says so."""
    sym = (card.get("symbol") or "").upper()
    if sym and sym != "PORTFOLIO":
        return [sym]
    try:
        from tradelab.registry import load_strategy_class
        return new_strategy.declared_symbols(load_strategy_class(card.get("strategy") or card.get("base_name") or ""))
    except Exception:
        return []


def _strategy_declares_symbols(strategy: str) -> bool:
    """True when the registered strategy class carries a non-empty `symbols`
    list (S2). Any failure to load the class means False — the run then gets
    the active universe exactly as before."""
    try:
        from tradelab.registry import load_strategy_class
        return bool(new_strategy.declared_symbols(load_strategy_class(strategy)))
    except Exception:
        return False


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


_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _normalize_symbols(raw) -> Tuple[list, list]:
    """Normalize a symbols payload (list or comma/whitespace-separated string)
    into (valid, malformed): uppercased, stripped, deduped, order preserved.
    Validity is the strict `_TICKER_RE` ticker shape — these feed a subprocess
    argv, so anything else is rejected, never passed through."""
    if isinstance(raw, str):
        parts = [p for p in re.split(r"[,\s]+", raw) if p]
    elif isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        return [], []
    seen: set = set()
    valid: list = []
    malformed: list = []
    for p in parts:
        s = p.strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        (valid if _TICKER_RE.match(s) else malformed).append(s)
    return valid, malformed


def _build_tradelab_argv(
    strategy: str, command: str, universe: Optional[str] = None,
    offline: bool = False, symbols: Optional[list] = None,
) -> Optional[list]:
    """Build the subprocess argv for a (strategy, command) pair.

    Returns None if the command is not in _ALLOWED_COMMANDS.
    Strategy must match a-z0-9_ pattern (no shell metacharacters).

    With `symbols`, emits `--symbols A,B,C` and skips universe injection
    entirely (the custom-symbols Test path). Otherwise injects --universe
    from launcher-state.json so the CLI has data to operate on (mirrors what
    the PowerShell launcher does via $activeUniverse). Without this,
    run/optimize/wf exit 2 with "No symbols provided".
    """
    if command not in _ALLOWED_COMMANDS:
        return None
    if not re.match(r"^[a-z0-9_]+$", strategy):
        return None
    cmd_argv = _ALLOWED_COMMANDS[command]
    universe_args: list = []
    symbol_args: list = []
    if symbols:
        if not all(isinstance(s, str) and _TICKER_RE.match(s) for s in symbols):
            return None
        symbol_args = ["--symbols", ",".join(symbols)]
    else:
        if not (universe and re.match(r"^[a-z0-9_]+$", universe)):
            # S2: a strategy that declares its own tickers runs on them — no
            # active-universe injection, the CLI falls back to the class.
            universe = "" if _strategy_declares_symbols(strategy) else _resolve_active_universe()
        if universe:
            universe_args = ["--universe", universe]
    offline_args = ["--offline"] if offline else []
    # tradelab CLI is `python -m tradelab.cli <subcommand> <strategy> [flags]`
    return [sys.executable, "-m", "tradelab.cli", cmd_argv[0], strategy, *cmd_argv[1:], *universe_args, *symbol_args, *offline_args]


# ─── Configurable roots (monkeypatched in tests) ─────────────────────


def _db_path() -> Path:
    return Path("data") / "tradelab_history.db"


def _cache_root() -> Path:
    return Path(".cache") / "ohlcv" / "1D"


def _src_root() -> Path:
    return Path("src")


def _new_strategy_jobs_root() -> Path:
    return Path(".cache") / "new_strategy_jobs"


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


def _resolve_server_dsr(scoring_run_id: str, client_dsr, db_path: Path):
    """Server-authoritative DSR for the activation gate (Step 3.5).

    The accept handlers take ``dsr_probability`` from the CLIENT payload. The
    floor's DSR_NEGATIVE blocker trips only on ``dsr < 0``; ``dsr=None`` does
    NOT trip (missing-data semantics). So a payload that OMITS dsr (-> None) or
    SPOOFS a clean value over a stored negative skips the floor — gate present
    but not wired to what it protects. This resolves dsr from the audit row
    keyed by ``scoring_run_id`` and routes on THAT; the client value never
    reaches the floor when a stored value exists.

    Decision (b) (reviewing session, 2026-06-03): when the run/dsr can't be
    resolved (no row, or a NULL dsr column), fall back to ``None`` — never the
    client value. Legitimate missing data still passes the floor; omission and
    spoofing are both dead. Mirrors the server-side resolution the
    ``/tradelab/strategies/<id>/activate`` path already performs, and must use
    the same ``db_path`` (``_db_path()``), not a cwd-relative default.
    """
    if not scoring_run_id:
        # No run reference -> nothing to resolve server-side. The activate /
        # accept flows always carry a scoring_run_id; a path with no run id is
        # out of scope (do not invent a lookup for it).
        return client_dsr
    from tradelab.audit.history import get_run
    row = get_run(scoring_run_id, db_path=db_path)
    server_dsr = row.dsr_probability if row is not None else None
    if server_dsr is not None:
        if client_dsr is not None and client_dsr != server_dsr:
            _log.warning(
                "DSR override: client dsr_probability=%r discarded; routing on "
                "stored value %r for scoring_run_id=%s",
                client_dsr, server_dsr, scoring_run_id,
            )
        return server_dsr
    # No stored value (missing row or NULL dsr) -> decision (b): None.
    if client_dsr is not None:
        _log.warning(
            "DSR discard: client dsr_probability=%r dropped to None (no stored "
            "value for scoring_run_id=%s); floor uses missing-data semantics",
            client_dsr, scoring_run_id,
        )
    return None


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


def _read_log_tail(log_path: Optional[str], max_lines: int = 100) -> str:
    """Last max_lines of a per-run log file, or "" if unreadable/absent."""
    if not log_path:
        return ""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _start_robustness_job(
    name: str, universe: Optional[str] = None, offline: bool = False,
    symbols: Optional[list] = None,
) -> dict:
    """Submit `run <name> --robustness` through the JobManager with a per-run
    log file. Replaces the old fire-and-forget DEVNULL Popen so the run has a
    real id, queue position, state, and a non-DEVNULL log to surface failures.

    Returns envelope fields merged into the POST response.
    """
    from tradelab.web import jobs as jobs_mod

    canonical = new_strategy._normalize_name(name)
    argv = _build_tradelab_argv(canonical, "run --robustness", universe=universe,
                                offline=offline, symbols=symbols)
    if argv is None:
        return {
            "robustness_started": False,
            "robustness_error": f"could not build robustness argv for {canonical!r}",
            "canonical_name": canonical,
        }
    log_path = _new_strategy_jobs_root() / f"{canonical}.log"
    jm = _get_job_manager()
    try:
        job_id, status = jm.submit(
            canonical, "run --robustness", argv, log_path=str(log_path)
        )
    except jobs_mod.DuplicateJobError as e:
        return {
            "robustness_started": True,
            "job_id": e.existing_job_id,
            "status": "queued",
            "canonical_name": canonical,
            "robustness_note": "already in flight",
        }
    return {
        "robustness_started": True,
        "job_id": job_id,
        "status": status.value if hasattr(status, "value") else str(status),
        "canonical_name": canonical,
    }


def _new_strategy_job_status(name: str) -> Tuple[str, int]:
    """Consolidated status for a candidate's robustness run: state, stage,
    log tail, and (once done) the audit run_id + verdict."""
    canonical = new_strategy._normalize_name(name)
    jm = _get_job_manager()
    candidates = [
        j for j in jm.list_jobs()
        if getattr(j, "strategy", None) == canonical and "robustness" in getattr(j, "command", "")
    ]
    if not candidates:
        return _err(f"no robustness job for {canonical!r}", data={"name": canonical}), 404

    # Newest by (started_at, id) — started_at is 1s-resolution so id breaks ties.
    job = sorted(candidates, key=lambda j: (j.started_at or "", j.id))[-1]
    raw = job.status.value if hasattr(job.status, "value") else str(job.status)
    # Endpoint contract is queued|running|done|failed; collapse the rest to failed.
    state = {"cancelled": "failed", "interrupted": "failed"}.get(raw, raw)
    log_tail = _read_log_tail(job.log_path) or (job.error_tail or "")

    out: dict = {
        "name": canonical,
        "state": state,
        "stage": job.last_event_summary,
        "started_at": job.started_at,
        "finished_at": job.ended_at,
        "log_tail": log_tail,
        "job_id": job.id,
    }
    if state == "failed":
        out["error"] = job.error_tail or log_tail or f"job exited with code {job.exit_code}"
    if state == "done":
        # Best-effort: attach the candidate's latest audit run_id + verdict.
        try:
            runs = audit_reader.history_for_strategy(canonical, limit=1, db_path=_db_path())
            if runs:
                out["run_id"] = runs[0].get("run_id")
                out["verdict"] = runs[0].get("verdict")
        except Exception:
            pass
    return _ok(out), 200


def _new_strategy_advisory_verdict(payload: dict) -> Tuple[str, int]:
    """ADVISORY, candidate-only: recompute a completed run's verdict under
    caller-supplied threshold overrides and return it labelled as advisory.

    Read-only by construction — it loads the run's backtest_result.json +
    robustness_result.json, recomputes in memory, and writes NOTHING. It
    cannot touch the stored verdict, the yaml, the THRESHOLDS dict, or create
    a card, so it is impossible to apply to a registered/locked strategy's
    persisted verdict.
    """
    from tradelab.results import BacktestResult
    from tradelab.robustness.suite import RobustnessSuiteResult
    from tradelab.robustness.verdict import compute_verdict

    folder_str = (payload.get("report_folder") or "").strip()
    if not folder_str:
        return _err("report_folder required"), 400
    overrides = payload.get("overrides") or {}
    if not isinstance(overrides, dict):
        return _err("overrides must be an object of threshold numbers"), 400
    # Only accept numeric override values; silently drop anything else.
    clean = {
        str(k): float(v)
        for k, v in overrides.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }

    rr = _reports_root().resolve()
    p = Path(folder_str)
    if p.is_absolute():
        rf = p.resolve()
    elif folder_str.startswith("reports"):
        rf = (rr.parent / folder_str).resolve()
    else:
        rf = (rr / folder_str).resolve()
    try:
        rf.relative_to(rr)
    except ValueError:
        return _err("report_folder is not under the reports root"), 400

    bt_path = rf / "backtest_result.json"
    rob_path = rf / "robustness_result.json"
    if not bt_path.exists() or not rob_path.exists():
        return _err("run is missing backtest_result.json or robustness_result.json"), 404
    try:
        bt = BacktestResult.model_validate_json(bt_path.read_text(encoding="utf-8"))
        rob = RobustnessSuiteResult.model_validate_json(rob_path.read_text(encoding="utf-8"))
    except Exception as e:
        return _err(f"could not load run results: {type(e).__name__}: {e}"), 500

    # Candidate runs are scored without walk-forward, so wf=None faithfully
    # reconstructs the canonical inputs; with no overrides advisory == canonical.
    advisory = compute_verdict(
        bt,
        dsr=rob.dsr_probability,
        mc=rob.monte_carlo,
        landscape=rob.param_landscape,
        entry_delay=rob.entry_delay,
        loso=rob.loso,
        noise=rob.noise_injection,
        overrides=clean or None,
    )
    return _ok({
        "advisory": True,
        "canonical_verdict": rob.verdict.verdict,
        "advisory_verdict": advisory.verdict,
        "overrides": clean,
    }), 200


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

    m = re.match(r"^/tradelab/new-strategy/job/([^/]+)$", path)
    if m:
        return _new_strategy_job_status(m.group(1))

    if path == "/tradelab/new-strategy/template":
        # S2: render the SimpleStrategy skeleton for the dashboard's
        # "New from template" button. Nothing is written to disk.
        from tradelab.cli_init import render_strategy_template
        name = (q.get("name") or "my_strategy").strip()
        kind = (q.get("type") or "simple").strip()
        try:
            rendered = render_strategy_template(name, type=kind)
        except ValueError as e:
            return _err(str(e)), 400
        return _ok(rendered), 200

    if path == "/tradelab/strategies":
        from tradelab.registry import list_registered_strategies
        try:
            strategies = list(list_registered_strategies().keys())
        except Exception as e:
            return _err(f"registry error: {e}"), 200
        return _ok({"strategies": strategies}), 200

    if path == "/tradelab/universes":
        # Universe names for the Research-tab Test control's universe picker.
        from tradelab.config import get_config
        try:
            names = sorted(get_config().universes.keys())
        except Exception as e:
            return _err(f"config error: {e}"), 200
        return _ok({"universes": names, "active": _resolve_active_universe()}), 200

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

    m = re.match(r"^/tradelab/jobs/([^/]+)/log$", path)
    if m:
        # S4: tail of a job's combined stdout+stderr (run.log beside its
        # progress.jsonl). Plain text; the board links here for a failed trial.
        job_id = m.group(1)
        if not re.match(r"^[0-9a-f]{32}$", job_id):
            return _err("bad job id"), 400
        jm = _get_job_manager()
        log = Path(jm.cache_root) / "jobs" / job_id / "run.log"
        if not log.exists():
            return _err("no log for this job (it predates per-job logs, or is still running)"), 404
        try:
            data = log.read_bytes()[-16000:].decode("utf-8", errors="replace")
        except OSError as e:
            return _err(f"log unreadable: {e}"), 500
        return _ok({"job_id": job_id, "tail": data, "truncated": log.stat().st_size > 16000}), 200

    if path == "/tradelab/cards/retired":
        from tradelab.live.cards import RetiredLog
        return _ok({"retired": RetiredLog(_cards_path()).all()}), 200

    if path == "/tradelab/board":
        return _ok(_build_board()), 200

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

    m = re.match(r"^/tradelab/cards/([^/]+)/activity$", path)
    if m:
        # S3: one strategy's own orders, round-trips, daily P&L and positions,
        # attributed by the client_order_id prefix the paper engine stamps.
        from tradelab.live.cards import CardRegistry
        from tradelab.live import card_activity
        card_id = m.group(1)
        cards_path = _cards_path()
        card = CardRegistry(cards_path).get(card_id) if cards_path.exists() else None
        if card is None:
            return _err(f"card not found: {card_id}"), 404
        try:
            days = max(1, min(int(q.get("days", "90")), 365))
        except (TypeError, ValueError):
            days = 90
        symbols = _card_symbols(card)

        def _orders():
            from tradelab.live.alpaca_client import list_closed_orders
            return list_closed_orders(days=days)

        def _positions():
            from tradelab.live.alpaca_client import list_positions_detail
            return list_positions_detail()

        activity = card_activity.build_activity(
            card, card_symbols=symbols,
            list_closed_orders=_orders, list_positions=_positions,
        )
        activity["days"] = days
        return _ok(activity), 200

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

    if path == "/tradelab/new-strategy/advisory-verdict":
        # handle_post returns the 200-envelope body; the error field carries
        # any failure (consistent with the other POSTs here).
        body, _status = _new_strategy_advisory_verdict(payload)
        return body

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
            # Kick off background robustness run through the tracked job system
            # (id, queue, state, non-DEVNULL log) — not fire-and-forget.
            rob = _start_robustness_job(name)
            return _ok({
                "final_path": reg["final_path"],
                **rob,
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
        rob = _start_robustness_job(new_name)
        return _ok({"final_path": reg["final_path"], **rob})

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

    m = re.match(r"^/tradelab/cards/([^/]+)/flatten$", path)
    if m:
        return _flatten_card(m.group(1), payload)

    m = re.match(r"^/tradelab/cards/([^/]+)/override$", path)
    if m:
        return _renew_override(m.group(1), payload)

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
            # Phase 1 scope: per-run cascade attribution for bulk delete is
            # intentionally deferred to a later slice — bulk records
            # cascaded_card_ids: [] (no regression vs today). Single-run delete
            # carries accurate cascade audit via handle_delete_with_status_with_body.
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
        # Step 3.5: server-authoritative DSR on the activation gate. An empty
        # scoring_run_id on an activating accept is itself a bypass door (skip
        # resolution -> floor sees the client value), so require it BEFORE
        # resolution. Non-activating accepts keep the client value (out of
        # scope — the floor never runs).
        activate = bool(payload.get("activate", False))
        scoring_run_id = payload.get("scoring_run_id", "")
        # S5 (specialist): the pine path is routed on SERVER facts exactly like
        # the python path — run id mandatory, verdict/DSR/folder from the audit
        # row, the run must belong to this base_name, the client folder must
        # be the run's own — then the ladder gate. Client verdict is ignored.
        if not (isinstance(scoring_run_id, str) and scoring_run_id.strip()):
            return _err("scoring_run_id required — accept is routed on the audit row"), 422
        from tradelab.audit.history import get_run
        row = get_run(scoring_run_id, db_path=_db_path())
        if row is None:
            return _err(f"unknown scoring_run_id {scoring_run_id!r}"), 404
        if (row.strategy_name or "") != (payload.get("base_name") or ""):
            return _err(f"run {scoring_run_id!r} belongs to {row.strategy_name!r}, "
                        f"not {payload.get('base_name')!r}"), 422
        lookup = audit_reader.resolve_run_folder(scoring_run_id, db_path=_db_path())
        if lookup.status != "ok" or lookup.folder is None:
            return _err(f"run {scoring_run_id!r} has no report folder"), 422
        server_folder = str(lookup.folder).replace("\\", "/")
        client_folder = str(payload.get("report_folder") or "").replace("\\", "/").rstrip("/")
        if client_folder and Path(client_folder).resolve() != Path(server_folder).resolve():
            return _err("report_folder does not match the run's own folder"), 422
        dsr_probability = _resolve_server_dsr(scoring_run_id, payload.get("dsr_probability"), _db_path())
        server_verdict = row.verdict or "INCONCLUSIVE"
        # S5: every accept path runs the ladder gate — a card only ever comes
        # from a Full trial of the current code under the current thresholds.
        gate_resp = _ladder_gate_response(scoring_run_id, row.strategy_name)
        if gate_resp is not None:
            return gate_resp
        try:
            registry = CardRegistry(_cards_path())
            data = approve_strategy.accept_scored(
                base_name=payload["base_name"],
                symbol=payload["symbol"],
                timeframe=payload["timeframe"],
                report_folder=server_folder,
                verdict=server_verdict,
                dsr_probability=dsr_probability,
                scoring_run_id=scoring_run_id,
                registry=registry,
                pine_archive_root=_pine_archive_root(),
                reports_root=_reports_root(),
                activate=activate,
                db_path=_db_path(),
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
        except approve_strategy.PromotionBlocked as e:
            body = {"error": str(e), "data": None, "state": "BLOCKED", "blockers": e.blockers}
            return json.dumps(body), 422
        except approve_strategy.AdvisoryRefused as e:
            body = {"error": str(e), "data": None, "state": "ADVISORY"}
            return json.dumps(body), 422
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
        # Step 3.5: identical server-authoritative DSR treatment as
        # /tradelab/accept (condition a — no residual surface on the Python
        # path). Require scoring_run_id for activation, then resolve dsr from
        # the audit row; never route on the client value when activating.
        activate = bool(payload.get("activate", False))
        scoring_run_id = payload.get("scoring_run_id", "")
        # S4 (specialist review): every accept — not only activation — is
        # routed on SERVER facts. The run id is mandatory; verdict, DSR and the
        # report folder are read from the audit row, never from the payload,
        # so the board and Accept can never disagree and a client cannot
        # upgrade a BLOCKED/ADVISORY run by posting "ROBUST" or another
        # run's folder.
        if not (isinstance(scoring_run_id, str) and scoring_run_id.strip()):
            return _err("scoring_run_id required — accept is routed on the audit row"), 422
        from tradelab.audit.history import get_run
        row = get_run(scoring_run_id, db_path=_db_path())
        if row is None:
            return _err(f"unknown scoring_run_id {scoring_run_id!r}"), 404
        if (row.strategy_name or "") != (payload.get("strategy") or ""):
            return _err(f"run {scoring_run_id!r} belongs to {row.strategy_name!r}, "
                        f"not {payload.get('strategy')!r}"), 422
        lookup = audit_reader.resolve_run_folder(scoring_run_id, db_path=_db_path())
        if lookup.status != "ok" or lookup.folder is None:
            return _err(f"run {scoring_run_id!r} has no report folder"), 422
        server_folder = str(lookup.folder).replace("\\", "/")
        client_folder = str(payload.get("report_folder") or "").replace("\\", "/").rstrip("/")
        if client_folder and Path(client_folder).resolve() != Path(server_folder).resolve():
            return _err("report_folder does not match the run's own folder"), 422
        dsr_probability = _resolve_server_dsr(scoring_run_id, payload.get("dsr_probability"), _db_path())
        server_verdict = row.verdict or "INCONCLUSIVE"
        # S5: only a Full trial of the CURRENT code under the CURRENT thresholds
        # entitles a strategy to be accepted — and not while a canary is failing.
        # Route first so a BLOCKED/ADVISORY run is told THAT (accept_python_run
        # raises the proper 422 shapes); the ladder gate applies to CLEAR runs.
        pre_route, _ = _route_for_run({"verdict": server_verdict, "dsr_probability": dsr_probability,
                                       "report_card_html_path": row.report_card_html_path})
        override_req = payload.get("override")
        override_record = None
        if override_req is not None:
            # S6: an override is the only way an ADVISORY run becomes a card.
            # Policy (tradelab.override): ADVISORY only, typed name, written
            # reason, budget; and it needs the same current Full trial + clean
            # canaries that Accept needs.
            if not isinstance(override_req, dict):
                return _err("override must be an object {confirm, reason}"), 400
            resp = _override_grant_or_422(
                strategy=row.strategy_name, route=pre_route, confirm=override_req.get("confirm"),
                reason=override_req.get("reason"), scoring_run_id=scoring_run_id,
                row={"tier": row.tier, "code_hash": row.code_hash, "thresholds_hash": row.thresholds_hash},
                exclude_card_id=None,
            )
            if isinstance(resp, tuple):
                return resp
            override_record = resp
        ft = _full_trial_status_for(row.strategy_name, {
            "tier": row.tier, "code_hash": row.code_hash, "thresholds_hash": row.thresholds_hash,
        }) if pre_route == "CLEAR" else {"ok": True}
        if not ft["ok"]:
            body = {"error": f"not accepted: {ft['reason']}", "data": None,
                    "gate": "full_trial", "code": ft["code"]}
            return json.dumps(body), 422
        try:
            card = approve_strategy.accept_python_run(
                base_name=payload["base_name"], symbol=payload["symbol"],
                timeframe=payload["timeframe"], report_folder=server_folder,
                verdict=server_verdict,
                dsr_probability=dsr_probability,
                scoring_run_id=scoring_run_id,
                strategy=payload["strategy"],
                registry=CardRegistry(_cards_path()),
                reports_root=_reports_root(),
                activate=activate,
                # S6: the checkbox is gone — only an override record confirms ADVISORY.
                confirm_non_robust=False,
                allocation_usd=payload.get("allocation_usd"),
                db_path=_db_path(),
                override=override_record,
            )
            return _ok(card), 200
        except approve_strategy.PromotionBlocked as e:
            body = {"error": str(e), "data": None, "state": "BLOCKED", "blockers": e.blockers}
            return json.dumps(body), 422
        except approve_strategy.AdvisoryRefused as e:
            body = {"error": str(e), "data": None, "state": "ADVISORY"}
            return json.dumps(body), 422
        except approve_strategy.ActivationGateFailed as e:
            return _err(str(e)), 422
        except FileNotFoundError:
            return _err("report folder not found"), 404
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except Exception as e:
            from tradelab.override import LedgerUnavailable
            if isinstance(e, LedgerUnavailable):
                return _err(str(e)), 503
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
            strategy=strategy_id, limit=200, db_path=_db_path()
        )
        # S5: the same run the board shows — a bare `run` never counts, and a
        # valid Full trial wins over a later Trial.
        from tradelab.web import board as board_mod
        latest = board_mod.pick_representative_run(
            runs, full_ok=lambda row: _full_trial_status_for(strategy_id, {
                "tier": row.get("tier"), "code_hash": row.get("code_hash"),
                "thresholds_hash": row.get("thresholds_hash")})["ok"]) if runs else None
        if latest is None:
            return _err(f"no runs found for strategy {strategy_id!r} (a bare `run` does not count)"), 422

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

        # S5: the ladder gate applies here too (this path ARMS a card).
        gate_resp = _ladder_gate_response(latest["run_id"], latest["strategy_name"])
        if gate_resp is not None:
            return gate_resp

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
                db_path=_db_path(),
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
        except approve_strategy.PromotionBlocked as e:
            body = {"error": str(e), "data": None, "state": "BLOCKED", "blockers": e.blockers}
            return json.dumps(body), 422
        except approve_strategy.AdvisoryRefused as e:
            body = {"error": str(e), "data": None, "state": "ADVISORY"}
            return json.dumps(body), 422
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
        wanted = [str(cid) for cid in ids]
        refused: list[dict] = []
        if status_val == "enabled":
            # S4 (specialist review): the Live Trading "Enable Selected" button
            # reached the registry with no route check — the same gate as the
            # per-card PATCH applies here, card by card.
            allowed = []
            for cid in wanted:
                card = reg.get(cid)
                gate = _enable_gate(card, {"status": "enabled"}) if card is not None else None
                if gate:
                    refused.append({"id": cid, "reason": gate})   # same shape as bulk_update_status
                else:
                    allowed.append(cid)
            wanted = allowed
        updated, failed = reg.bulk_update_status(wanted, status_val) if wanted else ([], [])
        return _ok({"updated": updated, "failed": list(failed) + refused}), 200

    if path == "/tradelab/cards/bulk-delete":
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids:
            return _err("ids must be a non-empty list"), 400
        if payload.get("confirm") != "DELETE":
            return _err("missing confirm: 'DELETE' to bulk-delete cards"), 400
        cards_path = _cards_path()
        if not cards_path.exists():
            return _err("no cards.json"), 404
        from tradelab.live.cards import CardRegistry, RetiredLog
        reg = CardRegistry(cards_path)
        wanted = [str(cid) for cid in ids]
        snapshot = {cid: reg.get(cid) for cid in wanted}
        deleted, failed = reg.bulk_delete(wanted)
        # S4: bulk retirement is still retirement — the board must see it.
        log = RetiredLog(cards_path)
        for cid in deleted:
            card = snapshot.get(cid)
            if card is not None:
                try:
                    log.append(card)
                except Exception as e:  # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).warning("retired log write failed: %s", e)
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

    if path == "/tradelab/symbols/validate":
        # Cache-aware symbol check for the Research-tab custom-symbols box.
        # ok=True only when every symbol is well-formed AND cached — an
        # --offline run will then genuinely use all of them (kills the
        # silent-skip failure mode where uncached symbols vanish from a run).
        valid, malformed = _normalize_symbols(payload.get("symbols"))
        cache = _cache_root()
        cached_set = {s for s in valid if (cache / f"{s}.parquet").exists()}
        cached = [s for s in valid if s in cached_set]
        uncached = [s for s in valid if s not in cached_set]
        ok = bool(valid) and not malformed and not uncached
        return _ok({"cached": cached, "uncached": uncached,
                    "malformed": malformed, "ok": ok}), 200

    if path == "/tradelab/strategies/score":
        # Launch a robustness scoring run for an ALREADY-REGISTERED strategy
        # (the Research-tab "Test" control). Reuses the same tracked job path
        # as New Strategy / Save Variant; the result lands in the audit DB and
        # surfaces in the Research Pipeline. Optional `universe` overrides the
        # active one for this run only; alternatively `symbols` scores an
        # ad-hoc basket (validated, max 50) via the CLI's --symbols path.
        name = (payload.get("name") or "").strip()
        universe = (payload.get("universe") or "").strip() or None
        symbols_raw = payload.get("symbols")
        offline = bool(payload.get("offline", True))
        if not name:
            return _err("name is required"), 400
        if universe and symbols_raw:
            return _err("provide either universe or symbols, not both"), 400
        symbols: Optional[list] = None
        if symbols_raw:
            symbols, malformed = _normalize_symbols(symbols_raw)
            if malformed:
                return _err(f"malformed symbols: {', '.join(malformed)}"), 400
            if not symbols:
                return _err("symbols list is empty"), 400
            if len(symbols) > 50:
                return _err(f"too many symbols ({len(symbols)}); max 50"), 400
        from tradelab.registry import list_registered_strategies
        try:
            registered = list_registered_strategies()
        except Exception as e:
            return _err(f"registry error: {e}"), 500
        if name not in registered:
            return _err(f"strategy not registered: {name!r}"), 404
        if universe:
            from tradelab.config import get_config
            try:
                known = set(get_config().universes.keys())
            except Exception as e:
                return _err(f"config error: {e}"), 500
            if universe not in known:
                return _err(f"unknown universe: {universe!r}"), 400
        res = _start_robustness_job(name, universe=universe, offline=offline,
                                    symbols=symbols)
        if not res.get("robustness_started"):
            return _err(res.get("robustness_error") or "could not start scoring run"), 500
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
        card = reg.get(card_id)
        if card is None:
            return _err("card not found"), 404
        gate = _enable_gate(card, payload)
        if gate:
            return _err(gate), 422
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

def _flatten_card(card_id: str, payload: dict, *, deps: Optional[dict] = None) -> Tuple[str, int]:
    """S3: close ONE card's own open lots with prefixed market orders.

    Order of operations matters: the card is forced Off first so the paper
    daemon cannot re-enter between our sell and its next tick; then only the
    card's net lots (never another strategy's share of the symbol) are closed,
    each stamped ``{card}-{ts}-flatten-{SYM}`` so FIFO attribution survives.
    ``{"dry_run": true}`` returns the plan without submitting or forcing Off.
    ``deps`` (tests) may inject list_closed_orders / list_positions / submit /
    now; the real ones come from alpaca_client, which is paper-locked by
    configuration (paper_trading flag) — this route never selects live.
    """
    from tradelab.live.cards import CardRegistry
    from tradelab.live import card_activity
    from datetime import datetime, timezone

    cards_path = _cards_path()
    reg = CardRegistry(cards_path) if cards_path.exists() else None
    card = reg.get(card_id) if reg else None
    if card is None:
        return _err(f"card not found: {card_id}"), 404
    dry_run = bool(payload.get("dry_run"))
    deps = deps or {}

    def _orders():
        from tradelab.live.alpaca_client import list_closed_orders
        return list_closed_orders(days=365)

    def _positions():
        from tradelab.live.alpaca_client import list_positions_detail
        return list_positions_detail()

    def _submit(symbol, side, qty, client_order_id):
        from tradelab.live.alpaca_client import submit_market_order
        return submit_market_order(symbol, side, qty, client_order_id=client_order_id)

    list_closed = deps.get("list_closed_orders", _orders)
    list_pos = deps.get("list_positions", _positions)
    submit = deps.get("submit", _submit)
    now = deps.get("now") or datetime.now(timezone.utc)

    try:
        closed = list_closed()
        positions = list_pos()
    except Exception as e:  # noqa: BLE001
        return _err(f"alpaca unavailable: {type(e).__name__}: {e}"), 502
    card_orders = card_activity.orders_for_card(card_id, closed)
    plan = card_activity.plan_flatten(card_orders, positions)
    truncated = len(closed) >= card_activity.ORDERS_PAGE_LIMIT
    out = {
        "card_id": card_id, "dry_run": dry_run, "forced_off": False,
        "planned": plan["orders"], "skipped": plan["skipped"],
        "submitted": [], "errors": [], "truncated": truncated,
    }
    if truncated:
        out["errors"].append("order window hit the page limit — the card's lots may be incomplete; refusing to guess")
        return _ok(out), (200 if dry_run else 409)
    if dry_run:
        return _ok(out), 200

    if (card.get("status") or "").lower() == "enabled":
        reg.update(card_id, {"status": "disabled"})
        out["forced_off"] = True
    for o in plan["orders"]:
        cid = card_activity.flatten_stamp(card_id, o["symbol"], now)
        try:
            res = submit(o["symbol"], o["side"], o["qty"], cid)
            out["submitted"].append({**o, "client_order_id": cid, "order_id": (res or {}).get("id")})
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{o['symbol']}: {type(e).__name__}: {e}")
    return _ok(out), 200


def _route_for_run(run: dict) -> tuple[Optional[str], list]:
    """Promotion route for an audit row, computed exactly as Accept computes
    it (verdict + hard disqualifiers over the run folder's backtest_result.json).
    (None, []) when the folder cannot be scored — the board then treats the
    run as not a trial rather than guessing."""
    from pathlib import Path as _P
    from tradelab.web import approve_strategy
    rcp = run.get("report_card_html_path")
    if not rcp:
        return None, []
    p = _P(rcp)
    # report_card_html_path names dashboard.html inside the run folder (the
    # file itself may be gone); the folder is what carries the metrics.
    folder = p if p.is_dir() else p.parent
    if not folder.is_dir():
        return None, []
    try:
        metrics = approve_strategy._load_bt_metrics(folder)
    except Exception:  # noqa: BLE001 — fail closed: unscorable = not tried
        return None, []
    route, fatal = approve_strategy.route_promotion(
        (run.get("verdict") or "").upper(), metrics, run.get("dsr_probability"),
    )
    return route, list(fatal)


def _current_hashes_for(strategy_name: str) -> tuple[Optional[str], Optional[str]]:
    """(code_hash of the strategy file as it is NOW, hash of the whole
    robustness config in force NOW). None when either cannot be computed —
    the gate then refuses as 'unverifiable' (fail closed): a strategy whose
    file is gone or whose config will not load must not be accepted."""
    from tradelab import ladder
    from tradelab.config import get_config
    try:
        from tradelab.registry import load_strategy_class
        code = ladder.code_hash_for_class(load_strategy_class(strategy_name))
    except Exception:  # noqa: BLE001
        code = None
    try:
        thr = ladder.thresholds_hash(get_config().robustness)
    except Exception:  # noqa: BLE001
        thr = None
    return code, thr


def _ladder_gate_response(scoring_run_id: str, strategy_name: str):
    """422 body for an accept that the ladder refuses, else None. Routing
    (BLOCKED/ADVISORY) is left to the accept functions; the ladder gate is
    what stands between a CLEAR run and a card."""
    from tradelab.audit.history import get_run
    if not (isinstance(scoring_run_id, str) and scoring_run_id.strip()):
        return json.dumps({"error": "not accepted: scoring_run_id required — a card only comes from a "
                                    "Full trial on record", "data": None,
                           "gate": "full_trial", "code": "no_run"}), 422
    row = get_run(scoring_run_id, db_path=_db_path())
    if row is None:
        return json.dumps({"error": f"not accepted: unknown scoring_run_id {scoring_run_id!r}", "data": None,
                           "gate": "full_trial", "code": "no_run"}), 422
    # Route first: a BLOCKED/ADVISORY run must be told THAT by the accept
    # function's own 422 shapes; the ladder stands between CLEAR and a card.
    route, _ = _route_for_run({"verdict": row.verdict, "dsr_probability": row.dsr_probability,
                               "report_card_html_path": row.report_card_html_path})
    if route is None:
        return json.dumps({"error": "not accepted: this run cannot be scored (its report folder or "
                                    "backtest_result.json is missing) — run a Full trial", "data": None,
                           "gate": "full_trial", "code": "unscorable"}), 422
    if route != "CLEAR":
        return None
    ft = _full_trial_status_for(strategy_name or row.strategy_name, {
        "tier": row.tier, "code_hash": row.code_hash, "thresholds_hash": row.thresholds_hash,
    })
    if not ft["ok"]:
        return json.dumps({"error": f"not accepted: {ft['reason']}", "data": None,
                           "gate": "full_trial", "code": ft["code"]}), 422
    return None


def _canary_mismatch_now() -> bool:
    try:
        return not bool(run_canary_check(db_path=_db_path()).to_dict().get("all_match", True))
    except Exception:  # noqa: BLE001 — unknown ≠ mismatch (canary panel semantics)
        return False


def _full_trial_status_for(strategy_name: str, run: Optional[dict]) -> dict:
    from tradelab import ladder
    code, thr = _current_hashes_for(strategy_name)
    return ladder.full_trial_status(
        run, current_code_hash=code, current_thresholds_hash=thr,
        canary_mismatch=_canary_mismatch_now(),
    )


def _run_folder_of(run: dict):
    from pathlib import Path as _P
    rcp = run.get("report_card_html_path")
    if not rcp:
        return None
    p = _P(rcp)
    folder = p if p.is_dir() else p.parent
    return folder if folder.is_dir() else None


def _signals_for_run(run: dict) -> dict:
    """Score + gating/read-anyway split from the run folder's
    robustness_result.json (and validation.json when present)."""
    from tradelab import ladder
    folder = _run_folder_of(run)
    if folder is None:
        return {"score": None, "gating": [], "read_anyway": [], "hard_override": []}
    signals, diagnostics, extras = [], {}, []
    rob = folder / "robustness_result.json"
    if rob.exists():
        try:
            d = json.loads(rob.read_text(encoding="utf-8-sig"))
            v = d.get("verdict") or {}
            signals = v.get("signals") or []
            diagnostics = v.get("diagnostics") or {}
        except (OSError, json.JSONDecodeError):
            pass
    val = folder / "validation.json"
    if val.exists():
        try:
            d = json.loads(val.read_text(encoding="utf-8-sig"))
            summary = d.get("summary") or d.get("overall") or {}
            extras.append({"name": "validation_suite", "outcome": "info",
                           "reason": json.dumps(summary)[:160] if summary else "present"})
        except (OSError, json.JSONDecodeError):
            extras.append({"name": "validation_suite", "outcome": "info", "reason": "unreadable"})
    out = ladder.split_signals(signals, diagnostics, extras)
    out["score"] = ladder.score_from_signals(signals)
    return out


def _data_end_for_run(run: dict) -> Optional[str]:
    """Last bar the run's data ACTUALLY contained (backtest_result.json
    ``data_last_bar``), so the board can say "data to YYYY-MM-DD" — a verdict
    on bars that stop three months ago must not look like a fresh one. Runs
    that predate the field return None (never the requested ``end_date``,
    which would be a confident wrong label on exactly the stale case)."""
    from pathlib import Path as _P
    rcp = run.get("report_card_html_path")
    if not rcp:
        return None
    p = _P(rcp)
    folder = p if p.is_dir() else p.parent
    bt = folder / "backtest_result.json"
    if not bt.exists():
        return None
    try:
        d = json.loads(bt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    end = d.get("data_last_bar")
    return str(end)[:10] if end else None


def _build_board() -> dict:
    """Gather the board's inputs (registry, audit DB, cards, retired log,
    jobs, declared symbols) and hand them to the pure builder."""
    from tradelab.web import board as board_mod
    from tradelab.live.cards import CardRegistry, RetiredLog
    from tradelab.registry import list_registered_strategies, load_strategy_class

    try:
        registered = list(list_registered_strategies().keys())
    except Exception as e:  # noqa: BLE001
        return {"rows": [], "counts": {}, "error": f"registry error: {e}"}

    from tradelab import ladder
    code_thr_cache: dict[str, tuple] = {}
    canary_bad = _canary_mismatch_now()

    def _full_trial_no_canary(name: str, run: Optional[dict]) -> dict:
        if name not in code_thr_cache:
            code_thr_cache[name] = _current_hashes_for(name)
        code, thr = code_thr_cache[name]
        return ladder.full_trial_status(run, current_code_hash=code, current_thresholds_hash=thr)

    def _full_trial(name: str, run: Optional[dict]) -> dict:
        ft = _full_trial_no_canary(name, run)
        if ft["ok"] and canary_bad:
            return ladder.full_trial_status(run, current_code_hash=code_thr_cache[name][0],
                                            current_thresholds_hash=code_thr_cache[name][1], canary_mismatch=True)
        return ft

    # S5: which run represents a strategy on the board. A plain `run` (tier
    # basic) never counts. A Full trial that still passes the gate wins over
    # any later Trial, so a diagnostic robustness run cannot knock a strategy
    # off its accept-able rung; otherwise the newest Trial (or a legacy row
    # with no tier, which was a robustness run before the ladder existed).
    runs_by_name: dict[str, list[dict]] = {}
    for r in audit_reader.list_runs(limit=5000, db_path=_db_path()):
        name = r.get("strategy_name")
        if name:
            runs_by_name.setdefault(name, []).append(r)   # newest-first
    latest: dict[str, dict] = {}
    newer_trials: dict[str, dict] = {}
    for name, rows in runs_by_name.items():
        # tier/hash validity only — the canary state must not demote a valid
        # Full trial to "Full trial required" (derive_state handles the canary
        # with a disabled Accept and the real reason).
        chosen = board_mod.pick_representative_run(
            rows, full_ok=lambda row, _n=name: _full_trial_no_canary(_n, row)["ok"])
        if chosen is not None:
            latest[name] = chosen
            newest_trial = next((r for r in rows if (r.get("tier") or "trial") != "basic"), None)
            if newest_trial is not None and newest_trial.get("run_id") != chosen.get("run_id"):
                newer_trials[name] = newest_trial

    cards_path = _cards_path()
    cards = CardRegistry(cards_path).all() if cards_path.exists() else {}
    retired = RetiredLog(cards_path).all()
    try:
        jobs = [j.to_dict() for j in _get_job_manager().list_jobs()]
    except Exception:  # noqa: BLE001
        jobs = []

    def _symbols(name: str) -> list[str]:
        from tradelab.web.new_strategy import declared_symbols
        return declared_symbols(load_strategy_class(name))

    # Not strategies to promote: canaries (their own panel; never accept-able)
    # and abstract bases registered by mistake (S0 finding F7).
    from tradelab.cli_canary import CANARY_NAMES
    from tradelab.web.new_strategy import _is_abstract_base
    excluded: dict[str, str] = {}
    for name in registered:
        if name in CANARY_NAMES:
            excluded[name] = "canary — engine-integrity probe, see the Canaries panel"
            continue
        try:
            if _is_abstract_base(load_strategy_class(name)):
                excluded[name] = "abstract base class registered in tradelab.yaml — remove the entry"
        except Exception:  # noqa: BLE001 — unloadable stays on the board so its Trial can fail loudly
            pass

    # S6: could an override be granted right now (budget, canaries)?
    from tradelab import override as ov_mod
    from datetime import datetime as _dt, timezone as _tz
    _now = _dt.now(_tz.utc)
    try:
        policy = _promotion_policy()
        active_n = len(ov_mod.active_overrides(cards.values(), _now))
        if canary_bad:
            override_ok = {"ok": False, "reason": "engine integrity check is failing — no overrides while a canary is out of its expected set"}
        elif active_n >= policy["budget"]:
            override_ok = {"ok": False, "reason": f"override budget spent: {active_n} of {policy['budget']} active"}
        else:
            override_ok = {"ok": True, "reason": None}
        override_policy = {**policy, "active": active_n}
    except Exception as e:  # noqa: BLE001
        override_ok = {"ok": False, "reason": f"override policy unavailable: {e}"}
        override_policy = None

    out = board_mod.build_board(
        registered=registered, latest_runs=latest, route_for_run=_route_for_run,
        cards=cards, retired=retired, jobs=jobs, symbols_for=_symbols, excluded=excluded,
        data_end_for=_data_end_for_run, full_trial_for=_full_trial, signals_for=_signals_for_run,
        newer_trials=newer_trials, override_ok=override_ok, now=_now,
    )
    out["override_policy"] = override_policy
    out["rungs"] = ladder.RUNGS
    out["estimates"] = ladder.rung_estimates(jobs)
    out["canary_mismatch"] = canary_bad
    from datetime import datetime, timezone
    out["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def _promotion_policy() -> dict:
    """The S6 policy numbers from tradelab.yaml `promotion:`; the decided
    defaults (30 d / 50 % / 2 / 20 chars) when the config cannot be loaded —
    logged, since a stricter configured policy would then not apply."""
    from tradelab import override as ov
    try:
        from tradelab.config import get_config
        return ov.policy_from_config(get_config())
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("promotion policy: config unavailable (%s) — using defaults", e)
        from tradelab.config import PromotionConfig
        return ov.policy_from_config(PromotionConfig())


def _override_grant_or_422(*, strategy: str, route: Optional[str], confirm, reason, scoring_run_id: str,
                           row: dict, exclude_card_id: Optional[str]):
    """Validate an override request against the policy. Returns the receipt
    dict to store, or a (body, 422) tuple to return."""
    from datetime import datetime, timezone
    from tradelab import override as ov
    from tradelab.live.cards import CardRegistry
    policy = _promotion_policy()
    now = datetime.now(timezone.utc)
    cards_path = _cards_path()
    cards = list(CardRegistry(cards_path).all().values()) if cards_path.exists() else []
    active = len(ov.active_overrides(cards, now, exclude_card_id=exclude_card_id))
    try:
        ov.validate_request(strategy=strategy, confirm=confirm, reason=reason, route=route,
                            policy=policy, active_count=active)
    except ov.OverrideRefused as e:
        return json.dumps({"error": f"override refused: {e}", "data": None,
                           "gate": "override", "code": e.code}), 422
    # The same ladder + canary gate Accept applies — an override never skips a rung.
    ft = _full_trial_status_for(strategy, row)
    if not ft["ok"]:
        return json.dumps({"error": f"override refused: {ft['reason']}", "data": None,
                           "gate": "full_trial", "code": ft["code"]}), 422
    _, thr = _current_hashes_for(strategy)
    return ov.build_record(reason=reason, now=now, policy=policy, scoring_run_id=scoring_run_id,
                           thresholds_hash=thr)


def _renew_override(card_id: str, payload: dict) -> Tuple[str, int]:
    """POST /tradelab/cards/{id}/override — a renewal is a fresh override with a
    fresh reason: same policy, budget counted without this card, the card's
    own scoring run must still be a current Full trial."""
    from tradelab.audit.history import get_run
    from tradelab.live.cards import CardRegistry
    from tradelab.web import approve_strategy
    cards_path = _cards_path()
    reg = CardRegistry(cards_path) if cards_path.exists() else None
    card = reg.get(card_id) if reg else None
    if card is None:
        return _err("card not found"), 404
    if (card.get("promotion_route") or "").upper() != "ADVISORY":
        return json.dumps({"error": "override refused: only ADVISORY cards carry an override", "data": None,
                           "gate": "override", "code": "not_needed" if card.get("promotion_route") == "CLEAR" else "blocked"}), 422
    strategy = card.get("strategy") or card.get("base_name") or ""
    # Renewal needs NEW evidence: a Full trial newer than the current grant.
    # Either the client names it (scoring_run_id) or the newest Full trial of
    # the strategy is used; the card's original run never renews itself.
    granted_at = (card.get("override") or {}).get("granted_at") or card.get("created_at") or ""
    original_run = (card.get("override") or {}).get("scoring_run_id") or card.get("scoring_run_id")
    from tradelab.web.board import _iso_key

    def _is_new_evidence(r_id, ts):
        # newer than (or, at second precision, concurrent with) the grant, and
        # never the run the current override was granted on
        return r_id != original_run and _iso_key(ts) >= _iso_key(granted_at)

    run_id = payload.get("scoring_run_id") or ""
    if run_id:
        row = get_run(run_id, db_path=_db_path())
        if row is None or row.strategy_name != strategy:
            return _err("scoring_run_id unknown or not this strategy's run"), 422
    else:
        rows = audit_reader.list_runs(strategy=strategy, limit=200, db_path=_db_path())
        row = None
        for r in rows:   # newest first
            if r.get("tier") == "full" and _is_new_evidence(r.get("run_id"), r.get("timestamp_utc")):
                row = get_run(r["run_id"], db_path=_db_path())
                break
    if row is None or not _is_new_evidence(row.run_id, row.timestamp_utc):
        return json.dumps({"error": "override refused: renewal needs new evidence — run a Full trial newer "
                                    "than the current override, then renew from it", "data": None,
                           "gate": "full_trial", "code": "no_newer_trial"}), 422
    run_id = row.run_id
    route, _ = _route_for_run({"verdict": row.verdict, "dsr_probability": row.dsr_probability,
                               "report_card_html_path": row.report_card_html_path})
    resp = _override_grant_or_422(
        strategy=strategy, route=route, confirm=payload.get("confirm"), reason=payload.get("reason"),
        scoring_run_id=run_id,
        row={"tier": row.tier, "code_hash": row.code_hash, "thresholds_hash": row.thresholds_hash},
        exclude_card_id=card_id,
    )
    if isinstance(resp, tuple):
        return resp
    # Ledger first, fail closed (the row is the audit trail of the renewal).
    try:
        from tradelab.audit.verdict_ledger import log_decision
        log_decision(
            db_path=_db_path(), strategy_name=strategy, scoring_run_id=run_id, path="python",
            verdict=(row.verdict or "").upper(), promotion_route="ADVISORY", blockers=[],
            override_used=True, activated=False, override_reason=resp["reason"],
            override_expires_at=resp["expires_at"], allocation_cap_pct=resp["allocation_cap_pct"],
            thresholds_hash=resp["thresholds_hash"],
        )
    except Exception as e:  # noqa: BLE001
        return _err(f"audit ledger unavailable — override not renewed: {type(e).__name__}: {e}"), 503
    fields = {"override": resp, "scoring_run_id": run_id, "verdict": (row.verdict or "").upper(),
              "dsr_probability": row.dsr_probability}
    if card.get("override_expired_at"):
        fields["override_expired_at"] = None
    reg.update(card_id, fields)
    return _ok({"card_id": card_id, "override": resp, "scoring_run_id": run_id}), 200


def _enable_gate(card: dict, payload: dict) -> Optional[str]:
    """Server-side refusal for turning a card on. The tab hides the option,
    but the registry must not trust the browser: a BLOCKED promotion route
    (hard disqualifier — DSR<0, negative expectancy) never trades. Funding is
    not gated here — the paper daemon already skips unfunded cards, and the
    tab refuses Paper without a $ allocation."""
    if payload.get("status") != "enabled":
        return None
    route = (card.get("promotion_route") or "").upper()
    if route == "BLOCKED":
        return "refused: promotion route is BLOCKED (hard disqualifier) — this card cannot be enabled"
    if route == "ADVISORY":
        from datetime import datetime, timezone
        from tradelab import override as ov
        if not card.get("override"):
            return ("refused: promotion route is ADVISORY — enabling needs an override "
                    "(typed confirmation + written reason)")
        if not ov.is_active(card, datetime.now(timezone.utc)):
            return ("refused: this card's override has expired — renew it with a fresh reason "
                    "before switching it on")
    if route not in ("CLEAR", "ADVISORY"):
        return ("refused: this card has no promotion route on record (accepted before routes "
                "were stored) — retire it and re-accept from a trial")
    return None


_ALLOWED_PATCH_FIELDS = {
    "status", "quantity", "cadence", "daily_limit",
    "cooldown_seconds", "allow_collision", "allow_naked_short",
    "capital", "max_positions", "allocation_usd",
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
    if "allocation_usd" in payload:
        v = payload["allocation_usd"]
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
            return "allocation_usd must be a non-negative number or null"
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
        from tradelab.live.cards import CardRegistry, RetiredLog
        reg = CardRegistry(cards_path)
        card = reg.get(card_id)
        try:
            reg.delete(card_id)
        except KeyError:
            return _err("card not found"), 404
        # S4: the board shows the strategy as Retired rather than as a fresh
        # Candidate. Logging must never undo the delete — fail open.
        if card is not None:
            try:
                RetiredLog(cards_path).append(card)
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning("retired log write failed: %s", e)
        return _ok({"deleted": card_id}), 200

    # Phase 1 (audit slice C): single-run delete threads cascaded_card_ids
    # (the cards the FE actually disabled) from the body into the deletions.log
    # entry. Record-only — the server does NOT re-derive or re-disable here.
    # A missing/empty body resolves to [], so a body-less DELETE is unchanged.
    rm = re.match(r"^/tradelab/runs/([^/]+)$", path)
    if rm:
        cascaded = payload.get("cascaded_card_ids") or []
        return _delete_run(rm.group(1), cascaded_card_ids=cascaded)

    # Fall through to body-less variant for any remaining legacy routes
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


def _delete_run(run_id: str, cascaded_card_ids: list | None = None) -> tuple[str, int]:
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
        manifest = run_deletion.delete_run_atomic(
            run_id, db_path=db, cascaded_card_ids=cascaded_card_ids
        )
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
