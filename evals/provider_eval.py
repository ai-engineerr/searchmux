"""Compare SerpApi, Tavily, and Exa head-to-head on the same general
web-search queries: cost, latency (median and p95, not just mean),
result count, and how much text comes back. Plus two free relevance
signals: whether a factual answer actually shows up, and how much
providers agree on which sources exist at all.

Brave is excluded from the live run -- no key has been available --
but its published list price is included for reference, and it is
reported as a pending row, not silently omitted.

This is NOT a full relevance judge. Answer-containment and domain
overlap are free, objective signals, not "which result was actually
best" -- that needs a human or an LLM judge and a separate budget,
which this pass deliberately does not spend. Fifteen general queries
plus eight factual ones, not the 100-200 a full study would use: real
paid calls on three providers, and there is no standing signal on
acceptable spend for a bigger sample. Scaling it up is real future
work, not something to fake by inflating this one.

Every query goes to exactly one engine per provider -- SerpApi's
general-purpose `google`, Tavily's `tavily_search`, Exa's
`exa_search` -- so this compares general web search specifically, not
SerpApi's category-specific engines (flights, shopping, ...), which
Tavily and Exa have no equivalent for. Every provider is asked for the
same RESULT_COUNT results, so "avg results" reflects the provider, not
an accidental default.

Costs real money on all three providers. Run with:

    python -m evals.provider_eval
"""

import json
import logging
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from searchmux import SearchMux
from searchmux.envfile import load_env
from searchmux.models import SearchMuxError

logger = logging.getLogger(__name__)

QUERIES_PATH = str(Path(__file__).with_name("provider_queries.jsonl"))
FACTUAL_QUERIES_PATH = str(Path(__file__).with_name("factual_queries.jsonl"))

RESULT_COUNT = 10

# provider -> (engine_id, query param name, result-count param name)
_PROVIDER_ENGINES = {
    "serpapi": ("google", "q", "num"),
    "tavily": ("tavily_search", "query", "max_results"),
    "exa": ("exa_search", "query", "numResults"),
}

# List prices as published by each provider or a third-party pricing
# aggregator, checked 2026-09-30 via web search -- NOT necessarily
# your account's actual rate. SearchMux's own budget_usd ships no
# defaults for exactly this reason (SerpApi and Tavily both vary by
# plan tier); this table exists only to give the eval a cost column.
#
#   serpapi: SerpApi "Developer" plan, $75/mo for 5,000 searches.
#            Cheaper per-search on higher tiers, pricier on Starter.
#   tavily:  Tavily pay-as-you-go rate; a basic search costs 1 credit.
#            Cheaper per-credit on higher committed-volume plans.
#   exa:     Exa's base search endpoint, $7 / 1,000 requests, up to
#            10 results with text included.
#   brave:   Brave Search API "Search" plan, $5 / 1,000 requests.
#            Listed for reference; not live-tested (see below).
LIST_PRICE_PER_REQUEST = {
    "serpapi": 0.015,
    "tavily": 0.008,
    "exa": 0.007,
    "brave": 0.005,
}


