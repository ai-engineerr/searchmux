"""Tests for the provider comparison eval's offline logic."""

from evals.provider_eval import (
    QUERIES_PATH,
    _format_table,
    load_queries,
    run_one,
)
from searchmux import SearchMux
from searchmux.models import SearchMuxError


def test_queries_load_as_a_flat_list() -> None:
    queries = load_queries(QUERIES_PATH)
    assert len(queries) >= 10
    assert all(isinstance(q, str) and q for q in queries)


class _RaisingBackend:
    def fetch(self, engine_id: str, params: dict) -> dict:
        raise SearchMuxError("boom")


def test_run_one_survives_a_failing_backend() -> None:
    q = SearchMux(
        api_key="k", cache=None, backends={"serpapi": _RaisingBackend()}
    )
    result = run_one(q, "google", "q", "anything")
    assert result["ok"] is False
    assert result["result_count"] == 0


def test_format_table_includes_every_row() -> None:
    rows = [
        {
            "provider": "serpapi",
            "n": 5,
            "success_rate": 1.0,
            "avg_latency_ms": 120.0,
            "avg_result_count": 8.0,
            "avg_snippet_len": 90.0,
        }
    ]
    table = _format_table(rows)
    assert "serpapi" in table
    assert "100%" in table
