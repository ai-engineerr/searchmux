# SearchMux Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python library that routes plain-language search intent to the right one of SerpApi's 100+ engines, caches results, guards a credit budget, and makes SerpApi-backed agents testable offline.

**Architecture:** A request pipeline — router → cache → budget → transport → normalizer → cache write. Each stage is an independent module with one responsibility. The router is optional and bypassed when the caller pins an engine, so the library's core value has no LLM dependency.

**Tech Stack:** Python 3.11+, `httpx`, `pydantic`, `rank-bm25`, `anthropic` (router only), stdlib `sqlite3` for cache.

**Spec:** `docs/superpowers/specs/2026-09-26-searchmux-design.md`

## Global Constraints

Copied verbatim from the spec and `code-rules/`. Every task's requirements implicitly include this section.

- Python 3.11+ (uses `dataclass(slots=True)` and `X | None` syntax).
- **PEP 8; indent 4 spaces; max line length = 79.**
- Naming: `snake_case` for variables/functions, `CamelCase` for classes, folders in `snake_case`.
- Imports grouped stdlib → third-party → local, no wildcard imports.
- Type hints on all functions, methods, and public APIs.
- Google-style docstrings, concise and accurate.
- Use `logging`, never `print`. Catch specific exceptions; **no bare `except:`**.
- **Never hardcode secrets.** API keys come from `os.getenv()` only.
- **No hardcoded values** — all strings, URLs, and config live in `searchmux/constants.py`.
- Prefer built-ins and stdlib when feasible. No unnecessary abstractions.
- Generate unit-testable code: pure functions, dependency injection for side effects.
- **The entire test suite must pass with `SERPAPI_API_KEY` unset.** CI enforces this.
- Keep `requirements.txt` and `.env.example` current.

## Review Focus

Five failure modes the spec implies but no task's happy-path tests exercise, most likely to bite first. Each has a test assigned to the task that owns the code.

1. **`api_key` leaking into a committed cassette or cache key** — a disqualifying rule violation, not just a bug. A user records a cassette and commits it; the key must not be in the file, and two users with different keys must share cache entries. *Test in Task 5 and Task 7.*
2. **Concurrent budget decrement race** — the spec claims thread-safety. Twenty threads against a budget of 10 must yield exactly 10 successes and 10 `BudgetExceeded`, never 11 spends. *Test in Task 6.*
3. **Engine returns a missing or empty `results_key`** — SerpApi omits the key entirely on zero results. The normalizer must return `[]`, not raise `KeyError`. *Test in Task 4.*
4. **Non-ASCII and key-order variation in the same logical query** — `q="café"` and reordered params must hash identically, or the cache silently never hits and every call costs a credit. *Test in Task 5.*
5. **Cache entry read exactly at its TTL boundary** — an off-by-one on expiry either serves stale prices forever or never hits. Frozen-clock test at `ttl - 1`, `ttl`, `ttl + 1`. *Test in Task 5.*

---

### Task 1: Package skeleton, constants, models

**Files:**
- Create: `searchmux/__init__.py`, `searchmux/constants.py`, `searchmux/models.py`
- Create: `requirements.txt`, `.env.example`, `pyproject.toml`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Result`, `Money`, and the exception hierarchy `SearchMuxError`, `BudgetExceeded`, `RoutingError`, `CassetteMiss`, `SearchMuxAPIError`, `CatalogError`. Every later task imports from `searchmux.models`. Constants `SERPAPI_BASE_URL`, `ENV_API_KEY`, `DEFAULT_CACHE_PATH`, `DEFAULT_BUDGET`, `TTL_BY_CLASS`, `HTTP_TIMEOUT`, `HTTP_MAX_RETRIES` live in `searchmux.constants`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the Result and Money value objects."""

import pytest

from searchmux.models import BudgetExceeded, Money, SearchMuxError, Result


def test_result_keeps_raw_payload() -> None:
    raw = {"title": "Pixel 10", "link": "https://x.test", "junk": 1}
    r = Result(title="Pixel 10", url="https://x.test", raw=raw)
    assert r.raw["junk"] == 1
    assert r.snippet is None


def test_result_is_immutable() -> None:
    r = Result(title="a", raw={})
    with pytest.raises(AttributeError):
        r.title = "b"  # type: ignore[misc]


def test_money_formats_with_currency() -> None:
    assert str(Money(amount=79999.0, currency="INR")) == "INR 79999.00"


def test_budget_exceeded_is_a_searchmux_error() -> None:
    assert issubclass(BudgetExceeded, SearchMuxError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux'`

- [ ] **Step 3: Write minimal implementation**

`searchmux/constants.py`:

```python
"""Project-wide constants. No hardcoded values elsewhere."""

SERPAPI_BASE_URL = "https://serpapi.com/search"
ENV_API_KEY = "SERPAPI_API_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"

DEFAULT_CACHE_PATH = ".searchmux.db"
DEFAULT_BUDGET = 50
DEFAULT_ROUTER_TOP_K = 5

HTTP_TIMEOUT = 30.0
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_BASE = 0.5

# Cache lifetime in seconds, by volatility class.
TTL_VOLATILE = 15 * 60
TTL_NEWS = 60 * 60
TTL_STABLE = 30 * 24 * 60 * 60

TTL_BY_CLASS = {
    "volatile": TTL_VOLATILE,
    "news": TTL_NEWS,
    "stable": TTL_STABLE,
}
DEFAULT_TTL_CLASS = "news"

# Request keys that must never reach a cache key or a cassette file.
SECRET_PARAM_KEYS = frozenset({"api_key", "serp_api_key"})
```

`searchmux/models.py`:

```python
"""Value objects and the exception hierarchy for SearchMux."""

from dataclasses import dataclass, field


class SearchMuxError(Exception):
    """Base class for every error SearchMux raises."""


class BudgetExceeded(SearchMuxError):
    """Raised before a request that would exceed the credit budget."""


class RoutingError(SearchMuxError):
    """Raised when intent cannot be resolved to an engine."""


class CassetteMiss(SearchMuxError):
    """Raised on a replay miss. Never falls through to network."""


class SearchMuxAPIError(SearchMuxError):
    """Raised on a non-retryable SerpApi response."""


class CatalogError(SearchMuxError):
    """Raised when an engine is absent from the catalog."""


@dataclass(frozen=True, slots=True)
class Money:
    """A price with its currency."""

    amount: float
    currency: str

    def __str__(self) -> str:
        """Return the amount formatted with its currency code."""
        return f"{self.currency} {self.amount:.2f}"


@dataclass(frozen=True, slots=True)
class Result:
    """One normalized search result from any engine.

    Attributes:
        title: Display title.
        url: Destination link, when the engine supplies one.
        snippet: Short description or excerpt.
        position: Rank within the engine's own result list.
        source: The engine_id that produced this result.
        price: Populated for commerce engines only.
        extra: Engine-specific fields worth promoting.
        raw: The untouched original item. Nothing is ever lost.
    """

    title: str
    url: str | None = None
    snippet: str | None = None
    position: int | None = None
    source: str | None = None
    price: Money | None = None
    extra: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
```

`searchmux/__init__.py`:

```python
"""SearchMux: the search layer for AI agents over SerpApi."""

from searchmux.models import (
    BudgetExceeded,
    CassetteMiss,
    CatalogError,
    Money,
    SearchMuxAPIError,
    SearchMuxError,
    Result,
    RoutingError,
)

__all__ = [
    "BudgetExceeded",
    "CassetteMiss",
    "CatalogError",
    "Money",
    "SearchMuxAPIError",
    "SearchMuxError",
    "Result",
    "RoutingError",
]
__version__ = "0.1.0"
```

`requirements.txt`:

```
httpx>=0.27
pydantic>=2.7
rank-bm25>=0.2.2
anthropic>=0.40
pytest>=8.0
```

`.env.example`:

```
# Required for live searches. Tests run without it.
SERPAPI_API_KEY=
# Required only for the intent router (q.find without engine=).
ANTHROPIC_API_KEY=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux tests requirements.txt .env.example pyproject.toml
git commit -m "feat: package skeleton, constants, value objects"
```

---

### Task 2: Engine catalog

