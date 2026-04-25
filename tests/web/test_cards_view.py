"""Tests for tradelab.web.cards_view derived-fields helpers."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradelab.web import cards_view


def _write_alerts(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def test_derive_last_status_returns_most_recent_for_card(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": "2026-04-25T09:30:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "bar-v1",
         "status": "order_failed"},
        {"ts": "2026-04-25T10:30:00+00:00", "card_id": "foo-v1",
         "status": "order_failed"},
    ])

    out = cards_view.derive_last_status(["foo-v1", "bar-v1", "baz-v1"], log)

    assert out["foo-v1"] == "order_failed"
    assert out["bar-v1"] == "order_failed"
    assert out["baz-v1"] is None  # no entries → None


def test_derive_last_status_handles_missing_log(tmp_path: Path) -> None:
    log = tmp_path / "does_not_exist.jsonl"
    out = cards_view.derive_last_status(["foo-v1"], log)
    assert out == {"foo-v1": None}


def test_derive_last_status_skips_malformed_lines(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    log.write_text(
        '{"ts": "2026-04-25T09:30:00+00:00", "card_id": "foo-v1", "status": "order_submitted"}\n'
        'NOT JSON\n'
        '{"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1", "status": "order_failed"}\n',
        encoding="utf-8",
    )
    out = cards_view.derive_last_status(["foo-v1"], log)
    assert out["foo-v1"] == "order_failed"


def test_derive_fire_counts_filters_to_24h_window(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    now = datetime.now(timezone.utc)
    _write_alerts(log, [
        {"ts": (now - timedelta(hours=30)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},  # too old
        {"ts": (now - timedelta(hours=10)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=2)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "card_id": "bar-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=5)).isoformat(),
         "card_id": "foo-v1", "status": "order_failed"},  # not order_submitted, ignored
    ])

    counts = cards_view.derive_fire_counts(
        ["foo-v1", "bar-v1", "baz-v1"], log, hours=24
    )

    assert counts["foo-v1"] == 2  # only the two within 24h that submitted
    assert counts["bar-v1"] == 1
    assert counts["baz-v1"] == 0
