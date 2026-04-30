"""Per-channel send() tests. One success + one failure-isolation case per channel."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─── audible ─────────────────────────────────────────────────────────


def test_audible_send_falls_back_to_messagebeep_when_no_soundfile(monkeypatch):
    fake_winsound = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    cfg = {"notifications": {"audible": {"sound_file": ""}}}
    ok = send("critical", "T", "B", cfg)
    assert ok is True
    fake_winsound.MessageBeep.assert_called_once()


def test_audible_send_uses_playsound_when_soundfile_set(tmp_path, monkeypatch):
    wav = tmp_path / "panic.wav"
    wav.write_bytes(b"RIFF")
    fake_winsound = MagicMock()
    fake_winsound.SND_FILENAME = 0x20000
    fake_winsound.SND_ASYNC = 0x0001
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    cfg = {"notifications": {"audible": {"sound_file": str(wav)}}}
    ok = send("critical", "T", "B", cfg)
    assert ok is True
    fake_winsound.PlaySound.assert_called_once()


def test_audible_send_returns_false_on_winsound_error(monkeypatch):
    fake_winsound = MagicMock()
    fake_winsound.MessageBeep.side_effect = RuntimeError("audio device unavailable")
    monkeypatch.setattr("tradelab.live.notify_channels.audible.winsound", fake_winsound)
    from tradelab.live.notify_channels.audible import send
    ok = send("critical", "T", "B", {"notifications": {"audible": {"sound_file": ""}}})
    assert ok is False


# ─── windows_toast ───────────────────────────────────────────────────────


def test_windows_toast_send_calls_plyer_notify(monkeypatch):
    fake_plyer_notification = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", fake_plyer_notification)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("critical", "Guardrail blocked", "AAPL cooldown_active", {})
    assert ok is True
    fake_plyer_notification.notify.assert_called_once()
    kwargs = fake_plyer_notification.notify.call_args.kwargs
    assert "[CRITICAL]" in kwargs["title"]
    assert "Guardrail blocked" in kwargs["title"]
    assert kwargs["message"] == "AAPL cooldown_active"
    assert kwargs["app_name"] == "tradelab"


def test_windows_toast_send_returns_false_on_plyer_error(monkeypatch):
    fake = MagicMock()
    fake.notify.side_effect = RuntimeError("notification system unavailable")
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", fake)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("warning", "T", "B", {})
    assert ok is False


def test_windows_toast_no_op_when_plyer_unimportable(monkeypatch):
    monkeypatch.setattr("tradelab.live.notify_channels.windows_toast.notification", None)
    from tradelab.live.notify_channels.windows_toast import send
    ok = send("info", "T", "B", {})
    assert ok is False


# ─── ntfy ────────────────────────────────────────────────────────────


def test_ntfy_send_posts_to_topic_url(monkeypatch):
    fake_urlopen = MagicMock()
    fake_urlopen.return_value.__enter__.return_value.status = 200
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    cfg = {"notifications": {"ntfy": {"topic": "tradelab-test", "server": "https://ntfy.sh"}}}
    ok = send("critical", "Boom", "AAPL guardrail blocked", cfg)
    assert ok is True
    req = fake_urlopen.call_args[0][0]
    assert req.full_url == "https://ntfy.sh/tradelab-test"
    assert req.data == b"AAPL guardrail blocked"
    assert req.headers["Title"] == "Boom"
    assert req.headers["Priority"] == "5"


def test_ntfy_send_no_op_when_topic_empty(monkeypatch):
    fake_urlopen = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    ok = send("critical", "T", "B", {"notifications": {"ntfy": {"topic": "", "server": "https://ntfy.sh"}}})
    assert ok is False
    fake_urlopen.assert_not_called()


def test_ntfy_send_returns_false_on_http_error(monkeypatch):
    from urllib.error import URLError
    fake_urlopen = MagicMock(side_effect=URLError("connection refused"))
    monkeypatch.setattr("tradelab.live.notify_channels.ntfy.urlopen", fake_urlopen)
    from tradelab.live.notify_channels.ntfy import send
    cfg = {"notifications": {"ntfy": {"topic": "x", "server": "https://ntfy.sh"}}}
    ok = send("info", "T", "B", cfg)
    assert ok is False


# ─── email ───────────────────────────────────────────────────────────


def test_email_send_uses_starttls_login_and_sendmail(monkeypatch):
    smtp_instance = MagicMock()
    smtp_class = MagicMock(return_value=smtp_instance)
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", smtp_class)
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587,
        "user": "u@e.com", "password": "pw",
        "from_address": "u@e.com", "to_address": "amit@e.com",
    }}}
    ok = send("critical", "Boom", "Body line", cfg)
    assert ok is True
    smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("u@e.com", "pw")
    smtp_instance.sendmail.assert_called_once()
    args = smtp_instance.sendmail.call_args[0]
    assert args[0] == "u@e.com"
    assert args[1] == ["amit@e.com"]
    assert "Boom" in args[2]
    assert "Body line" in args[2]


def test_email_send_no_op_when_host_empty(monkeypatch):
    smtp_class = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", smtp_class)
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {"host": "", "to_address": "x@e.com"}}}
    ok = send("info", "T", "B", cfg)
    assert ok is False
    smtp_class.assert_not_called()


def test_email_send_returns_false_on_smtp_exception(monkeypatch):
    import smtplib as real_smtplib
    smtp_instance = MagicMock()
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    smtp_instance.login.side_effect = real_smtplib.SMTPAuthenticationError(535, b"nope")
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", MagicMock(return_value=smtp_instance))
    from tradelab.live.notify_channels.email import send
    cfg = {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587, "user": "u", "password": "x",
        "from_address": "u@e.com", "to_address": "amit@e.com",
    }}}
    ok = send("warning", "T", "B", cfg)
    assert ok is False


# ─── email.send_digest (Slice 7a B1 — daily digest path) ─────────────

def _digest_cfg():
    return {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587,
        "user": "u@e.com", "password": "pw",
        "from_address": "u@e.com",
    }}}


def _patch_smtp(monkeypatch):
    smtp_instance = MagicMock()
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    smtp_class = MagicMock(return_value=smtp_instance)
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", smtp_class)
    return smtp_class, smtp_instance


def test_send_digest_passes_subject_through_verbatim(monkeypatch):
    """No '[tradelab SEVERITY]' prefix — digest owns its own subject."""
    smtp_class, smtp_instance = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    send_digest(
        subject="tradelab digest 2026-04-27 — 3 alerts, 1 panic",
        html_body="<html><body><h1>hi</h1></body></html>",
        plaintext_body="hi",
        to_address="amit@e.com",
        config=_digest_cfg(),
    )
    raw = smtp_instance.sendmail.call_args[0][2]
    # Subject is in raw email — em-dash will be quoted-printable (=E2=80=94)
    # or base64-encoded; assert the ASCII anchors directly.
    assert "tradelab digest 2026-04-27" in raw
    assert "3 alerts, 1 panic" in raw
    assert "[tradelab" not in raw  # no '[tradelab SEVERITY]' prefix


def test_send_digest_builds_multipart_alternative_with_html_and_plaintext(monkeypatch):
    """spec §5.3: multipart MIME with both text/plain and text/html parts."""
    smtp_class, smtp_instance = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    send_digest(
        subject="x",
        html_body="<html><body><p>HTML version</p></body></html>",
        plaintext_body="PLAIN version",
        to_address="amit@e.com",
        config=_digest_cfg(),
    )
    raw = smtp_instance.sendmail.call_args[0][2]
    assert "multipart/alternative" in raw
    assert "Content-Type: text/plain" in raw
    assert "Content-Type: text/html" in raw
    assert "PLAIN version" in raw
    assert "HTML version" in raw


def test_send_digest_uses_starttls_login_and_sendmail(monkeypatch):
    smtp_class, smtp_instance = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    send_digest("s", "<p>h</p>", "p", "amit@e.com", _digest_cfg())
    smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("u@e.com", "pw")
    args = smtp_instance.sendmail.call_args[0]
    assert args[0] == "u@e.com"
    assert args[1] == ["amit@e.com"]


def test_send_digest_raises_on_smtp_exception(monkeypatch):
    """spec §3.5 retry-cap depends on raise — must NOT swallow + return bool."""
    import smtplib as real_smtplib
    smtp_instance = MagicMock()
    smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_instance.__exit__ = MagicMock(return_value=False)
    smtp_instance.sendmail.side_effect = real_smtplib.SMTPDataError(550, b"rejected")
    monkeypatch.setattr("tradelab.live.notify_channels.email.smtplib.SMTP", MagicMock(return_value=smtp_instance))
    from tradelab.live.notify_channels.email import send_digest
    with pytest.raises(real_smtplib.SMTPDataError):
        send_digest("s", "<p>h</p>", "p", "amit@e.com", _digest_cfg())


def test_send_digest_raises_when_host_not_configured(monkeypatch):
    smtp_class, _ = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    cfg = {"notifications": {"smtp": {"host": "", "port": 587, "from_address": "u@e.com"}}}
    with pytest.raises(RuntimeError, match="smtp host not configured"):
        send_digest("s", "<p>h</p>", "p", "amit@e.com", cfg)
    smtp_class.assert_not_called()


def test_send_digest_raises_when_to_address_empty(monkeypatch):
    smtp_class, _ = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    with pytest.raises(RuntimeError, match="recipient"):
        send_digest("s", "<p>h</p>", "p", "", _digest_cfg())
    smtp_class.assert_not_called()


def test_send_digest_skips_login_when_no_user_configured(monkeypatch):
    smtp_class, smtp_instance = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    cfg = {"notifications": {"smtp": {
        "host": "smtp.local", "port": 25,
        "user": "", "password": "",
        "from_address": "noreply@local",
    }}}
    send_digest("s", "<p>h</p>", "p", "amit@e.com", cfg)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_not_called()
    smtp_instance.sendmail.assert_called_once()


def test_send_digest_falls_back_to_user_when_from_address_missing(monkeypatch):
    """B25: when from_address is empty/missing, MAIL FROM falls back to user.

    Pins _smtp_params line: `from_addr = str(smtp_cfg.get("from_address", "") or user)`.
    Regression that swaps fallback ordering or drops the fallback would be caught here.
    """
    smtp_class, smtp_instance = _patch_smtp(monkeypatch)
    from tradelab.live.notify_channels.email import send_digest
    cfg = {"notifications": {"smtp": {
        "host": "smtp.example.com", "port": 587,
        "user": "u@e.com", "password": "pw",
        # from_address intentionally omitted
    }}}
    send_digest("s", "<p>h</p>", "p", "amit@e.com", cfg)
    args = smtp_instance.sendmail.call_args[0]
    assert args[0] == "u@e.com"  # MAIL FROM falls back to user
    assert args[1] == ["amit@e.com"]
    raw = args[2]
    assert "From: u@e.com" in raw  # message From: header also uses user


# ─── browser ─────────────────────────────────────────────────────────


def test_browser_send_calls_notify_broadcaster_broadcast(monkeypatch):
    fake_bc = MagicMock()
    fake_bc.broadcast = MagicMock()
    monkeypatch.setattr("tradelab.live.notify_channels.browser.get_notify_broadcaster", lambda: fake_bc)
    from tradelab.live.notify_channels.browser import send
    ok = send("warning", "Title", "Body", {})
    assert ok is True
    fake_bc.broadcast.assert_called_once()
    payload = fake_bc.broadcast.call_args[0][0]
    assert payload["severity"] == "warning"
    assert payload["title"] == "Title"
    assert payload["body"] == "Body"
    assert "ts" in payload


def test_browser_send_returns_false_on_broadcaster_error(monkeypatch):
    fake_bc = MagicMock()
    fake_bc.broadcast.side_effect = RuntimeError("no subscribers? actually any raise")
    monkeypatch.setattr("tradelab.live.notify_channels.browser.get_notify_broadcaster", lambda: fake_bc)
    from tradelab.live.notify_channels.browser import send
    ok = send("info", "T", "B", {})
    assert ok is False


def test_get_notify_broadcaster_is_a_singleton():
    from tradelab.web import get_notify_broadcaster
    assert get_notify_broadcaster() is get_notify_broadcaster()
