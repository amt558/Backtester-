"""
Lightweight .env loader.

tradelab does NOT depend on python-dotenv. This module implements the
subset of .env semantics we need: KEY=VALUE lines, comments (# prefix),
quoted values, blank lines. Loaded once at import; subsequent calls are
no-ops unless reload=True.

Lookup order for TWELVEDATA_API_KEY (and similar secrets):
  1. Existing process environment (os.environ) — wins on conflict
  2. .env file at the current working directory's repo root
  3. .env file at Path.home() / ".tradelab" / ".env" (user-level)

The .env file is gitignored via the project's .gitignore rule.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional


_LOADED = False
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    s = line.split("#", 1)[0].strip()
    if not s:
        return None
    m = _LINE_RE.match(s)
    if not m:
        return None
    key, raw = m.group(1), m.group(2)
    # Strip matched surrounding quotes
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    return key, raw


def _candidate_paths() -> Iterable[Path]:
    # Repo-root .env: walk up from cwd looking for tradelab.yaml as anchor
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "tradelab.yaml").exists():
            yield candidate / ".env"
            break
    # User-level
    yield Path.home() / ".tradelab" / ".env"


def load_env(reload: bool = False) -> dict[str, str]:
    """
    Populate os.environ from .env files. Returns a dict of keys loaded
    (i.e. those that weren't already set in os.environ).
    """
    global _LOADED
    if _LOADED and not reload:
        return {}

    loaded: dict[str, str] = {}
    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            parsed = _parse_line(line)
            if not parsed:
                continue
            key, value = parsed
            # Existing env wins
            if key in os.environ:
                continue
            os.environ[key] = value
            loaded[key] = value

    _LOADED = True
    return loaded
