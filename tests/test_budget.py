"""Tests for the credit budget guard."""

import threading

import pytest

from quiver.budget import Budget
from quiver.models import BudgetExceeded


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
