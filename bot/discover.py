"""Market discovery CLI.

    python -m bot.discover                # top markets by 24h volume
    python -m bot.discover bitcoin 150k   # filter question text by all terms

Prints token ids in the exact formats .env expects (MARKETS / FAIR_VALUES).
"""

from __future__ import annotations

import json
import sys

import requests

GAMMA = "https://gamma-api.polymarket.com"


def fetch_markets(limit: int = 100) -> list[dict]:
    r = requests.get(
        f"{GAMMA}/markets",
        params={
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
            "limit": limit,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def main(argv: list[str]) -> int:
    terms = [t.lower() for t in argv]
    markets = fetch_markets()
    shown = 0
    for m in markets:
        question = m.get("question") or ""
        if terms and not all(t in question.lower() for t in terms):
            continue
        try:
            token_ids = json.loads(m.get("clobTokenIds") or "[]")
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
        except json.JSONDecodeError:
            continue
        if len(token_ids) != 2:
            continue
        vol = float(m.get("volume24hr") or 0)
        print(f"\n{question}")
        print(f"  volume 24h: ${vol:,.0f}")
        for outcome, tid, px in zip(outcomes, token_ids, prices):
            print(f"  {outcome:>4} @ {float(px):.3f}  token: {tid}")
        print(f"  MARKETS entry (single):  {token_ids[0]}")
        print(f"  MARKETS entry (arb):     {token_ids[0]}:{token_ids[1]}")
        shown += 1
        if shown >= 10:
            break
    if shown == 0:
        print("no matching active markets found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
