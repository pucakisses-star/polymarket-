import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass
class Config:
    private_key: str = field(default_factory=lambda: os.getenv("PRIVATE_KEY", ""))
    clob_host: str = field(default_factory=lambda: os.getenv("CLOB_HOST", "https://clob.polymarket.com"))
    chain_id: int = field(default_factory=lambda: _int("CHAIN_ID", 137))
    signature_type: int = field(default_factory=lambda: _int("SIGNATURE_TYPE", 0))
    funder_address: str = field(default_factory=lambda: os.getenv("FUNDER_ADDRESS", ""))

    strategy: str = field(default_factory=lambda: os.getenv("STRATEGY", "mean_reversion"))
    markets: list[str] = field(default_factory=lambda: _list("MARKETS"))

    max_order_usdc: float = field(default_factory=lambda: _float("MAX_ORDER_USDC", 5.0))
    max_total_usdc: float = field(default_factory=lambda: _float("MAX_TOTAL_USDC", 50.0))
    poll_interval: int = field(default_factory=lambda: _int("POLL_INTERVAL", 30))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))

    mr_lower: float = field(default_factory=lambda: _float("MR_LOWER", 0.40))
    mr_upper: float = field(default_factory=lambda: _float("MR_UPPER", 0.60))

    mm_spread: float = field(default_factory=lambda: _float("MM_SPREAD", 0.02))
    mm_size: float = field(default_factory=lambda: _float("MM_SIZE", 5.0))

    def validate(self) -> None:
        if not self.private_key:
            raise RuntimeError("PRIVATE_KEY is required (set it in .env)")
        if not self.markets:
            raise RuntimeError("MARKETS is required (comma-separated token_ids)")
        if self.strategy not in ("mean_reversion", "market_make", "manual"):
            raise RuntimeError(f"Unknown STRATEGY: {self.strategy}")
        if not 0 < self.mr_lower < self.mr_upper < 1:
            raise RuntimeError("Need 0 < MR_LOWER < MR_UPPER < 1")
