"""Answer "should I buy the Pixel 10 now or wait?" with four engines.

The question needs four different kinds of live data: current prices,
recent news, video reviews, and search-interest trend. Each lives
behind a different SerpApi engine with its own parameter vocabulary and
its own response envelope. SearchMux gives them one shape and one budget.

Run it:

    python examples/pixel_agent.py              # live if a key is set
    python examples/pixel_agent.py --offline    # always free

With no SERPAPI_API_KEY set it replays ``demo_cassette.json`` and costs
nothing. That cassette is a hand-written synthetic fixture, not a real
capture — it exists so this demo runs on a fresh clone. With a key set,
it runs live and records a real cassette to ``recorded.json``.
"""

import logging
import os
import sys
from pathlib import Path

from searchmux import SearchMux
from searchmux.envfile import load_env
from searchmux.constants import ENV_API_KEY

HERE = Path(__file__).parent
DEMO_CASSETTE = str(HERE / "demo_cassette.json")
RECORDED_CASSETTE = str(HERE / "recorded.json")
DEMO_CACHE = str(HERE / ".searchmux-demo.db")

# Each question is (label, engine, params). Engines are pinned, so this
# demo needs no LLM and no ANTHROPIC_API_KEY.
QUESTIONS = [
    ("prices", "google_shopping", {"q": "Pixel 10 price India", "gl": "in"}),
    ("news", "google_news", {"q": "Pixel 10 price drop"}),
    ("reviews", "youtube", {"search_query": "Pixel 10 review"}),
    ("trend", "google_trends", {"q": "Pixel 10"}),
]


def gather(q: SearchMux) -> dict:
    """Run every question and return results keyed by label.

    Args:
        q: A configured SearchMux client.

    Returns:
        Mapping of label to the list of normalized results.
    """
    findings = {}
    for label, engine, params in QUESTIONS:
        findings[label] = q.search(engine=engine, **params)
    return findings


def summarize(findings: dict) -> str:
    """Turn the gathered results into a recommendation.

    Deliberately simple arithmetic rather than an LLM call: the point
    of the demo is the search layer, not the reasoning on top.

    Args:
        findings: Output of gather().

    Returns:
        A one-line recommendation.
    """
    priced = [r for r in findings["prices"] if r.price]
    prices = [r.price.amount for r in priced]
    # Report the currency the engine actually gave us, not a guess.
    currency = priced[0].price.currency if priced else None
    trend = [
        item.raw.get("values", [{}])[0].get("value")
        for item in findings["trend"]
    ]
    trend = [v for v in trend if isinstance(v, (int, float))]

    if not prices:
        return "no pricing data available"

    cheapest = min(prices)
    spread = max(prices) - cheapest
    cooling = len(trend) >= 2 and trend[-1] < max(trend)

    verdict = "wait" if cooling or spread > 0.1 * cheapest else "buy now"
    unit = f" {currency}" if currency else ""
    return (
        f"cheapest {cheapest:,.0f}{unit}, spread {spread:,.0f}, "
        f"interest {'cooling' if cooling else 'steady'} -> {verdict}"
    )


def main() -> None:
    """Run the agent, then print what it cost."""
    # Result titles carry typographic spaces and dashes that a
    # cp1252 Windows console cannot encode; replace rather than
    # crash on someone else's machine.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    load_env()
    offline = "--offline" in sys.argv
    live = bool(os.getenv(ENV_API_KEY)) and not offline

    # budget=8 is a hard ceiling: four questions asked twice. The
    # second pass comes from cache, so it spends nothing - that gap
    # between 8 allowed and 4 spent is the whole point.
    q = SearchMux(budget=8, cache=DEMO_CACHE)

    if live:
        print(f"live mode: recording to {RECORDED_CASSETTE}\n")
        with q.record(RECORDED_CASSETTE):
            findings = gather(q)
            gather(q)
    else:
        print("offline mode: replaying the synthetic demo cassette\n")
        with q.replay(DEMO_CASSETTE):
            findings = gather(q)
            gather(q)

    for label, results in findings.items():
        print(f"{label:9} {len(results)} results")
        for result in results[:2]:
            price = f"  [{result.price}]" if result.price else ""
            print(f"          - {result.title[:58]}{price}")

    print(f"\nrecommendation: {summarize(findings)}")
    print(f"cost: {q.report()}")


if __name__ == "__main__":
    main()
