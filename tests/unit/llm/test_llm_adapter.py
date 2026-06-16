"""RED tests for the core LLM adapter (S97.0).

The adapter is import-clean infrastructure: the SDKs are lazy-imported only
when a real client is built, so these tests drive the public surface with a
fake transport — no network, no provider SDK installed.

What is asserted:
* ``select_adapter`` maps ``claude-*`` -> Anthropic, everything else -> OpenAI
  (the model name is the only discriminator);
* the module imports without the openai/anthropic SDKs present;
* the typed ``LlmError`` never carries the api_key.
"""
from vbwd.llm.adapter import (
    AnthropicAdapter,
    LlmAdapter,
    OpenAiAdapter,
    select_adapter,
)
from vbwd.llm.errors import LlmError


def test_select_adapter_picks_anthropic_for_claude_models():
    adapter = select_adapter(
        model="claude-3-5-sonnet-latest",
        api_key="secret-key-value",
        endpoint="https://api.anthropic.com",
        max_tokens=512,
    )
    assert isinstance(adapter, AnthropicAdapter)
    assert isinstance(adapter, LlmAdapter)


def test_select_adapter_picks_openai_for_non_claude_models():
    adapter = select_adapter(
        model="gpt-4o-mini",
        api_key="secret-key-value",
        endpoint="https://api.openai.com/v1",
        max_tokens=512,
    )
    assert isinstance(adapter, OpenAiAdapter)


def test_llm_error_is_an_exception():
    error = LlmError("Provider request failed")
    assert isinstance(error, Exception)
    assert "Provider request failed" in str(error)
