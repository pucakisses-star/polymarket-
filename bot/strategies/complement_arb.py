"""Complement arbitrage.

Thesis: in a binary market, one YES share plus one NO share always redeems for
exactly $1 at resolution. If best_ask(YES) + best_ask(NO) < 1 - ARB_MIN_EDGE,
buying both legs locks in a riskless profit of (1 - combined cost) per pair,
regardless of the outcome.

This is real, model-free edge — but it is rare and competed-for. Opportunities
appear briefly in volatile or illiquid markets and are usually taken within
seconds. Expect this strategy to sit idle most of the time; that is correct
behavior, not a bug. Positions are held to resolution (redeem via the
Polymarket UI or the CTF contract; the bot does not auto-redeem).

Execution notes: both legs are marketable limits at the current best ask,
sized to the *smaller* leg's displayed depth so we never end up with a large
unhedged remainder. Legged risk (one side fills, the other misses) still
exists live; the residual is an ordinary directional position the risk engine
already caps.
"""

from __future__ import annotations

import logging

from ..models import DesiredOrder, Side
from .base import Strategy, TickContext

log = logging.getLogger("polybot.arb")


class ComplementArb(Strategy):
    name = "complement_arb"

    def __init__(self, cfg):
        self.min_edge = cfg.arb_min_edge
        self.max_order_usdc = cfg.max_order_usdc
        self.min_size = cfg.min_size_shares

    def desired_orders(self, ctx: TickContext) -> list[DesiredOrder]:
        out: list[DesiredOrder] = []
        for spec in ctx.markets:
            if not spec.complement_id:
                continue
            yes_book = ctx.books.get(spec.token_id)
            no_book = ctx.books.get(spec.complement_id)
            if yes_book is None or no_book is None:
                continue
            yes_ask, no_ask = yes_book.best_ask, no_book.best_ask
            if yes_ask is None or no_ask is None:
                continue

            combined = yes_ask.price + no_ask.price
            edge = 1.0 - combined
            if edge < self.min_edge:
                continue

            # equal shares on both legs; bounded by both depths and per-order cap
            shares = min(
                yes_ask.size,
                no_ask.size,
                self.max_order_usdc / max(yes_ask.price, 1e-9),
                self.max_order_usdc / max(no_ask.price, 1e-9),
            )
            shares = round(shares, 2)
            if shares < self.min_size:
                continue

            log.info(
                "ARB: YES %.3f + NO %.3f = %.3f, edge %.3f, %g shares",
                yes_ask.price, no_ask.price, combined, edge, shares,
            )
            reason = f"arb edge {edge:.3f} ({combined:.3f} < 1)"
            out.append(DesiredOrder(spec.token_id, Side.BUY, yes_ask.price, shares, reason))
            out.append(DesiredOrder(spec.complement_id, Side.BUY, no_ask.price, shares, reason))
        return out
