"""Fair-value taker.

Thesis: *you* supply an independent probability estimate for each market
(FAIR_VALUES). The bot only trades when the market price disagrees with your
estimate by more than FV_MIN_EDGE — buying below fair value, exiting above it.
The edge is your forecast; the bot only handles disciplined execution:

- It never chases: orders are marketable limits at the current best quote,
  sized no larger than the displayed depth (no slippage past the top level).
- Position sizing is fractional Kelly on your stated edge, capped by the risk
  engine's per-order/per-market/total limits.
- No estimate, no trade.

If your probabilities are no better than the market's, this loses (slowly, by
spread). That honesty is the point — the bot cannot conjure a forecast for you.
"""

from __future__ import annotations

import logging

from ..models import DesiredOrder, Side
from .base import Strategy, TickContext

log = logging.getLogger("polybot.fv")


class FairValue(Strategy):
    name = "fair_value"

    def __init__(self, cfg):
        self.fair_values: dict[str, float] = cfg.fair_values
        self.min_edge = cfg.fv_min_edge
        self.kelly_fraction = cfg.fv_kelly_fraction
        self.bankroll = cfg.fv_bankroll
        self.min_size = cfg.min_size_shares

    def _kelly_shares(self, fv: float, price: float, bankroll: float) -> float:
        """Full-Kelly fraction for a binary payout bought at `price` with
        believed win probability `fv` is (fv - price) / (1 - price)."""
        if price >= 1 or price <= 0:
            return 0.0
        f_star = (fv - price) / (1 - price)
        stake = max(f_star, 0.0) * self.kelly_fraction * bankroll
        return stake / price

    def desired_orders(self, ctx: TickContext) -> list[DesiredOrder]:
        out: list[DesiredOrder] = []
        bankroll = ctx.cash if ctx.cash is not None else self.bankroll
        for spec in ctx.markets:
            token = spec.token_id
            fv = self.fair_values.get(token)
            book = ctx.books.get(token)
            if fv is None or book is None:
                continue

            ask = book.best_ask
            if ask is not None and fv - ask.price >= self.min_edge:
                shares = min(self._kelly_shares(fv, ask.price, bankroll), ask.size)
                if shares >= self.min_size:
                    out.append(DesiredOrder(
                        token, Side.BUY, ask.price, round(shares, 2),
                        f"fv {fv:.2f} vs ask {ask.price:.3f} (edge {fv - ask.price:.3f})",
                    ))

            bid = book.best_bid
            held = ctx.portfolio.shares(token)
            if bid is not None and held > 0 and bid.price - fv >= self.min_edge:
                shares = min(held, bid.size)
                if shares >= self.min_size:
                    out.append(DesiredOrder(
                        token, Side.SELL, bid.price, round(shares, 2),
                        f"exit: bid {bid.price:.3f} above fv {fv:.2f}",
                    ))
        return out
