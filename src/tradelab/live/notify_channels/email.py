"""Email notification channel via stdlib smtplib (STARTTLS)."""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

from tradelab.live.notify_channels import register


def send(severity: str, title: str, body: str, config: dict) -> bool:
    smtp_cfg = config.get("notifications", {}).get("smtp", {})
    host = smtp_cfg.get("host", "").strip()
    to_addr = smtp_cfg.get("to_address", "").strip()
    if not host or not to_addr:
        return False
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg.get("user", "")
    password = smtp_cfg.get("password", "")
    from_addr = smtp_cfg.get("from_address", user)

    msg = EmailMessage()
    msg["Subject"] = f"[tradelab {severity.upper()}] {title}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as conn:
            conn.starttls()
            if user:
                conn.login(user, password)
            conn.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[notify.email] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("email", send)
