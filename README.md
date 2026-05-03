# Polymarket Trading Bot

Automated trading on Polymarket via the official CLOB REST API
([`py-clob-client`](https://github.com/Polymarket/py-clob-client)). Includes
two simple strategies (mean-reversion and market-making) and hard caps on
per-order and total exposure.

> **Real money.** This bot signs orders with your Polygon private key and
> places live trades against on-chain markets. Always start with `DRY_RUN=true`
> and small `MAX_ORDER_USDC` / `MAX_TOTAL_USDC` limits.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and fill in PRIVATE_KEY, MARKETS, etc.
```

### Funding

You need USDC on Polygon in the wallet that matches your `SIGNATURE_TYPE`
(EOA address for `0`, Polymarket proxy for `1`, browser-wallet proxy for `2`).
Deposit via the Polymarket UI; the bot does not handle funding.

### Picking markets

`MARKETS` is a comma-separated list of CLOB **token IDs** (one per outcome —
typically YES/NO). Get them from the public Gamma API:

```bash
curl 'https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=5' \
  | jq '.[] | {question, clobTokenIds}'
```

Use the YES (or NO) token ID, not the condition ID.

## Run

```bash
python bot.py
```

Stops cleanly on Ctrl+C. With `DRY_RUN=true` it prints intended orders without
sending them.

## Strategies

- **mean_reversion** — buy when mid-price drops below `MR_LOWER`, sell when it
  rises above `MR_UPPER`. Size is bounded by `MAX_ORDER_USDC / mid`.
- **market_make** — places a resting bid and ask around mid-price separated by
  `MM_SPREAD`, each of size `MM_SIZE`.
- **manual** — does nothing; useful for testing connectivity.

Both strategies skip placement when total open exposure exceeds
`MAX_TOTAL_USDC`.

## Safety knobs

| Env var            | Effect                                                     |
| ------------------ | ---------------------------------------------------------- |
| `DRY_RUN=true`     | Log orders, never send. **Default.**                       |
| `MAX_ORDER_USDC`   | Refuse any single order whose notional exceeds this.       |
| `MAX_TOTAL_USDC`   | Stop placing new orders once open exposure reaches this.   |
| `POLL_INTERVAL`    | Seconds between strategy ticks.                            |

## Files

- `bot.py` — main loop, CLOB client, order placement
- `strategy.py` — pure functions returning `Signal`s
- `config.py` — env-var loader with validation
