"""Compare routing strategies on a labelled intent set.

Two questions, five arms:

Which engine gets picked (accuracy against evals/routing.jsonl):

1. ``bm25-top1`` is retrieval alone. No model, no cost.
2. ``baseline`` reproduces what a single generic search tool asks of a
   model: here are a hundred engine names, pick one. No schemas.
3. ``searchmux`` is BM25 top-k narrowing plus schema-constrained
   synthesis, which is what ``Router.route`` does.

Whether the resulting request would actually be valid (every required
parameter present, under its real name):

4. ``baseline, open params`` asks the same naive baseline to also
   write the parameters itself, with no per-engine schema keeping it
   honest — an unconstrained completion, because Anthropic's
   structured-output mode rejects an open object and would force this
   arm to be schema-constrained too, hiding the exact failure mode
   being measured.
5. ``searchmux`` reuses arm 3's own route() calls and checks the
   parameters it actually produced.

Arms 2-5 call an LLM and cost money, so they run only when
ANTHROPIC_API_KEY is set. Arm 1 always runs, and arms 4-5 only need
one route() call each per case, reusing arm 3's results rather than
routing every case twice.

Run with ``python -m evals.run_eval``.
"""

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from searchmux.catalog import get_engine, load_catalog
from searchmux.constants import (
    ENV_ANTHROPIC_KEY,
    ROUTER_EFFORT,
    ROUTER_MAX_TOKENS,
    ROUTER_MODEL,
)
from searchmux.envfile import load_env
from searchmux.models import CatalogError
from searchmux.router import ENGINE_ONLY_SCHEMA, Router

logger = logging.getLogger(__name__)

CASES_PATH = str(Path(__file__).with_name("routing.jsonl"))

_BASELINE_PROMPT = """\
Pick the single best search engine for this request.

Request: {intent}

Available engines:
{engines}

Reply with the engine_id and a params object."""

_OPEN_PARAMS_PROMPT = """\
Pick the single best search engine for this request and give it the \
parameters it needs.

Request: {intent}

Available engines:
{engines}

Reply with only a JSON object: {{"engine_id": "...", "params": {{...}}}}. \
You are not told each engine's parameter names; use your best judgment, \
the way you would for an API you have not seen documentation for."""


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


def check_validity(engine_id: str, params: dict) -> tuple[bool, list[str]]:
    """Check whether a decision names required parameters correctly.

    "Valid" here means: the engine exists, and every parameter the
    catalog marks required is present under its real key. A model that
    invents a plausible-but-wrong name (``q`` for Amazon, which
    actually needs ``k``) fails this exactly the way a real SerpApi
    call would fail with an unhelpful 400.

    Args:
        engine_id: The chosen engine.
        params: The parameters supplied for it.

    Returns:
        (valid, missing_required_keys). missing_required_keys is empty
        when the engine itself is unknown, since there is nothing more
        specific to report.
    """
    try:
        engine = get_engine(engine_id)
    except CatalogError:
        return False, []

    missing = [
        name
        for name, spec in engine.params.items()
        if spec.get("required") and name not in params
    ]
    return not missing, missing


def validity_score(
    name: str,
    predict_pair: Callable[[str], tuple[str, dict]],
    cases: list[dict],
) -> dict:
    """Score how often a strategy's own output would actually work.

    Unlike score_arm, this does not check the answer against a label —
    a request can be well-formed but route to the "wrong" engine, or
    correct about the engine but missing a parameter SerpApi requires.
    This measures only the second thing.

    Args:
        name: Arm label for the report.
        predict_pair: Maps an intent to (engine_id, params).
        cases: Labelled cases from load_cases (only intent is used).

    Returns:
        Keys arm, n, valid, errors, and validity.
    """
    valid = 0
    errors = 0
    for case in cases:
        try:
            engine_id, params = predict_pair(case["intent"])
        except Exception as exc:  # noqa: BLE001 - arm must not abort run
            logger.warning("%s failed on %r: %s", name, case["intent"], exc)
            errors += 1
            continue
        ok, missing = check_validity(engine_id, params)
        if ok:
            valid += 1
        else:
            logger.debug(
                "%s: %s missing %s", name, engine_id, missing or "(unknown)"
            )

    total = len(cases)
    return {
        "arm": name,
        "n": total,
        "valid": valid,
        "errors": errors,
        "validity": valid / total if total else 0.0,
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


def _open_params_predictor(
    client: object,
) -> Callable[[str], tuple[str, dict]]:
    """Return a predictor with no schema constraining its parameters.

    Calls the Messages API directly, without output_config, since
    structured-output mode requires every object to be closed and
    would force this arm to declare the very parameter names it is
    supposed to be guessing at. This is the realistic naive shape: a
    model given a tool with no argument schema, the way a single
    generic ``search`` tool actually works.
    """
    engine_ids = sorted(load_catalog())
    listing = "\n".join(f"- {engine_id}" for engine_id in engine_ids)

    def predict(intent: str) -> tuple[str, dict]:
        response = client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=ROUTER_MAX_TOKENS,
            output_config={"effort": ROUTER_EFFORT},
            messages=[{
                "role": "user",
                "content": _OPEN_PARAMS_PROMPT.format(
                    intent=intent, engines=listing
                ),
            }],
        )
        text = next(
            b.text for b in response.content
            if getattr(b, "type", "") == "text"
        )
        # Models occasionally wrap JSON in a code fence despite being
        # asked not to; strip one if present rather than fail on it.
        text = text.strip().removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
        decision = json.loads(text)
        return decision.get("engine_id", ""), decision.get("params") or {}

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


def _format_validity_table(rows: list[dict]) -> str:
    """Render validity-scored arms as a markdown table."""
    lines = [
        "| arm | n | valid | errors | validity |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['arm']} | {row['n']} | {row['valid']} "
            f"| {row['errors']} | {row['validity']:.0%} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Score every available arm and print markdown tables."""
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

    validity_rows = []

    if os.getenv(ENV_ANTHROPIC_KEY):
        import anthropic

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

        raw_client = anthropic.Anthropic()
        validity_rows.append(
            validity_score(
                "baseline, open params",
                _open_params_predictor(raw_client),
                cases,
            )
        )
        validity_rows.append(
            validity_score("searchmux", router.route, cases)
        )
    else:
        print(
            f"note: {ENV_ANTHROPIC_KEY} is unset, so only the free "
            f"retrieval arm ran.\n"
        )

    print("Which engine gets picked:\n")
    print(_format_table(rows))

    if validity_rows:
        print("\nWhether the request would actually work:\n")
        print(_format_validity_table(validity_rows))


class _RefuseLLM:
    """Placeholder LLM proving the retrieval arm never calls one."""

    def complete(self, prompt: str, schema: dict) -> dict:
        raise AssertionError("retrieval arm must not call an LLM")


if __name__ == "__main__":
    main()
