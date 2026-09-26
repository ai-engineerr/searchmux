# Quiver

**The search layer for AI agents over SerpApi.** Describe what you want to know; Quiver picks the right engine, caches the answer, meters the spend, and makes the whole thing testable offline.

```python
from quiver import Quiver

q = Quiver(budget=50)
results = q.find("current Pixel 10 prices in India")
# -> routed to google_shopping, params filled in, normalized Results back
```

---

## The problem

SerpApi exposes 100+ search engines. Each has its own parameter vocabulary and its own response envelope key — `organic_results`, `shopping_results`, `news_results`, `video_results`. Three consequences, none of them currently solved:

**Engine selection doesn't work at scale.** LLM agents degrade past roughly 20–30 tools. SerpApi's own `serpapi-search-tools-python` exposes 9 engines out of 100+. `serpapi-mcp` takes the opposite approach — one generic `search` tool where the model must name the engine and invent parameters unaided — so in practice it defaults to plain `google` for everything, or picks a plausible-but-wrong engine. Every wrong attempt costs a credit.

**Development is unaffordable.** A free SerpApi account carries 250 search credits per month. An agent making 4 searches per run, executed 40 times over an afternoon of debugging, burns 160 of them. There is no caching layer, so the second identical request costs exactly as much as the first.

**SerpApi-backed agents are effectively untestable.** A 30-test suite at 3 searches per test costs 90 credits per CI run, so the rational choice is to not write tests. Across the 120 projects in the BuiltWithSerpApi gallery, none ship a test suite that exercises a search path.

Quiver is the layer underneath all three.

---

## Measured results

Routing accuracy on [`evals/routing.jsonl`](evals/routing.jsonl) — 50 hand-labelled intents spanning every catalogued engine, phrased the way a user would phrase them, never naming the engine. Cases where the ambiguity is genuine (a plain web question really could go to Google, Bing, or DuckDuckGo) accept any of the reasonable engines; forcing one answer would measure the label rather than the router.

| arm | n | correct | accuracy |
| --- | --- | --- | --- |
| random choice over 24 engines | — | — | ~4% |
| **bm25-top1 (no LLM, no cost)** | **50** | **26** | **52%** |
| baseline (all engine names, no schemas) | 50 | — | needs a key |
| quiver (bm25 top-5 + schema-bound synthesis) | 50 | — | needs a key |

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
from quiver import Quiver

q = Quiver(budget=50)

# Routed: Quiver picks the engine and fills the params.
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
offline mode: replaying the synthetic demo cassette

prices    3 results
          - Google Pixel 10 (128GB, Obsidian)  [INR 79999.00]
news      2 results
reviews   2 results
trend     3 results

recommendation: cheapest 71,499 INR, spread 18,500, interest cooling -> wait
cost: {'credits_used': 0, 'remaining': 8, 'by_engine': {}, 'cache_hits': 4}
```

---

## What it does

**Intent router.** BM25 scores your intent against every engine's description and narrows 24 candidates to 5 for free — no model, no network, no credits. Only then does an LLM see those 5, *with their full parameter schemas*, and choose. An LLM picking among five fully-specified options beats an LLM picking among a hundred bare names, which is what a single generic search tool asks of it. Pin an engine and the whole stage is skipped.

**Transparent cache.** `sqlite3` from the standard library, no server, no new dependency. The key is a SHA-256 of the canonical request with `api_key` excluded, so it is portable across keys and machines, and identical queries in a dev loop cost nothing after the first. TTL is set per engine class: prices and flights expire in 15 minutes, news in an hour, patents and papers in 30 days.

**Budget guard.** A hard ceiling checked *before* the request, not after — the point is to not spend the credit. Thread-safe: check-and-increment happens under one lock, so twenty concurrent callers against a budget of ten get exactly ten successes.

**Record & replay.** Capture real responses once to a cassette file, then replay them forever in tests and CI at zero cost. A replay miss **raises** rather than falling through to the network, which is what stops a test suite silently becoming billable. `api_key` is stripped on write, so cassettes are safe to commit — and committing them is the point.

**Normalized results.** One `Result` dataclass across every engine, with `raw` always attached so nothing is lost. Swapping Bing for DuckDuckGo stops meaning a rewritten parser.

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

Quiver has no reason to exist without SerpApi: every engine definition, parameter schema, and response shape in it describes SerpApi's API, and the library's entire job is getting requests to the right SerpApi endpoint and results back in a usable shape.

`quiver/catalog.json` currently catalogues **24 engines** — the Google families (search, shopping, scholar, news, maps, local, flights, hotels, jobs, trends, images, videos, patents, finance, events, lens, autocomplete) plus YouTube, Bing, DuckDuckGo, Amazon, eBay, Walmart and Yelp. Every parameter was verified against the published SerpApi documentation rather than guessed; `amazon` takes `k`, `ebay` takes `_nkw`, `walmart` takes `query`, `yelp` requires `find_loc`.

Adding an engine is one JSON record and zero code, so catalogue breadth is a knob rather than a ceiling. The catalog is generated at build time and committed, so the library never does network I/O to resolve a schema and works fully offline.

### Known limitations

Stated plainly rather than discovered later:

- **24 engines, not 100+.** The remaining engines are additive JSON records; the routing and pipeline work is engine-agnostic.
- **`google_play` is deliberately not catalogued.** Its results nest as `organic_results[].items[]`, a list of lists that a flat results path cannot express. Listing an engine that silently returns nothing is worse than not listing it.
- **`google_trends` returns timeline entries, not links.** It is a time series, so `Result.title` carries the date and the values live in `Result.raw`.
- **`examples/demo_cassette.json` is a hand-written synthetic fixture, not a real capture.** It exists so the demo runs on a fresh clone with no key. Record a real one with `Quiver.record()`; the format is identical.
- **CrewAI and LlamaIndex** consume the emitted JSON-schema tool definition and should work by construction, but only the schema shape is tested here — treat them as unverified rather than supported.

---

## AI tool disclosure

Per the hackathon rules: this project was built with **Claude Code (Claude Opus 5)** used for design, implementation, test authoring, and documentation, including parallel subagents for independent modules and for verifying catalog parameters against SerpApi's published docs. All architectural decisions, the evaluation methodology, and the scope calls documented above were directed by the author. The measured 52% figure is a real run of `evals/run_eval.py`, not an estimate.

## License

MIT — see [LICENSE](LICENSE).
