from bot.engine import Engine, match_desired
from bot.execution.paper import PaperBroker
from bot.models import DesiredOrder, MarketSpec, Order, Side
from bot.strategies.base import Strategy, TickContext

from conftest import make_book


def test_match_keeps_equivalent_orders():
    open_orders = [Order(id="a", token_id="tok", side=Side.BUY, price=0.50, size=10)]
    desired = [DesiredOrder("tok", Side.BUY, 0.50, 10)]
    cancels, places = match_desired(open_orders, desired, {"tok": 0.01})
    assert cancels == [] and places == []


def test_match_replaces_moved_price():
    open_orders = [Order(id="a", token_id="tok", side=Side.BUY, price=0.50, size=10)]
    desired = [DesiredOrder("tok", Side.BUY, 0.45, 10)]
    cancels, places = match_desired(open_orders, desired, {"tok": 0.01})
    assert [o.id for o in cancels] == ["a"]
    assert places == desired


def test_match_cancels_unwanted_and_tolerates_partial_fill():
    stale = Order(id="a", token_id="tok", side=Side.SELL, price=0.60, size=10)
    partially_filled = Order(id="b", token_id="tok", side=Side.BUY, price=0.50, size=10, filled=0.5)
    open_orders = [stale, partially_filled]
    desired = [DesiredOrder("tok", Side.BUY, 0.50, 10)]  # within 10% of 9.5 remaining
    cancels, places = match_desired(open_orders, desired, {"tok": 0.01})
    assert [o.id for o in cancels] == ["a"]
    assert places == []


class FakeMD:
    def __init__(self, books):
        self.books = books

    def get_book(self, token_id):
        return self.books.get(token_id)

    def get_tick_size(self, token_id):
        return 0.01


class OneShotBuyer(Strategy):
    name = "test"

    def desired_orders(self, ctx: TickContext):
        return [DesiredOrder("tok", Side.BUY, 0.52, 10, "test")]


def make_engine(cfg, books, strategy=None, cash=100.0):
    cfg.markets = [MarketSpec("tok")]
    cfg.state_file = "/dev/null"
    broker = PaperBroker(starting_cash=cash)
    engine = Engine(cfg, broker, FakeMD(books), strategy or OneShotBuyer())
    return engine, broker


def test_engine_places_fills_and_tracks_position(cfg, tmp_path):
    books = {"tok": make_book("tok", asks=((0.52, 100),))}
    engine, broker = make_engine(cfg, books)
    engine.cfg.state_file = str(tmp_path / "state.json")
    engine.step()  # places the buy
    assert len(broker.open_orders()) == 1
    engine.step()  # simulator matches against the ask at 0.52
    assert engine.portfolio.shares("tok") == 10
    # desired size 10 vs held -> strategy still wants a resting buy; risk caps apply upstream


def test_engine_kill_switch_cancels_everything(cfg, tmp_path):
    cfg.max_drawdown_pct = 2.0
    books = {"tok": make_book("tok", bids=((0.48, 100),), asks=((0.52, 100),))}
    engine, broker = make_engine(cfg, books)
    engine.cfg.state_file = str(tmp_path / "state.json")
    engine.step()
    engine.step()  # fill at 0.52
    assert engine.portfolio.shares("tok") == 10
    # market collapses -> equity tanks past the 5% drawdown
    books["tok"] = make_book("tok", bids=((0.10, 100),), asks=((0.12, 100),))
    engine.step()
    assert engine.risk.halted
    assert engine._stopping
    assert broker.open_orders() == []
