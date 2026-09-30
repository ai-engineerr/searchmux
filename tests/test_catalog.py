"""Tests for catalog loading and lookup."""

import json

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


def test_every_engine_declares_a_provider() -> None:
    for engine_id, engine in load_catalog().items():
        assert engine.provider, f"{engine_id} has no provider"


def test_existing_engines_are_serpapi() -> None:
    assert get_engine("google").provider == "serpapi"


def test_new_provider_engines_are_catalogued() -> None:
    for engine_id, provider in [
        ("tavily_search", "tavily"),
        ("brave_search", "brave"),
        ("exa_search", "exa"),
    ]:
        engine = get_engine(engine_id)
        assert engine.provider == provider


def test_cacheable_defaults_to_true() -> None:
    assert get_engine("google").cacheable is True


def test_cacheable_false_is_read_from_the_record(tmp_path) -> None:
    custom = tmp_path / "catalog.json"
    custom.write_text(
        json.dumps(
            [
                {
                    "engine_id": "no_cache_engine",
                    "provider": "serpapi",
                    "description": "test",
                    "keywords": ["test"],
                    "params": {"q": {"type": "string", "required": True}},
                    "results_key": "organic_results",
                    "result_map": {},
                    "cacheable": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    catalog = load_catalog(path=str(custom))
    assert catalog["no_cache_engine"].cacheable is False
