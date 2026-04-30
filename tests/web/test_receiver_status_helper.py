"""Tests for handlers.probe_receiver_status() — the in-process helper
introduced for B8 to remove the daily_summary HTTP self-call."""
from unittest.mock import patch

import pytest

from tradelab.web import handlers


def test_probe_receiver_status_all_up_returns_full_dict():
    fake_health = {"status": "ok", "cards_loaded": 5}
    fake_tunnels = {"tunnels": [{"proto": "https", "public_url": "https://abc.ngrok.io"}]}

    def _probe(url, timeout=1.5):
        if "/health" in url:
            return fake_health
        return fake_tunnels

    with patch.object(handlers, "_probe_json", side_effect=_probe):
        result = handlers.probe_receiver_status()
    assert result == {
        "receiver_up": True,
        "ngrok_up": True,
        "ngrok_url": "https://abc.ngrok.io",
        "cards_loaded": 5,
    }


def test_probe_receiver_status_all_down_returns_safe_defaults():
    """When both probes raise, the helper returns a safe all-down envelope."""
    with patch.object(handlers, "_probe_json", side_effect=ConnectionRefusedError("nope")):
        result = handlers.probe_receiver_status()
    assert result == {
        "receiver_up": False,
        "ngrok_up": False,
        "ngrok_url": None,
        "cards_loaded": None,
    }


def test_probe_receiver_status_receiver_down_ngrok_up_returns_asymmetric_envelope():
    """Asymmetric case: receiver crashed but ngrok tunnel still alive.

    The helper must NOT short-circuit on the first failed probe — operators
    benefit from knowing 'tunnel is intact, but the receiver process died'.
    Pin this behavior so a future refactor can't quietly change it.
    """
    fake_tunnels = {"tunnels": [{"proto": "https", "public_url": "https://still-up.ngrok.io"}]}

    def _probe(url, timeout=1.5):
        if "/health" in url:
            raise ConnectionRefusedError("receiver dead")
        return fake_tunnels

    with patch.object(handlers, "_probe_json", side_effect=_probe):
        result = handlers.probe_receiver_status()
    assert result == {
        "receiver_up": False,
        "ngrok_up": True,
        "ngrok_url": "https://still-up.ngrok.io",
        "cards_loaded": None,
    }
