"""Wire SearchMux into OpenAI's function calling, end to end.

The search side needs only a SerpApi key (or none at all in --offline
mode, replaying the same demo cassette the other examples use). The
chat side needs a real OPENAI_API_KEY, since there is no offline
replay for OpenAI's own responses.

Run it:

    python examples/openai_agent.py --offline   # search is free and
                                                  # offline; still
                                                  # needs OPENAI_API_KEY
                                                  # for the chat model
    python examples/openai_agent.py              # both sides live
"""

import json
import logging
import os
import sys
from pathlib import Path

from searchmux import SearchMux
from searchmux.constants import ENV_API_KEY
from searchmux.envfile import load_env

HERE = Path(__file__).parent
DEMO_CASSETTE = str(HERE / "demo_cassette.json")
DEMO_CACHE = str(HERE / ".searchmux-openai-demo.db")

MODEL = "gpt-4.1-mini"
SYSTEM = (
    "You help with quick shopping questions. Use the search tool for "
    "anything needing current prices or availability; answer directly "
    "otherwise."
)


def run_agent(
    client, q: SearchMux, user_message: str, live: bool
) -> str:
    """Drive one OpenAI function-calling turn using SearchMux.

    Args:
        client: An openai.OpenAI client.
        q: A configured SearchMux client. Only search(engine=...) is
            used here, so no ANTHROPIC_API_KEY is needed even when
            OpenAI decides to call the tool.
        user_message: The user's question.
        live: Whether search is hitting SerpApi for real. When False,
            the query is pinned to match the offline cassette's one
            recording rather than the model's own free-text intent.

    Returns:
        The model's final text reply.
    """
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_message},
    ]
    tools = [q.as_openai_tool()]

    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=tools
    )
    message = response.choices[0].message

    if not message.tool_calls:
        return message.content or ""

    messages.append(message)
    for call in message.tool_calls:
        intent = json.loads(call.function.arguments)["intent"]
        # Pinned to google_shopping: this demo only needs one engine,
        # so there is no reason to spend a routing call deciding that.
        # The offline cassette holds one recording, made with these
        # exact params; a live run would pass the model's own intent
        # as the query instead of this fixed one.
        query = intent if live else "Pixel 10 price India"
        results = q.search(engine="google_shopping", q=query, gl="in")
        summary = "\n".join(
            f"{r.title}: {r.price}" for r in results[:3] if r.price
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": summary or "No priced results found.",
            }
        )

    final = client.chat.completions.create(model=MODEL, messages=messages)
    return final.choices[0].message.content or ""


def main() -> None:
    """Run one example question through the OpenAI + SearchMux loop."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING)
    load_env()

    offline = "--offline" in sys.argv
    live = bool(os.getenv(ENV_API_KEY)) and not offline

    q = SearchMux(budget=4, cache=DEMO_CACHE)

    try:
        import openai
    except ImportError:
        print("This example needs the openai package: pip install openai")
        return

    client = openai.OpenAI()  # reads OPENAI_API_KEY from the environment
    question = "What does the Pixel 10 cost right now?"

    if live:
        answer = run_agent(client, q, question, live=True)
    else:
        print("offline mode: search side replays the demo cassette\n")
        with q.replay(DEMO_CASSETTE):
            answer = run_agent(client, q, question, live=False)

    print(f"Q: {question}")
    print(f"A: {answer}")
    print(f"\nsearch cost: {q.report()}")


if __name__ == "__main__":
    main()
