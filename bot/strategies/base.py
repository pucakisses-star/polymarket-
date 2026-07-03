from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import DesiredOrder, MarketSpec, OrderBook
from ..portfolio import Portfolio


@dataclass
class TickContext:
    """Everything a strategy sees on one tick."""

    books: dict[str, OrderBook]
    portfolio: Portfolio
    markets: list[MarketSpec]
    ticks: dict[str, float] = field(default_factory=dict)  # token_id -> tick size
    cash: float | None = None  # known in paper mode only

    def tick(self, token_id: str) -> float:
        return self.ticks.get(token_id, 0.01)


class Strategy(ABC):
    """Strategies are *declarative*: each tick they return the full set of
    orders they want resting right now. The engine diffs that against actual
    open orders and issues the minimal cancels/places. Returning [] means
    'cancel everything of mine'."""

    name: str = "base"

    @abstractmethod
    def desired_orders(self, ctx: TickContext) -> list[DesiredOrder]: ...
