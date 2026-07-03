import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from bot.config import Config
from bot.models import BookLevel, OrderBook


@pytest.fixture
def cfg(monkeypatch):
    for var in (
        "MODE", "STRATEGY", "MARKETS", "FAIR_VALUES", "PRIVATE_KEY",
        "MAX_ORDER_USDC", "MAX_POSITION_USDC", "MAX_TOTAL_USDC",
    ):
        monkeypatch.delenv(var, raising=False)
    c = Config()
    c.min_size_shares = 1.0
    c.min_notional_usdc = 0.1
    return c


def make_book(token="tok", bids=((0.48, 100),), asks=((0.52, 100),)):
    return OrderBook(
        token_id=token,
        bids=[BookLevel(p, s) for p, s in bids],
        asks=[BookLevel(p, s) for p, s in asks],
    )
