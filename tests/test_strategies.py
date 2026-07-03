from bot.models import Fill, MarketSpec, Side
from bot.portfolio import Portfolio
from bot.strategies import ComplementArb, FairValue, MarketMaker
from bot.strategies.base import TickContext

from conftest import make_book


def ctx_for(cfg, books, markets, portfolio=None, cash=None):
    return TickContext(
        books=books,
        portfolio=portfolio or Portfolio(),
        markets=[MarketSpec.parse(m) for m in markets],
        ticks={t: 0.01 for t in books},
        cash=cash,
    )


# ---------- market maker ----------

def test_mm_quotes_both_sides_when_holding(cfg):
    mm = MarketMaker(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o", "tok", Side.BUY, 0.50, 20))
    orders = mm.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"], pf))
    sides = {o.side for o in orders}
    assert sides == {Side.BUY, Side.SELL}
    bid = next(o for o in orders if o.side is Side.BUY)
    ask = next(o for o in orders if o.side is Side.SELL)
    assert bid.price < ask.price
    assert ask.size <= 20  # never sells more than held


def test_mm_no_naked_sell(cfg):
    mm = MarketMaker(cfg)
    orders = mm.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"]))
    assert all(o.side is Side.BUY for o in orders)


def test_mm_inventory_skew_lowers_quotes_when_long(cfg):
    cfg.mm_inventory_limit = 20.0
    cfg.mm_skew_intensity = 1.0
    mm = MarketMaker(cfg)
    flat = mm.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"]))
    long_pf = Portfolio()
    long_pf.apply_fill(Fill("o", "tok", Side.BUY, 0.50, 10))  # half the limit
    skewed = mm.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"], long_pf))
    flat_bid = next(o.price for o in flat if o.side is Side.BUY)
    skewed_bid = next(o.price for o in skewed if o.side is Side.BUY)
    assert skewed_bid < flat_bid  # long inventory -> quote lower to shed it


def test_mm_stops_buying_at_inventory_cap(cfg):
    cfg.mm_inventory_limit = 20.0
    mm = MarketMaker(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o", "tok", Side.BUY, 0.50, 20))  # at the cap
    orders = mm.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"], pf))
    assert not any(o.side is Side.BUY for o in orders)
    assert any(o.side is Side.SELL for o in orders)  # still working out of it


def test_mm_pulls_quotes_on_wide_spread(cfg):
    cfg.mm_max_book_spread = 0.05
    mm = MarketMaker(cfg)
    wide = make_book(bids=((0.30, 100),), asks=((0.70, 100),))
    assert mm.desired_orders(ctx_for(cfg, {"tok": wide}, ["tok"])) == []


# ---------- fair value ----------

def test_fv_buys_only_with_edge(cfg):
    cfg.fair_values = {"tok": 0.60}
    cfg.fv_min_edge = 0.05
    fv = FairValue(cfg)
    # ask 0.52, fv 0.60 -> edge 0.08 >= 0.05: buy
    orders = fv.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"], cash=100.0))
    assert len(orders) == 1 and orders[0].side is Side.BUY
    assert orders[0].price == 0.52
    # fv 0.55 -> edge 0.03: no trade
    cfg.fair_values = {"tok": 0.55}
    fv2 = FairValue(cfg)
    assert fv2.desired_orders(ctx_for(cfg, {"tok": make_book("tok")}, ["tok"], cash=100.0)) == []


def test_fv_size_capped_by_depth(cfg):
    cfg.fair_values = {"tok": 0.90}
    cfg.fv_kelly_fraction = 1.0
    fv = FairValue(cfg)
    thin = make_book(asks=((0.50, 3),))
    orders = fv.desired_orders(ctx_for(cfg, {"tok": thin}, ["tok"], cash=10_000.0))
    assert orders and orders[0].size <= 3


def test_fv_exits_above_fair_value(cfg):
    cfg.fair_values = {"tok": 0.40}
    fv = FairValue(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o", "tok", Side.BUY, 0.35, 10))
    book = make_book(bids=((0.48, 50),), asks=((0.52, 50),))
    orders = fv.desired_orders(ctx_for(cfg, {"tok": book}, ["tok"], pf, cash=100.0))
    sells = [o for o in orders if o.side is Side.SELL]
    assert len(sells) == 1 and sells[0].size == 10


# ---------- complement arb ----------

def test_arb_fires_when_sum_below_one(cfg):
    cfg.arb_min_edge = 0.01
    cfg.max_order_usdc = 100.0
    arb = ComplementArb(cfg)
    books = {
        "yes": make_book("yes", asks=((0.55, 50),)),
        "no": make_book("no", asks=((0.42, 30),)),
    }  # 0.97 -> 3% riskless edge
    orders = arb.desired_orders(ctx_for(cfg, books, ["yes:no"]))
    assert len(orders) == 2
    assert {o.token_id for o in orders} == {"yes", "no"}
    assert all(o.side is Side.BUY for o in orders)
    assert orders[0].size == orders[1].size == 30  # matched legs, min depth


def test_arb_idle_when_no_edge(cfg):
    arb = ComplementArb(cfg)
    books = {
        "yes": make_book("yes", asks=((0.55, 50),)),
        "no": make_book("no", asks=((0.47, 50),)),
    }  # sums to 1.02
    assert arb.desired_orders(ctx_for(cfg, books, ["yes:no"])) == []
