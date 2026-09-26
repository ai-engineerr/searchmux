"""Emit a tool schema consumable by agent frameworks."""

TOOL_DESCRIPTION = (
    "Search the live web. Describe what you want to know in plain "
    "language; the right search engine is selected automatically from "
    "over a hundred available engines, covering the web, shopping and "
    "prices, news, academic papers, maps and places, flights, hotels, "
    "jobs, videos, patents, and finance."
)


def tool_schema(name: str = "search") -> dict:
    """Return a function-calling schema for SearchMux.find.

    Args:
        name: Tool name exposed to the model.

    Returns:
        A schema accepted by Anthropic, OpenAI, and LangChain.
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
