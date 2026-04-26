"""Tests for daily_summary.render() pure-function and its sub-renderers."""
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.live import daily_summary


def _make_panic_entry(ts: str, level: str, **extra) -> dict:
    return {"ts": ts, "level": level, **extra}


def _make_notify_entry(ts: str, severity: str, title: str, **extra) -> dict:
    return {"ts": ts, "severity": severity, "title": title, **extra}


def _make_alert_entry(ts: str, status: str, card_id: str, **extra) -> dict:
    return {"ts": ts, "status": status, "card_id": card_id, **extra}


def test_render_anomaly_section_all_clear(monkeypatch):
    """No anomalies today → returns the ✓ all-clear header and counts (0,0,0,0)."""
    monkeypatch.setattr(daily_summary, "_today_panics", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_order_failures", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_receiver_downtimes", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_ngrok_changes", lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "✓ No anomalies today" in section
    assert counts == {"panic": 0, "block": 0, "fail": 0, "silent": 0, "downtime": 0, "ngrok": 0}


def test_render_anomaly_section_with_panic(monkeypatch):
    """One panic event → renders PANIC L1 badge with timestamp."""
    monkeypatch.setattr(daily_summary, "_today_panics", lambda d: [
        _make_panic_entry("2026-04-27T18:22:00+00:00", "L1", cards_disabled=8),
    ])
    for fn in ("_today_silent_transitions", "_today_guardrail_blocks", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "PANIC L1" in section
    assert "14:22 ET" in section  # 18:22 UTC = 14:22 ET on 04-27
    assert "8 cards disabled" in section
    assert counts["panic"] == 1


def test_render_anomaly_section_with_blocks(monkeypatch):
    """Three guardrail blocks across two cards → renders count + per-card breakdown."""
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [
        _make_alert_entry("2026-04-27T13:30:00+00:00", "guardrail_blocked", "card-a", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T13:35:00+00:00", "guardrail_blocked", "card-a", reason="cooldown_active"),
        _make_alert_entry("2026-04-27T14:00:00+00:00", "guardrail_blocked", "card-b", reason="symbol_collision"),
    ])
    for fn in ("_today_panics", "_today_silent_transitions", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "3 guardrail blocks" in section
    assert "card-a" in section
    assert "card-b" in section
    assert "cooldown_active" in section
    assert counts["block"] == 3


def test_render_anomaly_section_with_silent_transition(monkeypatch):
    """One silent-card transition → renders SILENT badge + card_id."""
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [
        _make_notify_entry("2026-04-27T15:00:00+00:00", "WARNING", "Card silent", card_id="card-c"),
    ])
    for fn in ("_today_panics", "_today_guardrail_blocks", "_today_order_failures",
               "_today_receiver_downtimes", "_today_ngrok_changes"):
        monkeypatch.setattr(daily_summary, fn, lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "SILENT" in section
    assert "card-c" in section
    assert counts["silent"] == 1


def test_render_anomaly_section_section_error_degrades(monkeypatch):
    """If one section's data source raises, that section gets [error: <type>] but rest continues."""
    monkeypatch.setattr(daily_summary, "_today_panics",
                         lambda d: (_ for _ in ()).throw(RuntimeError("simulated")))
    monkeypatch.setattr(daily_summary, "_today_silent_transitions", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_guardrail_blocks", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_order_failures", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_receiver_downtimes", lambda d: [])
    monkeypatch.setattr(daily_summary, "_today_ngrok_changes", lambda d: [])

    section, counts = daily_summary._render_anomaly_section(date(2026, 4, 27))
    assert "[error: RuntimeError]" in section
    # Other sections still rendered (no anomalies in them)
    assert counts["block"] == 0


def test_render_snapshot_section_with_data(monkeypatch):
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 12, "enabled": 8, "disabled": 3, "silent": 1})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 14)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity", lambda d: {
        "CRITICAL": 4, "WARNING": 2, "INFO": 11, "DEBUG": 0,
    })
    monkeypatch.setattr(daily_summary, "_open_positions",
                         lambda: [{"symbol": "AMZN", "qty": "12", "side": "long"}])
    monkeypatch.setattr(daily_summary, "_open_orders",
                         lambda: [{"symbol": "GOOG", "qty": "10", "side": "buy", "status": "new"}])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "ngrok_url": "abc.ngrok-free.app"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))

    assert "12 total" in section and "8 enabled" in section
    assert "14 order submissions" in section
    assert "4 CRITICAL" in section
    assert "AMZN" in section and "GOOG" in section
    assert "abc.ngrok-free.app" in section
    assert "up" in section.lower()  # receiver line rendered


def test_render_snapshot_section_empty_alpaca(monkeypatch):
    """When Alpaca returns empty lists, show empty-state lines, not tables."""
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 0, "enabled": 0, "disabled": 0, "silent": 0})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions", lambda: [])
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "ngrok_url": "—"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))
    assert "Open positions (0)" in section
    assert "Open orders (0)" in section
    # No <table> rows when empty
    assert "<table" not in section


def test_render_snapshot_section_alpaca_error_degrades(monkeypatch):
    """If Alpaca raises, the positions section shows [error: ...] but rest renders."""
    monkeypatch.setattr(daily_summary, "_card_counts",
                         lambda: {"total": 1, "enabled": 1, "disabled": 0, "silent": 0})
    monkeypatch.setattr(daily_summary, "_today_order_submission_count", lambda d: 0)
    monkeypatch.setattr(daily_summary, "_today_notify_counts_by_severity",
                         lambda d: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0})
    monkeypatch.setattr(daily_summary, "_open_positions",
                         lambda: (_ for _ in ()).throw(RuntimeError("alpaca down")))
    monkeypatch.setattr(daily_summary, "_open_orders", lambda: [])
    monkeypatch.setattr(daily_summary, "_receiver_status",
                         lambda: {"up": True, "ngrok_url": "x"})

    section = daily_summary._render_snapshot_section(date(2026, 4, 27))
    assert "[error: RuntimeError]" in section
    # The rest still rendered
    assert "1 total" in section
