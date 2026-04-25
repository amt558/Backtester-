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


def test_group_by_base_name_extracts_and_groups() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "disabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
        "viprasol-amzn-v3": {"card_id": "viprasol-amzn-v3", "status": "enabled"},
        "scalper-spy-v1": {"card_id": "scalper-spy-v1", "status": "enabled"},
        "manual-card": {"card_id": "manual-card", "status": "disabled"},  # no -vN
    }
    groups = cards_view.group_by_base_name(cards)

    by_name = {g["base_name"]: g for g in groups}

    assert "viprasol-amzn" in by_name
    assert "scalper-spy" in by_name
    assert "manual-card" in by_name  # cards without -vN form their own group

    vip = by_name["viprasol-amzn"]
    assert vip["enabled_count"] == 2
    assert vip["total_count"] == 3
    # Within group: enabled first (sorted by version desc), then disabled
    assert [c["card_id"] for c in vip["cards"]] == [
        "viprasol-amzn-v3", "viprasol-amzn-v2", "viprasol-amzn-v1"
    ]


def test_group_by_base_name_flags_multi_enabled_collision() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "enabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
    }
    groups = cards_view.group_by_base_name(cards)
    assert groups[0]["multi_enabled_warning"] is True


def test_group_by_base_name_no_warning_when_one_enabled() -> None:
    cards = {
        "viprasol-amzn-v1": {"card_id": "viprasol-amzn-v1", "status": "disabled"},
        "viprasol-amzn-v2": {"card_id": "viprasol-amzn-v2", "status": "enabled"},
    }
    groups = cards_view.group_by_base_name(cards)
    assert groups[0]["multi_enabled_warning"] is False


def test_list_cards_view_combines_grouping_and_derivations(tmp_path: Path) -> None:
    cards = {
        "foo-v1": {"card_id": "foo-v1", "secret": "x" * 32, "symbol": "AAPL",
                   "status": "enabled", "quantity": 10, "cadence": "daily"},
        "foo-v2": {"card_id": "foo-v2", "secret": "y" * 32, "symbol": "AAPL",
                   "status": "disabled", "quantity": None},  # missing v1 fields
    }
    log = tmp_path / "alerts.jsonl"
    now = datetime.now(timezone.utc)
    _write_alerts(log, [
        {"ts": (now - timedelta(hours=2)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "card_id": "foo-v1", "status": "order_submitted"},
    ])

    view = cards_view.list_cards_view(cards, log)

    assert "groups" in view
    assert "total_cards" in view
    assert "total_enabled" in view
    assert view["total_cards"] == 2
    assert view["total_enabled"] == 1

    foo_group = view["groups"][0]
    assert foo_group["base_name"] == "foo"
    foo_v1 = foo_group["cards"][0]  # enabled first
    assert foo_v1["card_id"] == "foo-v1"
    assert foo_v1["last_status"] == "order_submitted"
    assert foo_v1["fires_24h"] == 2
    # foo-v2 was missing v1 fields — hydration should NOT happen here
    # (caller is expected to pass already-hydrated cards). But the derived
    # fields should still attach.
    foo_v2 = foo_group["cards"][1]
    assert foo_v2["last_status"] is None
    assert foo_v2["fires_24h"] == 0


def test_tail_alerts_for_card_returns_most_recent_first(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": "2026-04-25T09:00:00+00:00", "card_id": "foo-v1", "status": "order_submitted"},
        {"ts": "2026-04-25T09:30:00+00:00", "card_id": "bar-v1", "status": "order_submitted"},
        {"ts": "2026-04-25T10:00:00+00:00", "card_id": "foo-v1", "status": "order_failed"},
    ])

    out = cards_view.tail_alerts_for_card("foo-v1", log, limit=10)

    assert len(out) == 2
    assert out[0]["ts"] == "2026-04-25T10:00:00+00:00"  # most recent first
    assert out[1]["ts"] == "2026-04-25T09:00:00+00:00"


def test_tail_alerts_for_card_respects_limit(tmp_path: Path) -> None:
    log = tmp_path / "alerts.jsonl"
    _write_alerts(log, [
        {"ts": f"2026-04-25T09:0{i}:00+00:00", "card_id": "foo-v1",
         "status": "order_submitted"}
        for i in range(8)
    ])
    out = cards_view.tail_alerts_for_card("foo-v1", log, limit=3)
    assert len(out) == 3
    # Most recent 3 (indices 7, 6, 5)
    assert out[0]["ts"] == "2026-04-25T09:07:00+00:00"
    assert out[2]["ts"] == "2026-04-25T09:05:00+00:00"
