"""Compare SerpApi, Tavily, and Exa head-to-head across six query
categories: cost, latency (median and p95, not just mean), result
count, how much text comes back, and two free relevance signals --
whether a known factual answer actually shows up, and how much
providers agree on which sources exist at all.

Brave is excluded from the live run -- no key has been available --
but its published list price is included for reference, and it is
reported as a pending row, not silently omitted.

This is NOT a full relevance judge. Answer-containment and domain
overlap are free, objective signals, not "which result was actually
best" -- that needs a human or an LLM judge and a separate budget,
which this pass deliberately does not spend.

60 queries across six categories (factual, research, current_events,
how_to, technical, health_science), not the 100-200 a fuller study
would eventually use -- scaled to what's reasonable to spend without
a standing budget signal for this specific eval. Growing this further
is real future work, not something to fake by inflating this run.

Every query goes to exactly one engine per provider -- SerpApi's
general-purpose `google`, Tavily's `tavily_search`, Exa's
`exa_search` -- so this compares general web search specifically, not
SerpApi's category-specific engines (flights, shopping, ...), which
Tavily and Exa have no equivalent for. Every provider is asked for the
same RESULT_COUNT results, so "avg results" reflects the provider, not
an accidental default.

Each run is saved as a dated snapshot under evals/results/, so this
becomes a real history to compare against over time rather than a
one-off number. Nothing here runs on a schedule or in CI -- that would
mean committing to recurring paid spend on three providers, which
needs its own explicit decision, not a default.

Costs real money on all three providers. Run with:

    python -m evals.provider_eval
"""

import json
import logging
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from searchmux import SearchMux
from searchmux.envfile import load_env
from searchmux.models import SearchMuxError

logger = logging.getLogger(__name__)

QUERIES_PATH = str(Path(__file__).with_name("provider_queries.jsonl"))
RESULTS_DIR = Path(__file__).with_name("results")

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


