"""Main loop: fetch books -> settle fills -> risk checks -> reconcile orders.

Strategies declare the orders they want resting; the engine diffs that against
reality and issues the minimal set of cancels and placements. On any exit
(clean or crash) it cancels every resting order so nothing trades unattended.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .config import Config
from .execution.base import Broker
from .marketdata import RestMarketData
from .models import DesiredOrder, Order
from .portfolio import Portfolio
from .risk import RiskEngine
from .strategies import Strategy

log = logging.getLogger("polybot.engine")


def match_desired(
    open_orders: list[Order], desired: list[DesiredOrder], ticks: dict[str, float]
) -> tuple[list[Order], list[DesiredOrder]]:
    """Diff resting orders against desired state.

    Returns (to_cancel, to_place). An open order survives if some desired
    order matches it on token, side, price (within half a tick) and size
    (within 10% or one share). Everything else is canceled; unmatched desired
    orders are placed."""
    unmatched = list(desired)
    keep_ids: set[str] = set()
    for o in open_orders:
        tick = ticks.get(o.token_id, 0.01)
        for d in unmatched:
            if (
                d.token_id == o.token_id
                and d.side == o.side
                and abs(d.price - o.price) <= tick / 2 + 1e-9
                and abs(d.size - o.remaining) <= max(0.10 * d.size, 1.0)
            ):
                keep_ids.add(o.id)
                unmatched.remove(d)
                break
    to_cancel = [o for o in open_orders if o.id not in keep_ids]
    return to_cancel, unmatched


class Engine:
    def __init__(
        self,
        cfg: Config,
        broker: Broker,
        marketdata: RestMarketData,
        strategy: Strategy,
        portfolio: Portfolio | None = None,
    ):
        self.cfg = cfg
        self.broker = broker
        self.md = marketdata
        self.strategy = strategy
        self.portfolio = portfolio or Portfolio()
        self.risk = RiskEngine(cfg)
        self._stopping = False
        self._tokens = sorted({t for m in cfg.markets for t in m.all_tokens()})

    # ---------- one tick ----------

    def step(self) -> None:
        books = {}
        for tok in self._tokens:
            book = self.md.get_book(tok)
            if book is not None:
                books[tok] = book
        if not books:
            log.warning("no orderbooks fetched this tick")
            return

        # settle simulated fills (no-op live), then absorb fills into the portfolio
        self.broker.on_books(books)
        for fill in self.broker.poll_fills():
            self.portfolio.apply_fill(fill)
            log.info(
                "FILL %s %s %.2f @ %.3f | realized=%.2f",
                fill.side.value, fill.token_id[:10], fill.size, fill.price,
                self.portfolio.realized_pnl,
            )

        marks = {tok: b.mid for tok, b in books.items() if b.mid is not None}

        # kill switch on equity drawdown (paper: exact; live: cash unknown -> skipped)
        equity = None
        if self.broker.cash() is not None:
            equity = self.broker.cash() + self.portfolio.position_value(marks)
        if not self.risk.check_drawdown(equity):
            log.error("halted — canceling all orders and stopping")
            self.broker.cancel_all()
            self._stopping = True
            return

        try:
            open_orders = self.broker.open_orders()
        except Exception:
            log.warning("open-order state unknown; skipping tick rather than double-quote")
            return

        ticks = {tok: self.md.get_tick_size(tok) for tok in books}
        from .strategies.base import TickContext

        ctx = TickContext(
            books=books,
            portfolio=self.portfolio,
            markets=self.cfg.markets,
            ticks=ticks,
            cash=self.broker.cash(),
        )
        desired = self.strategy.desired_orders(ctx)

        # risk-filter the batch (later orders see earlier approvals as pending)
        approved: list[DesiredOrder] = []
        for d in desired:
            ok, why = self.risk.validate(d, self.portfolio, open_orders, approved)
            if ok:
                approved.append(d)
            else:
                log.debug("risk reject %s %s: %s", d.side.value, d.token_id[:10], why)

        to_cancel, to_place = match_desired(open_orders, approved, ticks)
        for o in to_cancel:
            self.broker.cancel(o.id)
        for d in to_place:
            self.broker.place(d)

        self._log_status(marks, open_orders, equity)

    def _log_status(self, marks, open_orders, equity) -> None:
        pos = {
            t[:10]: round(p.shares, 2)
            for t, p in self.portfolio.positions.items()
            if abs(p.shares) > 1e-9
        }
        log.info(
            "tick | equity=%s realized=%.2f unrealized=%.2f exposure=%.2f open=%d pos=%s",
            f"{equity:.2f}" if equity is not None else "n/a",
            self.portfolio.realized_pnl,
            self.portfolio.unrealized_pnl(marks),
            self.portfolio.total_exposure(open_orders),
            len(open_orders),
            pos or "{}",
        )

    # ---------- lifecycle ----------

    def run(self) -> None:
        self._load_state()
        log.info(
            "starting mode=%s strategy=%s markets=%d poll=%.1fs",
            self.cfg.mode, self.strategy.name, len(self.cfg.markets), self.cfg.poll_interval,
        )
        try:
            while not self._stopping:
                started = time.time()
                try:
                    self.step()
                except Exception:
                    log.exception("tick failed")
                self._save_state()
                remaining = self.cfg.poll_interval - (time.time() - started)
                while remaining > 0 and not self._stopping:
                    time.sleep(min(remaining, 0.5))
                    remaining -= 0.5
        finally:
            log.info("shutting down: canceling all resting orders")
            self.broker.cancel_all()
            self._save_state()
            log.info("stopped | realized_pnl=%.2f", self.portfolio.realized_pnl)

    def stop(self, *_args) -> None:
        self._stopping = True

    # ---------- persistence ----------

    def _save_state(self) -> None:
        state = {"portfolio": self.portfolio.to_dict()}
        if hasattr(self.broker, "to_dict"):
            state["broker"] = self.broker.to_dict()
        path = Path(self.cfg.state_file)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, path)

    def _load_state(self) -> None:
        path = Path(self.cfg.state_file)
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log.warning("could not load %s: %s", path, e)
            return
        if "portfolio" in state:
            self.portfolio = Portfolio.from_dict(state["portfolio"])
        if "broker" in state and hasattr(self.broker, "restore"):
            self.broker.restore(state["broker"])
        log.info("restored state from %s", path)
