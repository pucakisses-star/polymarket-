"""Live broker: thin wrapper over py-clob-client with tick rounding and
exchange-minimum checks. Imported lazily so paper mode never needs the SDK."""

from __future__ import annotations

import logging

from ..config import Config
from ..marketdata import RestMarketData
from ..models import DesiredOrder, Fill, Order, Side, round_to_tick
from .base import Broker

log = logging.getLogger("polybot.live")


class LiveBroker(Broker):
    def __init__(self, cfg: Config, marketdata: RestMarketData):
        from py_clob_client.client import ClobClient

        self.cfg = cfg
        self.md = marketdata
        kwargs = dict(
            host=cfg.clob_host,
            key=cfg.private_key,
            chain_id=cfg.chain_id,
            signature_type=cfg.signature_type,
        )
        if cfg.funder_address:
            kwargs["funder"] = cfg.funder_address
        self.client = ClobClient(**kwargs)
        self.client.set_api_creds(self.client.create_or_derive_api_creds())
        self._seen_trade_ids: set[str] = set()
        self._primed = False

    # ---------- Broker interface ----------

    def place(self, d: DesiredOrder) -> Order | None:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        tick = self.md.get_tick_size(d.token_id)
        price = round_to_tick(d.price, tick, d.side)
        size = round(d.size, 2)
        if size < self.cfg.min_size_shares or price * size < self.cfg.min_notional_usdc:
            log.info("skip below exchange minimums: %.2f @ %.3f", size, price)
            return None
        args = OrderArgs(
            price=price,
            size=size,
            side=BUY if d.side is Side.BUY else SELL,
            token_id=d.token_id,
        )
        try:
            signed = self.client.create_order(args)
            resp = self.client.post_order(signed, OrderType.GTC)
        except Exception as e:
            log.error("post_order failed (%s %.2f @ %.3f): %s", d.side.value, size, price, e)
            return None
        order_id = (resp or {}).get("orderID", "")
        if not order_id:
            log.error("post_order gave no orderID: %s", resp)
            return None
        log.info("LIVE placed %s %s %.2f @ %.3f id=%s", d.side.value, d.token_id[:10], size, price, order_id[:12])
        return Order(id=order_id, token_id=d.token_id, side=d.side, price=price, size=size)

    def cancel(self, order_id: str) -> None:
        try:
            self.client.cancel(order_id)
        except Exception as e:
            log.error("cancel(%s) failed: %s", order_id[:12], e)

    def cancel_all(self) -> None:
        try:
            self.client.cancel_all()
            log.info("LIVE canceled all resting orders")
        except Exception as e:
            log.error("cancel_all failed: %s", e)

    def open_orders(self) -> list[Order]:
        try:
            raw = self.client.get_orders() or []
        except Exception as e:
            log.error("get_orders failed: %s", e)
            raise  # engine must not treat unknown state as "no orders"
        out = []
        for o in raw:
            try:
                size = float(o["original_size"])
                out.append(
                    Order(
                        id=o["id"],
                        token_id=o["asset_id"],
                        side=Side(o["side"].upper()),
                        price=float(o["price"]),
                        size=size,
                        filled=float(o.get("size_matched", 0)),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                log.warning("unparseable order %s: %s", o, e)
        return out

    def poll_fills(self) -> list[Fill]:
        try:
            trades = self.client.get_trades() or []
        except Exception as e:
            log.error("get_trades failed: %s", e)
            return []
        fills: list[Fill] = []
        for t in trades:
            tid = t.get("id")
            if not tid or tid in self._seen_trade_ids:
                continue
            self._seen_trade_ids.add(tid)
            if not self._primed:
                continue  # trades from before this session
            try:
                fills.append(
                    Fill(
                        order_id=t.get("taker_order_id", ""),
                        token_id=t["asset_id"],
                        side=Side(t["side"].upper()),
                        price=float(t["price"]),
                        size=float(t["size"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                log.warning("unparseable trade %s: %s", t, e)
        if not self._primed:
            self._primed = True
            log.info("primed trade history (%d prior trades ignored)", len(self._seen_trade_ids))
        return fills
