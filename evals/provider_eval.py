"""Compare SerpApi, Tavily, and Exa head-to-head on the same general
web-search queries: latency, result count, and whether anything came
back at all.

Brave is excluded -- no key has been available to run it, the same
disclosed limitation as the rest of this project.

This is NOT a relevance judge. "Quality" here means structural signals
-- did the provider return results, how many, how fast, how much text
per result -- not "which answer was actually better," which would need
a human or an LLM judge and a separate budget for that judge to call.
Treat this as a first, honest, deliberately small pass (15 queries,
not the 100-200 a full pass would use), not a final verdict: a bigger
sample is real future work, not something to fake by inflating this
one.

Every query goes to exactly one engine per provider -- SerpApi's
general-purpose `google`, Tavily's `tavily_search`, Exa's
`exa_search` -- so this compares general web search specifically, not
SerpApi's category-specific engines (flights, shopping, ...), which
Tavily and Exa have no equivalent for.

Costs real money on all three providers. Run with:

    python -m evals.provider_eval
"""

import json
import logging
import time
from pathlib import Path

from searchmux import SearchMux
from searchmux.envfile import load_env
from searchmux.models import SearchMuxError

logger = logging.getLogger(__name__)

QUERIES_PATH = str(Path(__file__).with_name("provider_queries.jsonl"))

# provider -> (engine_id, query param name)
_PROVIDER_ENGINES = {
    "serpapi": ("google", "q"),
    "tavily": ("tavily_search", "query"),
    "exa": ("exa_search", "query"),
}


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


def run_one(q: SearchMux, engine: str, param: str, query: str) -> dict:
    """Run one query against one engine and time it.

    A failure is recorded as ok=False rather than raised, so one bad
    query does not abort the whole comparison.

    Args:
        q: A SearchMux configured for exactly one provider.
        engine: The engine to call.
        param: The engine's query parameter name.
        query: The search text.

    Returns:
        Keys ok, latency_ms, result_count, avg_snippet_len.
    """
    start = time.perf_counter()
    try:
        results = q.search(engine=engine, **{param: query})
    except SearchMuxError as exc:
        logger.warning("%s failed on %r: %s", engine, query, exc)
        return {
            "ok": False,
            "latency_ms": (time.perf_counter() - start) * 1000,
            "result_count": 0,
            "avg_snippet_len": 0.0,
        }
    return {
        "ok": True,
        "latency_ms": (time.perf_counter() - start) * 1000,
        "result_count": len(results),
        "avg_snippet_len": (
            sum(len(r.snippet or "") for r in results) / len(results)
            if results
            else 0.0
        ),
    }


def score_provider(provider: str, queries: list[str]) -> dict:
    """Run every query against one provider and average the results.

    Args:
        provider: One of "serpapi", "tavily", "exa".
        queries: The queries to run.

    Returns:
        Keys provider, n, success_rate, avg_latency_ms,
        avg_result_count, avg_snippet_len.
    """
    engine, param = _PROVIDER_ENGINES[provider]
    q = SearchMux(cache=None, budget=len(queries) + 5)
    rows = [run_one(q, engine, param, query) for query in queries]

    n = len(rows)
    return {
        "provider": provider,
        "n": n,
        "success_rate": sum(r["ok"] for r in rows) / n if n else 0.0,
        "avg_latency_ms": (
            sum(r["latency_ms"] for r in rows) / n if n else 0.0
        ),
        "avg_result_count": (
            sum(r["result_count"] for r in rows) / n if n else 0.0
        ),
        "avg_snippet_len": (
            sum(r["avg_snippet_len"] for r in rows) / n if n else 0.0
        ),
    }


def _format_table(rows: list[dict]) -> str:
    """Render scored providers as a markdown table."""
    lines = [
        "| provider | n | success | avg latency | avg results | "
        "avg snippet chars |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['provider']} | {row['n']} | "
            f"{row['success_rate']:.0%} | {row['avg_latency_ms']:.0f} ms "
            f"| {row['avg_result_count']:.1f} | "
            f"{row['avg_snippet_len']:.0f} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Score every provider and print a markdown table."""
    logging.basicConfig(level=logging.WARNING)
    load_env()
    queries = load_queries(QUERIES_PATH)
    rows = [score_provider(p, queries) for p in _PROVIDER_ENGINES]

    print(
        f"Head-to-head on {len(queries)} general web-search queries "
        f"(Brave excluded -- no key available):\n"
    )
    print(_format_table(rows))


if __name__ == "__main__":
    main()
