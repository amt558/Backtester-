"""Thin web-layer wrapper over the `tradelab compare` CLI.

Validates input, resolves run_ids → report folders via audit_reader,
subprocesses the CLI, returns the generated HTML path for the frontend
to open in a new tab.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

from tradelab.web import audit_reader


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")
RESULT_FILE_NAME = "backtest_result.json"


def _err(msg: str, status: int = 400) -> Tuple[dict, int]:
    return {"error": msg, "data": None}, status


def _ok(data: dict, status: int = 200) -> Tuple[dict, int]:
    return {"error": None, "data": data}, status


def run_compare(run_ids: list, benchmark: str = "SPY",
                timeout_s: int = 60,
                reports_root: Path = Path("reports")) -> Tuple[dict, int]:
    if not isinstance(run_ids, list) or len(run_ids) < 2:
        return _err("at least 2 runs required")
    for rid in run_ids:
        if not isinstance(rid, str) or not RUN_ID_PATTERN.match(rid):
            return _err(f"invalid run_id: {rid!r}")

    folders = []
    ineligible = []
    unknown = []
    for rid in run_ids:
        folder = audit_reader.get_run_folder(rid)
        if folder is None:
            unknown.append(rid)
            continue
        if not (folder / RESULT_FILE_NAME).exists():
            ineligible.append(rid)
            continue
        folders.append(folder)

    if unknown:
        return _err(f"unknown run_id: {unknown[0]}")
    if ineligible:
        return _err(
            f"{len(ineligible)} runs can't be compared (predate JSON persistence): "
            + ", ".join(ineligible)
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_root / f"compare_{ts}.html"
    argv = [
        sys.executable, "-m", "tradelab.cli", "compare",
        *[str(f) for f in folders],
        "--output", str(out_path),
        "--benchmark", benchmark,
        "--no-open",
    ]
    try:
        proc = subprocess.run(
            argv, capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _err(f"compare timeout after {timeout_s}s", status=500)

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        return _err(f"compare exited {proc.returncode}: {tail}", status=500)

    return _ok({"report_path": str(out_path)})
