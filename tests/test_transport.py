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
