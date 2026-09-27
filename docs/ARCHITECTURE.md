# Architecture

How SearchMux is put together, and why each piece is shaped the way it is.

For the public API surface see [API.md](API.md). For the engine catalog see [ENGINES.md](ENGINES.md).

---

## The pipeline

Every search takes the same path. Stages 2, 3 and 6 are middleware over a transport core; stage 1 is optional and skipped entirely when the caller names an engine.

```
intent: str
   │
   ▼
[1] Router          resolve intent → (engine_id, params)      router.py
   │
   ▼
[2] Cache lookup    hit? return, cost 0                       cache.py
   │ miss
   ▼
[3] Budget guard    raise BudgetExceeded BEFORE spending      budget.py
   │
   ▼
[4] Transport       httpx → serpapi.com/search                transport.py
   │                  …or replay from a cassette              cassette.py
   ▼
[5] Normalizer      engine envelope → list[Result]            normalize.py
   │
   ▼
[6] Cache write     persist, keyed by canonical request hash  cache.py
```

`client.py` owns the pipeline; every other module is independently testable and knows nothing about the others.

## Modules

| Module | Responsibility |
|---|---|
| `client.py` | The `SearchMux` facade. Owns the pipeline and nothing else. |
| `catalog.py` / `catalog.json` | Engine metadata: parameters, result envelope, cache class. |
| `router.py` | Intent → engine. BM25 retrieval plus schema-bound synthesis. |
| `llm.py` | Anthropic structured-output client. Used only by the router. |
| `cache.py` | SQLite response cache and the canonical request key. |
| `budget.py` | Thread-safe credit ceiling. |
| `cassette.py` | Record and replay, so tests cost nothing. |
| `normalize.py` | Engine-specific envelopes → one `Result` shape. |
| `transport.py` | HTTP, with retry on server errors only. |
| `models.py` | `Result`, `Money`, and the exception hierarchy. |
| `envfile.py` | Opt-in `.env` loading. Never called on import. |
| `adapters/` | Tool-schema emission and the MCP server. |

---

## Design decisions

### The catalog is generated, then committed

`catalog.json` is built at build time by `scripts/build_catalog.py` and checked into the repository. Nothing resolves a schema over the network at runtime.

The library is therefore importable offline, deterministic across machines, and reproducible for anyone reviewing it. Adding an engine is one JSON record and zero lines of code.

### Routing is off by default, because measurement said so

The original thesis was that narrowing 100+ engines to a handful before the model sees them would beat handing it everything. **The evaluation disproved that.**

BM25 narrowing to five scored 82%, which is exactly its own retrieval recall@5 of 82%. The model chose correctly from every shortlist it received; the shortlist was simply missing the right engine 18% of the time. Recall measured 52 / 72 / 82 / 86 / 88 / 100% at k = 1 / 3 / 5 / 8 / 12 / 24.

The premise that agents degrade past 20–30 tools does not bind at 24 engines. `DEFAULT_ROUTER_TOP_K` is therefore `None`, meaning no narrowing. `Router(top_k=12)` remains available for catalogs large enough that prompt size, rather than accuracy, becomes the binding cost.

### Parameters travel as name/value pairs

A schema built from every engine's parameters is rejected by the Anthropic API with `Schema is too complex`. Parameter validity cannot be bought by brute force.

So `params` is a fixed-size array of `{name, value}` objects. The schema stays the same size however large the catalog grows, and parameter names are checked against the chosen engine afterwards in `Router._validate`, with one repair attempt before raising.

This reaches the same 98% engine accuracy as an unschema'd baseline while also guaranteeing the parameter shape, which the baseline does not.

### Structured outputs need every object closed

`additionalProperties: false` is required on **nested** object schemas too, not just the root. A missed nested object produces a 400 at call time, not at definition time. `tests/test_router.py` walks the built schema recursively and asserts every object level is closed.

### The cache key excludes secrets

`request_key()` hashes canonical JSON of `(engine_id, sorted params)` with every key in `SECRET_PARAM_KEYS` removed. Three consequences:

- Two users with different API keys share cache entries.
- No key text can reach the digest input, so a key cannot leak through a cache file.
- Cassettes, which reuse the same function, match regardless of which key recorded them.

Parameters are sorted and encoded with `ensure_ascii=False`, so key order and non-ASCII queries both hash deterministically. A cache that silently never hits would make every call billable, which is the exact failure the library exists to prevent.

### The budget is checked before the request

`Budget.spend()` performs check-and-increment inside a single lock acquisition. Doing it in two acquisitions is the bug the concurrency test exists to catch: twenty threads against a budget of ten must yield exactly ten successes.

The check precedes the HTTP call rather than following it. The point is not to spend the credit.

### A replay miss raises

In replay mode, a request absent from the cassette raises `CassetteMiss` and **never** falls through to the network. This is the detail that makes offline tests honest — without it, a test could silently start costing money when someone changes a query string.

`api_key` is stripped when a cassette is written, so cassettes are safe to commit. Committing them is the point: it is what lets a reviewer run the suite with no account.

### Currency is derived, never invented

SerpApi frequently reports `currency` as `null` and carries the symbol inside the price text (`₹67,400`). An earlier version defaulted to `"USD"`, which misreported money.

`Money.currency` is now optional. The normalizer uses the engine's currency field when present, falls back to the symbol extracted from the price text, and otherwise leaves it `None`. An unknown currency stays unknown.

### Result envelopes may nest

`results_key` supports a dotted path, so `interest_over_time.timeline_data` resolves correctly. Any missing segment yields `[]` rather than raising, because SerpApi omits the key entirely when a search returns nothing, and that is not an error.

`google_play` is deliberately absent from the catalog: its results nest as `organic_results[].items[]`, a list of lists no flat or dotted path can express. Listing an engine that silently returns nothing is worse than not listing it.

---

## Testing strategy

The whole suite runs with **no API key**, enforced in CI by clearing `SERPAPI_API_KEY` and `ANTHROPIC_API_KEY` on Python 3.11, 3.12 and 3.13.

| Layer | What it covers |
|---|---|
| Unit | Cache key canonicalization, TTL boundaries, budget arithmetic and thread-safety, per-engine normalization, cassette round-trips |
| Integration | The full pipeline against `httpx.MockTransport` and against cassettes |
| Contract | `test_sdk_compat.py` asserts the installed `anthropic` SDK accepts the parameters the router sends |
| Safety | `test_no_secrets.py` scans every **git-tracked** file for key-shaped strings and asserts `.env` is untracked |

`test_sdk_compat.py` exists because the LLM client's unit tests inject a fake. A fake cannot catch an SDK too old to accept `output_config` — `anthropic` 0.40 parses the call and rejects it at runtime. The contract test fails at install time instead, which is why `requirements.txt` pins `>=1.8`.

## Dependencies

| Package | Needed for |
|---|---|
| `httpx` | Transport |
| `pydantic` | Schema validation |
| `rank-bm25` | Optional retrieval, only when `top_k` is set |
| `anthropic>=1.8` | Optional, router only |
| `mcp>=2` | Optional, `searchmux-mcp` only |

The cache uses the standard library's `sqlite3`. There is no embedding model and no vector store.

Only `find()` without a pinned engine needs an LLM. The pinned path, the cache, the budget guard and cassettes all work with `httpx` plus the standard library.
