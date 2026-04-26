"""Windows toast notification channel via plyer."""
from __future__ import annotations

import sys

try:
    from plyer import notification  # type: ignore[import-not-found]
except Exception:
    notification = None  # type: ignore[assignment]

from tradelab.live.notify_channels import register


def send(severity: str, title: str, body: str, config: dict) -> bool:
    if notification is None:
        return False
    try:
        notification.notify(
            title=f"[{severity.upper()}] {title}",
            message=body,
            app_name="tradelab",
            timeout=10,
        )
        return True
    except Exception as e:
        print(f"[notify.windows_toast] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("windows_toast", send)
