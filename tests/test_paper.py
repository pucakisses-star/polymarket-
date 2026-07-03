from bot.execution.paper import PaperBroker
from bot.models import DesiredOrder, Side

from conftest import make_book


def test_buy_reserves_and_cancel_refunds():
    b = PaperBroker(starting_cash=10.0)
    order = b.place(DesiredOrder("tok", Side.BUY, 0.50, 10))  # reserve 5.0
    assert order is not None
    assert abs(b.available - 5.0) < 1e-9
    assert abs(b.reserved - 5.0) < 1e-9
    b.cancel(order.id)
    assert abs(b.available - 10.0) < 1e-9
    assert abs(b.reserved) < 1e-9


def test_batch_of_buys_cannot_overspend():
    b = PaperBroker(starting_cash=10.0)
    assert b.place(DesiredOrder("tok", Side.BUY, 0.50, 12)) is not None  # 6.0
    assert b.place(DesiredOrder("tok", Side.BUY, 0.50, 12)) is None  # would need 6 more


def test_fill_walks_depth_with_price_improvement():
    b = PaperBroker(starting_cash=100.0)
    b.place(DesiredOrder("tok", Side.BUY, 0.55, 15))
    # asks: 10 @ 0.50, then 20 @ 0.60 (above limit -> untouched)
    book = make_book(asks=((0.50, 10), (0.60, 20)))
    b.on_books({"tok": book})
    fills = b.poll_fills()
    assert len(fills) == 1
    assert fills[0].price == 0.50 and fills[0].size == 10  # filled at level, not limit
    assert b.shares["tok"] == 10
    # 5 shares remain resting; only their reservation is still held
    (open_order,) = b.open_orders()
    assert abs(open_order.remaining - 5) < 1e-9
    assert abs(b.reserved - 0.55 * 5) < 1e-9
    # paid 10*0.50 = 5.0 total
    assert abs((b.available + b.reserved) - 95.0) < 1e-9


def test_sell_requires_holdings():
    b = PaperBroker(starting_cash=100.0)
    assert b.place(DesiredOrder("tok", Side.SELL, 0.60, 5)) is None
    b.shares["tok"] = 10
    assert b.place(DesiredOrder("tok", Side.SELL, 0.60, 8)) is not None
    # second sell would over-commit the same shares
    assert b.place(DesiredOrder("tok", Side.SELL, 0.60, 5)) is None


def test_sell_fills_against_bids():
    b = PaperBroker(starting_cash=0.0)
    b.shares["tok"] = 10
    b.place(DesiredOrder("tok", Side.SELL, 0.55, 10))
    book = make_book(bids=((0.60, 4), (0.55, 100)))
    b.on_books({"tok": book})
    fills = b.poll_fills()
    assert sum(f.size for f in fills) == 10
    assert fills[0].price == 0.60  # best bid first, price improvement
    assert abs(b.available - (4 * 0.60 + 6 * 0.55)) < 1e-9
    assert b.shares["tok"] == 0


def test_ttl_expiry_refunds():
    b = PaperBroker(starting_cash=10.0, order_ttl_sec=0.0)
    order = b.place(DesiredOrder("tok", Side.BUY, 0.50, 10))
    order.created_ts -= 1  # force past TTL
    b.on_books({"tok": make_book(asks=((0.90, 5),))})
    assert b.open_orders() == []
    assert abs(b.available - 10.0) < 1e-9


def test_restore_folds_reserved_into_available():
    b = PaperBroker(starting_cash=0.0)
    b.restore({"available": 7.0, "reserved": 3.0, "shares": {"tok": 2}})
    assert b.available == 10.0 and b.reserved == 0.0
    assert b.shares["tok"] == 2
