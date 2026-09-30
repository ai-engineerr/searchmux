"""Tests for the provider comparison eval's offline logic."""

from evals.provider_eval import (
    QUERIES_PATH,
    _aggregate,
    _format_category_table,
    _format_overall_table,
    _percentile,
    domain_overlap,
    load_queries,
    run_one,
)
from searchmux import SearchMux
from searchmux.models import SearchMuxError


def test_queries_load_with_category_and_optional_expect_any() -> None:
    cases = load_queries(QUERIES_PATH)
    assert len(cases) >= 30
    categories = {c["category"] for c in cases}
    assert "factual" in categories
    assert len(categories) >= 4
    for case in cases:
        assert case["query"]
        assert case["category"]


def test_factual_category_queries_have_an_expected_answer() -> None:
    cases = load_queries(QUERIES_PATH)
    factual = [c for c in cases if c["category"] == "factual"]
    assert len(factual) >= 5
    for case in factual:
        assert case["expect_any"]


def test_percentile_of_a_single_value_is_itself() -> None:
    assert _percentile([42.0], 0.95) == 42.0


def test_percentile_p95_is_near_the_top() -> None:
    values = [float(i) for i in range(1, 21)]  # 1..20
    assert _percentile(values, 0.95) >= 18.0


def test_percentile_of_empty_list_is_zero() -> None:
    assert _percentile([], 0.95) == 0.0


def test_aggregate_of_no_rows_is_all_zero() -> None:
    stats = _aggregate([])
    assert stats["n"] == 0
    assert stats["success_rate"] == 0.0


class _RaisingBackend:
    def fetch(self, engine_id: str, params: dict) -> dict:
        raise SearchMuxError("boom")


def test_run_one_survives_a_failing_backend() -> None:
    q = SearchMux(
        api_key="k", cache=None, backends={"serpapi": _RaisingBackend()}
    )
    case = {"query": "anything", "category": "factual", "expect_any": ["x"]}
    result = run_one(q, "google", "q", "num", case)
    assert result["ok"] is False
    assert result["result_count"] == 0
    assert result["first_attempt"] is True  # no transport.py retry occurred
    assert result["contains_answer"] is False  # no results, nothing found


def test_run_one_skips_containment_check_without_expect_any() -> None:
    q = SearchMux(
        api_key="k", cache=None, backends={"serpapi": _RaisingBackend()}
    )
    case = {"query": "anything", "category": "research", "expect_any": None}
    result = run_one(q, "google", "q", "num", case)
    assert result["contains_answer"] is None


def test_domain_overlap_scores_shared_domains_higher() -> None:
    provider_rows = {
        "a": [{"urls": ["https://x.test/1", "https://y.test/1"]}],
        "b": [{"urls": ["https://x.test/2", "https://z.test/1"]}],
    }
    overlap = domain_overlap(provider_rows)
    # Shared: x.test. Union: x.test, y.test, z.test -> 1/3.
    assert overlap["a vs b"] == 1 / 3


def test_domain_overlap_skips_queries_with_no_results_on_either_side() -> (
    None
):
    provider_rows = {
        "a": [{"urls": []}],
        "b": [{"urls": ["https://x.test/1"]}],
    }
    overlap = domain_overlap(provider_rows)
    assert overlap["a vs b"] == 0.0


def _sample_row(provider: str) -> dict:
    return {
        "provider": provider,
        "overall": {
            "n": 5,
            "success_rate": 1.0,
            "first_attempt_rate": 0.8,
            "median_latency_ms": 120.0,
            "p95_latency_ms": 300.0,
            "avg_result_count": 8.0,
            "avg_approx_tokens": 40.0,
            "list_price_per_request": 0.015,
            "total_list_cost": 0.075,
        },
        "by_category": {
            "factual": {
                "n": 2,
                "success_rate": 1.0,
                "first_attempt_rate": 1.0,
                "median_latency_ms": 100.0,
                "p95_latency_ms": 110.0,
                "avg_result_count": 9.0,
                "avg_approx_tokens": 30.0,
            }
        },
        "containment_rate": 0.5,
    }


def test_format_overall_table_includes_every_row_and_pending_brave() -> (
    None
):
    table = _format_overall_table([_sample_row("serpapi")])
    assert "serpapi" in table
    assert "100%" in table
    assert "brave" in table
    assert "pending" in table


def test_format_category_table_reflects_that_categorys_stats() -> None:
    table = _format_category_table([_sample_row("serpapi")], "factual")
    assert "serpapi" in table
    assert "100 ms" in table
