"""Broker interface implemented by the paper simulator and the live client."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import DesiredOrder, Fill, Order, OrderBook


class Broker(ABC):
    @abstractmethod
    def place(self, d: DesiredOrder) -> Order | None:
        """Submit an order. Returns the resting Order, or None if rejected."""

    @abstractmethod
    def cancel(self, order_id: str) -> None: ...

    @abstractmethod
    def cancel_all(self) -> None: ...

    @abstractmethod
    def open_orders(self) -> list[Order]: ...

    @abstractmethod
    def poll_fills(self) -> list[Fill]:
        """Drain fills that occurred since the last poll."""

    def on_books(self, books: dict[str, OrderBook]) -> None:
        """Paper broker hooks this to simulate matching. No-op live."""

    def cash(self) -> float | None:
        """Total account cash if known (paper). None when unknown (live)."""
        return None
