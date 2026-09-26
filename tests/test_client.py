"""Tests for the SearchMux facade and the request pipeline."""

import httpx
import pytest

from searchmux import SearchMux
from searchmux.models import BudgetExceeded, RoutingError
from searchmux.transport import Transport

BODY = {"organic_results": [{"title": "t", "link": "u", "position": 1}]}


def _stub_transport(body: dict, calls: dict) -> Transport:
    """Return a Transport that counts calls and replays one body."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Transport(api_key="test-key", client=client)


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


def test_budget_exhaustion_raises_before_the_call() -> None:
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
    results = q.find("anything at all", engine="google")
    assert results[0].title == "t"


def test_pinned_find_uses_the_intent_as_the_query(tmp_path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=Transport(api_key="k", client=client),
    )
    q.find("pixel 10 reviews", engine="google")
    assert seen["q"] == "pixel 10 reviews"


def test_explicit_params_override_the_intent(tmp_path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=Transport(api_key="k", client=client),
    )
    q.find("ignored", engine="google", q="explicit")
    assert seen["q"] == "explicit"


def test_find_without_engine_or_router_raises(tmp_path) -> None:
    q = SearchMux(api_key="test-key", cache=None)
    with pytest.raises(RoutingError, match="engine"):
        q.find("something")


def test_find_uses_an_injected_router(tmp_path) -> None:
    calls: dict = {}

    class FakeRouter:
        def route(self, intent: str) -> tuple[str, dict]:
            return "google", {"q": "routed"}

    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
        router=FakeRouter(),
    )
    assert q.find("what should I read")[0].title == "t"


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


def test_missing_key_raises_only_when_a_call_is_needed(
    tmp_path, monkeypatch
) -> None:
    """Constructing without a key is fine; fetching without one is not."""
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    q = SearchMux(cache=None)
    with pytest.raises(ValueError, match="SERPAPI_API_KEY"):
        q.search(engine="google", q="x")
