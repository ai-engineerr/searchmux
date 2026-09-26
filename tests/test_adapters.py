"""Tests for framework tool emission."""

from quiver import Quiver
from quiver.adapters.tool import tool_schema


def test_schema_has_a_single_intent_parameter() -> None:
    schema = tool_schema()
    assert schema["name"] == "search"
    props = schema["input_schema"]["properties"]
    assert "intent" in props
    assert schema["input_schema"]["required"] == ["intent"]


def test_schema_description_mentions_engine_breadth() -> None:
    assert "engine" in tool_schema()["description"].lower()


def test_as_tool_returns_the_schema(tmp_path) -> None:
    q = Quiver(api_key="k", cache=str(tmp_path / "c.db"))
    assert q.as_tool()["name"] == "search"


def test_schema_is_json_serializable() -> None:
    import json

    json.dumps(tool_schema())
