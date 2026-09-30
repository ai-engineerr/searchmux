"""Tests for the SerpApi transport layer."""

import json

import httpx
import pytest

from searchmux.models import SearchMuxAPIError
from searchmux.transport import BraveBackend, ExaBackend, TavilyBackend, Transport


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
