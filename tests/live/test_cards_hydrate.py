"""Tests for _hydrate_card backward-compat helper."""
from __future__ import annotations

from tradelab.live.cards import _hydrate_card


MINIMAL_OLD_CARD = {
    "card_id": "foo-v1",
    "secret": "s" * 32,
    "symbol": "AMZN",
    "status": "disabled",
    "quantity": None,
}


def test_hydrate_fills_missing_v1_fields() -> None:
    out = _hydrate_card(MINIMAL_OLD_CARD)
    assert out["cadence"] == "daily"
    assert out["last_fired_at"] is None
    assert out["last_attempted_at"] is None
    assert out["enabled_at"] is None
    assert out["daily_limit"] == 5
    assert out["cooldown_seconds"] == 30
    assert out["allow_collision"] is False
    assert out["allow_naked_short"] is False


def test_hydrate_preserves_existing_v1_fields() -> None:
    rich_card = dict(MINIMAL_OLD_CARD,
                     cadence="intraday",
                     daily_limit=50,
                     allow_collision=True)
    out = _hydrate_card(rich_card)
    assert out["cadence"] == "intraday"
    assert out["daily_limit"] == 50
    assert out["allow_collision"] is True
    # Non-overridden defaults still applied
    assert out["cooldown_seconds"] == 30


def test_hydrate_preserves_legacy_v0_fields() -> None:
    out = _hydrate_card(MINIMAL_OLD_CARD)
    assert out["card_id"] == "foo-v1"
    assert out["secret"] == "s" * 32
    assert out["symbol"] == "AMZN"
    assert out["status"] == "disabled"
    assert out["quantity"] is None
