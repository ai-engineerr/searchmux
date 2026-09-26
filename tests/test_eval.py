"""Tests for the routing evaluation harness."""

from evals.run_eval import CASES_PATH, load_cases, score_arm


class NullLLM:
    """Fails loudly if a retrieval-only arm calls an LLM."""

    def complete(self, prompt: str, schema: dict) -> dict:
        raise AssertionError("retrieval-only arm must not call the LLM")


def test_cases_load_with_intent_and_expected() -> None:
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 40
    for case in cases:
        assert case["intent"]
        assert case["expected"]


def test_expected_is_normalized_to_a_list() -> None:
    for case in load_cases(CASES_PATH):
        assert isinstance(case["expected"], list)


def test_every_expected_engine_is_catalogued() -> None:
    """A typo in the eval set would silently depress every arm."""
    from quiver.catalog import load_catalog

    catalog = load_catalog()
    for case in load_cases(CASES_PATH):
        for engine_id in case["expected"]:
            assert engine_id in catalog, engine_id


def test_score_arm_computes_accuracy() -> None:
    cases = [
        {"intent": "a", "expected": ["google"]},
        {"intent": "b", "expected": ["bing"]},
    ]
    result = score_arm("always-google", lambda i: "google", cases)
    assert result["n"] == 2
    assert result["correct"] == 1
    assert result["accuracy"] == 0.5


def test_score_arm_accepts_any_listed_engine() -> None:
    cases = [{"intent": "a", "expected": ["google", "bing"]}]
    assert score_arm("x", lambda i: "bing", cases)["correct"] == 1


def test_score_arm_survives_a_failing_predictor() -> None:
    def broken(intent: str) -> str:
        raise RuntimeError("boom")

    result = score_arm("broken", broken, [{"intent": "a", "expected": ["g"]}])
    assert result["correct"] == 0
    assert result["errors"] == 1


def test_bm25_retrieval_beats_chance_by_a_wide_margin() -> None:
    """Random choice over 25 engines is 4%. This is the sanity floor.

    The real measured figure goes in the README; this only guards
    against retrieval being outright broken.
    """
    from quiver.router import Router

    router = Router(llm=NullLLM())
    cases = load_cases(CASES_PATH)
    scored = score_arm("bm25-top1", lambda i: router.retrieve(i)[0], cases)
    assert scored["accuracy"] > 0.2, scored
