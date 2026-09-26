# SearchMux — Design Spec

**Date:** 2026-09-26
**Target:** SerpApi India Hackathon 2026, submission deadline 2026-10-05 23:59 IST
**Track:** Open-Source Integrations
**Status:** Approved, ready for implementation planning

---

## 1. Problem

SerpApi exposes 100+ search engines. Every engine has its own parameter vocabulary and its own response envelope key (`organic_results`, `shopping_results`, `news_results`, `video_results`, ...). Three consequences follow, and all three are unsolved in the existing ecosystem:

**Engine selection does not work at scale.** LLM agents degrade past roughly 20-30 tools. SerpApi's own `serpapi-search-tools-python` exposes 9 engines out of 100+, and `serpapi-mcp` takes the opposite approach: a single generic `search` tool where the model must name the engine and synthesise parameters unaided. In practice the model defaults to plain `google` for everything, picks a plausible-but-wrong engine, or hallucinates an engine id outright. Each wrong attempt costs a search credit.

**Development is unaffordable.** A free SerpApi account carries 250 search credits per month. An agent making 4 searches per run, executed 40 times during an afternoon of debugging, consumes 160 credits. There is no caching layer, so the second identical request costs exactly as much as the first.

**SerpApi-backed agents are effectively untestable.** A 30-test suite at 3 searches per test costs 90 credits per CI run. No record/replay facility exists, so the rational response is to not write tests. A survey of the 120 projects in the BuiltWithSerpApi gallery found no test suites exercising search paths.

## 2. What SearchMux is

A Python library interposed between agent code and SerpApi's HTTP API: a request pipeline with pluggable middleware, an intent router in front, and framework adapters behind.

Not an application. No UI, no hosted service, no database beyond a local SQLite cache file. Installed with `pip install searchmux`.

### Non-goals

- Not a SerpApi client replacement. `serpapi-python` stays underneath as transport.
- Not an agent framework. SearchMux supplies tools; orchestration belongs elsewhere.
- No proxying, rate-limit evasion, or ToS circumvention. Caching reduces duplicate billable requests, which is a supported usage pattern, not a bypass.

## 3. Architecture

```
intent: str
   |
   v
[1] Router          intent -> (engine_id, params)
   |
   v
[2] Cache lookup    hit -> return, cost 0
   | miss
   v
[3] Budget guard    raise BudgetExceeded BEFORE spending a credit
   |
   v
[4] Transport       httpx -> serpapi.com/search, OR replay from cassette
   |
   v
[5] Normalizer      engine envelope -> list[Result]
   |
   v
[6] Cache write     persist keyed by canonical request hash
```

Stages 2, 3 and 6 are middleware over a transport core. Stage 1 is optional and bypassed entirely when the caller pins an engine.

## 4. Components

### 4.1 Engine catalog

A generated JSON artifact, one record per engine:

```json
{
  "engine_id": "google_scholar",
  "description": "Academic papers, citations, and scholarly literature",
  "keywords": ["paper", "research", "citation", "academic", "journal"],
  "params": {
    "q":      {"type": "string", "required": true},
    "as_ylo": {"type": "integer", "required": false},
    "num":    {"type": "integer", "required": false, "max": 20}
  },
  "results_key": "organic_results",
  "result_map": {"title": "title", "url": "link", "snippet": "snippet"}
}
```

Generated at build time by `scripts/build_catalog.py` and **committed to the repo**. Runtime never performs network I/O to resolve schemas: the library is deterministic, importable offline, and reproducible for judges.

Scope for v1: ~25 engines covering the high-traffic surface (google, and the shopping / news / scholar / maps / flights / hotels / jobs / trends / youtube / patents / images / videos / local families, plus bing, duckduckgo, amazon, ebay, walmart, yelp). Catalog size is a scaling knob, not a blocker; adding an engine is one JSON record and zero code.

### 4.2 Router

Two stages, deliberately cheap before expensive.

