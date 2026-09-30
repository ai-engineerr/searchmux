# API reference

Everything public in `searchmux`. For how the pieces fit together see [ARCHITECTURE.md](ARCHITECTURE.md).

```python
from searchmux import SearchMux
```

---

## `SearchMux`

The facade. One instance owns one budget, one cache and one optional router.

```python
SearchMux(
    api_key: str | None = None,
    tavily_api_key: str | None = None,
    brave_api_key: str | None = None,
    exa_api_key: str | None = None,
    budget: int = 50,
    budget_usd: float | None = None,
    cost_per_request: dict[str, float] | None = None,
    cache: str | None = ".searchmux.db",
    transport: Backend | None = None,
    backends: dict[str, Backend] | None = None,
    router: object | None = None,
    no_cache: set[str] | None = None,
)
```

| Argument | Meaning |
|---|---|
| `api_key` | SerpApi key. Falls back to `SERPAPI_API_KEY`. May be `None` when only replaying cassettes. |
| `tavily_api_key` | Tavily key. Falls back to `TAVILY_API_KEY`. |
| `brave_api_key` | Brave key. Falls back to `BRAVE_API_KEY`. |
| `exa_api_key` | Exa key. Falls back to `EXA_API_KEY`. |
| `budget` | Maximum billable requests for this instance. Cache hits and replays do not count. Always active. |
| `budget_usd` | Optional dollar cap, checked alongside `budget`. `None`, the default, disables dollar tracking entirely — every existing caller is unaffected. |
| `cost_per_request` | `{provider: your real cost per request}`, e.g. `{"serpapi": 0.0075}` — your own pricing plan, not a published default. Only consulted when `budget_usd` is set; a provider used with no rate here raises `ValueError` before the request is made. |
| `cache` | SQLite path, or `None` to disable caching. |
| `transport` | Injected SerpApi `Backend`, for tests. Takes precedence over `backends={"serpapi": ...}` when both are given. |
| `backends` | Injected `{provider: Backend}`, for testing Tavily/Brave/Exa without a key. |
| `router` | Anything with `route(intent) -> (engine_id, params)`. |
| `no_cache` | Provider names or engine ids to exclude from caching at runtime, on top of the catalog's own `cacheable` flag. Only narrows — it can never re-enable an engine the catalog marked non-cacheable. |

No network call happens at construction. A missing key raises only when a request actually needs one.

### `search(engine, **params) -> list[Result]`

Run one search against a named engine. Fully deterministic: no LLM, no routing.

```python
q = SearchMux(budget=50)
results = q.search(engine="google_shopping", q="Pixel 10", gl="in")
```

Raises `CatalogError` for an unknown engine, `BudgetExceeded` if the budget is spent, and `SearchMuxAPIError` on a SerpApi error.

### `find(intent, engine=None, providers=None, **params) -> list[Result]`

Resolve plain-language intent to an engine, then search.

```python
q.find("current Pixel 10 prices in India")     # routed, needs a router
q.find("Pixel 10", engine="google_shopping")   # pinned, no LLM at all
```

When `engine` is given, the intent becomes the `q` parameter unless you override it:

```python
q.find("pixel 10 reviews", engine="google")            # q="pixel 10 reviews"
q.find("ignored", engine="google", q="explicit")       # q="explicit"
```

Raises `RoutingError` when no engine is pinned and no router is configured.

`providers` gives routing an ordered fallback chain instead of one unrestricted attempt:

```python
q.find("latest AI research papers", providers=["exa", "serpapi"])
```

Each provider is tried on its own; if that attempt fails — `SearchMuxAPIError`, a missing key, or no matching engine for that provider — the next provider in the list is tried. `None` (the default) considers every provider in a single attempt, exactly as before. There's no automatic "cheapest" mode: sort your own list by your own `cost_per_request` rates for cheapest-first.

### `report() -> dict`

```python
q.report()
# {'credits_used': 4, 'remaining': 46,
#  'by_engine': {'google_shopping': 1, 'google_news': 3},
#  'spent_usd': 0.03, 'remaining_usd': 4.97,  # only when budget_usd is set
#  'cache_hits': 12}
```

### `record(path)` / `replay(path)`

Context managers. `record` captures every live response to a cassette; `replay` serves from one and costs nothing.

```python
with q.record("tests/fixtures/prices.json"):
    q.search(engine="google_shopping", q="Pixel 10")

with q.replay("tests/fixtures/prices.json"):
    q.search(engine="google_shopping", q="Pixel 10")   # 0 credits
```

A replay miss raises `CassetteMiss`; it never falls through to the network. `api_key` is stripped on write, so cassettes are safe to commit, and a cassette recorded with one key replays with any key or none.

### `as_tool() -> dict`

Returns an Anthropic-shaped tool definition. LangChain's structured-tool helpers accept the same flat shape directly.

```python
tools = [q.as_tool()]
```

### `as_openai_tool() -> dict`

Returns the same schema wrapped in OpenAI's function-calling envelope (`{"type": "function", "function": {...}}`), since OpenAI expects a different shape than Anthropic's `input_schema`. Built from `as_tool()` internally, so the two can't drift apart.

