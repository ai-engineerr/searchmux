"""Tests for the Result and Money value objects."""

import pytest

from searchmux.models import (
    BudgetExceeded,
    Money,
    Result,
    SearchMuxError,
)


def test_result_keeps_raw_payload() -> None:
    raw = {"title": "Pixel 10", "link": "https://x.test", "junk": 1}
    r = Result(title="Pixel 10", url="https://x.test", raw=raw)
    assert r.raw["junk"] == 1
    assert r.snippet is None


def test_result_is_immutable() -> None:
    r = Result(title="a", raw={})
    with pytest.raises(AttributeError):
        r.title = "b"  # type: ignore[misc]


def test_money_formats_with_currency() -> None:
    assert str(Money(amount=79999.0, currency="INR")) == "INR 79999.00"


def test_budget_exceeded_is_a_searchmux_error() -> None:
    assert issubclass(BudgetExceeded, SearchMuxError)
