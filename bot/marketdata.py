"""Market data via the public CLOB REST endpoints (no auth needed)."""

from __future__ import annotations

import logging

import requests

from .models import OrderBook

log = logging.getLogger("polybot.md")

DEFAULT_TICK = 0.01


class RestMarketData:
    def __init__(self, clob_host: str, timeout: float = 10.0):
        self.host = clob_host.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self._tick_cache: dict[str, float] = {}

    def get_book(self, token_id: str) -> OrderBook | None:
        try:
            r = self.session.get(
                f"{self.host}/book", params={"token_id": token_id}, timeout=self.timeout
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("get_book(%s…) failed: %s", token_id[:12], e)
            return None
        return OrderBook.from_raw(token_id, data.get("bids"), data.get("asks"))

    def get_tick_size(self, token_id: str) -> float:
        if token_id in self._tick_cache:
            return self._tick_cache[token_id]
        tick = DEFAULT_TICK
        try:
            r = self.session.get(
                f"{self.host}/tick-size", params={"token_id": token_id}, timeout=self.timeout
            )
            r.raise_for_status()
            tick = float(r.json().get("minimum_tick_size", DEFAULT_TICK))
        except Exception as e:
            log.warning("get_tick_size(%s…) failed, assuming %s: %s", token_id[:12], DEFAULT_TICK, e)
        self._tick_cache[token_id] = tick
        return tick
