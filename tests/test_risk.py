from bot.models import DesiredOrder, Fill, Order, Side
from bot.portfolio import Portfolio
from bot.risk import RiskEngine


def test_per_order_cap(cfg):
    cfg.max_order_usdc = 5.0
    risk = RiskEngine(cfg)
    ok, why = risk.validate(DesiredOrder("tok", Side.BUY, 0.50, 20), Portfolio(), [], [])
    assert not ok and "MAX_ORDER_USDC" in why


def test_position_cap_counts_held_open_and_pending(cfg):
    cfg.max_order_usdc = 100.0
    cfg.max_position_usdc = 10.0
    cfg.max_total_usdc = 1000.0
    risk = RiskEngine(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, 0.50, 10))  # cost 5.0
    open_orders = [Order(token_id="tok", side=Side.BUY, price=0.40, size=10)]  # 4.0
    pending = [DesiredOrder("tok", Side.BUY, 0.50, 1)]  # 0.5
    # 5.0 + 4.0 + 0.5 + 1.0 > 10 -> reject
    ok, why = risk.validate(DesiredOrder("tok", Side.BUY, 0.50, 2), pf, open_orders, pending)
    assert not ok and "MAX_POSITION_USDC" in why
    # small enough passes
    ok, _ = risk.validate(DesiredOrder("tok", Side.BUY, 0.25, 1), pf, open_orders, pending)
    assert ok


def test_total_exposure_cap_holds_after_fills(cfg):
    """The old bot's fatal flaw: filled positions must still count."""
    cfg.max_order_usdc = 100.0
    cfg.max_position_usdc = 1000.0
    cfg.max_total_usdc = 10.0
    risk = RiskEngine(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "a", Side.BUY, 0.50, 16))  # cost 8.0, no open orders left
    ok, why = risk.validate(DesiredOrder("b", Side.BUY, 0.50, 6), pf, [], [])
    assert not ok and "MAX_TOTAL_USDC" in why


def test_sell_capped_to_holdings(cfg):
    risk = RiskEngine(cfg)
    pf = Portfolio()
    pf.apply_fill(Fill("o1", "tok", Side.BUY, 0.50, 10))
    ok, why = risk.validate(DesiredOrder("tok", Side.SELL, 0.60, 11), pf, [], [])
    assert not ok and "exceeds held" in why
    open_sells = [Order(token_id="tok", side=Side.SELL, price=0.60, size=6)]
    ok, why = risk.validate(DesiredOrder("tok", Side.SELL, 0.60, 5), pf, open_sells, [])
    assert not ok
    ok, _ = risk.validate(DesiredOrder("tok", Side.SELL, 0.60, 4), pf, open_sells, [])
    assert ok


def test_drawdown_kill_switch(cfg):
    cfg.max_drawdown_pct = 10.0
    risk = RiskEngine(cfg)
    assert risk.check_drawdown(100.0)
    assert risk.check_drawdown(95.0)  # -5% ok
    assert not risk.check_drawdown(89.0)  # -11% halts
    assert risk.halted
    ok, why = risk.validate(DesiredOrder("tok", Side.BUY, 0.50, 1), Portfolio(), [], [])
    assert not ok and "halted" in why
    # equity=None (live mode) never trips it
    fresh = RiskEngine(cfg)
    assert fresh.check_drawdown(None)


def test_exchange_minimums(cfg):
    cfg.min_size_shares = 5.0
    risk = RiskEngine(cfg)
    ok, why = risk.validate(DesiredOrder("tok", Side.BUY, 0.50, 2), Portfolio(), [], [])
    assert not ok and "min" in why.lower()
