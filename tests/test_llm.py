"""Tests for the Anthropic-backed structured-output client."""

import json
from types import SimpleNamespace

import pytest

from quiver.llm import AnthropicClient
from quiver.models import QuiverError

SCHEMA = {
    "type": "object",
    "properties": {"engine_id": {"type": "string"}},
    "required": ["engine_id"],
}


class FakeMessages:
    """Records the request and returns a scripted response."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)]
        )


def _client(text: str) -> tuple[AnthropicClient, FakeMessages]:
    messages = FakeMessages(text)
    fake = SimpleNamespace(messages=messages)
    return AnthropicClient(client=fake), messages


def test_complete_returns_the_parsed_object() -> None:
    client, _ = _client('{"engine_id": "google_shopping"}')
    assert client.complete("pick one", SCHEMA) == {
        "engine_id": "google_shopping"
    }


def test_request_constrains_the_output_format() -> None:
    client, messages = _client('{"engine_id": "google"}')
    client.complete("pick one", SCHEMA)
    fmt = messages.kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"] == SCHEMA["properties"]


def test_schema_gets_additional_properties_closed() -> None:
    """Structured outputs reject an open object schema."""
    client, messages = _client('{"engine_id": "google"}')
    client.complete("pick one", SCHEMA)
    schema = messages.kwargs["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False


def test_caller_schema_is_not_mutated() -> None:
    client, _ = _client('{"engine_id": "google"}')
    client.complete("pick one", SCHEMA)
    assert "additionalProperties" not in SCHEMA


def test_prompt_is_sent_as_the_user_message() -> None:
    client, messages = _client('{"engine_id": "google"}')
    client.complete("pick an engine", SCHEMA)
    assert messages.kwargs["messages"] == [
        {"role": "user", "content": "pick an engine"}
    ]


def test_unparseable_response_raises_quiver_error() -> None:
    client, _ = _client("not json at all")
    with pytest.raises(QuiverError, match="valid JSON"):
        client.complete("pick one", SCHEMA)


def test_response_without_a_text_block_raises() -> None:
    messages = FakeMessages("")
    messages.create = lambda **kw: SimpleNamespace(content=[])
    client = AnthropicClient(client=SimpleNamespace(messages=messages))
    with pytest.raises(QuiverError, match="no text"):
        client.complete("pick one", SCHEMA)


def test_thinking_blocks_are_skipped() -> None:
    messages = FakeMessages("")
    messages.create = lambda **kw: SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="hmm"),
            SimpleNamespace(type="text", text='{"engine_id": "bing"}'),
        ]
    )
    client = AnthropicClient(client=SimpleNamespace(messages=messages))
    assert client.complete("pick one", SCHEMA)["engine_id"] == "bing"


def test_json_round_trips_unicode() -> None:
    payload = {"engine_id": "google", "q": "café"}
    client, _ = _client(json.dumps(payload, ensure_ascii=False))
    assert client.complete("pick one", SCHEMA) == payload
