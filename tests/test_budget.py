"""Tests for the credit budget guard."""

import threading

import pytest

from searchmux.budget import Budget
from searchmux.models import BudgetExceeded


def test_spend_increments_usage() -> None:
    budget = Budget(limit=3)
    budget.spend("google")
    assert budget.used == 1
    assert budget.remaining == 2


def test_spend_raises_at_the_limit() -> None:
    budget = Budget(limit=1)
    budget.spend("google")
    with pytest.raises(BudgetExceeded, match="1"):
        budget.spend("google")


def test_rejected_spend_does_not_increment() -> None:
    budget = Budget(limit=1)
    budget.spend("google")
    with pytest.raises(BudgetExceeded):
        budget.spend("google")
    assert budget.used == 1


def test_report_breaks_down_by_engine() -> None:
    budget = Budget(limit=5)
    budget.spend("google")
    budget.spend("google")
    budget.spend("bing")
    assert budget.report() == {
        "credits_used": 3,
        "remaining": 2,
        "by_engine": {"google": 2, "bing": 1},
    }


def test_zero_limit_rejects_immediately() -> None:
    with pytest.raises(BudgetExceeded):
        Budget(limit=0).spend("google")


def test_concurrent_spends_never_exceed_the_limit() -> None:
    budget = Budget(limit=10)
    granted: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            budget.spend("google")
        except BudgetExceeded:
            return
        with lock:
            granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(granted) == 10
    assert budget.used == 10


def test_dollar_tracking_is_off_by_default() -> None:
    budget = Budget(limit=3, cost_per_request={"serpapi": 100.0})
    budget.spend("google", provider="serpapi")
    assert "spent_usd" not in budget.report()
    assert "remaining_usd" not in budget.report()


def test_dollar_budget_tracks_spend() -> None:
    budget = Budget(
        limit=100, budget_usd=1.0, cost_per_request={"serpapi": 0.25}
    )
    budget.spend("google", provider="serpapi")
    budget.spend("google", provider="serpapi")
    report = budget.report()
    assert report["spent_usd"] == 0.5
    assert report["remaining_usd"] == 0.5


def test_dollar_budget_raises_before_exceeding() -> None:
    budget = Budget(
        limit=100, budget_usd=0.5, cost_per_request={"serpapi": 0.4}
    )
    budget.spend("google", provider="serpapi")
    with pytest.raises(BudgetExceeded, match=r"\$"):
        budget.spend("google", provider="serpapi")
    assert budget.report()["spent_usd"] == 0.4


def test_dollar_budget_rejected_spend_does_not_increment_anything() -> None:
    budget = Budget(
        limit=100, budget_usd=0.1, cost_per_request={"serpapi": 0.4}
    )
    with pytest.raises(BudgetExceeded):
        budget.spend("google", provider="serpapi")
    assert budget.used == 0
    assert budget.report()["spent_usd"] == 0.0


def test_dollar_budget_missing_rate_raises_value_error() -> None:
    budget = Budget(limit=100, budget_usd=10.0, cost_per_request={})
    with pytest.raises(ValueError, match="tavily"):
        budget.spend("tavily_search", provider="tavily")
    assert budget.used == 0


def test_request_count_limit_still_applies_with_a_dollar_budget() -> None:
    budget = Budget(
        limit=1, budget_usd=100.0, cost_per_request={"serpapi": 0.01}
    )
    budget.spend("google", provider="serpapi")
    with pytest.raises(BudgetExceeded, match="1"):
        budget.spend("google", provider="serpapi")


def test_concurrent_spends_never_exceed_the_dollar_budget() -> None:
    budget = Budget(
        limit=1000, budget_usd=1.0, cost_per_request={"serpapi": 0.1}
    )
    granted: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            budget.spend("google", provider="serpapi")
        except BudgetExceeded:
            return
        with lock:
            granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(granted) == 10
    assert budget.report()["spent_usd"] == pytest.approx(1.0)
