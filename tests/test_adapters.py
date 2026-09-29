"""Tests for framework tool emission."""

from searchmux import SearchMux
from searchmux.adapters.tool import tool_schema


def test_schema_has_a_single_intent_parameter() -> None:
    schema = tool_schema()
    assert schema["name"] == "search"
    props = schema["input_schema"]["properties"]
    assert "intent" in props
    assert schema["input_schema"]["required"] == ["intent"]


def test_schema_description_mentions_engine_breadth() -> None:
    assert "engine" in tool_schema()["description"].lower()


def test_as_tool_returns_the_schema(tmp_path) -> None:
    q = SearchMux(api_key="k", cache=str(tmp_path / "c.db"))
    assert q.as_tool()["name"] == "search"


def test_schema_is_json_serializable() -> None:
    import json

    json.dumps(tool_schema())


def test_openai_schema_wraps_in_function_envelope() -> None:
    from searchmux.adapters.tool import openai_tool_schema

    schema = openai_tool_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search"
    props = schema["function"]["parameters"]["properties"]
    assert "intent" in props


def test_openai_schema_matches_the_anthropic_one() -> None:
    """The two must never drift apart on name, description, or params."""
    from searchmux.adapters.tool import openai_tool_schema

    anthropic_schema = tool_schema()
    openai_schema = openai_tool_schema()
    assert openai_schema["function"]["name"] == anthropic_schema["name"]
    assert (
        openai_schema["function"]["description"]
        == anthropic_schema["description"]
    )
    assert (
        openai_schema["function"]["parameters"]
        == anthropic_schema["input_schema"]
    )


def test_as_openai_tool_returns_function_envelope(tmp_path) -> None:
    q = SearchMux(api_key="k", cache=str(tmp_path / "c.db"))
    result = q.as_openai_tool()
    assert result["type"] == "function"
    assert result["function"]["name"] == "search"


def test_openai_schema_is_json_serializable() -> None:
    import json

    from searchmux.adapters.tool import openai_tool_schema

    json.dumps(openai_tool_schema())
