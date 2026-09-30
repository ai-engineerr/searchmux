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


def test_missing_tavily_key_names_the_right_env_var(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
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


def test_no_cache_provider_override_skips_caching(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
        no_cache={"serpapi"},
    )
    q.search(engine="google", q="x")
    q.search(engine="google", q="x")
    assert calls["n"] == 2
    assert q.report()["cache_hits"] == 0


def test_no_cache_engine_id_override_skips_caching(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
        no_cache={"google"},
    )
    q.search(engine="google", q="x")
    q.search(engine="google", q="x")
    assert calls["n"] == 2


def test_no_cache_override_does_not_affect_other_engines(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=str(tmp_path / "c.db"),
        transport=_stub_transport(BODY, calls),
        no_cache={"tavily"},
    )
    q.search(engine="google", q="x")
    q.search(engine="google", q="x")
    assert calls["n"] == 1
    assert q.report()["cache_hits"] == 1


def test_is_cacheable_respects_the_catalog_flag() -> None:
    from searchmux.catalog import Engine
    from searchmux.client import _is_cacheable

    spec = Engine(
        engine_id="x",
        provider="serpapi",
        description="d",
        keywords=[],
        params={},
        results_key="r",
        result_map={},
        cacheable=False,
    )
    assert _is_cacheable(spec, "x", set()) is False


def test_is_cacheable_true_by_default() -> None:
    from searchmux.catalog import Engine
    from searchmux.client import _is_cacheable

    spec = Engine(
        engine_id="x",
        provider="serpapi",
        description="d",
        keywords=[],
        params={},
        results_key="r",
        result_map={},
    )
    assert _is_cacheable(spec, "x", set()) is True


def test_is_cacheable_respects_provider_override() -> None:
    from searchmux.catalog import Engine
    from searchmux.client import _is_cacheable

    spec = Engine(
        engine_id="tavily_search",
        provider="tavily",
        description="d",
        keywords=[],
        params={},
        results_key="r",
        result_map={},
    )
    assert _is_cacheable(spec, "tavily_search", {"tavily"}) is False


def test_is_cacheable_respects_engine_id_override() -> None:
    from searchmux.catalog import Engine
    from searchmux.client import _is_cacheable

    spec = Engine(
        engine_id="google",
        provider="serpapi",
        description="d",
        keywords=[],
        params={},
        results_key="r",
        result_map={},
    )
    assert _is_cacheable(spec, "google", {"google"}) is False


def test_budget_usd_raises_before_exceeding(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
        budget=100,
        budget_usd=0.5,
        cost_per_request={"serpapi": 0.4},
    )
    q.search(engine="google", q="a")
    with pytest.raises(BudgetExceeded):
        q.search(engine="google", q="b")
    assert calls["n"] == 1


def test_budget_usd_unset_ignores_cost_per_request(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
        budget=2,
        cost_per_request={"serpapi": 1000.0},
    )
    q.search(engine="google", q="a")
    q.search(engine="google", q="b")
    assert calls["n"] == 2


def test_budget_usd_missing_rate_raises_value_error(tmp_path) -> None:
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, {}),
        budget_usd=10.0,
    )
    with pytest.raises(ValueError, match="serpapi"):
        q.search(engine="google", q="x")


def test_report_includes_usd_fields_when_budget_usd_is_set(
    tmp_path,
) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
        budget_usd=1.0,
        cost_per_request={"serpapi": 0.25},
    )
    q.search(engine="google", q="a")
    report = q.report()
    assert report["spent_usd"] == 0.25
    assert report["remaining_usd"] == 0.75


def test_report_omits_usd_fields_by_default(tmp_path) -> None:
    calls: dict = {}
    q = SearchMux(
        api_key="test-key",
        cache=None,
        transport=_stub_transport(BODY, calls),
    )
    q.search(engine="google", q="a")
    assert "spent_usd" not in q.report()


def test_no_cache_cannot_re_enable_a_non_cacheable_engine() -> None:
    """no_cache only narrows; it can never override the catalog's own
    cacheable=False back to True."""
    from searchmux.catalog import Engine
    from searchmux.client import _is_cacheable

    spec = Engine(
        engine_id="x",
        provider="serpapi",
        description="d",
        keywords=[],
        params={},
        results_key="r",
        result_map={},
        cacheable=False,
    )
    assert _is_cacheable(spec, "x", set()) is False