**Files:**
- Create: `searchmux/catalog.py`, `searchmux/catalog.json`, `scripts/build_catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `CatalogError` from `searchmux.models`; `TTL_BY_CLASS` from `searchmux.constants`.
- Produces: `Engine` dataclass with fields `engine_id: str`, `description: str`, `keywords: list[str]`, `params: dict`, `results_key: str`, `result_map: dict`, `ttl_class: str`. Functions `load_catalog(path: str | None = None) -> dict[str, Engine]` and `get_engine(engine_id: str) -> Engine`. Task 4 uses `results_key`/`result_map`, Task 5 uses `ttl_class`, Task 9 uses `description`/`keywords`/`params`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for catalog loading and lookup."""

import pytest

from searchmux.catalog import get_engine, load_catalog
from searchmux.models import CatalogError


def test_catalog_loads_the_committed_file() -> None:
    catalog = load_catalog()
    assert len(catalog) >= 20
    assert "google" in catalog
    assert "google_shopping" in catalog


def test_engine_exposes_routing_and_parsing_metadata() -> None:
    engine = get_engine("google_scholar")
    assert engine.results_key == "organic_results"
    assert "q" in engine.params
    assert engine.params["q"]["required"] is True
    assert engine.keywords
    assert engine.ttl_class in {"volatile", "news", "stable"}


def test_unknown_engine_raises_catalog_error() -> None:
    with pytest.raises(CatalogError, match="no_such_engine"):
        get_engine("no_such_engine")


def test_every_engine_declares_a_required_param() -> None:
    for engine_id, engine in load_catalog().items():
        required = [
            name
            for name, spec in engine.params.items()
            if spec.get("required")
        ]
        assert required, f"{engine_id} has no required param"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.catalog'`

- [ ] **Step 3: Write minimal implementation**

`searchmux/catalog.py`:

```python
"""Load and query the generated engine catalog."""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from searchmux.constants import DEFAULT_TTL_CLASS
from searchmux.models import CatalogError

logger = logging.getLogger(__name__)

_CATALOG_FILE = Path(__file__).with_name("catalog.json")


@dataclass(frozen=True, slots=True)
class Engine:
    """Metadata describing one SerpApi engine.

    Attributes:
        engine_id: The value SerpApi expects for its `engine` param.
        description: Human-readable purpose, used for BM25 retrieval.
        keywords: Extra retrieval terms.
        params: Param name -> {"type", "required", ...}.
        results_key: Response key holding the result list.
        result_map: Result field -> source key in the raw item.
        ttl_class: Cache volatility class.
    """

    engine_id: str
    description: str
    keywords: list[str]
    params: dict
    results_key: str
    result_map: dict
    ttl_class: str = DEFAULT_TTL_CLASS


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> dict[str, Engine]:
    """Return every catalogued engine, keyed by engine_id.

    Args:
        path: Optional override for the catalog file location.

    Returns:
        Mapping of engine_id to Engine.

    Raises:
        CatalogError: If the catalog file is missing or malformed.
    """
    target = Path(path) if path else _CATALOG_FILE
    try:
        records = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"catalog not found at {target}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"catalog at {target} is not valid JSON") from exc

    catalog = {}
    for record in records:
        engine = Engine(
            engine_id=record["engine_id"],
            description=record["description"],
            keywords=record.get("keywords", []),
            params=record["params"],
            results_key=record["results_key"],
            result_map=record.get("result_map", {}),
            ttl_class=record.get("ttl_class", DEFAULT_TTL_CLASS),
        )
        catalog[engine.engine_id] = engine

    logger.debug("loaded %d engines from %s", len(catalog), target)
    return catalog


def get_engine(engine_id: str) -> Engine:
    """Return one engine by id.

    Args:
        engine_id: The SerpApi engine identifier.

    Returns:
        The matching Engine.

    Raises:
        CatalogError: If no such engine is catalogued.
    """
    try:
        return load_catalog()[engine_id]
    except KeyError as exc:
        raise CatalogError(f"unknown engine: {engine_id}") from exc
```

`searchmux/catalog.json` — seed with these 25 records. Full shape shown for the first three; follow the identical shape for the rest.

```json
[
  {
    "engine_id": "google",
    "description": "General web search across the whole internet",
    "keywords": ["web", "general", "anything", "google", "search"],
    "params": {
      "q": {"type": "string", "required": true},
      "gl": {"type": "string", "required": false},
      "hl": {"type": "string", "required": false},
      "num": {"type": "integer", "required": false}
    },
    "results_key": "organic_results",
    "result_map": {
      "title": "title", "url": "link", "snippet": "snippet",
      "position": "position"
    },
    "ttl_class": "news"
  },
  {
    "engine_id": "google_shopping",
    "description": "Retail product listings with current prices, sellers, and ratings",
    "keywords": ["price", "buy", "cost", "product", "shopping", "cheap", "deal"],
    "params": {
      "q": {"type": "string", "required": true},
      "gl": {"type": "string", "required": false},
      "hl": {"type": "string", "required": false}
    },
    "results_key": "shopping_results",
    "result_map": {
      "title": "title", "url": "product_link", "snippet": "snippet",
      "position": "position", "price": "extracted_price",
      "currency": "currency", "source": "source"
    },
    "ttl_class": "volatile"
  },
  {
    "engine_id": "google_scholar",
    "description": "Academic papers, citations, and scholarly literature",
    "keywords": ["paper", "research", "citation", "academic", "journal", "study"],
    "params": {
      "q": {"type": "string", "required": true},
      "as_ylo": {"type": "integer", "required": false},
      "as_yhi": {"type": "integer", "required": false},
      "num": {"type": "integer", "required": false, "max": 20}
    },
    "results_key": "organic_results",
    "result_map": {
      "title": "title", "url": "link", "snippet": "snippet",
      "position": "position"
    },
    "ttl_class": "stable"
  }
]
```

Remaining 22 engines to add, with `results_key` and `ttl_class`:

| engine_id | results_key | ttl_class | description focus |
|---|---|---|---|
| `google_news` | `news_results` | `news` | recent news articles and coverage |
| `google_maps` | `local_results` | `stable` | places, businesses, addresses, ratings |
| `google_local` | `local_results` | `stable` | nearby businesses in a locality |
| `google_flights` | `best_flights` | `volatile` | airline routes, fares, schedules |
| `google_hotels` | `properties` | `volatile` | hotel availability and nightly rates |
| `google_jobs` | `jobs_results` | `news` | job postings and openings |
| `google_trends` | `interest_over_time` | `news` | search interest over time |
| `google_images` | `images_results` | `stable` | pictures and visual references |
| `google_videos` | `video_results` | `news` | video clips across the web |
| `google_patents` | `organic_results` | `stable` | patents and inventions |
| `google_finance` | `markets` | `volatile` | stock quotes and market data |
| `google_events` | `events_results` | `news` | upcoming local events |
| `google_play` | `organic_results` | `stable` | Android apps and games |
| `google_lens` | `visual_matches` | `stable` | reverse image lookup |
| `google_autocomplete` | `suggestions` | `news` | query suggestions |
| `youtube` | `video_results` | `news` | YouTube videos and reviews |
| `bing` | `organic_results` | `news` | Bing web search |
| `duckduckgo` | `organic_results` | `news` | privacy-preserving web search |
| `amazon` | `organic_results` | `volatile` | Amazon marketplace listings |
| `ebay` | `organic_results` | `volatile` | eBay auctions and used goods |
| `walmart` | `organic_results` | `volatile` | Walmart inventory and prices |
| `yelp` | `organic_results` | `stable` | restaurant and service reviews |

