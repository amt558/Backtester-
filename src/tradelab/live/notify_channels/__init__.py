"""Notification channel registry. Each channel module exposes `send(severity, title, body, config) -> bool`.

Slots are populated by importing each channel module. Tests monkeypatch CHANNELS
directly to install fakes — this avoids cascading imports during unit tests.
"""
from __future__ import annotations

from typing import Callable, Dict

# Channel signature: (severity_str, title, body, live_config_dict) -> bool
ChannelSend = Callable[[str, str, str, dict], bool]

CHANNELS: Dict[str, ChannelSend] = {}


def register(name: str, send_fn: ChannelSend) -> None:
    CHANNELS[name] = send_fn


# Best-effort imports — a missing channel module should not crash the dispatcher.
# Each channel module calls register() at import time.
for _mod in ("audible", "windows_toast", "ntfy", "email", "browser"):
    try:
        __import__(f"tradelab.live.notify_channels.{_mod}", fromlist=["_"])
    except Exception as e:
        import sys
        print(f"[notify_channels] failed to register {_mod}: {type(e).__name__}: {e}", file=sys.stderr)
