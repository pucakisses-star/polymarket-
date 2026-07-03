"""Depth-aware paper trading simulator.

Runs against live orderbook snapshots but keeps everything virtual:

- Cash is *reserved* when a buy is placed and released on cancel/expiry, so a
  batch of resting buys can never promise more cash than exists.
- Fills walk the real book level by level: a buy fills against every ask at or
  below its limit, at the *level's* price (price improvement is passed on),
  capped by the displayed size at each level.
- Sells are only accepted up to the shares actually held (minus shares already
  committed to other resting sells).
- Orders expire after a TTL so nothing rests forever.

Deliberate simplifications (paper results are still optimistic — see README):
no queue position, no partial visibility, fills sized by a single snapshot.
"""

from __future__ import annotations

import logging
import time

from ..models import DesiredOrder, Fill, Order, OrderBook, Side
from .base import Broker

log = logging.getLogger("polybot.paper")


class PaperBroker(Broker):
    def __init__(self, starting_cash: float, order_ttl_sec: float = 300.0, fee_bps: float = 0.0):
        self.available = starting_cash
        self.reserved = 0.0
        self.shares: dict[str, float] = {}
        self.orders: dict[str, Order] = {}
        self.order_ttl_sec = order_ttl_sec
        self.fee_bps = fee_bps
        self._fills: list[Fill] = []

    # ---------- Broker interface ----------

    def place(self, d: DesiredOrder) -> Order | None:
        if d.side is Side.BUY:
            need = d.notional
            if need > self.available + 1e-9:
                log.info("paper reject BUY: need %.2f, available %.2f", need, self.available)
                return None
            self.available -= need
            self.reserved += need
        else:
            committed = sum(
                o.remaining
                for o in self.orders.values()
                if o.token_id == d.token_id and o.side is Side.SELL
            )
            if d.size + committed > self.shares.get(d.token_id, 0.0) + 1e-9:
                log.info(
                    "paper reject SELL: %.2f + committed %.2f > held %.2f",
                    d.size, committed, self.shares.get(d.token_id, 0.0),
                )
                return None
        order = Order(token_id=d.token_id, side=d.side, price=d.price, size=d.size)
        self.orders[order.id] = order
        log.debug("paper place %s %s %.2f @ %.3f", d.side.value, d.token_id[:10], d.size, d.price)
        return order

    def cancel(self, order_id: str) -> None:
        order = self.orders.pop(order_id, None)
        if order is None:
            return
        self._release(order)
        order.status = "CANCELED"

    def cancel_all(self) -> None:
        for oid in list(self.orders):
            self.cancel(oid)

    def open_orders(self) -> list[Order]:
        return list(self.orders.values())

    def poll_fills(self) -> list[Fill]:
        fills, self._fills = self._fills, []
        return fills

    def cash(self) -> float | None:
        return self.available + self.reserved

    # ---------- matching ----------

    def on_books(self, books: dict[str, OrderBook]) -> None:
        now = time.time()
        for order in list(self.orders.values()):
            if now - order.created_ts > self.order_ttl_sec:
                log.info("paper expire %s %s @ %.3f", order.side.value, order.token_id[:10], order.price)
                order.status = "EXPIRED"
                self._release(order)
                self.orders.pop(order.id, None)
                continue
            book = books.get(order.token_id)
            if book is None:
                continue
            self._match(order, book)
            if order.remaining <= 1e-9:
                order.status = "FILLED"
                self.orders.pop(order.id, None)

    def _match(self, order: Order, book: OrderBook) -> None:
        levels = book.asks if order.side is Side.BUY else book.bids
        for level in levels:
            if order.remaining <= 1e-9:
                break
            crosses = (
                level.price <= order.price + 1e-12
                if order.side is Side.BUY
                else level.price >= order.price - 1e-12
            )
            if not crosses:
                break
            qty = min(order.remaining, level.size)
            if qty <= 0:
                continue
            fee = qty * level.price * self.fee_bps / 10_000
            if order.side is Side.BUY:
                # reserved at limit price; pay level price, release the difference
                self.reserved -= order.price * qty
                self.available += (order.price - level.price) * qty - fee
                self.shares[order.token_id] = self.shares.get(order.token_id, 0.0) + qty
            else:
                self.available += level.price * qty - fee
                self.shares[order.token_id] = self.shares.get(order.token_id, 0.0) - qty
            order.filled += qty
            self._fills.append(
                Fill(order.id, order.token_id, order.side, level.price, qty, fee=fee)
            )
            log.info(
                "paper FILL %s %s %.2f @ %.3f (cash=%.2f)",
                order.side.value, order.token_id[:10], qty, level.price, self.available + self.reserved,
            )

    def _release(self, order: Order) -> None:
        if order.side is Side.BUY:
            refund = order.price * order.remaining
            self.reserved -= refund
            self.available += refund

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "reserved": self.reserved,
            "shares": dict(self.shares),
            # resting orders are not persisted: on restart we start flat-of-orders,
            # matching live behavior where shutdown cancels everything
        }

    def restore(self, d: dict) -> None:
        # any reserved cash belonged to orders that no longer exist
        self.available = d.get("available", self.available) + d.get("reserved", 0.0)
        self.reserved = 0.0
        self.shares = dict(d.get("shares", {}))
