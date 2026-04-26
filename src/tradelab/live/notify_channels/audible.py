"""Audible notification channel. Plays a WAV if configured, else MessageBeep."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import winsound  # type: ignore[import-not-found]  # Windows-only stdlib
except ImportError:
    winsound = None  # type: ignore[assignment]

from tradelab.live.notify_channels import register


_BEEP_BY_SEVERITY = {
    "critical": "MB_ICONHAND",
    "warning": "MB_ICONEXCLAMATION",
    "info": "MB_OK",
}


def send(severity: str, title: str, body: str, config: dict) -> bool:
    if winsound is None:
        return False
    try:
        path = config.get("notifications", {}).get("audible", {}).get("sound_file", "")
        if path and Path(path).is_file():
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            const_name = _BEEP_BY_SEVERITY.get(severity, "MB_OK")
            winsound.MessageBeep(getattr(winsound, const_name, winsound.MB_OK))
        return True
    except Exception as e:
        print(f"[notify.audible] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("audible", send)
