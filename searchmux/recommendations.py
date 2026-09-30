"""Data-backed default provider ordering, derived from a real eval run.

Not automatic: SearchMux does not classify a query's category itself
and never uses this on its own. It is an opinionated starting point a
caller can pass straight to SearchMux.find(providers=...) once they
already know what kind of query they're routing -- the measurement
changes what the default *should* be, without SearchMux silently
guessing the category for you.

Derived from evals/results/2026-09-30.json (60 queries, 10 per
category, against SerpApi's `google`, Tavily's `tavily_search`, and
Exa's `exa_search`), ordered primarily by p95 latency within each
category. That run's clearest finding was SerpApi's recurring latency
tail -- its median was often fine, its p95 wasn't, in nearly every
category -- which a ranking by median alone would have hidden.

Brave is not included: no live data exists for it yet. This only
covers general web search, the engines these three providers share;
it says nothing about SerpApi's category-specific engines --
google_flights, google_shopping, google_patents, and the rest -- which
Tavily and Exa have no equivalent for and this ranking doesn't touch.

A single eval run is a snapshot, not a permanent truth. Re-running
`python -m evals.provider_eval` over time (each run saved under
evals/results/) is how this table should eventually be revisited, not
treated as fixed.
"""

# category -> provider order, best-measured p95 latency first, from
# the 2026-09-30 run (evals/results/2026-09-30.json).
RECOMMENDED_PROVIDERS: dict[str, list[str]] = {
    "current_events": ["exa", "tavily", "serpapi"],
    "health_science": ["tavily", "exa", "serpapi"],
    "technical": ["exa", "tavily", "serpapi"],
    "how_to": ["tavily", "exa", "serpapi"],
    "factual": ["tavily", "serpapi", "exa"],
    "research": ["exa", "tavily", "serpapi"],
}

# Used when the caller's category isn't one of the six measured above:
# the overall (not per-category) p95 ordering from the same run.
DEFAULT_ORDER: list[str] = ["exa", "tavily", "serpapi"]


def recommended_providers(category: str | None = None) -> list[str]:
    """Return a data-backed provider fallback order for one category.

    Args:
        category: One of RECOMMENDED_PROVIDERS' keys ("factual",
            "research", "current_events", "how_to", "technical",
            "health_science"). None, or any other value, returns
            DEFAULT_ORDER -- the overall ranking from the same run.

    Returns:
        Provider names, best-measured-p95-latency first. Pass
        straight to SearchMux.find(providers=...).
    """
    if category is None:
        return list(DEFAULT_ORDER)
    return list(RECOMMENDED_PROVIDERS.get(category, DEFAULT_ORDER))
