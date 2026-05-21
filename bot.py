import logging
import signal
import sys
import time

from config import Config
from paper import PaperBroker
from strategy import Signal, market_make, mean_reversion

log = logging.getLogger("polybot")


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._stopping = False
        self.paper: PaperBroker | None = None
        self.client = None
        if cfg.paper_trading:
            self.paper = PaperBroker(cfg.clob_host, cfg.paper_starting_cash, cfg.paper_state_file)
        else:
            self.client = self._build_live_client()

    def _build_live_client(self):
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        kwargs = dict(
            host=self.cfg.clob_host,
            key=self.cfg.private_key,
            chain_id=self.cfg.chain_id,
            signature_type=self.cfg.signature_type,
        )
        if self.cfg.funder_address:
            kwargs["funder"] = self.cfg.funder_address
        client = ClobClient(**kwargs)
        creds: ApiCreds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        return client

    def _book(self, token_id: str) -> tuple[float, float] | None:
        if self.paper:
            return self.paper.get_book(token_id)
        try:
            book = self.client.get_order_book(token_id)
        except Exception as e:
            log.warning("get_order_book(%s) failed: %s", token_id, e)
            return None
        if not book.bids or not book.asks:
            return None
        return float(book.bids[-1].price), float(book.asks[-1].price)

    def _open_exposure_usdc(self) -> float:
        if self.paper:
            return self.paper.open_exposure_usdc()
        try:
            orders = self.client.get_orders()
        except Exception as e:
            log.warning("get_orders failed: %s", e)
            return 0.0
        total = 0.0
        for o in orders or []:
            try:
                px = float(o.get("price", 0))
                sz = float(o.get("original_size", o.get("size", 0)))
                rem = float(o.get("size_matched", 0))
                total += px * max(sz - rem, 0)
            except (TypeError, ValueError):
                continue
        return total

    def _signals_for(self, token_id: str, best_bid: float, best_ask: float) -> list[Signal]:
        mid = (best_bid + best_ask) / 2
        if self.cfg.strategy == "mean_reversion":
            sig = mean_reversion(
                token_id, mid, self.cfg.mr_lower, self.cfg.mr_upper,
                size=min(self.cfg.mm_size, self.cfg.max_order_usdc / max(mid, 0.01)),
            )
            return [sig] if sig else []
        if self.cfg.strategy == "market_make":
            return market_make(token_id, best_bid, best_ask, self.cfg.mm_spread, self.cfg.mm_size)
        return []

    def _place(self, sig: Signal) -> None:
        notional = sig.price * sig.size
        if notional > self.cfg.max_order_usdc:
            log.info("skip %s: notional %.2f > MAX_ORDER_USDC %.2f", sig.token_id, notional, self.cfg.max_order_usdc)
            return

        if self.paper:
            self.paper.place(sig.token_id, sig.side, sig.price, sig.size)
            return

        if self.cfg.dry_run:
            log.info("[DRY] %s %s sz=%.2f px=%.3f (%s)", sig.side, sig.token_id[:10], sig.size, sig.price, sig.reason)
            return

        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL
        side = BUY if sig.side == "BUY" else SELL
        args = OrderArgs(price=sig.price, size=sig.size, side=side, token_id=sig.token_id)
        try:
            signed = self.client.create_order(args)
            resp = self.client.post_order(signed, OrderType.GTC)
            log.info("LIVE %s %s sz=%.2f px=%.3f -> %s", sig.side, sig.token_id[:10], sig.size, sig.price, resp)
        except Exception as e:
            log.error("post_order failed for %s: %s", sig.token_id, e)

    def step(self) -> None:
        exposure = self._open_exposure_usdc()
        if exposure >= self.cfg.max_total_usdc:
            log.info("exposure %.2f >= MAX_TOTAL_USDC %.2f, holding", exposure, self.cfg.max_total_usdc)
            return
        marks: dict[str, float] = {}
        for token_id in self.cfg.markets:
            snap = self._book(token_id)
            if snap is None:
                continue
            best_bid, best_ask = snap
            marks[token_id] = (best_bid + best_ask) / 2
            if self.paper:
                self.paper.settle(token_id, best_bid, best_ask)
            for sig in self._signals_for(token_id, best_bid, best_ask):
                self._place(sig)
        if self.paper and marks:
            log.info("paper %s", self.paper.summary(marks))

    def run(self) -> None:
        mode = "PAPER" if self.paper else ("DRY" if self.cfg.dry_run else "LIVE")
        log.info("starting mode=%s strategy=%s markets=%d", mode, self.cfg.strategy, len(self.cfg.markets))
        while not self._stopping:
            try:
                self.step()
            except Exception:
                log.exception("step failed")
            for _ in range(self.cfg.poll_interval):
                if self._stopping:
                    break
                time.sleep(1)
        log.info("stopped")

    def stop(self, *_args) -> None:
        self._stopping = True


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    cfg = Config()
    cfg.validate()
    bot = Bot(cfg)
    signal.signal(signal.SIGINT, bot.stop)
    signal.signal(signal.SIGTERM, bot.stop)
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
