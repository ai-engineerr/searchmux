# Multi-Provider Search Backends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tavily, Brave Search, and Exa as first-class catalog providers alongside SerpApi, sharing the existing cache, budget guard, cassette replay, and `Result` normalization unchanged.

**Architecture:** `Engine` gains a `provider` field; `transport.py`'s single `Transport` class is split into a shared `Backend` base (the retry/backoff loop, unchanged) plus one `_build_request`-only subclass per provider; `SearchMux` builds backends lazily per provider, keyed off `Engine.provider`, with a new `backends=` injection kwarg alongside the untouched `transport=` kwarg.

**Tech Stack:** Python 3.11+, httpx, pytest, `httpx.MockTransport` for offline request-shape tests.

**Spec:** [docs/superpowers/specs/2026-09-30-multi-provider-backends-design.md](../specs/2026-09-30-multi-provider-backends-design.md)

## Global Constraints

- Local work only: no `git push`, no PyPI build/upload, until explicitly authorized (spec §6).
- This work ships as version `0.2.0` (spec §6).
- No new test may require `TAVILY_API_KEY`, `BRAVE_API_KEY`, or `EXA_API_KEY` to run; the whole suite stays offline-by-default (spec §5).
- README's opening framing and Team section are unchanged — SerpApi stays the lead positioning (spec §2, §6). No task in this plan touches `README.md`.
- Exa auth uses the `x-api-key` header, a deliberate choice over the equally valid `Authorization: Bearer` form (spec §3).
- The `transport=` constructor kwarg must keep working byte-for-byte for every existing SerpApi test, and takes precedence over `backends={"serpapi": ...}` when both are supplied (spec §4.4).
- Brave has no live-verified key available; only Tavily and Exa get the manual live smoke check (spec §2, §5).
- ruff: line-length 79, rule sets E/W/F/I/UP/B/SIM (`pyproject.toml`).

## Review Focus

- A provider key is missing for the engine actually requested — `SearchMux` must raise `ValueError` naming that provider's specific env var, and must not raise at construction time. → Task 5.
- Requesting a SerpApi engine must never require or touch a Tavily/Brave/Exa key, and vice versa (provider isolation). → Task 5.
- A new backend's 4xx response (e.g. a rejected key) must raise immediately without retrying, exactly like SerpApi's existing behavior — a retry bug here would triple billable attempts on every bad key. → Task 3.
- Both `transport=` and `backends={"serpapi": ...}` supplied together — the legacy kwarg must win, since losing that precedence would silently break the 126 existing tests' assumption of exclusive control. → Task 5.
- Cache and budget must generalize correctly to a non-SerpApi engine, not only work for SerpApi by coincidence — a second identical `tavily_search` call must hit cache and cost zero extra budget. → Task 5.

---

### Task 1: `provider` field on `Engine` + new provider constants

