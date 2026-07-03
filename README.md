# Polymarket Trading Bot

An event-driven trading bot for [Polymarket](https://polymarket.com)'s CLOB,
with a depth-aware paper-trading simulator, a real risk engine, and three
strategies that each have an explicit thesis.

> **Real money warning.** Live mode signs orders with your Polygon private key.
> Start in paper mode (the default — needs no key and no funds), keep risk
> limits small, and read [What this bot is honest about](#what-this-bot-is-honest-about)
> before going live.

## Quick start (paper mode, no money needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# find something liquid to trade
python -m bot.discover world cup

# put a token id in .env as MARKETS=..., then:
python -m bot
```

You'll see the bot quote, get simulated fills against the *live* orderbook,
and report equity/P&L every tick. State persists in `bot_state.json`; delete
it to reset the paper account.

## Architecture

```
bot/
  engine.py            main loop: books -> fills -> risk -> reconcile orders
  models.py            Order/Fill/OrderBook/Side + tick rounding
  config.py            .env loader with validation
  marketdata.py        public CLOB REST endpoints (book, tick size)
  portfolio.py         positions, cost basis, realized/unrealized P&L
  risk.py              pre-trade checks + drawdown kill switch
  discover.py          CLI: find markets and their token ids
  execution/
    paper.py           depth-aware simulator (reserved cash, TTL, price improvement)
    live.py            py-clob-client wrapper (tick rounding, exchange minimums)
  strategies/
    market_maker.py    inventory-skewed two-sided quoting
    fair_value.py      trade only when your estimate disagrees with the market
    complement_arb.py  buy YES+NO when they sum below $1 (riskless at resolution)
tests/                 37 unit tests: pytest
```

Design principles:

- **Declarative strategies.** Each tick a strategy returns the orders it wants
  resting *right now*; the engine diffs that against actual open orders and
  issues minimal cancels/placements. Quotes follow the market instead of
  piling up.
- **Positions count.** Exposure = cost of held positions **plus** resting buy
  notional, so `MAX_TOTAL_USDC` still binds after fills (the classic bot-drains-
  wallet failure mode).
- **Nothing outlives the process.** Shutdown — clean or crash — cancels every
  resting order.
- **Kill switch.** If equity draws down `MAX_DRAWDOWN_PCT` from its peak, the
  bot cancels everything and halts (paper mode; live mode can't observe total
  equity so it relies on the exposure caps).

## Strategies

### `market_maker`
Earns the spread quoting both sides, with three defenses a naive quoter lacks:
inventory skew (quotes lean against accumulated position), quote pulling when
the book blows out (don't be the stale quote news traders pick off), and a
spread floor. Works best on quiet, liquid markets. Still REST-polling — a fast
mover will beat it on breaking news.

### `fair_value`
**You** supply a probability estimate per market (`FAIR_VALUES=token=0.45`).
The bot trades only when the market disagrees with you by `FV_MIN_EDGE` or
more, sizing with fractional Kelly, never taking more than the displayed
depth. The edge is your forecast — if your estimates are no better than the
market's, this loses slowly by the spread. No estimate, no trade.

### `complement_arb`
YES + NO always redeems for exactly $1. If `ask(YES) + ask(NO) < 1 - edge`,
buying both legs is riskless profit at resolution, model-free. Real but rare
and competed-for: expect it to sit idle most of the time — that's correct
behavior. Needs `MARKETS=yes_token:no_token` pairs (the discover CLI prints
them). Positions are held to resolution; redeem via the Polymarket UI.

## Risk limits

| Variable            | Meaning                                                        |
| ------------------- | -------------------------------------------------------------- |
| `MAX_ORDER_USDC`    | Max notional of any single order                               |
| `MAX_POSITION_USDC` | Max capital in one market (held cost + resting buys)           |
| `MAX_TOTAL_USDC`    | Max capital at risk everywhere (positions **and** open orders) |
| `MAX_DRAWDOWN_PCT`  | Equity drop from peak that halts the bot and cancels all       |

All four are enforced centrally in `bot/risk.py` before any order reaches the
broker; strategies cannot bypass them.

## Going live

1. Prove the strategy out in paper mode for at least a few days.
2. Create a **fresh burner wallet**; fund it on Polygon with only what you can
   lose. Never reuse a key that has ever been pasted anywhere.
3. In `.env`: `MODE=live`, `PRIVATE_KEY=...`, `ACK_LIVE_RISK=true`, and set
   `SIGNATURE_TYPE`/`FUNDER_ADDRESS` per your account type (0 = plain wallet,
   1 = email login proxy, 2 = browser-wallet proxy — proxy address is shown in
   the Polymarket UI).
4. Polymarket geoblocks US IPs at the API; run from a permitted region.
5. Start with tiny limits and watch the first fills yourself.

## What this bot is honest about

- **Paper results are optimistic.** The simulator has no queue position and no
  adverse selection: in paper you capture every spread; live, informed flow
  fills you exactly when you're wrong. Treat paper P&L as an upper bound, and
  market-maker paper P&L as a *loose* upper bound.
- **Polling REST every few seconds is slow** by market-making standards.
  Competitive making needs the websocket feed and sub-second reactions.
- **No strategy here prints money on its own.** `complement_arb` has genuine
  edge but is scarce; `fair_value` is only as good as your forecasts;
  `market_maker` earns spread but bleeds to informed flow in fast markets. The
  bot's job is disciplined execution and not blowing up — the edge is yours to
  bring.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```
