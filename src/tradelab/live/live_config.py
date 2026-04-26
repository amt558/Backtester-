"""Runtime configuration for notification channels + global guardrail thresholds.

On-disk: tradelab/live/live_config.json (gitignored via /live/*.json).
In-memory: a single dict cache, refreshed by reload().

Schema is intentionally a plain dict — no pydantic — to keep PATCH semantics
(deep-merge of partial payloads) simple. mask_passwords() returns a copy with
SMTP password replaced; never mutates the source.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

# Path resolved against the tradelab/ repo root (parent of src/).
_LIVE_CONFIG_PATH = Path(__file__).resolve().parents[3] / "live" / "live_config.json"

_DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "notifications": {
        "enabled_channels": ["browser"],
        "severity_routing": {
            "critical": ["browser", "windows_toast", "audible", "ntfy", "email"],
            "warning":  ["browser", "windows_toast", "audible"],
            "info":     ["browser"],
        },
        "ntfy": {
            "topic": "",
            "server": "https://ntfy.sh",
        },
        "smtp": {
            "host": "",
            "port": 587,
            "user": "",
            "password": "",
            "from_address": "",
            "to_address": "",
        },
        "audible": {
            "volume_pct": 70,
            "sound_file": "",
        },
    },
    "guardrails": {
        "max_exposure_pct": 0.90,
        "default_daily_limit": 5,
        "default_cooldown_seconds": 30,
    },
    "silence": {
        "multipliers": {"intraday": 2, "daily": 5, "weekly": 21},
    },
    "email_digest": {
        "enabled": False,
        "send_time": "16:00",
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _deep_merge_defaults(target: dict, defaults: dict) -> dict:
    """Add any missing default keys to target (recursive). Existing keys preserved."""
    for k, v in defaults.items():
        if k not in target:
            target[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(target[k], dict):
            _deep_merge_defaults(target[k], v)
    return target


def reload() -> None:
    """Re-read from disk into the cache. Writes defaults if file missing."""
    global _cache
    with _lock:
        if _LIVE_CONFIG_PATH.exists():
            raw = _LIVE_CONFIG_PATH.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        else:
            data = {}
        _deep_merge_defaults(data, _DEFAULTS)
        _cache = data
        if not _LIVE_CONFIG_PATH.exists():
            _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(_LIVE_CONFIG_PATH, _cache)


def get() -> dict[str, Any]:
    """Return the cached config (lazy-loads on first call)."""
    if not _cache:
        reload()
    return _cache


def save(new_cfg: dict[str, Any]) -> None:
    """Atomic write + cache refresh."""
    global _cache
    with _lock:
        _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_LIVE_CONFIG_PATH, new_cfg)
        _cache = copy.deepcopy(new_cfg)


def update(partial: dict[str, Any]) -> None:
    """Deep-merge partial into the cache, then save."""
    cfg = copy.deepcopy(get())
    _deep_merge_overwrite(cfg, partial)
    save(cfg)


def _deep_merge_overwrite(target: dict, src: dict) -> None:
    """Merge src into target, overwriting at the leaf level."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge_overwrite(target[k], v)
        else:
            target[k] = v


def mask_passwords(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copy with SMTP password replaced by '******' if non-empty."""
    masked = copy.deepcopy(cfg)
    pw = masked.get("notifications", {}).get("smtp", {}).get("password", "")
    if pw:
        masked["notifications"]["smtp"]["password"] = "******"
    return masked


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