`scripts/build_catalog.py` — regenerates `catalog.json` from SerpApi docs. It must be runnable but is not on the critical path; keep it to fetching each engine's doc page and emitting the param table, with the hand-written `description`, `keywords`, `result_map`, and `ttl_class` preserved from the existing file by merging on `engine_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_catalog.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/catalog.py searchmux/catalog.json scripts tests/test_catalog.py
git commit -m "feat: engine catalog with 25 seeded engines"
```

---

### Task 3: Transport

**Files:**
- Create: `searchmux/transport.py`
- Test: `tests/test_transport.py`

**Interfaces:**
- Consumes: `SERPAPI_BASE_URL`, `HTTP_TIMEOUT`, `HTTP_MAX_RETRIES`, `HTTP_BACKOFF_BASE` from `searchmux.constants`; `SearchMuxAPIError` from `searchmux.models`.
- Produces: `Transport` class with `__init__(self, api_key: str, client: httpx.Client | None = None)` and `fetch(self, engine_id: str, params: dict) -> dict` returning the raw decoded JSON body. Tasks 5, 6, 7 and 8 wrap this.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the SerpApi transport layer."""

import httpx
import pytest

from searchmux.models import SearchMuxAPIError
from searchmux.transport import Transport


def _transport(handler: httpx.MockTransport) -> Transport:
    client = httpx.Client(transport=handler)
    return Transport(api_key="test-key", client=client)


def test_fetch_sends_engine_and_api_key() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"organic_results": []})

    _transport(httpx.MockTransport(handler)).fetch("google", {"q": "x"})
    assert seen["engine"] == "google"
    assert seen["api_key"] == "test-key"
    assert seen["q"] == "x"


def test_four_xx_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(SearchMuxAPIError, match="bad key"):
        _transport(httpx.MockTransport(handler)).fetch("google", {"q": "x"})
    assert calls["n"] == 1


def test_five_xx_retries_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    t = _transport(httpx.MockTransport(handler))
    with pytest.raises(SearchMuxAPIError):
        t.fetch("google", {"q": "x"})
    assert calls["n"] == 3


def test_five_xx_then_success_returns_body() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"organic_results": [{"a": 1}]})

    body = _transport(httpx.MockTransport(handler)).fetch("google", {"q": "x"})
    assert body["organic_results"] == [{"a": 1}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.transport'`

- [ ] **Step 3: Write minimal implementation**

```python
"""HTTP transport for SerpApi, with retry on server errors."""

import logging
import time

import httpx

from searchmux.constants import (
    HTTP_BACKOFF_BASE,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERPAPI_BASE_URL,
)
from searchmux.models import SearchMuxAPIError

logger = logging.getLogger(__name__)


class Transport:
    """Performs SerpApi HTTP requests.

    Retries 5xx and timeouts with exponential backoff. Never retries
    4xx, because a bad request stays bad and each attempt is billable.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store credentials and the HTTP client.

        Args:
            api_key: SerpApi key.
            client: Injected client, for tests. A default is built
                when omitted.
        """
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=HTTP_TIMEOUT)

    def fetch(self, engine_id: str, params: dict) -> dict:
        """Run one search and return the raw decoded body.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters, without api_key or engine.

        Returns:
            The decoded JSON response body.

        Raises:
            SearchMuxAPIError: On a 4xx, or after retries are exhausted.
        """
        query = {**params, "engine": engine_id, "api_key": self._api_key}
        last_error: Exception | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            try:
                response = self._client.get(SERPAPI_BASE_URL, params=query)
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "timeout on %s, attempt %d", engine_id, attempt + 1
                )
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code < 500:
                    raise SearchMuxAPIError(
                        f"{engine_id} returned {response.status_code}: "
                        f"{self._error_text(response)}"
                    )
                last_error = SearchMuxAPIError(
                    f"{engine_id} returned {response.status_code}"
                )
                logger.warning(
                    "server error on %s, attempt %d", engine_id, attempt + 1
                )

            if attempt < HTTP_MAX_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_BASE * (2**attempt))

        raise SearchMuxAPIError(
            f"{engine_id} failed after {HTTP_MAX_RETRIES} attempts"
        ) from last_error

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """Return SerpApi's error message, or the raw body."""
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_transport.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/transport.py tests/test_transport.py
git commit -m "feat: SerpApi transport with 5xx retry, no 4xx retry"
```

---

### Task 4: Normalizer

**Files:**
- Create: `searchmux/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `get_engine` and `Engine` from `searchmux.catalog`; `Money`, `Result` from `searchmux.models`.
- Produces: `normalize(engine_id: str, body: dict) -> list[Result]`. Task 8 calls it.

- [ ] **Step 1: Write the failing test**

Covers Review Focus item 3 — a missing `results_key` must yield `[]`, not raise.

```python
"""Tests for envelope normalization across engines."""

from searchmux.normalize import normalize


def test_organic_results_map_to_common_shape() -> None:
    body = {
        "organic_results": [
            {
                "title": "A paper",
                "link": "https://x.test/a",
                "snippet": "about things",
                "position": 1,
            }
        ]
    }
    results = normalize("google_scholar", body)
    assert len(results) == 1
    assert results[0].title == "A paper"
    assert results[0].url == "https://x.test/a"
    assert results[0].position == 1
    assert results[0].source == "google_scholar"
    assert results[0].price is None


def test_shopping_results_populate_price() -> None:
    body = {
        "shopping_results": [
            {
                "title": "Pixel 10",
                "product_link": "https://x.test/p",
                "extracted_price": 79999.0,
                "currency": "INR",
                "source": "Flipkart",
            }
        ]
    }
    result = normalize("google_shopping", body)[0]
    assert result.price is not None
    assert result.price.amount == 79999.0
    assert result.price.currency == "INR"
    assert result.extra["seller"] == "Flipkart"


def test_missing_results_key_returns_empty_list() -> None:
    assert normalize("google", {"search_metadata": {"status": "Success"}}) == []


def test_empty_results_key_returns_empty_list() -> None:
    assert normalize("google", {"organic_results": []}) == []


def test_raw_item_is_always_preserved() -> None:
    body = {"organic_results": [{"title": "t", "link": "u", "odd": 9}]}
    assert normalize("google", body)[0].raw["odd"] == 9


