"""Core data types shared across the bot."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


def round_to_tick(price: float, tick: float, side: Side) -> float:
    """Round a price onto the market's tick grid, never in the trader's
    disfavor: buys round down, sells round up. Clamped inside (0, 1)."""
    q = price / tick
    n = math.floor(q + 1e-9) if side is Side.BUY else math.ceil(q - 1e-9)
    px = n * tick
    px = max(tick, min(1 - tick, px))
    return round(px, 6)


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    """Normalized orderbook: bids sorted best (highest) first, asks sorted
    best (lowest) first, regardless of how the API returned them."""

    token_id: str
    bids: list[BookLevel]
    asks: list[BookLevel]
    ts: float = field(default_factory=time.time)

    @classmethod
    def from_raw(cls, token_id: str, bids_raw: list[dict], asks_raw: list[dict]) -> "OrderBook":
        bids = sorted(
            (BookLevel(float(l["price"]), float(l["size"])) for l in bids_raw or []),
            key=lambda l: -l.price,
        )
        asks = sorted(
            (BookLevel(float(l["price"]), float(l["size"])) for l in asks_raw or []),
            key=lambda l: l.price,
        )
        return cls(token_id=token_id, bids=bids, asks=asks)

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2

    @property
    def spread(self) -> float | None:
        if not self.bids or not self.asks:
            return None
        return self.asks[0].price - self.bids[0].price

    def depth_at_or_better(self, side: Side, price: float) -> float:
        """Shares available to a *taker* on `side` at limit `price`."""
        if side is Side.BUY:
            return sum(l.size for l in self.asks if l.price <= price + 1e-12)
        return sum(l.size for l in self.bids if l.price >= price - 1e-12)


@dataclass
class DesiredOrder:
    """What a strategy wants resting on the book right now."""

    token_id: str
    side: Side
    price: float
    size: float  # shares
    reason: str = ""

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass
class Order:
    token_id: str
    side: Side
    price: float
    size: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    filled: float = 0.0
    status: str = "OPEN"  # OPEN | FILLED | CANCELED | EXPIRED
    created_ts: float = field(default_factory=time.time)

    @property
    def remaining(self) -> float:
        return max(self.size - self.filled, 0.0)


@dataclass
class Fill:
    order_id: str
    token_id: str
    side: Side
    price: float
    size: float
    fee: float = 0.0
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class MarketSpec:
    """A market to trade. `token_id` is the primary (usually YES) outcome
    token; `complement_id` is the opposite outcome, required only by the
    complement-arbitrage strategy."""

    token_id: str
    complement_id: str | None = None

    @classmethod
    def parse(cls, raw: str) -> "MarketSpec":
        parts = [p.strip() for p in raw.split(":") if p.strip()]
        if len(parts) == 1:
            return cls(token_id=parts[0])
        if len(parts) == 2:
            return cls(token_id=parts[0], complement_id=parts[1])
        raise ValueError(f"bad MARKETS entry: {raw!r} (want 'token' or 'yes_token:no_token')")

    def all_tokens(self) -> list[str]:
        return [self.token_id] + ([self.complement_id] if self.complement_id else [])