```python
tools = [q.as_openai_tool()]
response = openai_client.chat.completions.create(model="gpt-4.1-mini", messages=messages, tools=tools)
```

See [`examples/openai_agent.py`](../examples/openai_agent.py) for a complete working loop.

---

## `Result`

Frozen dataclass. One shape for every engine.

```python
@dataclass(frozen=True, slots=True)
class Result:
    title: str
    url: str | None = None
    snippet: str | None = None
    position: int | None = None
    source: str | None = None      # the engine_id that produced it
    price: Money | None = None     # commerce engines only
    extra: dict = {}               # engine-specific promoted fields
    raw: dict = {}                 # the untouched original item
```

`raw` is always populated. Nothing an engine returns is lost to normalization, so anything the mapping does not promote is still reachable.

## `Money`

```python
@dataclass(frozen=True, slots=True)
class Money:
    amount: float
    currency: str | None = None
```

`currency` is `None` when the engine did not report one. SerpApi often leaves the field null and puts a symbol in the price text, so the normalizer recovers the symbol where it can and otherwise leaves it unknown. **A currency is never guessed.**

```python
str(Money(67400.0, "₹"))    # '₹ 67400.00'
str(Money(1200.0))          # '1200.00'
```

---

## Exceptions

All inherit `SearchMuxError`, so one `except SearchMuxError` catches everything.

| Exception | Raised when |
|---|---|
| `BudgetExceeded` | The budget is spent. Raised **before** the request. |
| `RoutingError` | Intent cannot be resolved, or no router is configured. |
| `CassetteMiss` | A replay has no recording for this request. |
| `SearchMuxAPIError` | SerpApi returned 4xx, or retries were exhausted. |
| `CatalogError` | The engine is not in the catalog. |

`ValueError` is raised if a request needs an API key and none is available.

---

## `Router`

```python
from searchmux.router import Router

Router(llm=None, top_k=None, providers=None)
```

| Argument | Meaning |
|---|---|
| `llm` | Anything with `complete(prompt, schema) -> dict`. Defaults to an Anthropic client, which requires `ANTHROPIC_API_KEY`. |
| `top_k` | How many candidates survive BM25 retrieval. `None`, the default, means no narrowing. |
| `providers` | Restrict every call this router makes to these provider names, e.g. `{"serpapi"}`. `None`, the default, considers every catalogued engine. |

**Narrowing is off by default because it measured worse.** See [ARCHITECTURE.md](ARCHITECTURE.md#routing-is-off-by-default-because-measurement-said-so).

```python
router.retrieve("cheapest flight to Tokyo")   # ranked engine ids, free, no LLM
router.route("cheapest flight to Tokyo")      # ('google_flights', {...}), one LLM call
router.route("cheapest flight to Tokyo", providers={"serpapi"})  # this call only
```

`route()`'s own `providers` argument narrows further than whatever the constructor already allows — it's what `SearchMux.find(providers=[...])` uses internally to build its fallback chain, one provider at a time.

`route()` validates the decision against the chosen engine's schema, drops parameters the engine does not accept, and makes exactly one repair attempt before raising `RoutingError`.

---

## `Catalog`

```python
from searchmux.catalog import get_engine, load_catalog

load_catalog()                    # {engine_id: Engine}
get_engine("google_scholar")      # one Engine, or CatalogError
```

`Engine` carries `engine_id`, `provider`, `description`, `keywords`, `params`, `results_key`, `result_map`, `ttl_class` and `cacheable`. See [ENGINES.md](ENGINES.md).

## `load_env`

```python
from searchmux.envfile import load_env
load_env()          # reads ./.env, returns the names it set
```

Deliberately **not** called on import — a library that silently reads a file from the working directory surprises its callers. Scripts call it; the library itself only reads `os.environ`. Values already set in the environment always win.

---

## MCP server

```bash
pip install -e ".[mcp,router]"
searchmux-mcp
```

Exposes a single `find` tool over stdio. Routing needs `ANTHROPIC_API_KEY`; without it the server still starts, logs a warning, and the tool reports that routing is unconfigured rather than failing obscurely.

## Configuration

Everything lives in `searchmux/constants.py`.

| Constant | Default | Meaning |
|---|---|---|
| `DEFAULT_BUDGET` | `50` | Billable requests per instance |
| `DEFAULT_CACHE_PATH` | `.searchmux.db` | Cache file |
| `DEFAULT_ROUTER_TOP_K` | `None` | No narrowing |
| `TTL_VOLATILE` | `900` | Prices, flights, hotels |
| `TTL_NEWS` | `3600` | News, jobs, videos |
| `TTL_STABLE` | `2592000` | Patents, scholar, maps |
| `HTTP_TIMEOUT` | `30.0` | Per request |
| `HTTP_MAX_RETRIES` | `3` | 5xx and timeouts only; 4xx is never retried |
| `ROUTER_MODEL` | `claude-opus-5` | Set to a cheaper model if routing volume warrants |
