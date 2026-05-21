"""Paper-trading broker. Uses live Polymarket orderbook data but simulates
fills against a virtual USDC balance — no wallet, no API creds, no real money.
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

log = logging.getLogger("polybot.paper")


@dataclass
class PaperOrder:
    id: str
    token_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float  # shares (outcome tokens)
    filled: float = 0.0
    created: float = field(default_factory=time.time)

    @property
    def remaining(self) -> float:
        return max(self.size - self.filled, 0.0)


@dataclass
class PaperState:
    cash: float  # virtual USDC
    positions: dict[str, float] = field(default_factory=dict)  # token_id -> shares
    open_orders: list[PaperOrder] = field(default_factory=list)
    realized_pnl: float = 0.0
    cost_basis: dict[str, float] = field(default_factory=dict)  # token_id -> total cost paid for current position

    def to_json(self) -> dict:
        d = asdict(self)
        d["open_orders"] = [asdict(o) for o in self.open_orders]
        return d

    @classmethod
    def from_json(cls, d: dict) -> "PaperState":
        orders = [PaperOrder(**o) for o in d.get("open_orders", [])]
        return cls(
            cash=d["cash"],
            positions=d.get("positions", {}),
            open_orders=orders,
            realized_pnl=d.get("realized_pnl", 0.0),
            cost_basis=d.get("cost_basis", {}),
        )


class PaperBroker:
    """Drop-in stand-in for the live CLOB client when PAPER_TRADING=true."""

    def __init__(self, clob_host: str, starting_cash: float, state_path: str):
        self.clob_host = clob_host.rstrip("/")
        self.state_path = Path(state_path)
        self.state = self._load(starting_cash)
        self._next_id = int(time.time() * 1000)

    def _load(self, starting_cash: float) -> PaperState:
        if self.state_path.exists():
            try:
                with self.state_path.open() as f:
                    state = PaperState.from_json(json.load(f))
                log.info("loaded paper state: cash=%.2f positions=%d", state.cash, len(state.positions))
                return state
            except Exception as e:
                log.warning("failed to load %s, starting fresh: %s", self.state_path, e)
        log.info("starting fresh paper account with %.2f USDC", starting_cash)
        return PaperState(cash=starting_cash)

    def _save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(self.state.to_json(), f, indent=2)
        os.replace(tmp, self.state_path)

    # ---------- market data (public endpoint, no auth) ----------

    def get_book(self, token_id: str) -> tuple[float, float] | None:
        try:
            r = requests.get(f"{self.clob_host}/book", params={"token_id": token_id}, timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("get_book(%s) failed: %s", token_id, e)
            return None
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if not bids or not asks:
            return None
        # CLOB returns bids sorted ascending and asks descending; best are last
        best_bid = float(bids[-1]["price"])
        best_ask = float(asks[-1]["price"])
        return best_bid, best_ask

    # ---------- order management ----------

    def place(self, token_id: str, side: str, price: float, size: float) -> PaperOrder:
        self._next_id += 1
        order = PaperOrder(id=f"paper-{self._next_id}", token_id=token_id, side=side, price=price, size=size)
        # Reserve cash for buys so we don't oversell available balance
        if side == "BUY":
            reserve = price * size
            if reserve > self.state.cash:
                log.info("paper: insufficient cash %.2f for buy notional %.2f, skipping",
                         self.state.cash, reserve)
                return order
        elif side == "SELL":
            held = self.state.positions.get(token_id, 0.0)
            if size > held:
                log.info("paper: insufficient shares %.2f to sell %.2f of %s, skipping",
                         held, size, token_id[:10])
                return order
        self.state.open_orders.append(order)
        self._save()
        log.info("paper: queued %s sz=%.2f px=%.3f on %s", side, size, price, token_id[:10])
        return order

    def open_exposure_usdc(self) -> float:
        return sum(o.price * o.remaining for o in self.state.open_orders if o.side == "BUY")

    def settle(self, token_id: str, best_bid: float, best_ask: float) -> None:
        """Walk open orders for token_id and fill any that would cross the live book."""
        remaining: list[PaperOrder] = []
        for o in self.state.open_orders:
            if o.token_id != token_id or o.remaining <= 0:
                if o.remaining > 0:
                    remaining.append(o)
                continue
            fill = 0.0
            # A resting BUY at price P fills when the live best ask drops to <= P.
            # Conservatively fill at the order's limit price (worst case for the trader).
            if o.side == "BUY" and best_ask <= o.price:
                fill = o.remaining
                cost = fill * o.price
                if cost <= self.state.cash:
                    self.state.cash -= cost
                    self.state.positions[token_id] = self.state.positions.get(token_id, 0.0) + fill
                    self.state.cost_basis[token_id] = self.state.cost_basis.get(token_id, 0.0) + cost
                    o.filled += fill
                    log.info("paper FILL BUY %.2f @ %.3f cash=%.2f pos=%.2f",
                             fill, o.price, self.state.cash, self.state.positions[token_id])
            elif o.side == "SELL" and best_bid >= o.price:
                held = self.state.positions.get(token_id, 0.0)
                fill = min(o.remaining, held)
                if fill > 0:
                    proceeds = fill * o.price
                    avg_cost = (self.state.cost_basis.get(token_id, 0.0) / held) if held > 0 else 0.0
                    realized = (o.price - avg_cost) * fill
                    self.state.cash += proceeds
                    self.state.positions[token_id] = held - fill
                    self.state.cost_basis[token_id] = max(self.state.cost_basis.get(token_id, 0.0) - avg_cost * fill, 0.0)
                    self.state.realized_pnl += realized
                    o.filled += fill
                    log.info("paper FILL SELL %.2f @ %.3f pnl=%+.2f cash=%.2f pos=%.2f",
                             fill, o.price, realized, self.state.cash, self.state.positions[token_id])
            if o.remaining > 0:
                remaining.append(o)
        self.state.open_orders = remaining
        self._save()

    def summary(self, marks: dict[str, float]) -> str:
        unrealized = 0.0
        for tok, shares in self.state.positions.items():
            mark = marks.get(tok)
            if mark is None or shares == 0:
                continue
            cost = self.state.cost_basis.get(tok, 0.0)
            unrealized += (mark * shares) - cost
        equity = self.state.cash + sum(shares * marks.get(tok, 0.0) for tok, shares in self.state.positions.items())
        return (f"cash={self.state.cash:.2f} equity={equity:.2f} "
                f"realized={self.state.realized_pnl:+.2f} unrealized={unrealized:+.2f} "
                f"open_orders={len(self.state.open_orders)}")
