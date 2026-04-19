"""Determinism contract helpers — hashing, env fingerprint, footer renderer."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def hash_dataframe(df: pd.DataFrame) -> str:
    payload = pd.util.hash_pandas_object(df, index=True).values.tobytes()
    return hashlib.sha256(payload).hexdigest()[:16]


def hash_universe(data: dict) -> str:
    parts = []
    for sym in sorted(data.keys()):
        parts.append(f"{sym}:{hash_dataframe(data[sym])}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def hash_config(cfg: Any) -> str:
    if hasattr(cfg, "model_dump"):
        payload = json.dumps(cfg.model_dump(), sort_keys=True, default=str)
    elif hasattr(cfg, "dict"):
        payload = json.dumps(cfg.dict(), sort_keys=True, default=str)
    elif isinstance(cfg, dict):
        payload = json.dumps(cfg, sort_keys=True, default=str)
    else:
        payload = str(cfg)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def git_commit_hash(repo_root: Optional[Path] = None) -> str:
    try:
        cwd = str(repo_root) if repo_root else None
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "nogit"


def tradelab_version() -> str:
    try:
        from tradelab import __version__
        return __version__
    except Exception:
        return "unknown"


def env_fingerprint() -> dict:
    versions = {
        "python": sys.version.split()[0],
        "tradelab": tradelab_version(),
        "git_commit": git_commit_hash(),
    }
    for pkg in ("numpy", "pandas", "scipy", "optuna", "pydantic"):
        try:
            mod = __import__(pkg)
            versions[pkg] = getattr(mod, "__version__", "unknown")
        except Exception:
            versions[pkg] = "missing"
    return versions


def render_footer(data_hash=None, config_hash=None, seeds=None) -> str:
    env = env_fingerprint()
    lines = [
        "--- reproducibility footer ---",
        f"tradelab:   {env['tradelab']}",
        f"git:        {env['git_commit']}",
        f"python:     {env['python']}",
        f"numpy:      {env['numpy']}",
        f"pandas:     {env['pandas']}",
        f"scipy:      {env['scipy']}",
        f"optuna:     {env['optuna']}",
    ]
    if data_hash is not None:
        lines.append(f"data_sha:   {data_hash}")
    if config_hash is not None:
        lines.append(f"config_sha: {config_hash}")
    if seeds:
        for k in sorted(seeds.keys()):
            lines.append(f"seed[{k}]: {seeds[k]}")
    return "\n".join(lines)
