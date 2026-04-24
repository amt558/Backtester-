"""Pydantic models for the webhook receiver.

TradingView renders its `{{...}}` placeholders as strings at alert-fire time, so
numeric fields arrive as strings and need Pydantic coercion.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    """Matches the JSON the TradingView alert Message produces."""

    card_id: str = Field(min_length=1, max_length=128)
    secret: str = Field(min_length=1, max_length=256)
    action: Literal["buy", "sell"]
    symbol: str = Field(min_length=1, max_length=16)
    contracts: float = Field(ge=0)

    price: Optional[float] = None
    market_position: Optional[Literal["long", "short", "flat"]] = None
    position_size_after: Optional[float] = None
    order_id: Optional[str] = None
    order_comment: Optional[str] = None
    bar_time: Optional[str] = None
    bar_close: Optional[float] = None

    model_config = {"extra": "ignore"}


class OrderResult(BaseModel):
    id: str
    client_order_id: Optional[str]
    symbol: str
    qty: str
    side: str
    status: str
    submitted_at: Optional[str]
