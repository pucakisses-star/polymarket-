"""Position and P&L tracking from fills."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Fill, Order, Side


@dataclass
class Position:
    shares: float = 0.0
    cost: float = 0.0  # total USDC paid for the current shares

    @property
    def avg_price(self) -> float:
        return self.cost / self.shares if self.shares > 0 else 0.0


@dataclass
class Portfolio:
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def position(self, token_id: str) -> Position:
        return self.positions.setdefault(token_id, Position())

    def shares(self, token_id: str) -> float:
        pos = self.positions.get(token_id)
        return pos.shares if pos else 0.0

    def apply_fill(self, fill: Fill) -> None:
        pos = self.position(fill.token_id)
        self.fees_paid += fill.fee
        if fill.side is Side.BUY:
            pos.shares += fill.size
            pos.cost += fill.price * fill.size + fill.fee
        else:
            if pos.shares <= 0:
                # Selling something we don't track — record proceeds as pure pnl
                self.realized_pnl += fill.price * fill.size - fill.fee
                return
            size = min(fill.size, pos.shares)
            avg = pos.avg_price
            self.realized_pnl += (fill.price - avg) * size - fill.fee
            pos.cost = max(pos.cost - avg * size, 0.0)
            pos.shares -= size

    # ---------- valuation ----------

    def position_value(self, marks: dict[str, float]) -> float:
        return sum(
            p.shares * marks.get(tok, p.avg_price)
            for tok, p in self.positions.items()
            if p.shares > 0
        )

    def position_cost(self) -> float:
        return sum(p.cost for p in self.positions.values() if p.shares > 0)

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        return self.position_value(marks) - self.position_cost()

    def total_exposure(self, open_orders: list[Order]) -> float:
        """Capital at risk: cost of held positions plus notional of resting buys."""
        open_buys = sum(o.price * o.remaining for o in open_orders if o.side is Side.BUY)
        return self.position_cost() + open_buys

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        return {
            "positions": {t: {"shares": p.shares, "cost": p.cost} for t, p in self.positions.items()},
            "realized_pnl": self.realized_pnl,
            "fees_paid": self.fees_paid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Portfolio":
        pf = cls(realized_pnl=d.get("realized_pnl", 0.0), fees_paid=d.get("fees_paid", 0.0))
        for tok, p in d.get("positions", {}).items():
            pf.positions[tok] = Position(shares=p["shares"], cost=p["cost"])
        return pf