class _RetryWatcher(logging.Handler):
    """Counts WARNING records from searchmux.transport during one call.

    The retry loop lives inside Backend.fetch() and doesn't expose
    "did this need a retry" to the caller. Rather than change the
    transport layer for an eval-only need, this watches its logger
    for the warning it already emits on every timeout or 5xx.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def load_queries(path: str) -> list[str]:
    """Read one query per line from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        The queries, in file order.
    """
    queries = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line)["query"])
    return queries


def load_factual_queries(path: str) -> list[dict]:
    """Read {"query", "expect_any"} rows from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        One dict per line, each with a query and acceptable answers.
    """
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Simple and deterministic for the
    small samples this eval runs -- no interpolation edge cases.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct * (len(ordered) - 1))))
    return ordered[index]


def run_one(
    q: SearchMux, engine: str, param: str, count_param: str, query: str
) -> dict:
    """Run one query against one engine, timed and retry-instrumented.

    A failure is recorded as ok=False rather than raised, so one bad
    query does not abort the whole comparison.

    Args:
        q: A SearchMux configured for exactly one provider.
        engine: The engine to call.
        param: The engine's query parameter name.
        count_param: The engine's result-count parameter name.
        query: The search text.

    Returns:
        Keys ok, first_attempt, latency_ms, result_count,
        approx_tokens, urls, text.
    """
    watcher = _RetryWatcher()
    transport_logger = logging.getLogger("searchmux.transport")
    transport_logger.addHandler(watcher)
    start = time.perf_counter()
    try:
        results = q.search(
            engine=engine, **{param: query, count_param: RESULT_COUNT}
        )
        ok = True
    except SearchMuxError as exc:
        logger.warning("%s failed on %r: %s", engine, query, exc)
        results = []
        ok = False
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        transport_logger.removeHandler(watcher)

    text = " ".join(r.snippet or "" for r in results)
    return {
        "ok": ok,
        "first_attempt": watcher.count == 0,
        "latency_ms": latency_ms,
        "result_count": len(results),
        # Rough chars-to-tokens heuristic (~4 chars/token in English).
        # This is what actually costs money downstream: it's text an
        # agent's LLM call has to pay to read, not just a display
        # snippet -- which is why it matters for the cost story here.
        "approx_tokens": len(text) // 4,
        "urls": [r.url for r in results if r.url],
    }


def score_provider(provider: str, queries: list[str]) -> dict:
    """Run every query against one provider and summarize the results.

    Args:
        provider: One of "serpapi", "tavily", "exa".
        queries: The queries to run.

    Returns:
        Aggregate stats, plus "_rows" (per-query detail, used by the
        domain-overlap check).
    """
    engine, param, count_param = _PROVIDER_ENGINES[provider]
    q = SearchMux(cache=None, budget=len(queries) + 5)
    rows = [
        run_one(q, engine, param, count_param, query) for query in queries
    ]

    n = len(rows)
    latencies = [r["latency_ms"] for r in rows]
    price = LIST_PRICE_PER_REQUEST.get(provider)
    return {
        "provider": provider,
        "n": n,
        "success_rate": sum(r["ok"] for r in rows) / n if n else 0.0,
        "first_attempt_rate": (
            sum(r["first_attempt"] for r in rows) / n if n else 0.0
        ),
        "median_latency_ms": statistics.median(latencies) if n else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "avg_result_count": (
            sum(r["result_count"] for r in rows) / n if n else 0.0
        ),
        "avg_approx_tokens": (
            sum(r["approx_tokens"] for r in rows) / n if n else 0.0
        ),
        "list_price_per_request": price,
        "total_list_cost": price * n if price is not None else None,
        "_rows": rows,
    }


def domain_overlap(
    provider_rows: dict[str, list[dict]],
) -> dict[str, float]:
    """Return average domain-set overlap between every pair of providers.

    Jaccard similarity of the set of result domains, averaged across
    every query both providers answered. High overlap means the
    providers keep finding the same sources; low overlap means they
    are genuinely drawing from different parts of the web.

    Args:
        provider_rows: provider -> its run_one() rows, same query
            order for every provider.

    Returns:
        "{provider} vs {provider}" -> average Jaccard similarity.
    """
    providers = list(provider_rows)
    n_queries = min(len(rows) for rows in provider_rows.values())
    pairs = {}
    for i, p1 in enumerate(providers):
        for p2 in providers[i + 1 :]:
            scores = []
            for idx in range(n_queries):
                d1 = {
                    urlparse(u).netloc
                    for u in provider_rows[p1][idx]["urls"]
                }
                d2 = {
                    urlparse(u).netloc
                    for u in provider_rows[p2][idx]["urls"]
                }
                if not d1 or not d2:
                    continue
                scores.append(len(d1 & d2) / len(d1 | d2))
            pairs[f"{p1} vs {p2}"] = (
                sum(scores) / len(scores) if scores else 0.0
            )
    return pairs


def answer_containment(provider: str, factual_cases: list[dict]) -> dict:
    """Check how often a known answer actually appears in the results.

    A free, objective relevance proxy for queries with an unambiguous
    factual answer -- not a substitute for judging open-ended queries,
    where there is no single string to check for.

    Args:
        provider: One of "serpapi", "tavily", "exa".
        factual_cases: Rows from load_factual_queries.

    Returns:
        Keys provider, n, containment_rate.
    """
    engine, param, count_param = _PROVIDER_ENGINES[provider]
    q = SearchMux(cache=None, budget=len(factual_cases) + 5)
    hits = 0
    for case in factual_cases:
        try:
            results = q.search(
                engine=engine,
                **{param: case["query"], count_param: RESULT_COUNT},
            )
        except SearchMuxError as exc:
            logger.warning(
                "%s failed on %r: %s", engine, case["query"], exc
            )
            continue
        text = " ".join(
            f"{r.title or ''} {r.snippet or ''}" for r in results
        ).lower()
        if any(
            re.search(rf"\b{re.escape(answer.lower())}\b", text)
            for answer in case["expect_any"]
        ):
            hits += 1
    n = len(factual_cases)
    return {
        "provider": provider,
        "n": n,
        "containment_rate": hits / n if n else 0.0,
    }


def _format_table(rows: list[dict]) -> str:
    """Render scored providers as a markdown table."""
    lines = [
        "| provider | n | success | 1st-attempt | median lat | "
        "p95 lat | avg results | approx tokens | list cost/req | "
        "total list cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        price = row["list_price_per_request"]
        price_str = f"${price:.4f}" if price is not None else "—"
        total_str = (
            f"${row['total_list_cost']:.3f}"
            if row["total_list_cost"] is not None
            else "—"
        )
        lines.append(
            f"| {row['provider']} | {row['n']} | "
            f"{row['success_rate']:.0%} | "
            f"{row['first_attempt_rate']:.0%} | "
            f"{row['median_latency_ms']:.0f} ms | "
            f"{row['p95_latency_ms']:.0f} ms | "
            f"{row['avg_result_count']:.1f} | "
            f"{row['avg_approx_tokens']:.0f} | {price_str} | "
            f"{total_str} |"
        )
    lines.append(
        "| brave | 0 | pending — no API key available | | | | | | "
        f"${LIST_PRICE_PER_REQUEST['brave']:.4f} | — |"
    )
    return "\n".join(lines)


def main() -> None:
    """Score every provider, check relevance signals, print tables."""
    # A cp1252 Windows console can't encode the em dashes below;
    # replace rather than crash on someone else's machine.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    load_env()
    queries = load_queries(QUERIES_PATH)
    factual_cases = load_factual_queries(FACTUAL_QUERIES_PATH)

    run_started = datetime.now(UTC).isoformat(timespec="seconds")

    rows = [score_provider(p, queries) for p in _PROVIDER_ENGINES]
    provider_rows = {row["provider"]: row["_rows"] for row in rows}
    overlap = domain_overlap(provider_rows)
    containment = [
        answer_containment(p, factual_cases) for p in _PROVIDER_ENGINES
    ]

    print(f"Run started: {run_started}")
    print(
        f"{len(queries)} general web-search queries, "
        f"{RESULT_COUNT} results requested per query from every "
        f"provider. Latency is network-dependent and this is one "
        f"snapshot run, not a guaranteed steady-state number. SerpApi "
        f"does not charge a credit for a server-side cache hit on an "
        f"identical recent search; none of this run's queries repeat, "
        f"so that did not affect these numbers either way. Brave "
        f"excluded from live results, no key available.\n"
    )
    print(_format_table(rows))

    print(
        "\nDomain overlap between providers (Jaccard, higher = more "
        "agreement on sources):\n"
    )
    for pair, score in overlap.items():
        print(f"  {pair}: {score:.0%}")

    print(
        f"\nAnswer-containment on {len(factual_cases)} factual queries "
        f"with a known answer (free, word-boundary substring match — "
        f"not a full relevance judge):\n"
    )
    for row in containment:
        print(f"  {row['provider']}: {row['containment_rate']:.0%}")


if __name__ == "__main__":
    main()
