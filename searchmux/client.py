"""The SearchMux facade: one pipeline over cache, budget, and transport.

The pipeline is intent -> router -> cache -> budget -> transport ->
normalizer -> cache write. Routing is optional; pinning an engine skips
it, so the cache, the budget guard, and cassettes all work with no LLM
and no LLM key.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from searchmux.adapters.tool import openai_tool_schema, tool_schema
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
from searchmux.models import Result, RoutingError
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
            router: Object with route(intent) -> (engine_id, params).
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
            **params: Parameters, merged over whatever the router or
                the intent supplies.

        Returns:
            Normalized results.

        Raises:
            RoutingError: If no engine is pinned and no router is set.
        """
        if engine is not None:
            # The intent is the query unless the caller overrides q.
            return self.search(engine=engine, **{"q": intent, **params})

        if self._router is None:
            raise RoutingError(
                "no engine pinned and no router configured; pass "
                "engine= or construct SearchMux with a router"
            )
        engine_id, routed = self._router.route(intent)
        return self.search(engine=engine_id, **{**routed, **params})

    def as_tool(self) -> dict:
        """Return an Anthropic-shaped tool-use schema for this client.

        LangChain's structured-tool helpers accept this same shape.

        Returns:
            A schema accepted by Anthropic tool use and LangChain.
        """
        return tool_schema()

    def as_openai_tool(self) -> dict:
        """Return an OpenAI function-calling schema for this client.

        Returns:
            A dict ready to pass directly in an OpenAI `tools=[...]`
            list.
        """
        return openai_tool_schema()

    def _fetch(self, engine: str, params: dict) -> dict:
        """Replay, or spend a credit and call SerpApi.

        The budget is checked before the request, never after: the
        point is to not spend the credit.
        """
        replaying = (
            self._cassette is not None
            and self._cassette.mode == MODE_REPLAY
        )
        if replaying:
            return self._cassette.play(engine, params)

        self._budget.spend(engine)
        body = self._require_transport().fetch(engine, params)

        recording = (
            self._cassette is not None
            and self._cassette.mode == MODE_RECORD
        )
        if recording:
            self._cassette.capture(engine, params, body)
        return body

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

        A request absent from the cassette raises rather than reaching
        the network, so a test cannot silently become billable.

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