**Files:**
- Modify: `searchmux/constants.py`
- Modify: `searchmux/catalog.py`
- Modify: `searchmux/catalog.json`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: nothing (foundational task).
- Produces: `Engine.provider: str` (Task 4 sets it to `"tavily"`/`"brave"`/`"exa"` on new records; Task 5 reads it to route requests). New constants `TAVILY_BASE_URL`, `ENV_TAVILY_KEY`, `BRAVE_BASE_URL`, `ENV_BRAVE_KEY`, `EXA_BASE_URL`, `ENV_EXA_KEY` (consumed by Tasks 2, 3, 5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog.py`:

```python
def test_every_engine_declares_a_provider() -> None:
    for engine_id, engine in load_catalog().items():
        assert engine.provider, f"{engine_id} has no provider"


def test_existing_engines_are_serpapi() -> None:
    assert get_engine("google").provider == "serpapi"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_catalog.py -v`
Expected: FAIL — `Engine.__init__() got an unexpected keyword argument` or `AttributeError: 'Engine' object has no attribute 'provider'` (whichever fails first; `Engine` doesn't have the field yet).

- [ ] **Step 3: Add the new constants**

In `searchmux/constants.py`, replace the top block:

```python
SERPAPI_BASE_URL = "https://serpapi.com/search"
ENV_API_KEY = "SERPAPI_API_KEY"
ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
```

with:

```python
SERPAPI_BASE_URL = "https://serpapi.com/search"
ENV_API_KEY = "SERPAPI_API_KEY"

TAVILY_BASE_URL = "https://api.tavily.com/search"
ENV_TAVILY_KEY = "TAVILY_API_KEY"

BRAVE_BASE_URL = "https://api.search.brave.com/res/v1/web/search"
ENV_BRAVE_KEY = "BRAVE_API_KEY"

EXA_BASE_URL = "https://api.exa.ai/search"
ENV_EXA_KEY = "EXA_API_KEY"

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
```

- [ ] **Step 4: Add `provider` to the `Engine` dataclass**

In `searchmux/catalog.py`, change:

```python
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
```

to:

```python
@dataclass(frozen=True, slots=True)
class Engine:
    """Metadata describing one search engine, from any provider.

    Attributes:
        engine_id: The value the provider expects for this engine.
        provider: Which backend serves this engine ("serpapi",
            "tavily", "brave", or "exa").
        description: Human-readable purpose, used for BM25 retrieval.
        keywords: Extra retrieval terms.
        params: Param name -> {"type", "required", ...}.
        results_key: Response key holding the result list.
        result_map: Result field -> source key in the raw item.
        ttl_class: Cache volatility class.
    """

    engine_id: str
    provider: str
    description: str
```

Then update `load_catalog()`'s record-building loop, changing:

```python
        engine = Engine(
            engine_id=record["engine_id"],
            description=record["description"],
```

to:

```python
        engine = Engine(
            engine_id=record["engine_id"],
            provider=record["provider"],
            description=record["description"],
```

- [ ] **Step 5: Backfill `"provider": "serpapi"` onto all 24 existing catalog records**

Run this once from the repo root (it rewrites `searchmux/catalog.json` in place):

```bash
python -c "
import json
from pathlib import Path

path = Path('searchmux/catalog.json')
records = json.loads(path.read_text(encoding='utf-8'))

reordered = []
for record in records:
    new_record = {'engine_id': record['engine_id'], 'provider': 'serpapi'}
    for key, value in record.items():
        if key != 'engine_id':
            new_record[key] = value
    reordered.append(new_record)

path.write_text(
    json.dumps(reordered, indent=2, ensure_ascii=False) + '\n',
    encoding='utf-8',
)
print(f'updated {len(reordered)} records')
"
```

Expected output: `updated 24 records`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_catalog.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 7: Run the full suite to confirm nothing else broke**

Run: `python -m pytest -q`
Expected: PASS, same count as before this task (no regressions — `provider` is additive and every existing record now has it).

- [ ] **Step 8: Commit**

```bash
git add searchmux/constants.py searchmux/catalog.py searchmux/catalog.json tests/test_catalog.py
git commit -m "feat: add provider field to Engine and backfill existing catalog"
```

---

### Task 2: `Backend` base class — refactor `Transport` without changing its behavior

**Files:**
- Modify: `searchmux/transport.py`

**Interfaces:**
- Consumes: `SERPAPI_BASE_URL` (existing), `HTTP_TIMEOUT`/`HTTP_MAX_RETRIES`/`HTTP_BACKOFF_BASE` (existing).
- Produces: `Backend` (abstract base, `.fetch(engine_id, params) -> dict`, subclasses implement `_build_request(engine_id, params) -> dict`), `SerpApiBackend(api_key, client=None)`, and `Transport = SerpApiBackend` as a backward-compatible alias. Consumed by Task 3 (sibling backends), Task 5 (`client.py` imports), and every existing test that imports `Transport`.

This task is a pure refactor: no test changes, because the existing `tests/test_transport.py` and `tests/test_client.py` already pin the exact behavior being preserved.

- [ ] **Step 1: Confirm the tests this task must not break**

Run: `python -m pytest tests/test_transport.py tests/test_client.py -v`
Expected: PASS (baseline, before the refactor).

- [ ] **Step 2: Replace `searchmux/transport.py` with the split implementation**

Replace the entire file with:

```python
"""HTTP backends per search provider, with retry on server errors."""

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


class Backend:
    """Shared retry/backoff HTTP loop for every search provider.

    Retries 5xx and timeouts with exponential backoff. Never retries
    4xx, because a bad request stays bad and each attempt is
    billable. Subclasses supply only _build_request.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        """Store the HTTP client.

        Args:
            client: Injected client, for tests. A default is built
                when omitted.
        """
        self._client = client or httpx.Client(timeout=HTTP_TIMEOUT)

    def _build_request(self, engine_id: str, params: dict) -> dict:
        """Return kwargs for httpx.Client.request().

        Must include "method" and "url", plus "params" or "json" for
        the request body, and "headers" when auth needs one.
        """
        raise NotImplementedError

    def fetch(self, engine_id: str, params: dict) -> dict:
        """Run one search and return the raw decoded body.

        Args:
            engine_id: The provider's identifier for this engine.
            params: Engine parameters, without any secret.

        Returns:
            The decoded JSON response body.

        Raises:
            SearchMuxAPIError: On a 4xx, or after retries are
                exhausted.
        """
        request = self._build_request(engine_id, params)
        last_error: Exception | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            try:
                response = self._client.request(**request)
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
                    "server error on %s, attempt %d",
                    engine_id,
                    attempt + 1,
                )

            if attempt < HTTP_MAX_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_BASE * (2**attempt))

        raise SearchMuxAPIError(
            f"{engine_id} failed after {HTTP_MAX_RETRIES} attempts"
        ) from last_error

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """Return the provider's error message, or the raw body."""
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text


class SerpApiBackend(Backend):
    """Performs SerpApi HTTP requests."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store credentials and the HTTP client.

        Args:
            api_key: SerpApi key.
            client: Injected client, for tests.
        """
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        query = {**params, "engine": engine_id, "api_key": self._api_key}
        return {"method": "GET", "url": SERPAPI_BASE_URL, "params": query}


# Backward-compat: existing code and tests import Transport directly.
Transport = SerpApiBackend
```

- [ ] **Step 3: Run the tests to verify nothing broke**

Run: `python -m pytest tests/test_transport.py tests/test_client.py -v`
Expected: PASS, identical results to Step 1.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, same count as Task 1's Step 7.

- [ ] **Step 5: Commit**

```bash
git add searchmux/transport.py
git commit -m "refactor: split Transport into a shared Backend base and SerpApiBackend"
```

---

### Task 3: `TavilyBackend`, `BraveBackend`, `ExaBackend`

**Files:**
- Modify: `searchmux/transport.py`
- Modify: `tests/test_transport.py`

**Interfaces:**
- Consumes: `Backend` (Task 2), `TAVILY_BASE_URL`/`BRAVE_BASE_URL`/`EXA_BASE_URL` (Task 1).
- Produces: `TavilyBackend(api_key, client=None)`, `BraveBackend(api_key, client=None)`, `ExaBackend(api_key, client=None)` — each with the inherited `.fetch(engine_id, params) -> dict`. Consumed by Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transport.py` (add `import json` to the top of the file alongside the existing `import httpx` / `import pytest`):

```python
from searchmux.transport import BraveBackend, ExaBackend, TavilyBackend


def _tavily(handler: httpx.MockTransport) -> TavilyBackend:
    client = httpx.Client(transport=handler)
    return TavilyBackend(api_key="test-key", client=client)


def test_tavily_sends_bearer_auth_and_json_body() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    _tavily(httpx.MockTransport(handler)).fetch(
        "tavily_search", {"query": "x"}
    )
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {"query": "x"}


def test_tavily_four_xx_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(SearchMuxAPIError, match="bad key"):
        _tavily(httpx.MockTransport(handler)).fetch(
            "tavily_search", {"query": "x"}
        )
    assert calls["n"] == 1


def _brave(handler: httpx.MockTransport) -> BraveBackend:
    client = httpx.Client(transport=handler)
    return BraveBackend(api_key="test-key", client=client)


def test_brave_sends_subscription_token_header_and_query_params() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("x-subscription-token")
        seen["q"] = dict(request.url.params).get("q")
        return httpx.Response(200, json={"web": {"results": []}})

    _brave(httpx.MockTransport(handler)).fetch("brave_search", {"q": "x"})
    assert seen["token"] == "test-key"
    assert seen["q"] == "x"


def test_brave_four_xx_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(SearchMuxAPIError, match="bad key"):
        _brave(httpx.MockTransport(handler)).fetch(
            "brave_search", {"q": "x"}
        )
    assert calls["n"] == 1


def _exa(handler: httpx.MockTransport) -> ExaBackend:
    client = httpx.Client(transport=handler)
    return ExaBackend(api_key="test-key", client=client)


def test_exa_sends_x_api_key_header_and_json_body() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": []})

    _exa(httpx.MockTransport(handler)).fetch("exa_search", {"query": "x"})
    assert seen["key"] == "test-key"
    assert seen["body"] == {"query": "x"}


def test_exa_four_xx_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(SearchMuxAPIError, match="bad key"):
        _exa(httpx.MockTransport(handler)).fetch("exa_search", {"query": "x"})
    assert calls["n"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_transport.py -v`
Expected: FAIL — `ImportError: cannot import name 'TavilyBackend'`.

- [ ] **Step 3: Add the three backend classes**

In `searchmux/transport.py`, change the constants import to:

```python
from searchmux.constants import (
    BRAVE_BASE_URL,
    EXA_BASE_URL,
    HTTP_BACKOFF_BASE,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERPAPI_BASE_URL,
    TAVILY_BASE_URL,
)
```

Then append after `SerpApiBackend` (before the `Transport = SerpApiBackend` alias line):

```python
class TavilyBackend(Backend):
    """Performs Tavily HTTP requests.

    POST with a JSON body; auth is a bearer token, not a body field.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "POST",
            "url": TAVILY_BASE_URL,
            "json": params,
            "headers": {"Authorization": f"Bearer {self._api_key}"},
        }


class BraveBackend(Backend):
    """Performs Brave Search HTTP requests.

    GET with query params, closest to SerpApi's own shape; auth is a
    header, not a query param.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "GET",
            "url": BRAVE_BASE_URL,
            "params": params,
            "headers": {"X-Subscription-Token": self._api_key},
        }


class ExaBackend(Backend):
    """Performs Exa HTTP requests.

    POST with a JSON body; x-api-key is used over the equally valid
    Authorization: Bearer form, for the simpler single-purpose header.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "POST",
            "url": EXA_BASE_URL,
            "json": params,
            "headers": {"x-api-key": self._api_key},
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_transport.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add searchmux/transport.py tests/test_transport.py
git commit -m "feat: add TavilyBackend, BraveBackend, and ExaBackend"
```

---

### Task 4: Catalog entries for `tavily_search`, `brave_search`, `exa_search`

**Files:**
- Modify: `searchmux/catalog.json`
- Modify: `tests/test_catalog.py`
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `Engine.provider` (Task 1). No code changes needed in `searchmux/normalize.py` — the existing dotted-path `results_key` and `result_map` convention already covers all three shapes (spec §3).
- Produces: three new catalog records, retrievable via `get_engine("tavily_search")` / `get_engine("brave_search")` / `get_engine("exa_search")`. Consumed by Task 5's client tests and Task 6's live smoke check.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog.py`:

```python
def test_new_provider_engines_are_catalogued() -> None:
    for engine_id, provider in [
        ("tavily_search", "tavily"),
        ("brave_search", "brave"),
        ("exa_search", "exa"),
    ]:
        engine = get_engine(engine_id)
        assert engine.provider == provider
```

Append to `tests/test_normalize.py`:

```python
def test_tavily_results_map_to_common_shape() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/a",
                "content": "A thorough review of the Pixel 10.",
            }
        ]
    }
    result = normalize("tavily_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/a"
    assert result.snippet == "A thorough review of the Pixel 10."
    assert result.source == "tavily_search"


def test_brave_results_map_to_common_shape() -> None:
    body = {
        "web": {
            "results": [
                {
                    "title": "Pixel 10 review",
                    "url": "https://x.test/b",
                    "description": "Hands-on with the Pixel 10.",
                }
            ]
        }
    }
    result = normalize("brave_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/b"
    assert result.snippet == "Hands-on with the Pixel 10."
    assert result.source == "brave_search"


def test_exa_results_map_to_common_shape() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/c",
                "text": "Exa's neural search summary of the Pixel 10.",
            }
        ]
    }
    result = normalize("exa_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/c"
    assert result.snippet == "Exa's neural search summary of the Pixel 10."
    assert result.source == "exa_search"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_catalog.py tests/test_normalize.py -v`
Expected: FAIL — `CatalogError: unknown engine: tavily_search` (and likewise for the other two).

- [ ] **Step 3: Append the three catalog records**

Run this once from the repo root:

```bash
python -c "
import json
from pathlib import Path

path = Path('searchmux/catalog.json')
records = json.loads(path.read_text(encoding='utf-8'))

records += [
    {
        'engine_id': 'tavily_search',
        'provider': 'tavily',
        'description': (
            'Web search via Tavily, an API built for LLM agents, '
            'returning clean flat results'
        ),
        'keywords': ['web', 'general', 'tavily', 'llm', 'agent'],
        'params': {'query': {'type': 'string', 'required': True}},
        'results_key': 'results',
        'result_map': {
            'title': 'title',
            'url': 'url',
            'snippet': 'content',
        },
        'ttl_class': 'news',
    },
    {
        'engine_id': 'brave_search',
        'provider': 'brave',
        'description': (
            \"Web search via Brave Search's independent index\"
        ),
        'keywords': ['web', 'general', 'brave', 'privacy'],
        'params': {'q': {'type': 'string', 'required': True}},
        'results_key': 'web.results',
        'result_map': {
            'title': 'title',
            'url': 'url',
            'snippet': 'description',
        },
        'ttl_class': 'news',
    },
    {
        'engine_id': 'exa_search',
        'provider': 'exa',
        'description': (
            'Neural/semantic web search via Exa, tuned for finding '
            'pages by meaning rather than keywords'
        ),
        'keywords': ['web', 'general', 'exa', 'semantic', 'neural'],
        'params': {'query': {'type': 'string', 'required': True}},
        'results_key': 'results',
        'result_map': {
            'title': 'title',
            'url': 'url',
            'snippet': 'text',
        },
        'ttl_class': 'news',
    },
]

path.write_text(
    json.dumps(records, indent=2, ensure_ascii=False) + '\n',
    encoding='utf-8',
)
print(f'catalog now has {len(records)} records')
"
```

Expected output: `catalog now has 27 records`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_catalog.py tests/test_normalize.py -v`
Expected: PASS, all tests in both files.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add searchmux/catalog.json tests/test_catalog.py tests/test_normalize.py
git commit -m "feat: add tavily_search, brave_search, and exa_search to the catalog"
```

---

### Task 5: Multi-provider `SearchMux` — new keys, `_require_backend`, `backends=`

**Files:**
- Modify: `searchmux/client.py`
- Modify: `.env.example`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `TavilyBackend`/`BraveBackend`/`ExaBackend` (Task 3), `SerpApiBackend`/`Backend` (Task 2), `ENV_TAVILY_KEY`/`ENV_BRAVE_KEY`/`ENV_EXA_KEY` (Task 1), `get_engine(engine).provider` (Task 1), the `tavily_search` catalog entry (Task 4).
- Produces: `SearchMux(api_key=, tavily_api_key=, brave_api_key=, exa_api_key=, budget=, cache=, transport=, backends=, router=)`, `SearchMux._require_backend(provider: str) -> Backend`. This is the last code task — Task 6 uses this constructor with real keys, Task 7 only touches docs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client.py`:

```python
def test_missing_tavily_key_names_the_right_env_var(tmp_path) -> None:
    q = SearchMux(cache=None)
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        q.search(engine="tavily_search", query="x")


def test_tavily_engine_never_requires_a_serpapi_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        return httpx.Response(
            200, json={"results": [{"title": "t", "url": "u"}]}
        )

    from searchmux.transport import TavilyBackend

    backend = TavilyBackend(
        api_key="tavily-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    q = SearchMux(cache=str(tmp_path / "c.db"), backends={"tavily": backend})
    results = q.search(engine="tavily_search", query="x")
    assert results[0].title == "t"
    assert calls["n"] == 1


def test_legacy_transport_kwarg_wins_over_backends_map(tmp_path) -> None:
    calls_legacy: dict = {}
    calls_map: dict = {}
    legacy = _stub_transport(BODY, calls_legacy)
    mapped = _stub_transport(BODY, calls_map)
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=legacy,
        backends={"serpapi": mapped},
    )
    q.search(engine="google", q="x")
    assert calls_legacy.get("n") == 1
    assert "n" not in calls_map


def test_require_backend_rejects_an_unknown_provider() -> None:
    q = SearchMux(cache=None)
    with pytest.raises(ValueError, match="unknown provider"):
        q._require_backend("bing")


def test_full_pipeline_works_for_a_non_serpapi_engine(tmp_path) -> None:
    from searchmux.transport import TavilyBackend

    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        return httpx.Response(
            200, json={"results": [{"title": "t", "url": "u"}]}
        )

    backend = TavilyBackend(
        api_key="tavily-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    q = SearchMux(
        budget=1,
        cache=str(tmp_path / "c.db"),
        backends={"tavily": backend},
    )
    q.search(engine="tavily_search", query="x")
    q.search(engine="tavily_search", query="x")
    assert calls["n"] == 1
    assert q.report()["credits_used"] == 1
    assert q.report()["cache_hits"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL — `TypeError: SearchMux.__init__() got an unexpected keyword argument 'backends'`.

- [ ] **Step 3: Update `searchmux/client.py`**

Change the constants and transport imports:

```python
from searchmux.constants import (
    DEFAULT_BUDGET,
    DEFAULT_CACHE_PATH,
    ENV_API_KEY,
    TTL_BY_CLASS,
)
```

to:

```python
from searchmux.constants import (
    DEFAULT_BUDGET,
    DEFAULT_CACHE_PATH,
    ENV_API_KEY,
    ENV_BRAVE_KEY,
    ENV_EXA_KEY,
    ENV_TAVILY_KEY,
    TTL_BY_CLASS,
)
```

and:

```python
from searchmux.transport import Transport
```

to:

```python
from searchmux.transport import (
    Backend,
    BraveBackend,
    ExaBackend,
    SerpApiBackend,
    TavilyBackend,
)
```

After the imports and `logger = logging.getLogger(__name__)`, add the provider table:

```python
# provider -> (api-key attribute, env var name, backend class, kwarg name)
_PROVIDERS: dict[str, tuple[str, str, type[Backend], str]] = {
    "serpapi": ("_api_key", ENV_API_KEY, SerpApiBackend, "api_key"),
    "tavily": (
        "_tavily_api_key", ENV_TAVILY_KEY, TavilyBackend, "tavily_api_key",
    ),
    "brave": (
        "_brave_api_key", ENV_BRAVE_KEY, BraveBackend, "brave_api_key",
    ),
    "exa": ("_exa_api_key", ENV_EXA_KEY, ExaBackend, "exa_api_key"),
}
```

Replace the `__init__` method:

```python
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
            router: Object with route(intent) -> (engine_id, params).
        """
        self._api_key = api_key or os.getenv(ENV_API_KEY)
        self._budget = Budget(limit=budget)
        self._cache = Cache(cache) if cache else None
        self._transport = transport
        self._router = router
        self._cassette: Cassette | None = None
        self._cache_hits = 0
```

with:

```python
    def __init__(
        self,
        api_key: str | None = None,
        tavily_api_key: str | None = None,
        brave_api_key: str | None = None,
        exa_api_key: str | None = None,
        budget: int = DEFAULT_BUDGET,
        cache: str | None = DEFAULT_CACHE_PATH,
        transport: Backend | None = None,
        backends: dict[str, Backend] | None = None,
        router: object | None = None,
    ) -> None:
        """Build a client.

        Args:
            api_key: SerpApi key. Falls back to SERPAPI_API_KEY. May be
                None when only replaying cassettes.
            tavily_api_key: Tavily key. Falls back to TAVILY_API_KEY.
            brave_api_key: Brave key. Falls back to BRAVE_API_KEY.
            exa_api_key: Exa key. Falls back to EXA_API_KEY.
            budget: Maximum billable requests for this instance.
            cache: SQLite path, or None to disable caching.
            transport: Injected SerpApi backend, for tests. Takes
                precedence over backends={"serpapi": ...} when both
                are given.
            backends: Injected {provider: Backend}, for testing the
                other three providers.
            router: Object with route(intent) -> (engine_id, params).
        """
        self._api_key = api_key or os.getenv(ENV_API_KEY)
        self._tavily_api_key = tavily_api_key or os.getenv(ENV_TAVILY_KEY)
        self._brave_api_key = brave_api_key or os.getenv(ENV_BRAVE_KEY)
        self._exa_api_key = exa_api_key or os.getenv(ENV_EXA_KEY)
        self._budget = Budget(limit=budget)
        self._cache = Cache(cache) if cache else None
        self._transport = transport
        self._backends: dict[str, Backend] = dict(backends or {})
        self._router = router
        self._cassette: Cassette | None = None
        self._cache_hits = 0
```

Replace the `_fetch` method's transport line — change:

```python
        self._budget.spend(engine)
        body = self._require_transport().fetch(engine, params)
```

to:

```python
        self._budget.spend(engine)
        provider = get_engine(engine).provider
        body = self._require_backend(provider).fetch(engine, params)
```

Replace `_require_transport` entirely:

```python
    def _require_transport(self) -> Transport:
        """Return the transport, building one on first use.

        Raises:
            ValueError: If no API key is available.
        """
        if self._transport is None:
            if not self._api_key:
                raise ValueError(
                    f"no API key; set {ENV_API_KEY} or pass api_key="
                )
            self._transport = Transport(api_key=self._api_key)
        return self._transport
```

with:

```python
    def _require_backend(self, provider: str) -> Backend:
        """Return the backend for one provider, building it lazily.

        The legacy transport= kwarg is checked first so existing
        SerpApi-only injection keeps working unchanged; backends= is
        checked next for the other three providers' tests; only then
        is a real backend constructed from an API key.

        Raises:
            ValueError: If the provider is unrecognized, or no API
                key is available for it.
        """
        if provider == "serpapi" and self._transport is not None:
            return self._transport
        if provider in self._backends:
            return self._backends[provider]
        if provider not in _PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")

        attr, env_name, backend_cls, kwarg_name = _PROVIDERS[provider]
        key = getattr(self, attr)
        if not key:
            raise ValueError(
                f"no API key; set {env_name} or pass {kwarg_name}="
            )
        backend = backend_cls(api_key=key)
        self._backends[provider] = backend
        return backend
```

- [ ] **Step 4: Add the new provider keys to `.env.example`**

Append to `.env.example`:

```
# Optional additional providers. Each falls back to the env var named
# below; SearchMux never touches a key for a provider you don't use.
TAVILY_API_KEY=
BRAVE_API_KEY=
EXA_API_KEY=
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: PASS, all tests in the file, including the pre-existing ones.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add searchmux/client.py .env.example tests/test_client.py
git commit -m "feat: multi-provider SearchMux with lazy per-provider backends"
```

---

### Task 6: Live smoke check for Tavily and Exa

**Files:** none committed — this is a manual verification step against the real APIs, using the keys already present in the local, gitignored `.env`. Brave is skipped: no key is available (spec §2, §5).

**Interfaces:**
- Consumes: `SearchMux` (Task 5), the `tavily_search`/`exa_search` catalog entries (Task 4), real `TAVILY_API_KEY`/`EXA_API_KEY` values already in `.env`.
- Produces: confirmation (or a correction) that the doc-derived `result_map` in Task 4's catalog entries matches what each API actually returns — the same live-correction step that caught SerpApi's Amazon `k`-vs-`q` mismatch in the original catalog.

- [ ] **Step 1: Load the local `.env` and run a live Tavily search**

```bash
python -c "
from searchmux import SearchMux
from searchmux.envfile import load_env

load_env()
q = SearchMux(cache=None, budget=1)
for r in q.search(engine='tavily_search', query='Pixel 10 review'):
    print(r.title, '|', r.url, '|', (r.snippet or '')[:60])
"
```

Expected: at least one result with a non-empty `title` and `url`. If `title`/`url`/`snippet` come back empty while the raw response clearly has data, re-check Tavily's actual field names against `Result.raw` printed from the same run, and correct `result_map` in `searchmux/catalog.json`'s `tavily_search` record to match — then re-run this step until it passes.

- [ ] **Step 2: Run a live Exa search**

```bash
python -c "
from searchmux import SearchMux
from searchmux.envfile import load_env

load_env()
q = SearchMux(cache=None, budget=1)
for r in q.search(engine='exa_search', query='Pixel 10 review'):
    print(r.title, '|', r.url, '|', (r.snippet or '')[:60])
"
```

Expected: at least one result with a non-empty `title` and `url`. Apply the same correction process as Step 1 if the mapping is wrong.

- [ ] **Step 3: If either catalog record needed a correction, run the full suite and commit**

Run: `python -m pytest -q`
Expected: PASS.

```bash
git add searchmux/catalog.json
git commit -m "fix: correct result_map after a live Tavily/Exa smoke check"
```

If no correction was needed, skip this step — there is nothing to commit.

---

### Task 7: Docs, `CHANGELOG.md`, and the `0.2.0` version bump

**Files:**
- Modify: `scripts/build_engine_docs.py`
- Modify: `docs/ENGINES.md` (regenerated, not hand-edited)
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: the final `searchmux/catalog.json` (Tasks 1 and 4) and `searchmux/client.py` constructor signature (Task 5). Produces nothing further tasks depend on — this is the last task.

- [ ] **Step 1: Add a Provider column to the generated engine docs**

In `scripts/build_engine_docs.py`, change:

```python
        "## Summary",
        "",
        "| Engine | Required parameters | Results key | Cache TTL |",
        "| --- | --- | --- | --- |",
    ]
    for record in rows:
        required = ", ".join(
            f"`{name}`"
            for name, spec in record["params"].items()
            if spec.get("required")
        ) or "—"
        ttl = TTL_LABELS.get(record.get("ttl_class"), record.get("ttl_class"))
        out.append(
            f"| `{record['engine_id']}` | {required} | "
            f"`{record['results_key']}` | {ttl} |"
        )
```

to:

```python
        "## Summary",
        "",
        "| Engine | Provider | Required parameters | Results key | Cache TTL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in rows:
        required = ", ".join(
            f"`{name}`"
            for name, spec in record["params"].items()
            if spec.get("required")
        ) or "—"
        ttl = TTL_LABELS.get(record.get("ttl_class"), record.get("ttl_class"))
        out.append(
            f"| `{record['engine_id']}` | {record['provider']} | "
            f"{required} | `{record['results_key']}` | {ttl} |"
        )
```

And in the Details section, change:

```python
    for record in rows:
        out += [f"### `{record['engine_id']}`", "", record["description"], ""]
```

to:

```python
    for record in rows:
        out += [
            f"### `{record['engine_id']}`",
            "",
            f"Provider: `{record['provider']}`. {record['description']}",
            "",
        ]
```

- [ ] **Step 2: Regenerate `docs/ENGINES.md`**

Run: `python scripts/build_engine_docs.py`
Expected output: `wrote .../docs/ENGINES.md from 27 engines`.

- [ ] **Step 3: Update `docs/API.md`**

Change the `SearchMux(...)` signature block:

```python
SearchMux(
    api_key: str | None = None,
    budget: int = 50,
    cache: str | None = ".searchmux.db",
    transport: Transport | None = None,
    router: object | None = None,
)
```

to:

```python
SearchMux(
    api_key: str | None = None,
    tavily_api_key: str | None = None,
    brave_api_key: str | None = None,
    exa_api_key: str | None = None,
    budget: int = 50,
    cache: str | None = ".searchmux.db",
    transport: Backend | None = None,
    backends: dict[str, Backend] | None = None,
    router: object | None = None,
)
```

And the argument table, adding rows after `api_key` and after `transport`:

```markdown
| Argument | Meaning |
|---|---|
| `api_key` | SerpApi key. Falls back to `SERPAPI_API_KEY`. May be `None` when only replaying cassettes. |
| `tavily_api_key` | Tavily key. Falls back to `TAVILY_API_KEY`. |
| `brave_api_key` | Brave key. Falls back to `BRAVE_API_KEY`. |
| `exa_api_key` | Exa key. Falls back to `EXA_API_KEY`. |
| `budget` | Maximum billable requests for this instance. Cache hits and replays do not count. |
| `cache` | SQLite path, or `None` to disable caching. |
| `transport` | Injected SerpApi `Backend`, for tests. Takes precedence over `backends={"serpapi": ...}` when both are given. |
| `backends` | Injected `{provider: Backend}`, for testing Tavily/Brave/Exa without a key. |
| `router` | Anything with `route(intent) -> (engine_id, params)`. |
```

- [ ] **Step 4: Update `docs/ARCHITECTURE.md`**

In the pipeline diagram, change:

```
[4] Transport       httpx → serpapi.com/search                transport.py
   │                  …or replay from a cassette              cassette.py
```

to:

```
[4] Transport       httpx → the engine's provider backend      transport.py
   │                  …or replay from a cassette              cassette.py
```

In the Modules table, change:

```
| `transport.py` | HTTP, with retry on server errors only. |
```

to:

```
| `transport.py` | HTTP backends per provider (SerpApi, Tavily, Brave, Exa), retrying server errors only. |
```

Add a new Design decisions subsection, right after "### The catalog is generated, then committed":

```markdown
### One retry loop, four request shapes

`transport.py` holds a `Backend` base class with the retry/backoff loop
(unchanged from the original SerpApi-only `Transport`) and one subclass
per provider that supplies only `_build_request`: method, URL, and
whether auth and parameters go in headers, a query string, or a JSON
body. `Engine.provider` says which backend an engine uses; `SearchMux`
builds each backend lazily, only when an engine from that provider is
actually requested, so a SerpApi-only caller never needs a Tavily,
Brave, or Exa key.
```

- [ ] **Step 5: Update `CHANGELOG.md`**

Change:

```markdown
## [Unreleased]

Nothing yet.

## [0.1.5] — 2026-09-29
```

to:

```markdown
## [Unreleased]

Nothing yet.

## [0.2.0] — 2026-09-30

### Added

- Multi-provider search: `tavily_search`, `brave_search`, and
  `exa_search` join the catalog alongside SerpApi's 24 engines, all
  through the same cache, budget guard, cassette replay, and
  `Result` normalization. `Engine.provider` marks which backend each
  entry uses.
- `SearchMux(tavily_api_key=, brave_api_key=, exa_api_key=)`, each
  falling back to its own environment variable, and a `backends=`
  constructor kwarg for injecting fakes in tests. `transport=` keeps
  working exactly as before for SerpApi.
- `transport.py`'s retry/backoff loop is now shared by every backend
  through a `Backend` base class; `Transport` is kept as an alias
  for the SerpApi backend, so no existing import breaks.

### Verified

- Tavily and Exa request shapes were checked against a live call
  using real keys. Brave was built and doc-verified to the same
  standard but has no live check yet — no key was available.

## [0.1.5] — 2026-09-29
```

And at the bottom, change:

```markdown
[Unreleased]: https://github.com/ai-engineerr/searchmux/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/ai-engineerr/searchmux/compare/v0.1.4...v0.1.5
```

to:

```markdown
[Unreleased]: https://github.com/ai-engineerr/searchmux/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ai-engineerr/searchmux/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/ai-engineerr/searchmux/compare/v0.1.4...v0.1.5
```

- [ ] **Step 6: Bump the version in `pyproject.toml`**

Change:

```toml
version = "0.1.5"
```

to:

```toml
version = "0.2.0"
```

- [ ] **Step 7: Lint and run the full suite**

Run: `python -m ruff check .`
Expected: no errors. Fix any line-length or import-order issues ruff reports before continuing.

Run: `python -m pytest -q`
Expected: PASS, full suite green.

- [ ] **Step 8: Commit**

```bash
git add scripts/build_engine_docs.py docs/ENGINES.md docs/API.md docs/ARCHITECTURE.md CHANGELOG.md pyproject.toml
git commit -m "docs: document multi-provider backends and bump to 0.2.0"
```

**Do not run `git push`, `python -m build`, or `twine upload` at the end of this task or this plan** — every commit stays local until the user explicitly authorizes publishing (Global Constraints, spec §6).
