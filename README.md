# SearchMux

*A multiplexer routes one input to the right line among many. That is the job: one plain-language question, 100+ search engines, the correct one chosen.*

**The search layer for AI agents over SerpApi.** Describe what you want to know; SearchMux picks the right engine, caches the answer, meters the spend, and makes the whole thing testable offline.

```python
from searchmux import SearchMux

q = SearchMux(budget=50)
results = q.find("current Pixel 10 prices in India")
# -> routed to google_shopping, params filled in, normalized Results back
```

---

## The problem

SerpApi exposes 100+ search engines. Each has its own parameter vocabulary and its own response envelope key — `organic_results`, `shopping_results`, `news_results`, `video_results`. Three consequences, none of them currently solved:

**Engine selection doesn't work at scale.** LLM agents degrade past roughly 20–30 tools. SerpApi's own `serpapi-search-tools-python` exposes 9 engines out of 100+. `serpapi-mcp` takes the opposite approach — one generic `search` tool where the model must name the engine and invent parameters unaided — so in practice it defaults to plain `google` for everything, or picks a plausible-but-wrong engine. Every wrong attempt costs a credit.

**Development is unaffordable.** A free SerpApi account carries 250 search credits per month. An agent making 4 searches per run, executed 40 times over an afternoon of debugging, burns 160 of them. There is no caching layer, so the second identical request costs exactly as much as the first.

**SerpApi-backed agents are effectively untestable.** A 30-test suite at 3 searches per test costs 90 credits per CI run, so the rational choice is to not write tests. Across the 120 projects in the BuiltWithSerpApi gallery, none ship a test suite that exercises a search path.

SearchMux is the layer underneath all three.

---

## Measured results

Routing accuracy on [`evals/routing.jsonl`](evals/routing.jsonl) — 50 hand-labelled intents spanning every catalogued engine, phrased the way a user would phrase them, never naming the engine. Cases where the ambiguity is genuine (a plain web question really could go to Google, Bing, or DuckDuckGo) accept any of the reasonable engines; forcing one answer would measure the label rather than the router.

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

---

## Install

```bash
pip install -e .
cp .env.example .env     # add your SerpApi key, or don't — see below
```

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

---

## What it does

**Intent router.** BM25 scores your intent against every engine's description and narrows 24 candidates to 5 for free — no model, no network, no credits. Only then does an LLM see those 5, *with their full parameter schemas*, and choose. An LLM picking among five fully-specified options beats an LLM picking among a hundred bare names, which is what a single generic search tool asks of it. Pin an engine and the whole stage is skipped.

**Transparent cache.** `sqlite3` from the standard library, no server, no new dependency. The key is a SHA-256 of the canonical request with `api_key` excluded, so it is portable across keys and machines, and identical queries in a dev loop cost nothing after the first. TTL is set per engine class: prices and flights expire in 15 minutes, news in an hour, patents and papers in 30 days.

**Budget guard.** A hard ceiling checked *before* the request, not after — the point is to not spend the credit. Thread-safe: check-and-increment happens under one lock, so twenty concurrent callers against a budget of ten get exactly ten successes.

**Record & replay.** Capture real responses once to a cassette file, then replay them forever in tests and CI at zero cost. A replay miss **raises** rather than falling through to the network, which is what stops a test suite silently becoming billable. `api_key` is stripped on write, so cassettes are safe to commit — and committing them is the point.

**Normalized results.** One `Result` dataclass across every engine, with `raw` always attached so nothing is lost. Swapping Bing for DuckDuckGo stops meaning a rewritten parser.

**Drop-in for agents.** `q.as_tool()` emits a JSON-schema tool definition that Anthropic tool use, OpenAI function-calling and LangChain all consume directly. `searchmux-mcp` runs an MCP stdio server exposing a single `find` tool, so an MCP client gets all 24 engines behind one tool instead of a hundred:

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

90 tests, and **every one passes with `SERPAPI_API_KEY` unset**. CI enforces it by explicitly clearing the variable on Python 3.11, 3.12 and 3.13 — if a test needs the network, it is a mis-written test. There is no signup between you and a green suite.

---

## How SerpApi is used

SearchMux has no reason to exist without SerpApi: every engine definition, parameter schema, and response shape in it describes SerpApi's API, and the library's entire job is getting requests to the right SerpApi endpoint and results back in a usable shape.

`searchmux/catalog.json` currently catalogues **24 engines** — the Google families (search, shopping, scholar, news, maps, local, flights, hotels, jobs, trends, images, videos, patents, finance, events, lens, autocomplete) plus YouTube, Bing, DuckDuckGo, Amazon, eBay, Walmart and Yelp. Every parameter was verified against the published SerpApi documentation rather than guessed; `amazon` takes `k`, `ebay` takes `_nkw`, `walmart` takes `query`, `yelp` requires `find_loc`.

Adding an engine is one JSON record and zero code, so catalogue breadth is a knob rather than a ceiling. The catalog is generated at build time and committed, so the library never does network I/O to resolve a schema and works fully offline.

### Known limitations

Stated plainly rather than discovered later:

- **24 engines, not 100+.** The remaining engines are additive JSON records; the routing and pipeline work is engine-agnostic.
- **`google_play` is deliberately not catalogued.** Its results nest as `organic_results[].items[]`, a list of lists that a flat results path cannot express. Listing an engine that silently returns nothing is worse than not listing it.
- **`google_trends` returns timeline entries, not links.** It is a time series, so `Result.title` carries the date and the values live in `Result.raw`.
- **`examples/demo_cassette.json` is a real SerpApi capture**, trimmed to the first 3 results per engine and the fields the normalizer reads, with no credentials or search ids retained. `python examples/pixel_agent.py --offline` forces the free replay path even when a key is present.
- **CrewAI and LlamaIndex** consume the emitted JSON-schema tool definition and should work by construction, but only the schema shape is tested here — treat them as unverified rather than supported.

---

## AI tool disclosure

Per the hackathon rules: this project was built with **Claude Code (Claude Opus 5)** used for design, implementation, test authoring, and documentation, including parallel subagents for independent modules and for verifying catalog parameters against SerpApi's published docs. All architectural decisions, the evaluation methodology, and the scope calls documented above were directed by the authors. Every figure in the results table is a real run of `evals/run_eval.py` against the live API, including the one that disproved our own starting thesis. None are estimates.

## Team

Built by **Vikas Sharma** and **Manisha Choudhary** for the SerpApi India Hackathon 2026, in the Open-Source Integrations track.

## License

MIT — see [LICENSE](LICENSE).
