import logging
import signal
import sys

from .config import Config
from .engine import Engine
from .marketdata import RestMarketData
from .strategies import build


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    cfg = Config()
    cfg.validate()

    md = RestMarketData(cfg.clob_host)
    if cfg.mode == "live":
        from .execution.live import LiveBroker

        broker = LiveBroker(cfg, md)
    else:
        from .execution.paper import PaperBroker

        broker = PaperBroker(cfg.paper_cash, order_ttl_sec=cfg.order_ttl_sec)

    engine = Engine(cfg, broker, md, build(cfg.strategy, cfg))
    signal.signal(signal.SIGINT, engine.stop)
    signal.signal(signal.SIGTERM, engine.stop)
    engine.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
