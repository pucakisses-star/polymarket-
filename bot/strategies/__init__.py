from .base import Strategy, TickContext
from .complement_arb import ComplementArb
from .fair_value import FairValue
from .market_maker import MarketMaker


def build(name: str, cfg) -> Strategy:
    if name == "market_maker":
        return MarketMaker(cfg)
    if name == "fair_value":
        return FairValue(cfg)
    if name == "complement_arb":
        return ComplementArb(cfg)
    raise ValueError(f"unknown strategy {name!r}")


__all__ = ["Strategy", "TickContext", "MarketMaker", "FairValue", "ComplementArb", "build"]
