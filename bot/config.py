import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from .models import MarketSpec

load_dotenv()

STRATEGIES = ("market_maker", "fair_value", "complement_arb")
MODES = ("paper", "live")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _markets(name: str) -> list[MarketSpec]:
    raw = os.getenv(name, "")
    return [MarketSpec.parse(s) for s in raw.split(",") if s.strip()]


def _fair_values(name: str) -> dict[str, float]:
    """FAIR_VALUES="tokenid=0.45,tokenid2=0.62" -> {tokenid: 0.45, ...}"""
    raw = os.getenv(name, "")
    out: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tok, _, val = pair.partition("=")
        if not tok or not val:
            raise ValueError(f"bad FAIR_VALUES entry: {pair!r} (want token=prob)")
        out[tok.strip()] = float(val)
    return out


@dataclass
class Config:
    # mode / connection
    mode: str = field(default_factory=lambda: os.getenv("MODE", "paper").strip().lower())
    clob_host: str = field(default_factory=lambda: os.getenv("CLOB_HOST", "https://clob.polymarket.com"))
    chain_id: int = field(default_factory=lambda: _int("CHAIN_ID", 137))
    private_key: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY", ""))
    signature_type: int = field(default_factory=lambda: _int("SIGNATURE_TYPE", 0))
    funder_address: str = field(default_factory=lambda: os.getenv("FUNDER_ADDRESS", ""))
    ack_live_risk: bool = field(default_factory=lambda: _bool("ACK_LIVE_RISK", False))

    # what to trade
    strategy: str = field(default_factory=lambda: os.getenv("STRATEGY", "market_maker").strip())
    markets: list[MarketSpec] = field(default_factory=lambda: _markets("MARKETS"))

    # engine
    poll_interval: float = field(default_factory=lambda: _float("POLL_INTERVAL", 5.0))
    state_file: str = field(default_factory=lambda: os.getenv("STATE_FILE", "bot_state.json"))

    # risk limits
    max_order_usdc: float = field(default_factory=lambda: _float("MAX_ORDER_USDC", 10.0))
    max_position_usdc: float = field(default_factory=lambda: _float("MAX_POSITION_USDC", 25.0))
    max_total_usdc: float = field(default_factory=lambda: _float("MAX_TOTAL_USDC", 100.0))
    max_drawdown_pct: float = field(default_factory=lambda: _float("MAX_DRAWDOWN_PCT", 10.0))

    # exchange minimums (Polymarket enforces minimum order sizes)
    min_size_shares: float = field(default_factory=lambda: _float("MIN_SIZE_SHARES", 5.0))
    min_notional_usdc: float = field(default_factory=lambda: _float("MIN_NOTIONAL_USDC", 1.0))

    # paper account
    paper_cash: float = field(default_factory=lambda: _float("PAPER_CASH", 1000.0))
    order_ttl_sec: float = field(default_factory=lambda: _float("ORDER_TTL_SEC", 300.0))

    # market_maker params
    mm_quote_size: float = field(default_factory=lambda: _float("MM_QUOTE_SIZE", 10.0))
    mm_min_half_spread: float = field(default_factory=lambda: _float("MM_MIN_HALF_SPREAD", 0.01))
    mm_max_book_spread: float = field(default_factory=lambda: _float("MM_MAX_BOOK_SPREAD", 0.10))
    mm_inventory_limit: float = field(default_factory=lambda: _float("MM_INVENTORY_LIMIT", 50.0))
    mm_skew_intensity: float = field(default_factory=lambda: _float("MM_SKEW_INTENSITY", 1.0))

    # fair_value params
    fair_values: dict[str, float] = field(default_factory=lambda: _fair_values("FAIR_VALUES"))
    fv_min_edge: float = field(default_factory=lambda: _float("FV_MIN_EDGE", 0.05))
    fv_kelly_fraction: float = field(default_factory=lambda: _float("FV_KELLY_FRACTION", 0.25))
    fv_bankroll: float = field(default_factory=lambda: _float("FV_BANKROLL", 100.0))

    # complement_arb params
    arb_min_edge: float = field(default_factory=lambda: _float("ARB_MIN_EDGE", 0.01))

    def validate(self) -> None:
        if self.mode not in MODES:
            raise RuntimeError(f"MODE must be one of {MODES}, got {self.mode!r}")
        if self.strategy not in STRATEGIES:
            raise RuntimeError(f"STRATEGY must be one of {STRATEGIES}, got {self.strategy!r}")
        if not self.markets:
            raise RuntimeError(
                "MARKETS is required. Find token ids with: python -m bot.discover <search terms>"
            )
        if self.mode == "live":
            if not self.private_key:
                raise RuntimeError("PRIVATE_KEY is required for MODE=live")
            if not self.ack_live_risk:
                raise RuntimeError(
                    "MODE=live places real orders with real money. "
                    "Set ACK_LIVE_RISK=true to confirm you understand."
                )
        if self.strategy == "complement_arb":
            missing = [m.token_id for m in self.markets if not m.complement_id]
            if missing:
                raise RuntimeError(
                    "complement_arb needs yes:no token pairs in MARKETS; "
                    f"missing complement for: {', '.join(t[:16] for t in missing)}"
                )
        if self.strategy == "fair_value":
            missing = [m.token_id for m in self.markets if m.token_id not in self.fair_values]
            if missing:
                raise RuntimeError(
                    "fair_value needs a FAIR_VALUES entry for every market; "
                    f"missing: {', '.join(t[:16] for t in missing)}"
                )
        for fv in self.fair_values.values():
            if not 0.0 < fv < 1.0:
                raise RuntimeError(f"fair values must be probabilities in (0,1), got {fv}")
        if not 0 < self.max_drawdown_pct <= 100:
            raise RuntimeError("MAX_DRAWDOWN_PCT must be in (0, 100]")