def load_queries(path: str) -> list[dict]:
    """Read {"query", "category", "expect_any"} rows from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        One dict per line, in file order. expect_any is None for
        every non-factual query.
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
    q: SearchMux, engine: str, param: str, count_param: str, case: dict
) -> dict:
    """Run one query against one engine, timed and retry-instrumented.

    A failure is recorded as ok=False rather than raised, so one bad
    query does not abort the whole comparison.

    Args:
        q: A SearchMux configured for exactly one provider.
        engine: The engine to call.
        param: The engine's query parameter name.
        count_param: The engine's result-count parameter name.
        case: One row from load_queries (query, category, expect_any).

    Returns:
        Keys category, ok, first_attempt, latency_ms, result_count,
        approx_tokens, urls, contains_answer (None when expect_any is
        unset for this query).
    """
    watcher = _RetryWatcher()
    transport_logger = logging.getLogger("searchmux.transport")
    transport_logger.addHandler(watcher)
    start = time.perf_counter()
    try:
        results = q.search(
            engine=engine,
            **{param: case["query"], count_param: RESULT_COUNT},
        )
        ok = True
    except SearchMuxError as exc:
        logger.warning("%s failed on %r: %s", engine, case["query"], exc)
        results = []
        ok = False
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        transport_logger.removeHandler(watcher)

    snippet_text = " ".join(r.snippet or "" for r in results)
    contains_answer = None
    if case.get("expect_any"):
        combined = " ".join(
            f"{r.title or ''} {r.snippet or ''}" for r in results
        ).lower()
        contains_answer = any(
            re.search(rf"\b{re.escape(answer.lower())}\b", combined)
            for answer in case["expect_any"]
        )

    return {
        "category": case["category"],
        "ok": ok,
        "first_attempt": watcher.count == 0,
        "latency_ms": latency_ms,
        "result_count": len(results),
        # Rough chars-to-tokens heuristic (~4 chars/token in English).
        # This is what actually costs money downstream: it's text an
        # agent's LLM call has to pay to read, not just a display
        # snippet -- which is why it matters for the cost story here.
        "approx_tokens": len(snippet_text) // 4,
        "urls": [r.url for r in results if r.url],
        "contains_answer": contains_answer,
    }


def _aggregate(rows: list[dict]) -> dict:
    """Summarize a list of run_one() rows into one stats dict."""
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "success_rate": 0.0,
            "first_attempt_rate": 0.0,
            "median_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "avg_result_count": 0.0,
            "avg_approx_tokens": 0.0,
        }
    latencies = [r["latency_ms"] for r in rows]
    return {
        "n": n,
        "success_rate": sum(r["ok"] for r in rows) / n,
        "first_attempt_rate": sum(r["first_attempt"] for r in rows) / n,
        "median_latency_ms": statistics.median(latencies),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "avg_result_count": sum(r["result_count"] for r in rows) / n,
        "avg_approx_tokens": sum(r["approx_tokens"] for r in rows) / n,
    }


def score_provider(provider: str, cases: list[dict]) -> dict:
    """Run every case against one provider and summarize the results,
    overall and broken down by category.

    Args:
        provider: One of "serpapi", "tavily", "exa".
        cases: Rows from load_queries.

    Returns:
        Keys provider, overall (an _aggregate() dict plus cost),
        by_category (category -> _aggregate() dict),
        containment_rate (over cases with expect_any set),
        and "_rows" (per-case detail, used by domain_overlap).
    """
    engine, param, count_param = _PROVIDER_ENGINES[provider]
    q = SearchMux(cache=None, budget=len(cases) + 5)
    rows = [
        run_one(q, engine, param, count_param, case) for case in cases
    ]

    overall = _aggregate(rows)
    price = LIST_PRICE_PER_REQUEST.get(provider)
    overall["list_price_per_request"] = price
    overall["total_list_cost"] = (
        price * overall["n"] if price is not None else None
    )

    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    category_stats = {
        category: _aggregate(cat_rows)
        for category, cat_rows in by_category.items()
    }

    factual = [r for r in rows if r["contains_answer"] is not None]
    containment_rate = (
        sum(r["contains_answer"] for r in factual) / len(factual)
        if factual
        else 0.0
    )

    return {
        "provider": provider,
        "overall": overall,
        "by_category": category_stats,
        "containment_rate": containment_rate,
        "_rows": rows,
    }


def domain_overlap(provider_rows: dict[str, list[dict]]) -> dict:
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


def _format_overall_table(rows: list[dict]) -> str:
    """Render each provider's overall stats as a markdown table."""
    lines = [
        "| provider | n | success | 1st-attempt | median lat | "
        "p95 lat | avg results | approx tokens | list cost/req | "
        "total list cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        o = row["overall"]
        price = o["list_price_per_request"]
        price_str = f"${price:.4f}" if price is not None else "—"
        total_str = (
            f"${o['total_list_cost']:.3f}"
            if o["total_list_cost"] is not None
            else "—"
        )
        lines.append(
            f"| {row['provider']} | {o['n']} | "
            f"{o['success_rate']:.0%} | {o['first_attempt_rate']:.0%} "
            f"| {o['median_latency_ms']:.0f} ms | "
            f"{o['p95_latency_ms']:.0f} ms | "
            f"{o['avg_result_count']:.1f} | "
            f"{o['avg_approx_tokens']:.0f} | {price_str} | "
            f"{total_str} |"
        )
    lines.append(
        "| brave | 0 | pending — no API key available | | | | | | "
        f"${LIST_PRICE_PER_REQUEST['brave']:.4f} | — |"
    )
    return "\n".join(lines)


def _format_category_table(rows: list[dict], category: str) -> str:
    """Render one category's per-provider stats as a markdown table."""
    lines = [
        "| provider | n | success | median lat | p95 lat | "
        "avg results | approx tokens |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        c = row["by_category"].get(category)
        if c is None or not c["n"]:
            lines.append(f"| {row['provider']} | 0 | — | | | | |")
            continue
        lines.append(
            f"| {row['provider']} | {c['n']} | {c['success_rate']:.0%} "
            f"| {c['median_latency_ms']:.0f} ms | "
            f"{c['p95_latency_ms']:.0f} ms | "
            f"{c['avg_result_count']:.1f} | {c['avg_approx_tokens']:.0f} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Score every provider, check relevance signals, print and save."""
    # A cp1252 Windows console can't encode the em dashes below;
    # replace rather than crash on someone else's machine.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    load_env()
    cases = load_queries(QUERIES_PATH)
    categories = sorted({case["category"] for case in cases})

    run_started = datetime.now(UTC).isoformat(timespec="seconds")

    rows = [score_provider(p, cases) for p in _PROVIDER_ENGINES]
    provider_rows = {row["provider"]: row["_rows"] for row in rows}
    overlap = domain_overlap(provider_rows)

    print(f"Run started: {run_started}")
    print(
        f"{len(cases)} queries across {len(categories)} categories "
        f"({', '.join(categories)}), {RESULT_COUNT} results requested "
        f"per query from every provider. Latency is network-dependent "
        f"and this is one snapshot run, not a guaranteed steady-state "
        f"number. SerpApi does not charge a credit for a server-side "
        f"cache hit on an identical recent search; none of this run's "
        f"queries repeat, so that did not affect these numbers either "
        f"way. Brave excluded from live results, no key available.\n"
    )
    print("## Overall\n")
    print(_format_overall_table(rows))

    print("\n## By category\n")
    for category in categories:
        print(f"\n### {category}\n")
        print(_format_category_table(rows, category))

    print(
        "\n## Domain overlap between providers (Jaccard, higher = "
        "more agreement on sources)\n"
    )
    for pair, score in overlap.items():
        print(f"  {pair}: {score:.0%}")

    print(
        "\n## Answer-containment on the factual category (free, "
        "word-boundary substring match — not a full relevance judge)\n"
    )
    for row in rows:
        print(f"  {row['provider']}: {row['containment_rate']:.0%}")

    RESULTS_DIR.mkdir(exist_ok=True)
    snapshot_path = RESULTS_DIR / f"{run_started[:10]}.json"
    snapshot = {
        "run_started": run_started,
        "n_queries": len(cases),
        "result_count_requested": RESULT_COUNT,
        "providers": [
            {
                "provider": row["provider"],
                "overall": row["overall"],
                "by_category": row["by_category"],
                "containment_rate": row["containment_rate"],
            }
            for row in rows
        ],
        "domain_overlap": overlap,
        "list_price_per_request": LIST_PRICE_PER_REQUEST,
    }
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nSaved snapshot to {snapshot_path}")


if __name__ == "__main__":
    main()
