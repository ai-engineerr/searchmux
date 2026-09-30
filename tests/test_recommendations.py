"""Tests for the eval-derived provider recommendations."""

from searchmux.recommendations import (
    DEFAULT_ORDER,
    RECOMMENDED_PROVIDERS,
    recommended_providers,
)

_KNOWN_PROVIDERS = {"serpapi", "tavily", "exa"}


def test_every_category_orders_exactly_the_three_measured_providers() -> (
    None
):
    for category, order in RECOMMENDED_PROVIDERS.items():
        assert set(order) == _KNOWN_PROVIDERS, category
        assert len(order) == len(set(order)), category  # no duplicates


def test_default_order_is_one_of_the_three_measured_providers_too() -> None:
    assert set(DEFAULT_ORDER) == _KNOWN_PROVIDERS
    assert len(DEFAULT_ORDER) == len(set(DEFAULT_ORDER))


def test_recommended_providers_returns_the_categorys_order() -> None:
    assert (
        recommended_providers("current_events")
        == RECOMMENDED_PROVIDERS["current_events"]
    )


def test_recommended_providers_falls_back_for_an_unknown_category() -> (
    None
):
    assert recommended_providers("not_a_real_category") == DEFAULT_ORDER


def test_recommended_providers_falls_back_when_none() -> None:
    assert recommended_providers() == DEFAULT_ORDER
    assert recommended_providers(None) == DEFAULT_ORDER


def test_recommended_providers_returns_a_copy_not_the_shared_list() -> (
    None
):
    """Callers must not be able to mutate the module's own table."""
    result = recommended_providers("research")
    result.append("brave")
    assert "brave" not in RECOMMENDED_PROVIDERS["research"]
