from dataclasses import dataclass
from typing import Literal

Side = Literal["BUY", "SELL"]


@dataclass
class Signal:
    token_id: str
    side: Side
    price: float
    size: float
    reason: str


def mean_reversion(token_id: str, mid: float, lower: float, upper: float, size: float) -> Signal | None:
    if mid <= lower:
        return Signal(token_id, "BUY", round(mid, 3), size, f"mid {mid:.3f} <= lower {lower:.3f}")
    if mid >= upper:
        return Signal(token_id, "SELL", round(mid, 3), size, f"mid {mid:.3f} >= upper {upper:.3f}")
    return None


def market_make(token_id: str, best_bid: float, best_ask: float, spread: float, size: float) -> list[Signal]:
    mid = (best_bid + best_ask) / 2
    bid_px = max(0.01, round(mid - spread / 2, 3))
    ask_px = min(0.99, round(mid + spread / 2, 3))
    return [
        Signal(token_id, "BUY", bid_px, size, f"MM bid around mid {mid:.3f}"),
        Signal(token_id, "SELL", ask_px, size, f"MM ask around mid {mid:.3f}"),
    ]
