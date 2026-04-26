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
