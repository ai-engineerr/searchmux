"""Resolve plain-language intent to an engine and valid parameters.

Two stages, cheap before expensive. BM25 narrows 100+ engines to a
handful for free; only then does an LLM see the surviving candidates,
with their full parameter schemas, and pick one. An LLM choosing among
five fully specified options beats an LLM choosing among a hundred bare
names, which is what a single generic search tool asks it to do.
"""

import json
import logging
import os

from rank_bm25 import BM25Okapi

from searchmux.catalog import Engine, load_catalog
from searchmux.constants import DEFAULT_ROUTER_TOP_K, ENV_ANTHROPIC_KEY
from searchmux.models import RoutingError

logger = logging.getLogger(__name__)

# Structured outputs require every object schema to be closed, so an
# open `params` map is not expressible. The router therefore builds a
# schema per request from the candidates' own parameters: the model can
# only name parameters that actually exist.
ENGINE_ONLY_SCHEMA = {
    "type": "object",
    "properties": {"engine_id": {"type": "string"}},
    "required": ["engine_id"],
    "additionalProperties": False,
}

_PROMPT = """\
Pick the single best search engine for this request and fill in its
parameters.

Request: {intent}

Candidate engines:
{candidates}

Reply with the engine_id and a params object using only the parameters
listed for the engine you choose. Include every required parameter.
{correction}"""


class Router:
    """Chooses a SerpApi engine for an intent and builds its params."""

    def __init__(
        self,
        llm: object | None = None,
        top_k: int | None = DEFAULT_ROUTER_TOP_K,
    ) -> None:
        """Build the router and its retrieval index.

        Args:
            llm: Anything with complete(prompt, schema) -> dict. A
                default Anthropic-backed client is built when omitted.
            top_k: How many candidates survive retrieval.
        """
        self._llm = llm if llm is not None else _default_llm()
        self._top_k = top_k
        self._catalog = load_catalog()
        self.engine_ids = list(self._catalog)
        self._index = BM25Okapi(
            [
                _tokenize(f"{e.description} {' '.join(e.keywords)}")
                for e in self._catalog.values()
            ]
        )

    def retrieve(self, intent: str) -> list[str]:
        """Return the top_k candidate engine ids for an intent.

        Pure Python and free: no model, no network, no credits.

        Args:
            intent: Plain-language description of what is wanted.

        Returns:
            Engine ids, best first.
        """
        scores = self._index.get_scores(_tokenize(intent))
        ranked = sorted(
            zip(self.engine_ids, scores, strict=True),
            key=lambda pair: (-pair[1], pair[0]),
        )
        if self._top_k is None:
            return [engine_id for engine_id, _ in ranked]
        return [engine_id for engine_id, _ in ranked[: self._top_k]]

    def route(self, intent: str) -> tuple[str, dict]:
        """Resolve an intent to an engine and validated parameters.

        Args:
            intent: Plain-language description of what is wanted.

        Returns:
            The chosen engine_id and its parameters.

        Raises:
            RoutingError: If the chosen engine is not catalogued, or
                required parameters are still missing after one repair.
        """
        candidates = self.retrieve(intent)
        schema = self._decision_schema(candidates)
        decision = self._llm.complete(
            self._build_prompt(intent, candidates, ""), schema
        )

        try:
            return self._validate(decision)
        except RoutingError as first_error:
            logger.info("repairing routing decision: %s", first_error)
            correction = (
                f"\nYour previous reply was rejected: {first_error}. "
                f"Fix it."
            )
            retry = self._llm.complete(
                self._build_prompt(intent, candidates, correction),
                schema,
            )
            return self._validate(retry)

    def _decision_schema(self, candidates: list[str]) -> dict:
        """Build a closed output schema for one candidate set.

        `params` is a list of name/value pairs rather than an object
        keyed by parameter name. That keeps the schema a fixed, small
        size however large the catalog grows - a schema built from
        every engine's parameters is rejected outright by the API as
        too complex. Parameter names are checked against the chosen
        engine afterwards, in _validate.

        Args:
            candidates: Engine ids the model may choose between.

        Returns:
            A JSON schema for the routing decision.
        """
        return {
            "type": "object",
            "properties": {
                "engine_id": {"type": "string", "enum": list(candidates)},
                "params": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["name", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["engine_id", "params"],
            "additionalProperties": False,
        }

    def _build_prompt(
        self,
        intent: str,
        candidates: list[str],
        correction: str,
    ) -> str:
        """Render the prompt with only the candidate schemas.

        Excluding the other engines is the whole point: the model reads
        five schemas, not a hundred names.
        """
        described = [
            json.dumps(
                {
                    "engine_id": engine_id,
                    "description": self._catalog[engine_id].description,
                    "params": self._catalog[engine_id].params,
                },
                indent=2,
            )
            for engine_id in candidates
        ]
        return _PROMPT.format(
            intent=intent,
            candidates="\n".join(described),
            correction=correction,
        )

    def _validate(self, decision: dict) -> tuple[str, dict]:
        """Check a decision against the chosen engine's schema.

        Args:
            decision: The model's {engine_id, params} reply.

        Returns:
            The engine_id and its accepted parameters.

        Raises:
            RoutingError: On an unknown engine or a missing required
                parameter.
        """
        engine_id = decision.get("engine_id", "")
        if engine_id not in self._catalog:
            raise RoutingError(
                f"router chose {engine_id!r}, which is not a known engine"
            )

        engine = self._catalog[engine_id]
        params = _drop_unknown(engine, _as_mapping(decision.get("params")))
        missing = [
            name
            for name, spec in engine.params.items()
            if spec.get("required") and name not in params
        ]
        if missing:
            raise RoutingError(
                f"{engine_id} requires {', '.join(missing)}, which the "
                f"router omitted"
            )
        return engine_id, params


def _drop_unknown(engine: Engine, params: dict) -> dict:
    """Return only the parameters the engine actually accepts.

    A hallucinated parameter is dropped rather than sent, because
    SerpApi would reject the whole request and bill nothing useful.
    """
    kept = {}
    for name, value in params.items():
        if name in engine.params:
            kept[name] = value
        else:
            logger.debug(
                "dropping unknown param %s for %s", name, engine.engine_id
            )
    return kept


def _tokenize(text: str) -> list[str]:
    """Lowercase text and split it into alphanumeric tokens."""
    cleaned = "".join(
        char if char.isalnum() else " " for char in text.lower()
    )
    return cleaned.split()


def _default_llm() -> object:
    """Build the Anthropic-backed client.

    Raises:
        RoutingError: If no Anthropic key is configured. Pinning an
            engine avoids routing, and therefore this requirement.
    """
    if not os.getenv(ENV_ANTHROPIC_KEY):
        raise RoutingError(
            f"routing needs {ENV_ANTHROPIC_KEY}; pass engine= to skip "
            f"routing entirely"
        )
    from searchmux.llm import AnthropicClient

    return AnthropicClient()


def _as_mapping(params: object) -> dict:
    """Coerce the model's params into a plain dict.

    The schema asks for a list of {name, value} pairs; a plain object
    is accepted too so an injected or hand-written router stays valid.

    Args:
        params: Whatever the model returned for `params`.

    Returns:
        A name -> value mapping, empty when nothing usable was given.
    """
    if isinstance(params, dict):
        return params
    if not isinstance(params, list):
        return {}
    mapping = {}
    for pair in params:
        if isinstance(pair, dict) and "name" in pair:
            mapping[str(pair["name"])] = pair.get("value")
    return mapping
