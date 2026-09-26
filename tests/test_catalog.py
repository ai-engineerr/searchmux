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
