"""Emit a tool schema consumable by agent frameworks."""

TOOL_DESCRIPTION = (
    "Search the live web. Describe what you want to know in plain "
    "language; the right search engine is selected automatically from "
    "over a hundred available engines, covering the web, shopping and "
    "prices, news, academic papers, maps and places, flights, hotels, "
    "jobs, videos, patents, and finance."
)


def tool_schema(name: str = "search") -> dict:
    """Return an Anthropic-shaped tool-use schema for SearchMux.find.

    LangChain's structured-tool helpers accept this same flat shape
    (name, description, an input schema) directly. OpenAI's function
    calling wants a different envelope; use openai_tool_schema() for
    that instead of adapting this one by hand.

    Args:
        name: Tool name exposed to the model.

    Returns:
        A schema accepted by Anthropic tool use and LangChain.
    """
    return {
        "name": name,
        "description": TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "What you want to know, in plain language."
                    ),
                }
            },
            "required": ["intent"],
        },
    }


def openai_tool_schema(name: str = "search") -> dict:
    """Return an OpenAI function-calling schema for SearchMux.find.

    OpenAI's chat.completions and Responses APIs expect the schema
    wrapped in a {"type": "function", "function": {...}} envelope with
    a "parameters" key, not Anthropic's flat "input_schema". This
    builds that shape from the same underlying schema tool_schema()
    returns, so the two never drift apart.

    Args:
        name: Tool name exposed to the model.

    Returns:
        A dict ready to pass directly in an OpenAI `tools=[...]` list.
    """
    base = tool_schema(name)
    return {
        "type": "function",
        "function": {
            "name": base["name"],
            "description": base["description"],
            "parameters": base["input_schema"],
        },
    }
