from bot.models import Fill, Order, Side
from bot.portfolio import Portfolio


def test_buy_then_sell_realizes_pnl():
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, price=0.40, size=10))
    assert pf.shares("tok") == 10
    assert abs(pf.position("tok").avg_price - 0.40) < 1e-9

    pf.apply_fill(Fill("o2", "tok", Side.SELL, price=0.50, size=10))
    assert pf.shares("tok") == 0
    assert abs(pf.realized_pnl - 1.0) < 1e-9  # (0.50-0.40)*10


def test_partial_sell_keeps_cost_basis():
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, price=0.40, size=10))
    pf.apply_fill(Fill("o2", "tok", Side.BUY, price=0.60, size=10))  # avg 0.50
    pf.apply_fill(Fill("o3", "tok", Side.SELL, price=0.55, size=10))
    assert abs(pf.realized_pnl - 0.5) < 1e-9  # (0.55-0.50)*10
    assert abs(pf.position("tok").avg_price - 0.50) < 1e-9
    assert pf.shares("tok") == 10


def test_exposure_counts_positions_and_open_buys():
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, price=0.40, size=10))  # cost 4.0
    open_orders = [
        Order(token_id="tok", side=Side.BUY, price=0.30, size=10),  # 3.0 resting
        Order(token_id="tok", side=Side.SELL, price=0.60, size=5),  # sells don't add
    ]
    assert abs(pf.total_exposure(open_orders) - 7.0) < 1e-9


def test_unrealized_pnl_uses_marks():
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, price=0.40, size=10))
    assert abs(pf.unrealized_pnl({"tok": 0.45}) - 0.5) < 1e-9


def test_roundtrip_persistence():
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, price=0.40, size=10))
    pf.apply_fill(Fill("o2", "tok", Side.SELL, price=0.50, size=4))
    restored = Portfolio.from_dict(pf.to_dict())
    assert restored.shares("tok") == pf.shares("tok")
    assert restored.realized_pnl == pf.realized_pnl
