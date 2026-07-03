from bot.models import BookLevel, MarketSpec, OrderBook, Side, round_to_tick


def test_book_normalizes_sort_order():
    # feed bids ascending and asks descending (worst-first, like the CLOB API)
    book = OrderBook.from_raw(
        "tok",
        bids_raw=[{"price": "0.40", "size": "10"}, {"price": "0.45", "size": "5"}],
        asks_raw=[{"price": "0.60", "size": "10"}, {"price": "0.55", "size": "5"}],
    )
    assert book.best_bid.price == 0.45
    assert book.best_ask.price == 0.55
    assert abs(book.mid - 0.50) < 1e-9
    assert abs(book.spread - 0.10) < 1e-9


def test_depth_at_or_better():
    book = OrderBook(
        "tok",
        bids=[BookLevel(0.48, 10), BookLevel(0.45, 20)],
        asks=[BookLevel(0.52, 10), BookLevel(0.55, 20)],
    )
    assert book.depth_at_or_better(Side.BUY, 0.52) == 10
    assert book.depth_at_or_better(Side.BUY, 0.55) == 30
    assert book.depth_at_or_better(Side.SELL, 0.45) == 30


def test_round_to_tick_never_disfavors():
    assert round_to_tick(0.523, 0.01, Side.BUY) == 0.52  # buy rounds down
    assert round_to_tick(0.523, 0.01, Side.SELL) == 0.53  # sell rounds up
    assert round_to_tick(0.52, 0.01, Side.BUY) == 0.52  # on-grid unchanged
    assert round_to_tick(0.001, 0.01, Side.BUY) == 0.01  # clamped off zero
    assert round_to_tick(0.999, 0.01, Side.SELL) == 0.99  # clamped below 1


def test_market_spec_parse():
    assert MarketSpec.parse("abc") == MarketSpec("abc")
    assert MarketSpec.parse("a:b") == MarketSpec("a", "b")
    assert MarketSpec.parse(" a : b ") == MarketSpec("a", "b")