def test_item_without_title_is_skipped_not_fatal() -> None:
    body = {"organic_results": [{"link": "u"}, {"title": "ok", "link": "v"}]}
    results = normalize("google", body)
    assert [r.title for r in results] == ["ok"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.normalize'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Map engine-specific response envelopes onto Result."""

import logging

from searchmux.catalog import Engine, get_engine
from searchmux.models import Money, Result

logger = logging.getLogger(__name__)


def normalize(engine_id: str, body: dict) -> list[Result]:
    """Convert a raw SerpApi body into common Result objects.

    A missing or empty results key yields an empty list: SerpApi omits
    the key entirely when a search returns nothing, and that is not an
    error.

    Args:
        engine_id: The engine that produced this body.
        body: Raw decoded SerpApi response.

    Returns:
        Normalized results, in the engine's own order.
    """
    engine = get_engine(engine_id)
    items = body.get(engine.results_key)

    if not items:
        logger.debug("no %s in %s response", engine.results_key, engine_id)
        return []
    if isinstance(items, dict):
        items = [items]

    results = []
    for item in items:
        result = _build_result(engine, item)
        if result is not None:
            results.append(result)
    return results


def _build_result(engine: Engine, item: dict) -> Result | None:
    """Return one Result, or None when the item has no title."""
    mapping = engine.result_map
    title = item.get(mapping.get("title", "title"))
    if not title:
        logger.debug("skipping %s item without a title", engine.engine_id)
        return None

    return Result(
        title=str(title),
        url=item.get(mapping.get("url", "link")),
        snippet=item.get(mapping.get("snippet", "snippet")),
        position=item.get(mapping.get("position", "position")),
        source=engine.engine_id,
        price=_build_money(mapping, item),
        extra=_build_extra(mapping, item),
        raw=item,
    )


def _build_money(mapping: dict, item: dict) -> Money | None:
    """Return a Money when the engine maps a price field."""
    amount = item.get(mapping.get("price", "__absent__"))
    if amount is None:
        return None
    try:
        return Money(
            amount=float(amount),
            currency=str(item.get(mapping.get("currency"), "") or "USD"),
        )
    except (TypeError, ValueError):
        logger.debug("unparseable price %r", amount)
        return None


def _build_extra(mapping: dict, item: dict) -> dict:
    """Promote engine-specific fields worth surfacing."""
    extra = {}
    seller = item.get(mapping.get("source", "__absent__"))
    if seller:
        extra["seller"] = seller
    return extra
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/normalize.py tests/test_normalize.py
git commit -m "feat: normalize engine envelopes onto a common Result"
```

---

### Task 5: Cache

**Files:**
- Create: `searchmux/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: `SECRET_PARAM_KEYS`, `TTL_BY_CLASS`, `DEFAULT_TTL_CLASS` from `searchmux.constants`.
- Produces: `request_key(engine_id: str, params: dict) -> str` (a module-level pure function, reused by Task 7 for cassette keys) and `Cache` class with `__init__(self, path: str, now: Callable[[], float] = time.time)`, `get(self, key: str, ttl: int) -> dict | None`, `set(self, key: str, body: dict) -> None`, `close(self) -> None`.

- [ ] **Step 1: Write the failing test**

Covers Review Focus items 1, 4 and 5.

```python
"""Tests for cache keying and the SQLite cache."""

from searchmux.cache import Cache, request_key


def test_key_ignores_param_order() -> None:
    a = request_key("google", {"q": "x", "gl": "in"})
    b = request_key("google", {"gl": "in", "q": "x"})
    assert a == b


def test_key_excludes_the_api_key() -> None:
    with_key = request_key("google", {"q": "x", "api_key": "secret-1"})
    other_key = request_key("google", {"q": "x", "api_key": "secret-2"})
    bare = request_key("google", {"q": "x"})
    assert with_key == other_key == bare


def test_key_never_contains_the_secret() -> None:
    key = request_key("google", {"q": "x", "api_key": "secret-1"})
    assert "secret-1" not in key


def test_key_handles_non_ascii_queries() -> None:
    a = request_key("google", {"q": "café"})
    b = request_key("google", {"q": "café"})
    assert a == b
    assert a != request_key("google", {"q": "cafe"})


def test_key_separates_engines() -> None:
    assert request_key("google", {"q": "x"}) != request_key(
        "bing", {"q": "x"}
    )


def test_set_then_get_round_trips(tmp_path) -> None:
    cache = Cache(str(tmp_path / "c.db"))
    cache.set("k", {"organic_results": [{"a": 1}]})
    assert cache.get("k", ttl=60) == {"organic_results": [{"a": 1}]}
    cache.close()


def test_get_returns_none_on_miss(tmp_path) -> None:
    cache = Cache(str(tmp_path / "c.db"))
    assert cache.get("absent", ttl=60) is None
    cache.close()


def test_ttl_boundary_is_inclusive(tmp_path) -> None:
    clock = {"t": 1000.0}
    cache = Cache(str(tmp_path / "c.db"), now=lambda: clock["t"])
    cache.set("k", {"v": 1})

    clock["t"] = 1059.0
    assert cache.get("k", ttl=60) is not None
    clock["t"] = 1060.0
    assert cache.get("k", ttl=60) is not None
    clock["t"] = 1061.0
    assert cache.get("k", ttl=60) is None
    cache.close()


def test_set_overwrites_and_refreshes_timestamp(tmp_path) -> None:
    clock = {"t": 0.0}
    cache = Cache(str(tmp_path / "c.db"), now=lambda: clock["t"])
    cache.set("k", {"v": 1})
    clock["t"] = 100.0
    cache.set("k", {"v": 2})
    assert cache.get("k", ttl=60) == {"v": 2}
    cache.close()


def test_cache_persists_across_instances(tmp_path) -> None:
    path = str(tmp_path / "c.db")
    first = Cache(path)
    first.set("k", {"v": 1})
    first.close()

    second = Cache(path)
    assert second.get("k", ttl=3600) == {"v": 1}
    second.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.cache'`

- [ ] **Step 3: Write minimal implementation**

```python
"""SQLite-backed response cache, keyed by canonical request hash."""

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable

from searchmux.constants import SECRET_PARAM_KEYS

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    stored_at  REAL NOT NULL
)
"""


def request_key(engine_id: str, params: dict) -> str:
    """Return a stable hash identifying one logical request.

    Secret parameters are excluded, so the key is portable across API
    keys and safe to write into a committed file. Params are sorted and
    JSON-encoded with ensure_ascii off, so key order and non-ASCII text
    both hash deterministically.

    Args:
        engine_id: SerpApi engine identifier.
        params: Engine parameters, secrets included or not.

    Returns:
        A hex SHA-256 digest.
    """
    safe = {
        name: value
        for name, value in params.items()
        if name not in SECRET_PARAM_KEYS
    }
    canonical = json.dumps(
        [engine_id, sorted(safe.items())],
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cache:
    """Stores raw SerpApi bodies so repeat requests cost no credits.

    Raw bodies are stored rather than normalized results, so changing
    the normalizer does not invalidate a warm cache.
    """

    def __init__(
        self,
        path: str,
        now: Callable[[], float] = time.time,
    ) -> None:
        """Open the cache database.

        Args:
            path: SQLite file path.
            now: Clock function, injected for tests.
        """
        self._now = now
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, key: str, ttl: int) -> dict | None:
        """Return a cached body if present and within its TTL.

        Args:
            key: Request key from request_key.
            ttl: Maximum age in seconds, inclusive.

        Returns:
            The cached body, or None on a miss or expiry.
        """
        row = self._conn.execute(
            "SELECT body, stored_at FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None

        body, stored_at = row
        if self._now() - stored_at > ttl:
            logger.debug("cache entry %s expired", key[:8])
            return None
        return json.loads(body)

    def set(self, key: str, body: dict) -> None:
        """Store a body, replacing any existing entry.

        Args:
            key: Request key from request_key.
            body: Raw SerpApi response.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, body, stored_at) "
            "VALUES (?, ?, ?)",
            (key, json.dumps(body, ensure_ascii=False), self._now()),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cache.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/cache.py tests/test_cache.py
git commit -m "feat: sqlite cache with secret-free canonical request keys"
```

---

### Task 6: Budget guard

**Files:**
- Create: `searchmux/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Consumes: `BudgetExceeded` from `searchmux.models`.
- Produces: `Budget` class with `__init__(self, limit: int)`, `spend(self, engine_id: str) -> None` raising `BudgetExceeded`, properties `used: int` and `remaining: int`, and `report(self) -> dict`.

- [ ] **Step 1: Write the failing test**

Covers Review Focus item 2 — the concurrency claim.

```python
"""Tests for the credit budget guard."""

import threading

import pytest

from searchmux.budget import Budget
from searchmux.models import BudgetExceeded


def test_spend_increments_usage() -> None:
    budget = Budget(limit=3)
    budget.spend("google")
    assert budget.used == 1
    assert budget.remaining == 2


def test_spend_raises_at_the_limit() -> None:
    budget = Budget(limit=1)
    budget.spend("google")
    with pytest.raises(BudgetExceeded, match="1"):
        budget.spend("google")


def test_rejected_spend_does_not_increment() -> None:
    budget = Budget(limit=1)
    budget.spend("google")
    with pytest.raises(BudgetExceeded):
        budget.spend("google")
    assert budget.used == 1


def test_report_breaks_down_by_engine() -> None:
    budget = Budget(limit=5)
    budget.spend("google")
    budget.spend("google")
    budget.spend("bing")
    assert budget.report() == {
        "credits_used": 3,
        "remaining": 2,
        "by_engine": {"google": 2, "bing": 1},
    }


def test_zero_limit_rejects_immediately() -> None:
    with pytest.raises(BudgetExceeded):
        Budget(limit=0).spend("google")


def test_concurrent_spends_never_exceed_the_limit() -> None:
    budget = Budget(limit=10)
    granted: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            budget.spend("google")
        except BudgetExceeded:
            return
        with lock:
            granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(granted) == 10
    assert budget.used == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Credit budget enforcement, checked before any billable request."""

import logging
import threading
from collections import Counter

from searchmux.models import BudgetExceeded

logger = logging.getLogger(__name__)


class Budget:
    """Caps billable requests and records where credits went.

    Check-and-increment happens under one lock, so a concurrent caller
    can never push usage past the limit.
    """

    def __init__(self, limit: int) -> None:
        """Set the ceiling.

        Args:
            limit: Maximum billable requests allowed.
        """
        self._limit = limit
        self._used = 0
        self._by_engine: Counter[str] = Counter()
        self._lock = threading.Lock()

    def spend(self, engine_id: str) -> None:
        """Consume one credit, or refuse.

        Args:
            engine_id: The engine about to be called.

        Raises:
            BudgetExceeded: If the budget is already exhausted. Nothing
                is incremented when this raises.
        """
        with self._lock:
            if self._used >= self._limit:
                raise BudgetExceeded(
                    f"budget of {self._limit} credits is exhausted; "
                    f"raise it or narrow the query"
                )
            self._used += 1
            self._by_engine[engine_id] += 1

    @property
    def used(self) -> int:
        """Return credits consumed so far."""
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        """Return credits still available."""
        with self._lock:
            return self._limit - self._used

    def report(self) -> dict:
        """Return a spend breakdown.

        Returns:
            Keys credits_used, remaining, and by_engine.
        """
        with self._lock:
            return {
                "credits_used": self._used,
                "remaining": self._limit - self._used,
                "by_engine": dict(self._by_engine),
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_budget.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/budget.py tests/test_budget.py
git commit -m "feat: thread-safe credit budget guard"
```

---

### Task 7: Cassettes

**Files:**
- Create: `searchmux/cassette.py`
- Test: `tests/test_cassette.py`

**Interfaces:**
- Consumes: `request_key` from `searchmux.cache`; `CassetteMiss` from `searchmux.models`; `SECRET_PARAM_KEYS` from `searchmux.constants`.
- Produces: `Cassette` class with `__init__(self, path: str, mode: str)` where mode is `"record"` or `"replay"`, `play(self, engine_id: str, params: dict) -> dict` raising `CassetteMiss`, `capture(self, engine_id: str, params: dict, body: dict) -> None`, `save(self) -> None`, and `entry_count` property.

- [ ] **Step 1: Write the failing test**

Covers Review Focus item 1 for the committed-file path.

```python
"""Tests for record and replay cassettes."""

import json

import pytest

from searchmux.cassette import Cassette
from searchmux.models import CassetteMiss


def test_capture_then_replay_returns_the_body(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x"}, {"organic_results": [{"a": 1}]})
    recorder.save()

    player = Cassette(path, mode="replay")
    assert player.play("google", {"q": "x"}) == {
        "organic_results": [{"a": 1}]
    }


def test_replay_miss_raises_and_never_returns_none(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    Cassette(path, mode="record").save()

    player = Cassette(path, mode="replay")
    with pytest.raises(CassetteMiss, match="google"):
        player.play("google", {"q": "unrecorded"})


def test_api_key_is_stripped_from_the_saved_file(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture(
        "google", {"q": "x", "api_key": "super-secret"}, {"organic_results": []}
    )
    recorder.save()

    contents = (tmp_path / "c.json").read_text(encoding="utf-8")
    assert "super-secret" not in contents


def test_replay_matches_regardless_of_api_key(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x", "api_key": "k1"}, {"ok": True})
    recorder.save()

    player = Cassette(path, mode="replay")
    assert player.play("google", {"q": "x", "api_key": "k2"}) == {"ok": True}


def test_replay_on_a_missing_file_raises_on_first_play(tmp_path) -> None:
    player = Cassette(str(tmp_path / "absent.json"), mode="replay")
    with pytest.raises(CassetteMiss):
        player.play("google", {"q": "x"})


def test_saved_file_is_human_readable_json(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x"}, {"ok": True})
    recorder.save()

    payload = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert payload["entries"][0]["engine_id"] == "google"
    assert payload["entries"][0]["params"] == {"q": "x"}


def test_entry_count_reflects_captures(tmp_path) -> None:
    recorder = Cassette(str(tmp_path / "c.json"), mode="record")
    recorder.capture("google", {"q": "a"}, {})
    recorder.capture("google", {"q": "b"}, {})
    assert recorder.entry_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cassette.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.cassette'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Record and replay SerpApi responses, so tests cost nothing."""

import json
import logging
from pathlib import Path

from searchmux.cache import request_key
from searchmux.constants import SECRET_PARAM_KEYS
from searchmux.models import CassetteMiss

logger = logging.getLogger(__name__)

MODE_RECORD = "record"
MODE_REPLAY = "replay"


class Cassette:
    """A file of captured SerpApi responses.

    In replay mode a miss raises CassetteMiss and never falls through
    to the network. That is deliberate: a test must not silently start
    spending credits.
    """

    def __init__(self, path: str, mode: str) -> None:
        """Open a cassette.

        Args:
            path: Cassette file path.
            mode: Either "record" or "replay".

        Raises:
            ValueError: On an unknown mode.
        """
        if mode not in (MODE_RECORD, MODE_REPLAY):
            raise ValueError(f"mode must be record or replay, got {mode!r}")

        self._path = Path(path)
        self._mode = mode
        self._entries: dict[str, dict] = {}
        if mode == MODE_REPLAY:
            self._load()

    def _load(self) -> None:
        """Read entries from disk, tolerating an absent file."""
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("cassette %s does not exist yet", self._path)
            return
        except json.JSONDecodeError:
            logger.error("cassette %s is not valid JSON", self._path)
            return

        for entry in payload.get("entries", []):
            key = request_key(entry["engine_id"], entry["params"])
            self._entries[key] = entry["body"]

    def play(self, engine_id: str, params: dict) -> dict:
        """Return a recorded body for this request.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters. Secrets are ignored when
                matching, so any key replays any recording.

        Returns:
            The recorded response body.

        Raises:
            CassetteMiss: If nothing was recorded for this request.
        """
        key = request_key(engine_id, params)
        if key not in self._entries:
            raise CassetteMiss(
                f"no recording for {engine_id} with {self._safe(params)}; "
                f"re-record with SearchMux.record()"
            )
        return self._entries[key]

    def capture(self, engine_id: str, params: dict, body: dict) -> None:
        """Store one response for later replay.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters. Secrets are stripped.
            body: Raw response body.
        """
        key = request_key(engine_id, params)
        self._entries[key] = body
        self._captured = getattr(self, "_captured", {})
        self._captured[key] = {
            "engine_id": engine_id,
            "params": self._safe(params),
            "body": body,
        }

    def save(self) -> None:
        """Write captured entries to disk, secrets excluded."""
        entries = list(getattr(self, "_captured", {}).values())
        payload = {"version": 1, "entries": entries}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("wrote %d entries to %s", len(entries), self._path)

    @property
    def entry_count(self) -> int:
        """Return how many responses this cassette holds."""
        return len(self._entries)

    @staticmethod
    def _safe(params: dict) -> dict:
        """Return params with secret keys removed."""
        return {
            name: value
            for name, value in params.items()
            if name not in SECRET_PARAM_KEYS
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cassette.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/cassette.py tests/test_cassette.py
git commit -m "feat: record/replay cassettes, secrets stripped on write"
```

---

### Task 8: SearchMux facade — first end-to-end path

**Files:**
- Modify: `searchmux/__init__.py`
- Create: `searchmux/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: `SearchMux` class with `__init__(self, api_key: str | None = None, budget: int = DEFAULT_BUDGET, cache: str | None = DEFAULT_CACHE_PATH, transport: Transport | None = None, router: object | None = None)`, methods `search(self, engine: str, **params) -> list[Result]`, `find(self, intent: str, engine: str | None = None, **params) -> list[Result]`, `report(self) -> dict`, and context managers `record(self, path)` / `replay(self, path)`.

This is the first task whose deliverable is demoable. After it, `q.find(..., engine=...)` works with cache, budget, and cassettes — the router arrives in Task 9.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the SearchMux facade and the request pipeline."""

import httpx
import pytest

from searchmux import SearchMux
from searchmux.models import BudgetExceeded
from searchmux.transport import Transport


def _stub_transport(body: dict, calls: dict) -> Transport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Transport(api_key="test-key", client=client)


BODY = {"organic_results": [{"title": "t", "link": "u", "position": 1}]}


def test_search_returns_normalized_results(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
    )
    results = q.search(engine="google", q="x")
    assert results[0].title == "t"
    assert results[0].source == "google"


def test_second_identical_search_hits_cache(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
    )
    q.search(engine="google", q="x")
    q.search(engine="google", q="x")
    assert calls["n"] == 1
    assert q.report()["credits_used"] == 1
    assert q.report()["cache_hits"] == 1


def test_cache_hit_does_not_spend_budget(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        budget=1,
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
    )
    q.search(engine="google", q="x")
    q.search(engine="google", q="x")
    assert q.report()["credits_used"] == 1


def test_budget_exhaustion_raises_before_the_call(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        budget=1,
        cache=None,
        transport=_stub_transport(BODY, calls),
    )
    q.search(engine="google", q="a")
    with pytest.raises(BudgetExceeded):
        q.search(engine="google", q="b")
    assert calls["n"] == 1


def test_find_with_pinned_engine_needs_no_router(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
    )
    results = q.find("anything at all", engine="google", q="x")
    assert results[0].title == "t"


def test_record_then_replay_costs_no_credits(tmp_path) -> None:
    calls: dict = {}
    path = str(tmp_path / "cass.json")
    recorder = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
    )
    with recorder.record(path):
        recorder.search(engine="google", q="x")

    player = SearchMux(api_key=None, cache=None, transport=None)
    with player.replay(path):
        results = player.search(engine="google", q="x")
    assert results[0].title == "t"
    assert player.report()["credits_used"] == 0


def test_replay_works_without_an_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    calls: dict = {}
    path = str(tmp_path / "cass.json")
    recorder = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
    )
    with recorder.record(path):
        recorder.search(engine="google", q="x")

    player = SearchMux(cache=None)
    with player.replay(path):
        assert player.search(engine="google", q="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'SearchMux'`

- [ ] **Step 3: Write minimal implementation**

`searchmux/client.py`:

```python
"""The SearchMux facade: one pipeline over cache, budget, and transport."""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from searchmux.budget import Budget
from searchmux.cache import Cache, request_key
from searchmux.cassette import MODE_RECORD, MODE_REPLAY, Cassette
from searchmux.catalog import get_engine
from searchmux.constants import (
    DEFAULT_BUDGET,
    DEFAULT_CACHE_PATH,
    ENV_API_KEY,
    TTL_BY_CLASS,
)
from searchmux.models import Result
from searchmux.normalize import normalize
from searchmux.transport import Transport

logger = logging.getLogger(__name__)


class SearchMux:
    """Routes, caches, and meters SerpApi searches."""

    def __init__(
        self,
        api_key: str | None = None,
        budget: int = DEFAULT_BUDGET,
        cache: str | None = DEFAULT_CACHE_PATH,
        transport: Transport | None = None,
        router: object | None = None,
    ) -> None:
        """Build a client.

        Args:
            api_key: SerpApi key. Falls back to SERPAPI_API_KEY. May be
                None when only replaying cassettes.
            budget: Maximum billable requests for this instance.
            cache: SQLite path, or None to disable caching.
            transport: Injected transport, for tests.
            router: Injected router. Task 9 supplies the default.
        """
        self._api_key = api_key or os.getenv(ENV_API_KEY)
        self._budget = Budget(limit=budget)
        self._cache = Cache(cache) if cache else None
        self._transport = transport
        self._router = router
        self._cassette: Cassette | None = None
        self._cache_hits = 0

    def search(self, engine: str, **params) -> list[Result]:
        """Run one search against a named engine.

        Args:
            engine: SerpApi engine identifier.
            **params: Engine parameters.

        Returns:
            Normalized results.
        """
        spec = get_engine(engine)
        key = request_key(engine, params)
        ttl = TTL_BY_CLASS[spec.ttl_class]

        if self._cache is not None:
            cached = self._cache.get(key, ttl=ttl)
            if cached is not None:
                self._cache_hits += 1
                logger.debug("cache hit for %s", engine)
                return normalize(engine, cached)

        body = self._fetch(engine, params)

        if self._cache is not None:
            self._cache.set(key, body)
        return normalize(engine, body)

    def find(
        self,
        intent: str,
        engine: str | None = None,
        **params,
    ) -> list[Result]:
        """Resolve an intent to an engine and search.

        Args:
            intent: What the caller wants to know, in plain language.
            engine: Pin an engine to skip routing entirely.
            **params: Parameters, merged over anything the router
                produces.

        Returns:
            Normalized results.

        Raises:
            RoutingError: If no engine is pinned and no router is set.
        """
        if engine is not None:
            # The intent is the query unless the caller overrides q.
            return self.search(engine=engine, **{"q": intent, **params})

        from searchmux.models import RoutingError

        if self._router is None:
            raise RoutingError(
                "no engine pinned and no router configured; pass "
                "engine= or construct SearchMux with a router"
            )
        engine_id, routed = self._router.route(intent)
        return self.search(engine=engine_id, **{**routed, **params})

    def _fetch(self, engine: str, params: dict) -> dict:
        """Replay, or spend a credit and call SerpApi."""
        if self._cassette is not None and self._cassette.mode == MODE_REPLAY:
            return self._cassette.play(engine, params)

        self._budget.spend(engine)
        body = self._require_transport().fetch(engine, params)

        if self._cassette is not None and self._cassette.mode == MODE_RECORD:
            self._cassette.capture(engine, params, body)
        return body

    def _require_transport(self) -> Transport:
        """Return the transport, building one if needed."""
        if self._transport is None:
            if not self._api_key:
                raise ValueError(
                    f"no API key; set {ENV_API_KEY} or pass api_key="
                )
            self._transport = Transport(api_key=self._api_key)
        return self._transport

    @contextmanager
    def record(self, path: str) -> Iterator[None]:
        """Capture every live response to a cassette file.

        Args:
            path: Cassette path to write.
        """
        self._cassette = Cassette(path, mode=MODE_RECORD)
        try:
            yield
        finally:
            self._cassette.save()
            self._cassette = None

    @contextmanager
    def replay(self, path: str) -> Iterator[None]:
        """Serve every response from a cassette. Costs nothing.

        Args:
            path: Cassette path to read.
        """
        self._cassette = Cassette(path, mode=MODE_REPLAY)
        try:
            yield
        finally:
            self._cassette = None

    def report(self) -> dict:
        """Return credit spend and cache effectiveness.

        Returns:
            The budget report plus cache_hits.
        """
        return {**self._budget.report(), "cache_hits": self._cache_hits}
```

Add a `mode` property to `Cassette` in `searchmux/cassette.py`, since the facade reads it:

```python
    @property
    def mode(self) -> str:
        """Return this cassette's mode."""
        return self._mode
```

Append to `searchmux/__init__.py`'s imports and `__all__`:

```python
from searchmux.client import SearchMux
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_client.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the whole suite with no API key**

Run: `env -u SERPAPI_API_KEY pytest -q`
Expected: all tests pass. This is the invariant from the spec.

- [ ] **Step 6: Commit**

```bash
git add searchmux/client.py searchmux/cassette.py searchmux/__init__.py tests/test_client.py
git commit -m "feat: SearchMux facade wiring cache, budget, cassettes"
```

---

### Task 9: Intent router

**Files:**
- Create: `searchmux/router.py`
- Modify: `searchmux/client.py` (default router construction)
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `load_catalog` from `searchmux.catalog`; `RoutingError` from `searchmux.models`; `DEFAULT_ROUTER_TOP_K`, `ENV_ANTHROPIC_KEY` from `searchmux.constants`.
- Produces: `LLMClient` protocol with `complete(self, prompt: str, schema: dict) -> dict`; `Router` class with `__init__(self, llm: LLMClient | None = None, top_k: int = DEFAULT_ROUTER_TOP_K)`, `retrieve(self, intent: str) -> list[str]` returning candidate engine ids, and `route(self, intent: str) -> tuple[str, dict]`.

Before writing this task's code, load the `claude-api` skill — the default `LLMClient` targets Anthropic and the model id must be current, not remembered.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for BM25 retrieval and schema-constrained routing."""

import pytest

from searchmux.models import RoutingError
from searchmux.router import Router


class FakeLLM:
    """Returns a scripted routing decision."""

    def __init__(self, decision: dict) -> None:
        self.decision = decision
        self.prompts: list[str] = []

    def complete(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        return self.decision


def test_retrieve_ranks_shopping_for_a_price_intent() -> None:
    candidates = Router(llm=FakeLLM({})).retrieve(
        "current price of the Pixel 10 phone"
    )
    assert "google_shopping" in candidates


def test_retrieve_ranks_scholar_for_a_research_intent() -> None:
    candidates = Router(llm=FakeLLM({})).retrieve(
        "peer reviewed academic papers about CRISPR"
    )
    assert "google_scholar" in candidates


def test_retrieve_returns_at_most_top_k() -> None:
    router = Router(llm=FakeLLM({}), top_k=3)
    assert len(router.retrieve("flights to Tokyo")) == 3


def test_route_returns_engine_and_params() -> None:
    llm = FakeLLM({"engine_id": "google_shopping", "params": {"q": "Pixel 10"}})
    engine_id, params = Router(llm=llm).route("price of Pixel 10")
    assert engine_id == "google_shopping"
    assert params == {"q": "Pixel 10"}


def test_prompt_contains_only_the_candidate_schemas() -> None:
    llm = FakeLLM({"engine_id": "google", "params": {"q": "x"}})
    Router(llm=llm, top_k=2).route("something")
    prompt = llm.prompts[0]
    assert prompt.count('"engine_id"') <= 2 or prompt.count("engine_id:") <= 2


def test_engine_outside_the_catalog_raises() -> None:
    llm = FakeLLM({"engine_id": "invented_engine", "params": {"q": "x"}})
    with pytest.raises(RoutingError, match="invented_engine"):
        Router(llm=llm).route("something")


def test_missing_required_param_raises_after_one_repair() -> None:
    llm = FakeLLM({"engine_id": "google", "params": {}})
    with pytest.raises(RoutingError, match="q"):
        Router(llm=llm).route("something")
    assert len(llm.prompts) == 2


def test_unknown_param_is_dropped_not_fatal() -> None:
    llm = FakeLLM(
        {"engine_id": "google", "params": {"q": "x", "nonsense": 1}}
    )
    _, params = Router(llm=llm).route("something")
    assert params == {"q": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.router'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Resolve plain-language intent to an engine and valid parameters."""

import json
import logging
import os
from typing import Protocol

from rank_bm25 import BM25Okapi

from searchmux.catalog import Engine, load_catalog
from searchmux.constants import DEFAULT_ROUTER_TOP_K, ENV_ANTHROPIC_KEY
from searchmux.models import RoutingError

logger = logging.getLogger(__name__)

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "engine_id": {"type": "string"},
        "params": {"type": "object"},
    },
    "required": ["engine_id", "params"],
}

_PROMPT = """\
Pick the single best search engine for this request and fill in its
parameters.

Request: {intent}

Candidate engines:
{candidates}

Reply with the engine_id and a params object using only the parameters
listed for the engine you choose. Include every required parameter.
{correction}"""


class LLMClient(Protocol):
    """Anything that can return structured output for a prompt."""

    def complete(self, prompt: str, schema: dict) -> dict:
        """Return a dict conforming to schema."""
        ...


class Router:
    """Two-stage router: BM25 retrieval, then schema-bound synthesis.

    Retrieval is pure Python and free. Only the surviving candidates
    reach the LLM, so the model chooses among a handful of fully
    specified options instead of a hundred bare names.
    """

    def __init__(
        self,
        llm: LLMClient | None = None,
        top_k: int = DEFAULT_ROUTER_TOP_K,
    ) -> None:
        """Build the router and its retrieval index.

        Args:
            llm: Structured-output client. A default Anthropic client is
                built when omitted.
            top_k: How many candidates survive retrieval.
        """
        self._llm = llm or _default_llm()
        self._top_k = top_k
        self._catalog = load_catalog()
        self._engine_ids = list(self._catalog)
        self._index = BM25Okapi(
            [
                _tokenize(f"{e.description} {' '.join(e.keywords)}")
                for e in self._catalog.values()
            ]
        )

    def retrieve(self, intent: str) -> list[str]:
        """Return the top_k candidate engine ids for an intent.

        Args:
            intent: Plain-language description of what is wanted.

        Returns:
            Engine ids, best first.
        """
        scores = self._index.get_scores(_tokenize(intent))
        ranked = sorted(
            zip(self._engine_ids, scores),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [engine_id for engine_id, _ in ranked[: self._top_k]]

    def route(self, intent: str) -> tuple[str, dict]:
        """Resolve an intent to an engine and validated parameters.

        Args:
            intent: Plain-language description of what is wanted.

        Returns:
            The chosen engine_id and its parameters.

        Raises:
            RoutingError: If the engine is unknown, or required
                parameters are still missing after one repair attempt.
        """
        candidates = self.retrieve(intent)
        prompt = self._build_prompt(intent, candidates, correction="")
        decision = self._llm.complete(prompt, _DECISION_SCHEMA)

        try:
            return self._validate(decision, candidates)
        except RoutingError as first_error:
            logger.info("repairing routing decision: %s", first_error)
            repair = self._build_prompt(
                intent,
                candidates,
                correction=f"\nYour previous reply was rejected: "
                f"{first_error}. Fix it.",
            )
            retry = self._llm.complete(repair, _DECISION_SCHEMA)
            return self._validate(retry, candidates)

    def _build_prompt(
        self,
        intent: str,
        candidates: list[str],
        correction: str,
    ) -> str:
        """Render the routing prompt with only candidate schemas."""
        described = [
            json.dumps(
                {
                    "engine_id": engine_id,
                    "description": self._catalog[engine_id].description,
                    "params": self._catalog[engine_id].params,
                },
                indent=2,
            )
            for engine_id in candidates
        ]
        return _PROMPT.format(
            intent=intent,
            candidates="\n".join(described),
            correction=correction,
        )

    def _validate(
        self,
        decision: dict,
        candidates: list[str],
    ) -> tuple[str, dict]:
        """Check the decision against the chosen engine's schema."""
        engine_id = decision.get("engine_id", "")
        if engine_id not in self._catalog:
            raise RoutingError(
                f"router chose {engine_id!r}, which is not a known engine"
            )

        engine = self._catalog[engine_id]
        params = _drop_unknown(engine, decision.get("params", {}))
        missing = [
            name
            for name, spec in engine.params.items()
            if spec.get("required") and name not in params
        ]
        if missing:
            raise RoutingError(
                f"{engine_id} requires {', '.join(missing)}, which the "
                f"router omitted"
            )
        return engine_id, params


def _drop_unknown(engine: Engine, params: dict) -> dict:
    """Return only parameters the engine actually accepts."""
    kept = {}
    for name, value in params.items():
        if name in engine.params:
            kept[name] = value
        else:
            logger.debug("dropping unknown param %s for %s", name, engine.engine_id)
    return kept


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric tokens."""
    return [
        token
        for token in "".join(
            char if char.isalnum() else " " for char in text.lower()
        ).split()
        if token
    ]


def _default_llm() -> LLMClient:
    """Build the Anthropic-backed client.

    Raises:
        RoutingError: If no Anthropic key is configured.
    """
    if not os.getenv(ENV_ANTHROPIC_KEY):
        raise RoutingError(
            f"routing needs {ENV_ANTHROPIC_KEY}; pass engine= to skip "
            f"routing entirely"
        )
    from searchmux.llm import AnthropicClient

    return AnthropicClient()
```

Also create `searchmux/llm.py` holding `AnthropicClient`, implementing `complete` via the Anthropic SDK's tool-use for structured output. **Load the `claude-api` skill before writing it** so the model id is current.

Then in `searchmux/client.py`, replace the `find` router guard so a default router is built lazily when `ANTHROPIC_API_KEY` is present.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_router.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/router.py searchmux/llm.py searchmux/client.py tests/test_router.py
git commit -m "feat: two-stage intent router, BM25 then schema-bound LLM"
```

---

### Task 10: Evaluation harness

**Files:**
- Create: `evals/routing.jsonl`, `evals/run_eval.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `Router` from `searchmux.router`.
- Produces: `load_cases(path: str) -> list[dict]`, `score_arm(name: str, predict: Callable[[str], str], cases: list[dict]) -> dict` returning `{"arm", "n", "correct", "accuracy"}`, and a `__main__` that prints the three-arm table.

This task produces the number the demo video is built around. Do not cut it.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the routing evaluation harness."""

from evals.run_eval import load_cases, score_arm


def test_cases_load_with_intent_and_expected_engine() -> None:
    cases = load_cases("evals/routing.jsonl")
    assert len(cases) >= 40
    assert all("intent" in c and "expected" in c for c in cases)


def test_score_arm_computes_accuracy() -> None:
    cases = [
        {"intent": "a", "expected": "google"},
        {"intent": "b", "expected": "bing"},
    ]
    result = score_arm("perfect", lambda i: cases[0]["expected"], cases)
    assert result["n"] == 2
    assert result["correct"] == 1
    assert result["accuracy"] == 0.5


def test_bm25_top1_beats_chance_on_the_eval_set() -> None:
    from searchmux.router import Router

    router = Router(llm=_NullLLM())
    cases = load_cases("evals/routing.jsonl")
    scored = score_arm("bm25", lambda i: router.retrieve(i)[0], cases)
    assert scored["accuracy"] > 0.4


class _NullLLM:
    def complete(self, prompt: str, schema: dict) -> dict:
        raise AssertionError("retrieval-only arm must not call the LLM")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 3: Write minimal implementation**

`evals/routing.jsonl` — 50 lines, each `{"intent": "...", "expected": "<engine_id>"}`. Spread across all 25 catalogued engines, at least one per engine, phrased the way a user would phrase it, never using the engine's own name. Examples:

```jsonl
{"intent": "what does the Pixel 10 cost in India right now", "expected": "google_shopping"}
{"intent": "peer reviewed studies on CRISPR off-target effects", "expected": "google_scholar"}
{"intent": "cheapest flight from Delhi to Tokyo next month", "expected": "google_flights"}
{"intent": "good ramen places near Shibuya station", "expected": "google_maps"}
{"intent": "what happened in the budget announcement this week", "expected": "google_news"}
{"intent": "video reviews of the Sony WH-1000XM6", "expected": "youtube"}
{"intent": "is interest in electric scooters growing", "expected": "google_trends"}
{"intent": "remote python developer roles in Bangalore", "expected": "google_jobs"}
{"intent": "who owns the patent on rounded rectangles", "expected": "google_patents"}
{"intent": "current share price of Infosys", "expected": "google_finance"}
```

`evals/run_eval.py`:

```python
"""Compare routing arms on a labelled intent set."""

import json
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def load_cases(path: str) -> list[dict]:
    """Read labelled routing cases from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        One dict per line, each with intent and expected.
    """
    cases = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def score_arm(
    name: str,
    predict: Callable[[str], str],
    cases: list[dict],
) -> dict:
    """Score one routing strategy over every case.

    Args:
        name: Arm label for the report.
        predict: Maps an intent to a predicted engine_id.
        cases: Labelled cases from load_cases.

    Returns:
        Keys arm, n, correct, and accuracy.
    """
    correct = 0
    for case in cases:
        try:
            predicted = predict(case["intent"])
        except Exception:
            logger.warning("arm %s failed on %r", name, case["intent"])
            continue
        if predicted == case["expected"]:
            correct += 1

    total = len(cases)
    return {
        "arm": name,
        "n": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
    }
```

The `__main__` block wires three arms: a baseline that prompts the LLM with bare engine ids and no schemas, `Router.retrieve` top-1, and full `Router.route`. It prints a markdown table. Run it against a recorded cassette so it reproduces without a key.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the eval and record the numbers**

Run: `python -m evals.run_eval`
Paste the resulting table into the README. This is the submission's headline number.

- [ ] **Step 6: Commit**

```bash
git add evals tests/test_eval.py
git commit -m "feat: three-arm routing eval with 50 labelled intents"
```

---

### Task 11: Adapters

**Files:**
- Create: `searchmux/adapters/__init__.py`, `searchmux/adapters/tool.py`, `searchmux/adapters/mcp_server.py`
- Modify: `searchmux/client.py` (add `as_tool`)
- Test: `tests/test_adapters.py`

**Interfaces:**
- Consumes: `SearchMux` from `searchmux.client`.
- Produces: `tool_schema(name: str = "search") -> dict` emitting an OpenAI/Anthropic-compatible function schema, `SearchMux.as_tool(self) -> dict`, and an MCP server entry point `main() -> None`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for framework tool emission."""

from searchmux import SearchMux
from searchmux.adapters.tool import tool_schema


def test_schema_has_a_single_intent_parameter() -> None:
    schema = tool_schema()
    assert schema["name"] == "search"
    props = schema["input_schema"]["properties"]
    assert "intent" in props
    assert schema["input_schema"]["required"] == ["intent"]


def test_schema_description_mentions_engine_breadth() -> None:
    assert "engine" in tool_schema()["description"].lower()


def test_as_tool_returns_the_schema(tmp_path) -> None:
    q = SearchMux(api_key="k", cache=str(tmp_path / "c.db"))
    assert q.as_tool()["name"] == "search"


def test_schema_is_json_serializable() -> None:
    import json

    json.dumps(tool_schema())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'searchmux.adapters'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Emit a tool schema consumable by agent frameworks."""

TOOL_DESCRIPTION = (
    "Search the live web. Describe what you want to know in plain "
    "language; the right search engine is selected automatically from "
    "over a hundred available engines, covering the web, shopping and "
    "prices, news, academic papers, maps and places, flights, hotels, "
    "jobs, videos, patents, and finance."
)


def tool_schema(name: str = "search") -> dict:
    """Return a function-calling schema for SearchMux.find.

    Args:
        name: Tool name exposed to the model.

    Returns:
        A schema accepted by Anthropic, OpenAI, and LangChain.
    """
    return {
        "name": name,
        "description": TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "What you want to know, in plain language."
                    ),
                }
            },
            "required": ["intent"],
        },
    }
