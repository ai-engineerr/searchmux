"""Tests for BM25 retrieval and schema-constrained routing."""

import pytest

from searchmux.models import RoutingError
from searchmux.router import Router


class FakeLLM:
    """Returns scripted routing decisions and records its prompts."""

    def __init__(self, *decisions: dict) -> None:
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def complete(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        if len(self.decisions) == 1:
            return self.decisions[0]
        return self.decisions.pop(0)


class NullLLM:
    """Fails loudly if the retrieval-only path calls an LLM."""

    def complete(self, prompt: str, schema: dict) -> dict:
        raise AssertionError("retrieval must not call the LLM")


def test_retrieve_ranks_shopping_for_a_price_intent() -> None:
    candidates = Router(llm=NullLLM()).retrieve(
        "current price of the Pixel 10 phone"
    )
    assert "google_shopping" in candidates


def test_retrieve_ranks_scholar_for_a_research_intent() -> None:
    candidates = Router(llm=NullLLM()).retrieve(
        "peer reviewed academic papers about CRISPR"
    )
    assert "google_scholar" in candidates


def test_retrieve_returns_at_most_top_k() -> None:
    router = Router(llm=NullLLM(), top_k=3)
    assert len(router.retrieve("flights to Tokyo")) == 3


def test_retrieve_is_deterministic() -> None:
    router = Router(llm=NullLLM())
    first = router.retrieve("cheap hotels in Goa")
    assert router.retrieve("cheap hotels in Goa") == first


def test_route_returns_engine_and_params() -> None:
    llm = FakeLLM(
        {"engine_id": "google_shopping", "params": {"q": "Pixel 10"}}
    )
    engine_id, params = Router(llm=llm).route("price of Pixel 10")
    assert engine_id == "google_shopping"
    assert params == {"q": "Pixel 10"}


def test_prompt_carries_only_the_candidate_schemas() -> None:
    llm = FakeLLM({"engine_id": "google", "params": {"q": "x"}})
    router = Router(llm=llm, top_k=2)
    candidates = router.retrieve("something to read about")
    router.route("something to read about")

    prompt = llm.prompts[0]
    present = [e for e in router.engine_ids if f'"{e}"' in prompt]
    assert sorted(present) == sorted(candidates)


def test_engine_outside_the_catalog_raises() -> None:
    llm = FakeLLM({"engine_id": "invented_engine", "params": {"q": "x"}})
    with pytest.raises(RoutingError, match="invented_engine"):
        Router(llm=llm).route("something")


def test_missing_required_param_raises_after_one_repair() -> None:
    llm = FakeLLM({"engine_id": "google", "params": {}})
    with pytest.raises(RoutingError, match="q"):
        Router(llm=llm).route("something")
    assert len(llm.prompts) == 2


def test_repair_attempt_can_succeed() -> None:
    llm = FakeLLM(
        {"engine_id": "google", "params": {}},
        {"engine_id": "google", "params": {"q": "fixed"}},
    )
    engine_id, params = Router(llm=llm).route("something")
    assert engine_id == "google"
    assert params == {"q": "fixed"}
    assert len(llm.prompts) == 2


def test_repair_prompt_names_the_rejection_reason() -> None:
    llm = FakeLLM(
        {"engine_id": "google", "params": {}},
        {"engine_id": "google", "params": {"q": "fixed"}},
    )
    Router(llm=llm).route("something")
    assert "rejected" in llm.prompts[1]


def test_unknown_param_is_dropped_not_fatal() -> None:
    llm = FakeLLM(
        {"engine_id": "google", "params": {"q": "x", "nonsense": 1}}
    )
    _, params = Router(llm=llm).route("something")
    assert params == {"q": "x"}


def _closed_everywhere(schema: dict, path: str = "$") -> list[str]:
    """Return paths of object schemas missing additionalProperties."""
    problems = []
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            problems.append(path)
        for name, sub in (schema.get("properties") or {}).items():
            problems += _closed_everywhere(sub, f"{path}.{name}")
    return problems


def test_built_schema_is_closed_at_every_object_level() -> None:
    """Structured outputs reject any open object, nested ones included."""
    router = Router(llm=NullLLM(), top_k=4)
    candidates = router.retrieve("cheapest flight to Tokyo")
    schema = router._decision_schema(candidates)
    assert _closed_everywhere(schema) == []


def test_engine_only_schema_is_closed() -> None:
    from searchmux.router import ENGINE_ONLY_SCHEMA

    assert _closed_everywhere(ENGINE_ONLY_SCHEMA) == []


def test_built_schema_restricts_engine_to_the_candidates() -> None:
    router = Router(llm=NullLLM(), top_k=3)
    candidates = router.retrieve("academic papers on protein folding")
    schema = router._decision_schema(candidates)
    assert schema["properties"]["engine_id"]["enum"] == candidates


def test_built_schema_carries_params_as_name_value_pairs() -> None:
    router = Router(llm=NullLLM(), top_k=2)
    schema = router._decision_schema(router.retrieve("flights to Tokyo"))
    params = schema["properties"]["params"]
    assert params["type"] == "array"
    assert set(params["items"]["properties"]) == {"name", "value"}
    assert params["items"]["additionalProperties"] is False


def test_schema_size_does_not_grow_with_the_catalog() -> None:
    """A schema built from every engine's params is rejected as too
    complex by the API, so size must stay flat."""
    import json

    router = Router(llm=NullLLM())
    small = len(json.dumps(router._decision_schema(["google"])))
    large = len(json.dumps(router._decision_schema(router.engine_ids)))
    # Only the engine_id enum grows; the params schema is fixed.
    assert large - small < 600


def test_router_accepts_pair_list_params() -> None:
    llm = FakeLLM(
        {
            "engine_id": "google",
            "params": [{"name": "q", "value": "hello"}],
        }
    )
    engine_id, params = Router(llm=llm).route("something")
    assert engine_id == "google"
    assert params == {"q": "hello"}


def test_router_still_accepts_plain_dict_params() -> None:
    llm = FakeLLM({"engine_id": "google", "params": {"q": "hello"}})
    assert Router(llm=llm).route("x")[1] == {"q": "hello"}


def test_unknown_pair_name_is_dropped() -> None:
    llm = FakeLLM(
        {
            "engine_id": "google",
            "params": [
                {"name": "q", "value": "hello"},
                {"name": "nonsense", "value": "1"},
            ],
        }
    )
    assert Router(llm=llm).route("x")[1] == {"q": "hello"}


def test_top_k_none_returns_every_engine() -> None:
    router = Router(llm=NullLLM(), top_k=None)
    assert len(router.retrieve("anything")) == len(router.engine_ids)
