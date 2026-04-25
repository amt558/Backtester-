"""HTTP request handlers for /tradelab/* routes.

Pure dispatch — no HTTP server framework. launch_dashboard.py's
SimpleHTTPRequestHandler calls into these functions and writes the
returned JSON body with the returned status code.

Response envelope: {"error": null|str, "data": <payload>}.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from tradelab.audit import archive
from tradelab.web import audit_reader, freshness, new_strategy, ranges, whatif


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
        folder = audit_reader.get_run_folder(m.group(1), db_path=_db_path())
        if folder is None:
            return _err("run not found"), 404
        # Return path relative to tradelab root (used as iframe prefix)
        return _ok({"folder": str(folder).replace("\\", "/")}), 200

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
            )
            return _ok(data), 200
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

    # Fallback to legacy POST dispatcher for everything else
    return handle_post(path, body), 200


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
    return None


def handle_delete_with_status(path: str) -> tuple[str, int]:
    """DELETE dispatcher with explicit status."""
    m = re.match(r"^/tradelab/runs/([^/]+)$", path)
    if m:
        run_id = m.group(1)
        return _delete_run(run_id)

    return _err("not found"), 404


def _delete_run(run_id: str) -> tuple[str, int]:
    """Soft-archive a run: insert into archived_runs + remove report folder."""
    db = _db_path()
    if not db.exists():
        return _err("run not found"), 404

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT report_card_html_path FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return _err("run not found"), 404

    # Resolve the run's report folder. We only act on paths that resolve to
    # a real file (folder = its parent) or a real directory. A stale path
    # whose parent happens to exist is intentionally ignored — falling back
    # to `parent` could rmtree a directory holding other runs' artifacts
    # (e.g. _reports_root() itself on an idempotent second delete).
    report_path_str = row[0]
    folder: Path | None = None
    if report_path_str:
        p = Path(report_path_str)
        if p.is_file():
            folder = p.parent
        elif p.is_dir():
            folder = p

    if folder and folder.exists():
        try:
            shutil.rmtree(folder)
        except OSError as e:
            return _err(f"folder removal failed: {e}"), 409

    archive.archive_run(run_id, reason="user_delete", db_path=db)

    return "", 204
