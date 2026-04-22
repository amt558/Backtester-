"""HTTP request handlers for /tradelab/* routes.

Pure dispatch — no HTTP server framework. launch_dashboard.py's
SimpleHTTPRequestHandler calls into these functions and writes the
returned JSON body with the returned status code.

Response envelope: {"error": null|str, "data": <payload>}.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

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


def _build_tradelab_argv(strategy: str, command: str) -> Optional[list]:
    """Build the subprocess argv for a (strategy, command) pair.

    Returns None if the command is not in _ALLOWED_COMMANDS.
    Strategy must match a-z0-9_ pattern (no shell metacharacters).
    """
    if command not in _ALLOWED_COMMANDS:
        return None
    if not re.match(r"^[a-z0-9_]+$", strategy):
        return None
    cmd_argv = _ALLOWED_COMMANDS[command]
    # tradelab CLI is `python -m tradelab.cli <subcommand> <strategy> [flags]`
    return [sys.executable, "-m", "tradelab.cli", cmd_argv[0], strategy, *cmd_argv[1:]]


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


def _yaml_path() -> Path:
    return Path("tradelab.yaml")


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
        return _ok({
            "runs": audit_reader.list_runs(
                strategy=q.get("strategy") or None,
                verdicts=[v for v in q.get("verdict", "").split(",") if v] or None,
                since=q.get("since") or None,
                limit=int(q.get("limit", 50)),
                offset=int(q.get("offset", 0)),
                db_path=_db_path(),
            ),
            "total": audit_reader.count_runs(
                strategy=q.get("strategy") or None,
                verdicts=[v for v in q.get("verdict", "").split(",") if v] or None,
                since=q.get("since") or None,
                db_path=_db_path(),
            ),
        }), 200

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

    if path == "/tradelab/strategies":
        from tradelab.registry import list_registered_strategies
        try:
            strategies = list(list_registered_strategies().keys())
        except Exception as e:
            return _err(f"registry error: {e}"), 200
        return _ok({"strategies": strategies}), 200

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
            universe_name = payload.get("universe") or cfg.defaults.universe
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

    if path == "/tradelab/jobs":
        return _post_job(payload)

    if path.startswith("/tradelab/jobs/") and path.endswith("/cancel"):
        job_id = path[len("/tradelab/jobs/"):-len("/cancel")]
        return _cancel_job(job_id)

    # Fallback to legacy POST dispatcher for everything else
    return handle_post(path, body), 200


def _post_job(payload: dict) -> Tuple[str, int]:
    from tradelab.web import get_job_manager
    from tradelab.web import jobs as jobs_mod

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
