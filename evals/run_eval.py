"""Compare routing strategies on a labelled intent set.

Three arms:

1. ``baseline`` reproduces what a single generic search tool asks of a
   model: here are a hundred engine names, pick one. No schemas.
2. ``bm25-top1`` is retrieval alone. No model, no cost.
3. ``searchmux`` is BM25 top-k narrowing plus schema-constrained
   synthesis, which is what ``Router.route`` does.

Arms 1 and 3 call an LLM and cost money, so they run only when
ANTHROPIC_API_KEY is set. Arm 2 always runs.

Run with ``python -m evals.run_eval``.
"""

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from searchmux.catalog import load_catalog
from searchmux.constants import ENV_ANTHROPIC_KEY
from searchmux.envfile import load_env
from searchmux.router import ENGINE_ONLY_SCHEMA, Router

logger = logging.getLogger(__name__)

CASES_PATH = str(Path(__file__).with_name("routing.jsonl"))

_BASELINE_PROMPT = """\
Pick the single best search engine for this request.

Request: {intent}

Available engines:
{engines}

Reply with the engine_id and a params object."""


def load_cases(path: str) -> list[dict]:
    """Read labelled routing cases from a JSONL file.

    ``expected`` is normalized to a list, so a case may legitimately
    accept more than one engine. Some intents are genuinely ambiguous —
    a plain web question could be served by any general engine — and
    forcing a single answer would measure the label, not the router.

    Args:
        path: Path to the JSONL file.

    Returns:
        One dict per line, each with intent and a list of expected ids.
    """
    cases = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            expected = case["expected"]
            if isinstance(expected, str):
                expected = [expected]
            cases.append({"intent": case["intent"], "expected": expected})
    return cases


def score_arm(
    name: str,
    predict: Callable[[str], str],
    cases: list[dict],
) -> dict:
    """Score one routing strategy over every case.

    A predictor that raises is counted as a miss rather than aborting
    the run: a strategy that fails on hard inputs should show up as a
    lower score, not as no score at all.

    Args:
        name: Arm label for the report.
        predict: Maps an intent to a predicted engine_id.
        cases: Labelled cases from load_cases.

    Returns:
        Keys arm, n, correct, errors, and accuracy.
    """
    correct = 0
    errors = 0
    for case in cases:
        try:
            predicted = predict(case["intent"])
        except Exception as exc:  # noqa: BLE001 - arm must not abort run
            logger.warning("%s failed on %r: %s", name, case["intent"], exc)
            errors += 1
            continue
        if predicted in case["expected"]:
            correct += 1

    total = len(cases)
    return {
        "arm": name,
        "n": total,
        "correct": correct,
        "errors": errors,
        "accuracy": correct / total if total else 0.0,
    }


def _baseline_predictor(llm: object) -> Callable[[str], str]:
    """Return a predictor that shows the model every engine, no schemas.

    This is the shape a single generic ``search`` tool presents: a long
    list of names and no parameter information.
    """
    engine_ids = sorted(load_catalog())
    listing = "\n".join(f"- {engine_id}" for engine_id in engine_ids)

    def predict(intent: str) -> str:
        decision = llm.complete(
            _BASELINE_PROMPT.format(intent=intent, engines=listing),
            ENGINE_ONLY_SCHEMA,
        )
        return decision.get("engine_id", "")

    return predict


def _format_table(rows: list[dict]) -> str:
    """Render scored arms as a markdown table."""
    lines = [
        "| arm | n | correct | errors | accuracy |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['arm']} | {row['n']} | {row['correct']} "
            f"| {row['errors']} | {row['accuracy']:.0%} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Score every available arm and print a markdown table."""
    logging.basicConfig(level=logging.WARNING)
    load_env()
    cases = load_cases(CASES_PATH)
    rows = []

    retrieval_only = Router(llm=_RefuseLLM())
    rows.append(
        score_arm(
            "bm25-top1 (no LLM)",
            lambda intent: retrieval_only.retrieve(intent)[0],
            cases,
        )
    )

    if os.getenv(ENV_ANTHROPIC_KEY):
        from searchmux.llm import AnthropicClient

        llm = AnthropicClient()
        rows.append(
            score_arm("baseline (all names, no schemas)",
                      _baseline_predictor(llm), cases)
        )
        router = Router(llm=llm)
        rows.append(
            score_arm(
                "searchmux (bm25 + schemas)",
                lambda intent: router.route(intent)[0],
                cases,
            )
        )
    else:
        print(
            f"note: {ENV_ANTHROPIC_KEY} is unset, so only the free "
            f"retrieval arm ran.\n"
        )

    print(_format_table(rows))


class _RefuseLLM:
    """Placeholder LLM proving the retrieval arm never calls one."""

    def complete(self, prompt: str, schema: dict) -> dict:
        raise AssertionError("retrieval arm must not call an LLM")


if __name__ == "__main__":
    main()
