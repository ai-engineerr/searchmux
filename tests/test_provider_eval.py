"""Tests for the provider comparison eval's offline logic."""

from evals.provider_eval import (
    FACTUAL_QUERIES_PATH,
    QUERIES_PATH,
    _format_table,
    _percentile,
    domain_overlap,
    load_factual_queries,
    load_queries,
    run_one,
)
from searchmux import SearchMux
from searchmux.models import SearchMuxError


def test_queries_load_as_a_flat_list() -> None:
    queries = load_queries(QUERIES_PATH)
    assert len(queries) >= 10
    assert all(isinstance(q, str) and q for q in queries)


def test_factual_queries_have_an_expected_answer() -> None:
    cases = load_factual_queries(FACTUAL_QUERIES_PATH)
    assert len(cases) >= 5
    for case in cases:
        assert case["query"]
        assert case["expect_any"]


def test_percentile_of_a_single_value_is_itself() -> None:
    assert _percentile([42.0], 0.95) == 42.0


def test_percentile_p95_is_near_the_top() -> None:
    values = [float(i) for i in range(1, 21)]  # 1..20
    assert _percentile(values, 0.95) >= 18.0


def test_percentile_of_empty_list_is_zero() -> None:
    assert _percentile([], 0.95) == 0.0


class _RaisingBackend:
    def fetch(self, engine_id: str, params: dict) -> dict:
        raise SearchMuxError("boom")


def test_run_one_survives_a_failing_backend() -> None:
    q = SearchMux(
        api_key="k", cache=None, backends={"serpapi": _RaisingBackend()}
    )
    result = run_one(q, "google", "q", "num", "anything")
    assert result["ok"] is False
    assert result["result_count"] == 0
    assert result["first_attempt"] is True  # no transport.py retry occurred


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


def test_format_table_includes_every_row_and_the_pending_brave_row() -> (
    None
):
    rows = [
        {
            "provider": "serpapi",
            "n": 5,
            "success_rate": 1.0,
            "first_attempt_rate": 0.8,
            "median_latency_ms": 120.0,
            "p95_latency_ms": 300.0,
            "avg_result_count": 8.0,
            "avg_approx_tokens": 40.0,
            "list_price_per_request": 0.015,
            "total_list_cost": 0.075,
        }
    ]
    table = _format_table(rows)
    assert "serpapi" in table
    assert "100%" in table
    assert "brave" in table
    assert "pending" in table
