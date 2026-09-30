# SearchMux

[![PyPI](https://img.shields.io/pypi/v/searchmux)](https://pypi.org/project/searchmux/)
[![Tests](https://github.com/ai-engineerr/searchmux/actions/workflows/ci.yml/badge.svg)](https://github.com/ai-engineerr/searchmux/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/searchmux)](https://pypi.org/project/searchmux/)
[![License](https://img.shields.io/pypi/l/searchmux)](https://github.com/ai-engineerr/searchmux/blob/main/LICENSE)

A Python library — not an app, nothing to open or click — that sits between your AI agent and its search APIs: SerpApi, Tavily, Brave Search, and Exa. Ask it something once and it remembers the answer, so your agent never pays for the same search twice, on whichever provider answered it.

*A multiplexer routes one input to the right line among many. That is the job: one plain-language question, four search providers, the correct engine chosen.*

**Cost control and offline testing for agent search, across providers.** Describe what you want to know; SearchMux picks the right engine, caches the answer, caps the spend — in requests or in real dollars — and makes the whole thing testable offline, with zero network calls in CI. SerpApi is the most deeply integrated provider (24 engines, years of verified parameter quirks); Tavily, Brave, and Exa are additional, first-class providers sharing the same cache, budget guard, and offline-replay pipeline.

```python
from searchmux import SearchMux

q = SearchMux(budget=50)
results = q.find("current Pixel 10 prices in India")
# -> routed to google_shopping, params filled in, normalized Results back
```

---

## The problem

SerpApi alone exposes 100+ search engines, each with its own parameter vocabulary and response envelope key — `organic_results`, `shopping_results`, `news_results`, `video_results`. Add Tavily, Brave, and Exa and an agent builder is juggling four different APIs, four different billing accounts, and no shared way to cap what any of them cost. Three consequences, none of them solved by any single provider's own SDK:

**Engine selection doesn't work at scale.** LLM agents degrade past roughly 20–30 tools. SerpApi's own `serpapi-search-tools-python` exposes 9 engines out of 100+. `serpapi-mcp` takes the opposite approach — one generic `search` tool where the model must name the engine and invent parameters unaided — so in practice it defaults to plain `google` for everything, or picks a plausible-but-wrong engine. Every wrong attempt costs a credit, on whichever provider it hit.

**Development is unaffordable, per provider.** A free SerpApi account carries 250 search credits per month. An agent making 4 searches per run, executed 40 times over an afternoon of debugging, burns 160 of them — and Tavily, Brave, and Exa each have their own separate free-tier ceiling. None of them cache, so the second identical request costs exactly as much as the first, on every provider, every time.

**Search-backed agents are effectively untestable.** A 30-test suite at 3 searches per test costs 90 credits per CI run against any one of these APIs, so the rational choice is to not write tests. Across the 120 projects in the BuiltWithSerpApi gallery, none ship a test suite that exercises a search path.

SearchMux is the layer underneath all three, for every provider it supports — one cache, one budget (in requests or in dollars), one offline-replayable test path, regardless of which API actually answered the query.

---

## Measured results

**These numbers predate Tavily, Brave, and Exa.** They were measured against the 24-engine SerpApi-only catalog, before the multi-provider work landed. Adding three more general-purpose "web search" engines to the candidate pool plausibly changes routing accuracy, and we haven't re-run the eval to find out — that needs a live `ANTHROPIC_API_KEY`, which we don't have configured in this environment right now. Re-running it, on real data rather than a guess, is a known open item. Treat this table as evidence for the SerpApi-only router, not a current-catalog claim.

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

Our starting thesis was that narrowing 100+ engines down to a handful before the model sees them would beat handing it everything. **On this eval that is false, and the measurement says so plainly.**

BM25 narrowing to 5 scored 82% — *exactly* its own retrieval recall@5 of 82%. The model chose correctly from every shortlist it was given; the shortlist was simply missing the right engine 18% of the time. BM25 ranked `ebay` above `google_scholar` for "peer reviewed studies on CRISPR off-target effects". Recall@k measured 52 / 72 / 82 / 86 / 88 / 100% at k = 1 / 3 / 5 / 8 / 12 / 24, so narrowing is a hard ceiling, not a filter.

The premise that agents degrade past 20–30 tools simply does not bind at 24 engines. **Narrowing is therefore off by default.**

What survives, and why the schema layer still earns its place: a schema built from every engine's parameters is **rejected by the API as "Schema is too complex"**, so parameter validity cannot be bought by brute force. SearchMux carries `params` as a fixed list of name/value pairs — constant schema size however large the catalog grows — and validates names against the chosen engine afterwards, with one repair attempt. That lands the same 98% engine accuracy as the names-only baseline *while also* guaranteeing the parameter shape, which the baseline does not.

Retrieval stays available (`Router(top_k=12)`) for catalogs big enough that prompt size, not accuracy, becomes the binding cost.

Reproduce the free arm on a fresh clone, no API key required:

```bash
python -m evals.run_eval
```

The two LLM arms cost money to run, so they are not pre-baked here — set `ANTHROPIC_API_KEY` and the same command scores all three. **The 52% figure is keyword retrieval alone, with no model involved**, which is the finding that justified skipping embeddings entirely.

### Provider comparison

Head-to-head on 15 general web-search queries, run live against SerpApi's `google` engine, Tavily's `tavily_search`, and Exa's `exa_search` — Brave excluded, no key available. This is a first, deliberately small pass (15 queries, not the 100+ a full study would use), and it measures structural signals — did anything come back, how fast, how many results, how much text per result — not which answer was actually *better*. That needs a human or an LLM judge and its own budget, which this pass doesn't spend. Treat it as a starting data point, not a verdict.

| provider | n | success | avg latency | avg results | avg snippet chars |
| --- | --- | --- | --- | --- | --- |
| serpapi | 15 | 100% | 7992 ms | 7.9 | 144 |
| tavily | 15 | 100% | 1581 ms | 9.5 | 1194 |
| exa | 15 | 100% | 1970 ms | 9.8 | 498 |

All three answered every query. SerpApi was markedly slower on this run (one query hit a timeout and retried, which pulls its average up — that's a real cost of the general-purpose `google` engine, not a fluke to explain away). Tavily's snippets are roughly 8x longer than SerpApi's on average — it returns cleaned page content, not a search-result snippet. Exa's average sits right at its own 500-character cap (`contents.text.maxCharacters`, set in `ExaBackend` to bound context-window cost), confirming that cap is doing what it's supposed to.

Reproduce it, real cost on all three providers:

```bash
python -m evals.provider_eval
```

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

**Intent router.** BM25 scores your intent against every engine's description, free — no model, no network, no credits. By default every engine goes to the LLM alongside that ranking, because narrowing measured *worse* (see above); `Router(top_k=12)` remains available for catalogs big enough that prompt size, not accuracy, becomes the binding cost. Either way the LLM sees full parameter schemas for its candidates and chooses — picking among fully-specified options beats picking among bare names, which is what a single generic search tool asks of it. `providers=` narrows candidates to specific providers; pin an engine and the whole stage is skipped.

**Transparent cache.** `sqlite3` from the standard library, no server, no new dependency. The key is a SHA-256 of the canonical request with `api_key` excluded, so it is portable across keys and machines, and identical queries in a dev loop cost nothing after the first. TTL is set per engine class: prices and flights expire in 15 minutes, news in an hour, patents and papers in 30 days.

**Budget guard, in requests or in dollars.** A hard ceiling checked *before* the request, not after — the point is to not spend the credit. Thread-safe: check-and-increment happens under one lock, so twenty concurrent callers against a budget of ten get exactly ten successes. `budget_usd=` adds a real dollar cap on top, using rates you supply for your own pricing plan — no guessed prices baked in, since SerpApi's and Tavily's real cost varies by tier.

**Provider fallback.** `q.find(intent, providers=["exa", "serpapi"])` tries providers in order, moving to the next on a backend failure, a missing key, or no matching engine — instead of the caller catching and retrying by hand. `providers=None` is a single unrestricted attempt, unchanged from before this existed.

**Per-engine cache opt-out.** Every engine is cached by default; a catalog entry can declare `cacheable: false` for a provider whose terms restrict storing results, and `SearchMux(no_cache={...})` adds the same exclusion at runtime, by provider or by engine, without touching the catalog.

**Record & replay.** Capture real responses once to a cassette file, then replay them forever in tests and CI at zero cost. A replay miss **raises** rather than falling through to the network, which is what stops a test suite silently becoming billable. `api_key` is stripped on write, so cassettes are safe to commit — and committing them is the point.

**Normalized results.** One `Result` dataclass across every engine and every provider, with `raw` always attached so nothing is lost. Swapping Bing for Tavily stops meaning a rewritten parser. Where a provider reports it, relevance `score` and `published_date` are promoted onto `Result.extra` too.

**Drop-in for agents.** `q.as_tool()` emits an Anthropic-shaped tool definition that Anthropic tool use and LangChain's structured tools consume directly; `q.as_openai_tool()` emits the same schema wrapped in OpenAI's function-calling envelope, so the two never drift apart. See [`examples/openai_agent.py`](https://github.com/ai-engineerr/searchmux/blob/main/examples/openai_agent.py) for a real, working tool-calling loop, not just a claim. `searchmux-mcp` runs an MCP stdio server exposing a single `find` tool, so an MCP client gets every engine across every configured provider behind one tool instead of juggling several. It reads whichever of `SERPAPI_API_KEY`/`TAVILY_API_KEY`/`BRAVE_API_KEY`/`EXA_API_KEY` are set and restricts routing to those providers automatically, so it never picks an engine it has no key for:

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

179 tests, and **every one passes with every provider key unset** — `SERPAPI_API_KEY`, `TAVILY_API_KEY`, `BRAVE_API_KEY`, `EXA_API_KEY`, and `ANTHROPIC_API_KEY` alike. CI enforces it by explicitly clearing all five on Python 3.11, 3.12 and 3.13 — if a test needs the network, it is a mis-written test. There is no signup between you and a green suite.

---

## How each provider is used

SearchMux catalogues **27 engines across four providers**. Every request goes through the same pipeline regardless of provider — route, cache, budget, transport, normalize — with only the transport layer and the catalog data actually knowing which API it's talking to.

**SerpApi** is the most deeply integrated provider: 24 engines covering the Google families (search, shopping, scholar, news, maps, local, flights, hotels, jobs, trends, images, videos, patents, finance, events, lens, autocomplete) plus YouTube, Bing, DuckDuckGo, Amazon, eBay, Walmart and Yelp. Every parameter was verified against the published SerpApi documentation rather than guessed; `amazon` takes `k`, `ebay` takes `_nkw`, `walmart` takes `query`, `yelp` requires `find_loc`.

**Tavily, Brave, and Exa** each contribute one engine — `tavily_search`, `brave_search`, `exa_search` — general web search tuned for LLM agents (Tavily), an independent web index (Brave), and neural/semantic search (Exa). Tavily's and Exa's request shapes are verified against real, live API responses, not just documentation. Brave's is doc-verified only — no Brave API key has been available to confirm it against a live call, and that's stated here rather than left implicit.

Adding an engine is one JSON record and zero code, so catalogue breadth is a knob rather than a ceiling. The catalog is generated at build time and committed, so the library never does network I/O to resolve a schema and works fully offline.

### Known limitations

Stated plainly rather than discovered later:

- **27 engines across four providers, not 100+ SerpApi engines alone.** The remaining SerpApi engines are additive JSON records; the routing and pipeline work is provider- and engine-agnostic.
- **Brave's request shape is doc-verified only, not live-tested.** No Brave API key has been available yet. It's built to the same standard as Tavily and Exa, but flagged here until it's actually been confirmed against a real response.
- **The 98% routing-accuracy figure predates the multi-provider catalog.** It was measured against 24 SerpApi-only engines; see [Measured results](#measured-results) above.
- **`google_play` is deliberately not catalogued.** Its results nest as `organic_results[].items[]`, a list of lists that a flat results path cannot express. Listing an engine that silently returns nothing is worse than not listing it.
- **`google_trends` returns timeline entries, not links.** It is a time series, so `Result.title` carries the date and the values live in `Result.raw`.
- **`examples/demo_cassette.json` is a real SerpApi capture**, trimmed to the first 3 results per engine and the fields the normalizer reads, with no credentials or search ids retained. `python examples/pixel_agent.py --offline` forces the free replay path even when a key is present.
- **CrewAI and LlamaIndex** consume the emitted JSON-schema tool definition and should work by construction, but only the schema shape is tested here — treat them as unverified rather than supported.
- **No automatic "cheapest provider" selection.** `find(providers=[...])` fallback order is whatever you pass; sort it yourself by your own `cost_per_request` rates.

---

## AI tool disclosure

Per the hackathon rules: this project was built with **Claude Code** used for design, implementation, test authoring, and documentation, including parallel subagents for independent modules and for verifying catalog parameters against each provider's published docs and, where a key was available, real live responses. All architectural decisions, the evaluation methodology, and the scope calls documented above were directed by the authors. Every figure in the results table is a real run of `evals/run_eval.py` against the live API, including the one that disproved our own starting thesis. None are estimates.

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