```

`searchmux/adapters/mcp_server.py` exposes one `find` tool over stdio, delegating to a module-level `SearchMux`, reading the key from `os.getenv`. Add `as_tool` to `SearchMux` returning `tool_schema()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapters.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add searchmux/adapters tests/test_adapters.py searchmux/client.py
git commit -m "feat: tool schema emission and MCP server adapter"
```

---

### Task 12: Submission package

**Files:**
- Create: `README.md`, `LICENSE` (MIT), `.github/workflows/ci.yml`, `examples/pixel_agent.py`
- Test: `tests/test_no_secrets.py`

**Interfaces:**
- Consumes: everything.
- Produces: the artifacts a judge actually opens.

- [ ] **Step 1: Write the failing test**

Guards the disqualifying failure mode directly.

```python
"""Guard against committing anything that looks like a key."""

import pathlib
import re

KEY_PATTERN = re.compile(r"[0-9a-f]{40,}|sk-[A-Za-z0-9-]{20,}")
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}


def test_no_api_keys_in_tracked_files() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_DIRS & set(path.parts):
            continue
        if path.suffix not in {".py", ".json", ".md", ".yml", ".jsonl", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if KEY_PATTERN.search(text):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"possible secrets in: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_no_secrets.py -v`
Expected: PASS on a clean tree. If it fails, a real secret is committed — remove it and rewrite history before going further.

- [ ] **Step 3: Write the README**

Required sections, in this order:

1. One-sentence description and the problem statement (three bullets from spec §1).
2. **The eval table from Task 10.** Numbers first, before any feature list.
3. Install and 60-second quickstart, copy-pasteable.
4. The four features, one short paragraph each: routing, cache, budget, cassettes.
5. **"Run the tests without an API key"** — the instruction that proves the cassette claim. A judge must be able to clone and run `pytest` with no signup.
6. How SerpApi is used, and which engines are catalogued.
7. AI tool disclosure, as the hackathon rules require.
8. MIT license note.

`.github/workflows/ci.yml` runs `pytest` on Python 3.11, 3.12 and 3.13 with `SERPAPI_API_KEY` explicitly unset.

`examples/pixel_agent.py` is the demo script: a small agent answering "should I buy the Pixel 10 now or wait", printing `q.report()` at the end so the credit count is visible on camera.

- [ ] **Step 4: Verify the judge path end to end**

```bash
git clone <repo> /tmp/judge-check && cd /tmp/judge-check
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
env -u SERPAPI_API_KEY pytest -q
```
Expected: all tests pass on a clean clone with no key. If this fails, the submission fails.

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE .github examples tests/test_no_secrets.py
git commit -m "docs: README with eval results, CI, and keyless test path"
```

---

## Deferred

Recorded here rather than built, so the omissions are deliberate:

- Embedding-based retrieval. BM25 ships; Task 10 decides whether this is needed.
- The remaining ~75 engines. Adding one is a JSON record, no code.
- Verified CrewAI and LlamaIndex adapters. The emitted schema is compatible; the README says unverified rather than claiming support.
- Async client. The pipeline is synchronous; `httpx.AsyncClient` is a later addition behind the same facade.
- Cache eviction. SQLite grows unbounded; a `prune()` is trivial to add when it matters.