**Stage 1 — candidate retrieval.** BM25 over `description + keywords` for every catalog entry. Returns top-k, k=5 default. Pure Python, no model download, no embedding API, no network. Reduces the candidate set by ~80%.

**Stage 2 — parameter synthesis.** One LLM call carrying *only* the k selected schemas, returning structured output `{engine_id, params}`. Validated against that engine's param schema. On validation failure: one repair attempt with the error attached, then raise `RoutingError`. Never silently guess.

The thesis in one line: *an LLM choosing among 5 scored candidates with full schemas outperforms an LLM choosing among 100+ with none.* Section 8 measures it.

BM25 is the starting point specifically because engine descriptions are unusually literal. Embeddings are a documented upgrade path, taken only if measurement shows keyword retrieval insufficient — not on speculation.

**Deterministic bypass.** `q.find("...", engine="google_scholar")` skips both stages. Zero LLM calls, zero nondeterminism, for callers who already know.

### 4.3 Cache

`sqlite3` from the standard library. No new dependency, no server.

- **Key:** SHA-256 over canonical JSON of `(engine_id, sorted params)` with `api_key` excluded — so the cache is portable across keys and machines.
- **TTL by engine class:** volatile (prices, flights) 15 min; news 1 h; stable (patents, scholar) 30 d. Overridable per call.
- Stores the raw response, not the normalized form, so normalizer changes do not invalidate a warm cache.

### 4.4 Budget guard

A thread-safe counter checked *before* transport, raising `BudgetExceeded`. Accumulates per-engine spend for `q.report()`. Cache hits do not decrement.

The check must precede the HTTP call, not follow it — the whole point is to not spend the credit.

### 4.5 Record / replay (cassettes)

The VCR pattern, scoped to SerpApi.

- **Record mode:** real requests pass through; raw responses append to a cassette file (JSON), keyed by the same canonical hash as the cache.
- **Replay mode:** served from the cassette. **A miss raises `CassetteMiss` and never falls through to network.** This is the load-bearing detail — it is what stops a test silently becoming billable.
- `api_key` is stripped on write. Cassettes are safe to commit; committing them is the point, since it makes the test suite runnable by a judge with no key.

### 4.6 Surface adapters

Thin, mostly schema emission:

- plain Python: `q.find(intent)` / `q.search(engine=..., **params)`
- `q.as_tool()` -> JSON-schema tool definition consumable by LangChain, CrewAI, LlamaIndex, and OpenAI function-calling
- MCP server exposing a single `find` tool

v1 ships plain Python + MCP + a LangChain-verified `as_tool()`. CrewAI and LlamaIndex are schema-compatible by construction but unverified; the README will say so rather than claiming support.

## 5. Public API

```python
from searchmux import SearchMux

q = SearchMux(api_key=..., budget=50, cache="./.searchmux.db")

results = q.find("current Pixel 10 prices in India")     # routed
results = q.find("Pixel 10", engine="google_shopping")   # pinned, no LLM

for r in results:
    r.title, r.url, r.snippet, r.price, r.source, r.raw

q.report()        # {'credits_used': 4, 'cache_hits': 36, 'by_engine': {...}}

with q.replay("tests/fixtures/pixel.json"):
    ...           # zero credits, offline, raises on miss

with q.record("tests/fixtures/pixel.json"):
    ...           # captures once
```

## 6. Result model

```python
@dataclass(frozen=True, slots=True)
class Result:
    title:    str
    url:      str | None
    snippet:  str | None
    position: int | None
    source:   str | None       # engine_id that produced it
    price:    Money | None     # populated for commerce engines
    extra:    dict             # engine-specific promoted fields
    raw:      dict             # untouched original, nothing is ever lost
```

