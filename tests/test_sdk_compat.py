"""Guard the Anthropic SDK surface the router actually depends on.

The unit tests for the LLM client inject a fake, so they cannot catch
an SDK too old to accept the parameters we send. anthropic 0.40 parses
and then rejects `output_config` at call time; this test fails loudly
at install time instead.
"""

import inspect

import pytest

anthropic = pytest.importorskip("anthropic")

REQUIRED_PARAMS = ("model", "max_tokens", "messages", "output_config")


def test_messages_create_accepts_the_params_we_send() -> None:
    client = anthropic.Anthropic(api_key="not-used-for-signature-check")
    names = set(inspect.signature(client.messages.create).parameters)
    missing = [p for p in REQUIRED_PARAMS if p not in names]
    assert not missing, (
        f"installed anthropic {anthropic.__version__} does not accept "
        f"{missing}; requirements.txt pins >=1.8 for this reason"
    )
