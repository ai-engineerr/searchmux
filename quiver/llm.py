"""Structured-output LLM client used by the intent router.

Only the router needs this. Pinning an engine with
``q.find(..., engine=...)`` skips it entirely, so Quiver's cache,
budget guard, and cassettes never require an LLM or an LLM key.
"""

import json
import logging
from typing import Any

from quiver.constants import (
    ROUTER_EFFORT,
    ROUTER_MAX_TOKENS,
    ROUTER_MODEL,
)
from quiver.models import QuiverError

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Returns schema-conforming JSON from Claude.

    Uses the Messages API's structured-output support, so the response
    is guaranteed to parse against the supplied JSON schema rather than
    being coaxed into shape by prompt wording.
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str = ROUTER_MODEL,
    ) -> None:
        """Build the client.

        Args:
            client: An anthropic.Anthropic instance. Injected for
                tests; a default one is constructed when omitted, which
                reads ANTHROPIC_API_KEY from the environment.
            model: Model id to route with.
        """
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self._model = model

    def complete(self, prompt: str, schema: dict) -> dict:
        """Return a dict conforming to schema.

        Args:
            prompt: The full prompt to send.
            schema: JSON schema the response must satisfy.

        Returns:
            The parsed response object.

        Raises:
            QuiverError: If the response carries no text block, or its
                text is not valid JSON.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=ROUTER_MAX_TOKENS,
            output_config={
                "effort": ROUTER_EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": _closed(schema),
                },
            },
            messages=[{"role": "user", "content": prompt}],
        )

        text = _first_text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise QuiverError(
                f"router model did not return valid JSON: {text[:200]!r}"
            ) from exc


def _closed(schema: dict) -> dict:
    """Return the schema with additionalProperties closed.

    Structured outputs reject an open object schema. The caller's dict
    is copied rather than mutated, so a shared module-level schema
    constant stays untouched.
    """
    if schema.get("type") != "object":
        return schema
    return {**schema, "additionalProperties": False}


def _first_text(response: Any) -> str:
    """Return the first text block's content.

    Thinking blocks precede text on models with thinking enabled, so
    the block type is checked rather than assuming index zero.

    Raises:
        QuiverError: If no text block is present.
    """
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise QuiverError("router model returned no text block")