One shape across engines; `raw` always attached so no field is lost to normalization.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| Budget exhausted | `BudgetExceeded` before transport |
| Router cannot resolve | `RoutingError` after one repair attempt |
| Params fail schema validation | `ValidationError`, engine + offending field named |
| Cassette miss in replay | `CassetteMiss`, never network |
| SerpApi 4xx | `SearchMuxAPIError`, not retried |
| SerpApi 5xx / timeout | 3 retries, exponential backoff, then raise |
| Unknown response envelope | Return `Result` with `raw` only, warn once |

Fail loudly. The failure mode this library exists to prevent is silent spending.

## 8. Evaluation

A labelled set of intents mapped to expected engines, `evals/routing.jsonl`, ~50 entries. Three arms compared:

1. **Baseline** — generic single-tool prompt, all engine ids listed, no schemas (reproduces `serpapi-mcp` behaviour)
2. **BM25 top-1** — retrieval only, no LLM
3. **SearchMux** — BM25 top-5 + schema-constrained LLM synthesis

Reported as engine-selection accuracy plus invalid-parameter rate. Runs offline from cassettes, so a judge can reproduce it with no API key.

This is deliberate: the submission needs a defensible number, not a feature tour. It also settles the BM25-vs-embeddings question with data.

## 9. Testing

- Unit: cache key canonicalization, TTL expiry, budget arithmetic and thread-safety, normalizer per engine, cassette round-trip
- Integration: full pipeline against cassettes, zero credits
- Invariant test: **the entire suite runs with no `SERPAPI_API_KEY` set.** CI enforces this by unsetting it. If a test needs the network, it is mis-written.
- One live smoke test, opt-in via `--live`, excluded from CI

## 10. Layout

```
searchmux/
  __init__.py       SearchMux facade
  catalog.py        load + query the generated catalog
  catalog.json      generated, committed
  router.py         BM25 retrieval + LLM param synthesis
  cache.py          sqlite3 middleware
  budget.py         counter + BudgetExceeded
  cassette.py       record / replay
  normalize.py      envelope -> Result
  transport.py      httpx + retry
  models.py         Result, Money, exceptions
  adapters/
    tool.py         JSON-schema tool emission
    mcp_server.py   MCP entry point
scripts/build_catalog.py
evals/routing.jsonl
tests/
```

## 11. Dependencies

`httpx`, `pydantic` (schema validation + structured output), `rank-bm25` (~200 LOC, vendorable if it becomes a liability). Cache uses stdlib `sqlite3`. No embedding model, no vector store.

**Router LLM.** Pluggable behind a single `LLMClient` protocol with one method: `complete(prompt, schema) -> dict`. Default implementation targets Anthropic (`anthropic` SDK, tool-use for structured output). The protocol exists because the eval in section 8 needs to swap models, not for speculative multi-provider support — one implementation ships.

Note that both `pydantic` and the router LLM are needed *only* for `find()`. The pinned path (`q.find(..., engine=...)`), the cache, the budget guard and cassettes all work with `httpx` plus stdlib. Routing is an opt-in layer, not a hard dependency of the library's core value.

## 12. Sequencing

Ordered so a demoable artifact exists early and every later step is additive.

1. Catalog generator + ~25 engines, `models.py`, `transport.py`
2. Normalizer + `Result` (first real output)
3. Cache (first headline feature)
4. Budget guard (small, high visibility)
5. Router: BM25, then LLM synthesis (the thesis)
6. Cassettes (the judge-facing feature)
7. Eval harness + the number
8. Adapters: `as_tool()` + MCP
9. README, 90-second demo video, submission

Steps 1-6 are the minimum viable submission. Steps 7-8 are what make it win. If time runs short, cut catalog breadth before cutting the eval.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Catalog extraction slower than expected | Ship 25 engines; breadth is a knob, not a gate |
| BM25 retrieval too weak | Eval measures it; embeddings documented as upgrade |
| Router LLM cost during development | Cassettes cover LLM calls too |
| 9-day window | Sequencing above front-loads demoable value |
| Accidental key exposure (disqualifying) | `api_key` stripped on cassette write; CI greps for key patterns |
