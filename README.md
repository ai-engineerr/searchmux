# SearchMux

[![PyPI](https://img.shields.io/pypi/v/searchmux)](https://pypi.org/project/searchmux/)
[![Tests](https://github.com/ai-engineerr/searchmux/actions/workflows/ci.yml/badge.svg)](https://github.com/ai-engineerr/searchmux/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/searchmux)](https://pypi.org/project/searchmux/)
[![License](https://img.shields.io/pypi/l/searchmux)](https://github.com/ai-engineerr/searchmux/blob/main/LICENSE)

A Python library that sits between your AI agent and its search APIs — SerpApi, Tavily, Brave Search, and Exa. Ask it once and it remembers the answer, so your agent never pays for the same search twice.

*A multiplexer routes one input to the right line among many. That is the job: one plain-language question, four search providers, the correct engine chosen.*

**Cost control and offline testing for agent search, across providers.** SearchMux picks the engine, caches the answer, caps the spend in requests or real dollars, and tests offline with zero network calls in CI. SerpApi is the most deeply integrated provider, with 24 engines; Tavily, Brave, and Exa are first-class providers sharing the same cache, budget guard, and offline-replay pipeline.

```python
from searchmux import SearchMux

q = SearchMux(budget=50)
results = q.find("current Pixel 10 prices in India")
# -> routed to google_shopping, params filled in, normalized Results back
```

---

## The problem

SerpApi alone exposes 100+ search engines, each with its own parameter vocabulary and response shape. Add Tavily, Brave, and Exa and an agent builder is juggling four APIs, four billing accounts, and no shared way to cap the cost. Three consequences, unsolved by any single provider's SDK:

**Engine selection doesn't work at scale.** LLM agents degrade past roughly 20–30 tools. SerpApi's own `serpapi-search-tools-python` exposes 9 engines out of 100+; `serpapi-mcp` goes the other way, one generic `search` tool where the model must name the engine and invent parameters unaided — in practice it defaults to plain `google` or picks a plausible-but-wrong one. Every wrong attempt costs a credit.

**Development is unaffordable, per provider.** A free SerpApi account carries 250 search credits a month; 4 searches per run over an afternoon of debugging burns through 160 of them. Tavily, Brave, and Exa each have their own separate free-tier ceiling. None of them cache — the second identical request costs as much as the first, every time.

**Search-backed agents are effectively untestable.** A 30-test suite at 3 searches each costs 90 credits per CI run, so the rational choice is not writing tests. None of the 120 projects in the BuiltWithSerpApi gallery ship a test suite that exercises a search path.

SearchMux is the layer underneath all three, for every provider it supports: one cache, one budget, one offline-replayable test path — regardless of which API answered the query.

---

## Measured results

**These numbers predate Tavily, Brave, and Exa.** They were measured against the 24-engine SerpApi-only catalog. Adding three more general-purpose engines to the candidate pool plausibly changes routing accuracy; the eval hasn't been re-run to confirm that, since it needs a live `ANTHROPIC_API_KEY`. Treat this table as evidence for the SerpApi-only router, not a current-catalog claim.

Routing accuracy on [`evals/routing.jsonl`](https://github.com/ai-engineerr/searchmux/blob/main/evals/routing.jsonl) — 50 hand-labelled intents spanning every catalogued engine, phrased the way a user would phrase them, never naming the engine. Cases where the ambiguity is genuine (a plain web question really could go to Google, Bing, or DuckDuckGo) accept any of the reasonable engines; forcing one answer would measure the label rather than the router.

| arm | n | correct | accuracy |
| --- | --- | --- | --- |
| random choice over 24 engines | — | — | ~4% |
| BM25 top-1, no LLM at all | 50 | 26 | 52% |
| BM25 top-5 + closed schemas | 50 | 41 | 82% |
| BM25 top-12 + closed schemas | 50 | 44 | 88% |
| all engine names, no schemas (the `serpapi-mcp` shape) | 50 | 49 | 98% |
| **SearchMux: all engines + closed schema** | **50** | **49** | **98%** |

### What the numbers actually showed — including where we were wrong

The starting thesis was that narrowing 100+ engines to a handful before the model sees them would beat handing it everything. **This eval says that's false.**

BM25 narrowing to 5 scored 82% — exactly its own retrieval recall@5. The model chose correctly from every shortlist it received; the shortlist was missing the right engine 18% of the time (it ranked `ebay` above `google_scholar` for "peer reviewed studies on CRISPR off-target effects"). Recall@k: 52 / 72 / 82 / 86 / 88 / 100% at k = 1 / 3 / 5 / 8 / 12 / 24 — narrowing is a hard ceiling, not a filter.

That premise doesn't bind at 24 engines. **Narrowing is off by default.**

The schema layer still earns its place: a schema built from every engine's parameters is **rejected by the API as "Schema is too complex."** SearchMux carries `params` as a fixed list of name/value pairs — constant size regardless of catalog growth — and validates names against the chosen engine afterward, with one repair attempt. Same 98% accuracy as the names-only baseline, plus a guaranteed parameter shape the baseline doesn't have.

Retrieval stays available (`Router(top_k=12)`) for catalogs big enough that prompt size, not accuracy, becomes the binding cost.

Reproduce the free arm on a fresh clone, no API key required:

```bash
python -m evals.run_eval
```

The two LLM arms cost money, so they're not pre-baked here — set `ANTHROPIC_API_KEY` and the same command scores all three. **52% is keyword retrieval alone, no model involved** — the finding that justified skipping embeddings entirely.

### Provider comparison

Head-to-head on 60 queries across six categories — factual, research, current events, how-to, technical, health/science, 10 each — against SerpApi's `google`, Tavily's `tavily_search`, and Exa's `exa_search`. All three requested the same 10 results per query, so `avg results` reflects the provider, not an accidental default.

Run started 2026-09-30T09:06:59 UTC — one snapshot, one network location. Latency will move on a different run or network, which is why median and p95 are reported instead of a mean. Every run saves a dated JSON snapshot to [`evals/results/`](https://github.com/ai-engineerr/searchmux/tree/main/evals/results), building a real history over time. Nothing runs on a schedule or in CI — that would mean committing to recurring paid spend on three providers, a decision not yet made.

| provider | n | success | 1st-attempt | median latency | p95 latency | avg results | approx tokens returned | list cost/request | total list cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| serpapi | 60 | 98% | 97% | 1068 ms | 16195 ms | 8.0 | 282 | $0.0150 | $0.900 |
| tavily | 60 | 100% | 100% | 1486 ms | 2604 ms | 9.4 | 2536 | $0.0080 | $0.480 |
| exa | 60 | 100% | 100% | 1834 ms | 2371 ms | 9.9 | 1237 | $0.0070 | $0.420 |
| brave | — | **pending** — no API key available | | | | | | $0.0050 | — |

**Cost** is each provider's published list price per request, checked 2026-09-30 (SerpApi Developer plan, $75/mo for 5,000 searches; Tavily pay-as-you-go; Exa's base endpoint; Brave's Search plan) — not necessarily your account's rate, the same reason `budget_usd` ships no defaults.

**Approx tokens returned** replaces a raw snippet-character count: `len(text) // 4` across every result, a proxy for what a downstream LLM call pays to read. Tavily returns cleaned page content (long); Exa's snippets are capped at 500 characters (`contents.text.maxCharacters`); SerpApi returns a short native snippet.

**1st-attempt** separates "succeeded immediately" from "succeeded after a retry." SerpApi's median latency (1,068 ms) is competitive, but its p95 (16,195 ms) isn't — one of the 60 queries failed outright after 3 retries. That tail showed up in nearly every category: p95 was 91,643 ms for `current_events`, 31,823 ms for `health_science`, 20,441 ms for `technical`, 14,633 ms for `how_to`. A mean or a median alone would have hidden it. Tavily and Exa stayed tight everywhere, p95 within roughly 2x of their own median. Full per-category tables are in the [saved snapshot](https://github.com/ai-engineerr/searchmux/tree/main/evals/results).

SerpApi doesn't charge for a server-side cache hit on an identical recent search; none of this run's queries repeat, so that didn't affect these numbers.

**Brave** is listed with its published price for reference but has no live row — no API key has been available.

Two free relevance signals, not a full judge:

- **Domain overlap** — how much each pair of providers agrees on which sources exist for the same query: `serpapi vs tavily 13%`, `serpapi vs exa 3%`, `tavily vs exa 9%`. Low across the board — these three draw from genuinely different parts of the web, not the same handful of sites.
- **Answer-containment** — for the 10 factual-category queries (each with a known date, name, or number as the answer), whether that answer appears anywhere in the results, via plain word-boundary substring match. All three hit **100%**. A floor, not a relevance score — a page can contain the right number by coincidence, and open-ended queries have no single string to check for.

An LLM-judge relevance score (rating results 1–5, validated by hand-checking a subset) would be a real next step and is deliberately not run here — it costs its own budget, and this pass didn't have a standing signal on what's acceptable to spend.

Reproduce it, real cost on all three providers (~$1.80 total at these list prices for 60 queries):

```bash
python -m evals.provider_eval
```

**The measurement changes a default, not just this page.** `recommended_providers(category)` turns the per-category p95 findings above into a fallback order for `find()`:

```python
from searchmux import recommended_providers

q.find(
    "latest SpaceX launch news",
    providers=recommended_providers("current_events"),  # ['exa', 'tavily', 'serpapi']
)
```

Still not automatic — SearchMux doesn't classify your query's category, and this is one eval run's opinion, not a permanent ruling. See [`docs/API.md`](https://github.com/ai-engineerr/searchmux/blob/main/docs/API.md#recommended_providers) for what it deliberately doesn't cover.

---

## Install

```bash
pip install searchmux
cp .env.example .env     # add keys for whichever providers you use, or don't — see below
```

For local development, clone and install editable instead: `pip install -e .`

Python 3.11+. Core dependencies are `httpx`, `pydantic`, and `rank-bm25`. The `anthropic` SDK is needed only for intent routing.

## Quickstart

```python
from searchmux import SearchMux

q = SearchMux(budget=50)

# Routed: SearchMux picks the engine and fills the params.
q.find("peer reviewed papers on CRISPR safety")      # -> google_scholar
q.find("cheapest flight Delhi to Tokyo in March")    # -> google_flights

# Pinned: you name the engine. No LLM, fully deterministic, no key
# beyond SerpApi's.
q.find("Pixel 10", engine="google_shopping")

for r in q.find("Pixel 10 price", engine="google_shopping"):
    print(r.title, r.price, r.url)   # one shape for every engine
    r.raw                            # the untouched original, always

q.report()
# {'credits_used': 3, 'remaining': 47, 'by_engine': {...}, 'cache_hits': 1}
```

Run the worked example — four engines answering one question, offline, for free:

```bash
python examples/pixel_agent.py
```

```
offline mode: replaying the demo cassette

prices    3 results
          - Google Pixel 10 5G (Obsidian, 12GB RAM, 256GB Storage)  [₹ 67400.00]
          - Google Pixel 10 5G  [₹ 74999.00]
news      3 results
reviews   3 results
trend     3 results

recommendation: cheapest 67,400 ₹, spread 7,599, interest steady -> wait
cost: {'credits_used': 0, 'remaining': 8, 'by_engine': {}, 'cache_hits': 4}
```

### Across providers

```python
from searchmux import SearchMux

q = SearchMux(
    api_key="...",          # SerpApi
    tavily_api_key="...",
    exa_api_key="...",
    budget_usd=5.00,        # a real dollar cap, not just a request count
    cost_per_request={"serpapi": 0.0075, "tavily": 0.008, "exa": 0.005},
)

# Try Exa first (good for research/semantic queries), fall back to
# SerpApi if Exa fails, has no key, or has no matching engine.
q.find("recent papers on protein folding", providers=["exa", "serpapi"])

q.report()
# {..., 'spent_usd': 0.005, 'remaining_usd': 4.995}
```

Pin an engine directly on any provider — `tavily_search`, `brave_search`, `exa_search` — the same way you'd pin `google_shopping`; no LLM, no routing, just that engine.

The rates above are illustrative, not published prices — SerpApi and Tavily especially vary by plan tier, so SearchMux ships no defaults and expects your own numbers.

---

## What it does

**Intent router.** BM25 scores your intent against every engine's description, free — no model, no network, no credits. Every engine goes to the LLM by default, since narrowing measured worse (see above); `Router(top_k=12)` stays available once prompt size, not accuracy, becomes the binding cost. The LLM always sees full parameter schemas for its candidates, not bare names. `providers=` narrows candidates to specific providers; pin an engine and the whole stage is skipped.

**Transparent cache.** `sqlite3` from the standard library, no server, no new dependency. The key is a SHA-256 of the canonical request with `api_key` excluded, so it's portable across keys and machines — identical queries in a dev loop cost nothing after the first. TTL is set per engine class: prices and flights expire in 15 minutes, news in an hour, patents and papers in 30 days.

**Budget guard, in requests or in dollars.** A hard ceiling checked before the request, not after. Thread-safe: check-and-increment under one lock, so twenty concurrent callers against a budget of ten get exactly ten successes. `budget_usd=` adds a real dollar cap, using rates you supply — no guessed prices, since SerpApi's and Tavily's real cost varies by plan.

**Provider fallback.** `q.find(intent, providers=["exa", "serpapi"])` tries providers in order, falling back on a backend failure, a missing key, or no matching engine. `providers=None` is a single unrestricted attempt, unchanged from before. `recommended_providers(category)` turns the [provider comparison](#provider-comparison) eval's p95-latency findings into a ready-made fallback order per category — not automatic classification, just measurement feeding a default.

**Per-engine cache opt-out.** Every engine is cached by default; a catalog entry can declare `cacheable: false` for a provider whose terms restrict storing results, and `SearchMux(no_cache={...})` adds the same exclusion at runtime, by provider or by engine, without touching the catalog.

**Record & replay.** Capture real responses once to a cassette file, then replay them forever in tests and CI at zero cost. A replay miss **raises** rather than falling through to the network, which is what stops a test suite silently becoming billable. `api_key` is stripped on write, so cassettes are safe to commit — and committing them is the point.

**Normalized results.** One `Result` dataclass across every engine and every provider, with `raw` always attached so nothing is lost. Swapping Bing for Tavily stops meaning a rewritten parser. Where a provider reports it, relevance `score` and `published_date` are promoted onto `Result.extra` too.

**Drop-in for agents.** `q.as_tool()` emits an Anthropic-shaped tool definition, consumed directly by Anthropic tool use and LangChain's structured tools. `q.as_openai_tool()` wraps the same schema in OpenAI's function-calling envelope, so the two can't drift apart — see [`examples/openai_agent.py`](https://github.com/ai-engineerr/searchmux/blob/main/examples/openai_agent.py) for a working loop. `searchmux-mcp` runs an MCP stdio server exposing a single `find` tool across every configured provider. It reads whichever of `SERPAPI_API_KEY`/`TAVILY_API_KEY`/`BRAVE_API_KEY`/`EXA_API_KEY` are set and restricts routing to those, so it never picks an engine it has no key for:

```bash
pip install -e ".[mcp,router]"
searchmux-mcp
```

Routing over MCP needs `ANTHROPIC_API_KEY`; without it the server starts, logs a warning, and the `find` tool reports that routing is unconfigured rather than failing obscurely.

---

## Run the tests without an API key

This is the claim worth checking first:

```bash
pip install -r requirements.txt
python -m pytest -q
```

197 tests, and **every one passes with every provider key unset**. CI enforces it by clearing all five — `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `BRAVE_API_KEY`, `EXA_API_KEY`, `ANTHROPIC_API_KEY` — on Python 3.11, 3.12, and 3.13. A test that needs the network is a mis-written test.

---

## How each provider is used

SearchMux catalogues **27 engines across four providers**. Every request goes through the same pipeline regardless of provider — route, cache, budget, transport, normalize — with only the transport layer and the catalog data actually knowing which API it's talking to.

**SerpApi** is the most deeply integrated provider: 24 engines covering the Google families (search, shopping, scholar, news, maps, local, flights, hotels, jobs, trends, images, videos, patents, finance, events, lens, autocomplete) plus YouTube, Bing, DuckDuckGo, Amazon, eBay, Walmart and Yelp. Every parameter was verified against the published SerpApi documentation rather than guessed; `amazon` takes `k`, `ebay` takes `_nkw`, `walmart` takes `query`, `yelp` requires `find_loc`.

**Tavily, Brave, and Exa** each contribute one engine — `tavily_search`, `brave_search`, `exa_search`: general web search tuned for LLM agents, an independent web index, and neural/semantic search, respectively. Tavily's and Exa's request shapes are verified against live API responses, not just docs. Brave's is doc-verified only — no key has been available yet.

Adding an engine is one JSON record and zero code, so catalogue breadth is a knob rather than a ceiling. The catalog is generated at build time and committed, so the library never does network I/O to resolve a schema and works fully offline.

### Known limitations

Stated plainly rather than discovered later:

- **27 engines across four providers, not 100+ SerpApi engines alone.** The rest are additive JSON records — routing and pipeline work is provider- and engine-agnostic.
- **Brave's request shape is doc-verified only, not live-tested.** No key has been available yet — built to the same standard as Tavily and Exa, flagged until confirmed against a real response.
- **The 98% routing-accuracy figure predates the multi-provider catalog.** It was measured against 24 SerpApi-only engines; see [Measured results](#measured-results) above.
- **`google_play` is deliberately not catalogued.** Its results nest as `organic_results[].items[]`, a list of lists that a flat results path cannot express. Listing an engine that silently returns nothing is worse than not listing it.
- **`google_trends` returns timeline entries, not links.** It is a time series, so `Result.title` carries the date and the values live in `Result.raw`.
- **`examples/demo_cassette.json` is a real SerpApi capture**, trimmed to the first 3 results per engine and the fields the normalizer reads, with no credentials or search ids retained. `python examples/pixel_agent.py --offline` forces the free replay path even when a key is present.
- **CrewAI and LlamaIndex** consume the emitted JSON-schema tool definition and should work by construction, but only the schema shape is tested here — treat them as unverified rather than supported.
- **No automatic "cheapest provider" selection.** `find(providers=[...])` fallback order is whatever you pass; sort it yourself by your own `cost_per_request` rates.

---

## AI tool disclosure

Per the hackathon rules: this project was built with **Claude Code**, used for design, implementation, test authoring, and documentation — including parallel subagents for independent modules and verifying catalog parameters against live responses where a key was available. Architectural decisions, evaluation methodology, and scope calls were directed by the authors. Every figure in the results tables is a real run against the live API, including the one that disproved the starting thesis. None are estimates.

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/API.md](https://github.com/ai-engineerr/searchmux/blob/main/docs/API.md) | Every public class, method and exception |
| [docs/ARCHITECTURE.md](https://github.com/ai-engineerr/searchmux/blob/main/docs/ARCHITECTURE.md) | How the pipeline fits together, and why each decision was made |
| [docs/searchmux-architecture.html](https://htmlpreview.github.io/?https://github.com/ai-engineerr/searchmux/blob/main/docs/searchmux-architecture.html) | Interactive runtime architecture diagram — trust boundaries, primary path, guided views |
| [docs/ENGINES.md](https://github.com/ai-engineerr/searchmux/blob/main/docs/ENGINES.md) | All 27 engines across four providers, their parameters and cache policy (generated from the catalog) |
| [docs/DESIGN.md](https://github.com/ai-engineerr/searchmux/blob/main/docs/DESIGN.md) | The original design specification |
| [docs/IMPLEMENTATION-PLAN.md](https://github.com/ai-engineerr/searchmux/blob/main/docs/IMPLEMENTATION-PLAN.md) | The task-by-task build plan, kept as a record |
| [CONTRIBUTING.md](https://github.com/ai-engineerr/searchmux/blob/main/CONTRIBUTING.md) | Setup, code style, and how to add an engine |
| [SECURITY.md](https://github.com/ai-engineerr/searchmux/blob/main/SECURITY.md) | How credentials are handled, and how to report an issue |
| [CHANGELOG.md](https://github.com/ai-engineerr/searchmux/blob/main/CHANGELOG.md) | Release history, including what we got wrong and corrected |

## Team

Built by **[Vikas Sharma](https://www.linkedin.com/in/vikas-sharma005/)** and **[Manisha Choudhary](https://www.linkedin.com/in/mani-shaa/)**.

## License

MIT — see [LICENSE](https://github.com/ai-engineerr/searchmux/blob/main/LICENSE).
