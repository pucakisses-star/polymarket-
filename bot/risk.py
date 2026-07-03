"""Pre-trade checks and the drawdown kill switch."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config
from .models import DesiredOrder, Order, Side
from .portfolio import Portfolio

log = logging.getLogger("polybot.risk")


@dataclass
class RiskEngine:
    cfg: Config
    peak_equity: float | None = None
    halted: bool = False
    halt_reason: str = ""

    def check_drawdown(self, equity: float | None) -> bool:
        """Update the high-water mark; halt if drawdown breaches the limit.
        Returns True if trading may continue."""
        if self.halted:
            return False
        if equity is None:
            return True
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        limit = self.peak_equity * (1 - self.cfg.max_drawdown_pct / 100)
        if equity < limit:
            self.halted = True
            self.halt_reason = (
                f"drawdown kill switch: equity {equity:.2f} < "
                f"{limit:.2f} ({self.cfg.max_drawdown_pct}% below peak {self.peak_equity:.2f})"
            )
            log.error(self.halt_reason)
            return False
        return True

    def validate(
        self,
        d: DesiredOrder,
        portfolio: Portfolio,
        open_orders: list[Order],
        pending: list[DesiredOrder],
    ) -> tuple[bool, str]:
        """Check one desired order. `pending` = orders already approved this
        tick, so a batch can't collectively blow through the caps."""
        if self.halted:
            return False, f"halted: {self.halt_reason}"
        if not 0 < d.price < 1:
            return False, f"price {d.price} outside (0,1)"
        if d.size <= 0:
            return False, "non-positive size"
        if d.size < self.cfg.min_size_shares:
            return False, f"size {d.size:.2f} < exchange min {self.cfg.min_size_shares}"
        if d.notional < self.cfg.min_notional_usdc:
            return False, f"notional {d.notional:.2f} < exchange min {self.cfg.min_notional_usdc}"
        if d.notional > self.cfg.max_order_usdc:
            return False, f"notional {d.notional:.2f} > MAX_ORDER_USDC {self.cfg.max_order_usdc}"

        if d.side is Side.BUY:
            pending_buy = sum(p.notional for p in pending if p.side is Side.BUY)
            pos_cost = portfolio.position(d.token_id).cost
            same_market_open = sum(
                o.price * o.remaining
                for o in open_orders
                if o.token_id == d.token_id and o.side is Side.BUY
            )
            same_market_pending = sum(
                p.notional for p in pending if p.side is Side.BUY and p.token_id == d.token_id
            )
            if pos_cost + same_market_open + same_market_pending + d.notional > self.cfg.max_position_usdc:
                return False, (
                    f"market exposure {pos_cost + same_market_open + same_market_pending + d.notional:.2f} "
                    f"> MAX_POSITION_USDC {self.cfg.max_position_usdc}"
                )
            total = portfolio.total_exposure(open_orders) + pending_buy + d.notional
            if total > self.cfg.max_total_usdc:
                return False, f"total exposure {total:.2f} > MAX_TOTAL_USDC {self.cfg.max_total_usdc}"
        else:
            pending_sells = sum(
                p.size for p in pending if p.side is Side.SELL and p.token_id == d.token_id
            )
            open_sells = sum(
                o.remaining
                for o in open_orders
                if o.token_id == d.token_id and o.side is Side.SELL
            )
            held = portfolio.shares(d.token_id)
            if d.size + pending_sells + open_sells > held + 1e-9:
                return False, (
                    f"sell {d.size:.2f} + resting {open_sells + pending_sells:.2f} "
                    f"exceeds held {held:.2f}"
                )
        return True, ""
