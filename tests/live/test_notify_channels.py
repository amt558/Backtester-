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
