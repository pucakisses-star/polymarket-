"""Inventory-aware market maker.

Thesis: earn the spread on two-sided flow while staying near-flat. The three
defenses this has that a naive quoter lacks:

1. Inventory skew — as we accumulate shares, both quotes shift down (and vice
   versa when short of our target), so the market pays us to mean-revert our
   inventory instead of letting it grow.
2. Quote pull — if the observed book spread blows out past MM_MAX_BOOK_SPREAD
   (news, chaos, or a dead market), we stop quoting entirely rather than be
   the stale quote that informed flow picks off.
3. Spread floor — we never quote tighter than MM_MIN_HALF_SPREAD from the
   (skewed) mid, so we don't compete to zero with other makers.

Still a *slow* market maker (REST polling). Suitable for quiet markets and for
learning; a fast mover will still beat it to the punch on news.
"""

from __future__ import annotations

import logging

from ..models import DesiredOrder, Side, round_to_tick
from .base import Strategy, TickContext

log = logging.getLogger("polybot.mm")


class MarketMaker(Strategy):
    name = "market_maker"

    def __init__(self, cfg):
        self.quote_size = cfg.mm_quote_size
        self.min_half_spread = cfg.mm_min_half_spread
        self.max_book_spread = cfg.mm_max_book_spread
        self.inventory_limit = cfg.mm_inventory_limit
        self.skew_intensity = cfg.mm_skew_intensity

    def desired_orders(self, ctx: TickContext) -> list[DesiredOrder]:
        out: list[DesiredOrder] = []
        for spec in ctx.markets:
            token = spec.token_id
            book = ctx.books.get(token)
            if book is None or book.mid is None:
                continue
            if book.spread > self.max_book_spread:
                log.debug("pull quotes on %s: spread %.3f too wide", token[:10], book.spread)
                continue

            tick = ctx.tick(token)
            inv = ctx.portfolio.shares(token)
            inv_ratio = max(-1.0, min(1.0, inv / self.inventory_limit))

            half = max(self.min_half_spread, book.spread / 2)
            center = book.mid - inv_ratio * self.skew_intensity * half

            bid_px = round_to_tick(center - half, tick, Side.BUY)
            ask_px = round_to_tick(center + half, tick, Side.SELL)
            if bid_px >= ask_px:  # degenerate after rounding/clamping
                continue

            # Buy only while under the inventory cap
            buy_room = self.inventory_limit - inv
            buy_size = min(self.quote_size, max(buy_room, 0.0))
            if buy_size > 0:
                out.append(DesiredOrder(token, Side.BUY, bid_px, round(buy_size, 2), "mm bid"))

            # Sell only what we hold
            sell_size = min(self.quote_size, inv)
            if sell_size > 0:
                out.append(DesiredOrder(token, Side.SELL, ask_px, round(sell_size, 2), "mm ask"))
        return out
