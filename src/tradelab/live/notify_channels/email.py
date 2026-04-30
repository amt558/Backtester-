"""Email notification channel via stdlib smtplib (STARTTLS).

Two entry points:
  - ``send(severity, title, body, config) -> bool``: alerts. Subject is
    prefixed with ``[tradelab SEVERITY]``. Plaintext-only. Returns False
    on failure (callers want best-effort dispatch).
  - ``send_digest(subject, html_body, plaintext_body, to_address, config) -> None``:
    daily digest. Subject passes through verbatim. Multipart MIME
    (text/plain + text/html). Raises on failure (caller's retry-cap
    logic depends on exceptions, not bool).

Both share the SMTP plumbing below.
"""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

from tradelab.live.notify_channels import register


def _smtp_params(config: dict) -> tuple[str, int, str, str, str]:
    """Pull (host, port, user, password, from_addr) out of config.

    Returns host="" when the SMTP block is missing/blank — callers decide
    whether that's a no-op (alerts) or a hard failure (digest).
    """
    smtp_cfg = config.get("notifications", {}).get("smtp", {})
    host = str(smtp_cfg.get("host", "")).strip()
    port = int(smtp_cfg.get("port", 587))
    user = str(smtp_cfg.get("user", ""))
    password = str(smtp_cfg.get("password", ""))
    from_addr = str(smtp_cfg.get("from_address", "") or user)
    return host, port, user, password, from_addr


def send(severity: str, title: str, body: str, config: dict) -> bool:
    smtp_cfg = config.get("notifications", {}).get("smtp", {})
    to_addr = str(smtp_cfg.get("to_address", "")).strip()
    host, port, user, password, from_addr = _smtp_params(config)
    if not host or not to_addr:
        return False

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


def send_digest(
    subject: str,
    html_body: str,
    plaintext_body: str,
    to_address: str,
    config: dict,
) -> None:
    """Send a multipart MIME digest. Raises on any failure.

    Subject is passed through verbatim (no ``[tradelab ...]`` prefix —
    digest sender owns its own subject formatting per spec §3.3).
    """
    host, port, user, password, from_addr = _smtp_params(config)
    if not host:
        raise RuntimeError("smtp host not configured")
    if not to_address:
        raise RuntimeError("digest recipient (to_address) is empty")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.set_content(plaintext_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=10) as conn:
        conn.starttls()
        if user:
            conn.login(user, password)
        conn.sendmail(from_addr, [to_address], msg.as_string())


register("email", send)
