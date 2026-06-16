"""RED tests for the core LlmClient (S97.0).

A fake adapter (no SDK, no network) drives both call shapes:

* ``.generate`` forces JSON and returns the parsed dict;
* ``.chat`` returns plain text;
* an SDK/adapter failure surfaces as ``LlmError`` whose message NEVER contains
  the api_key;
* a successful call stamps ``last_active_at`` via the injected callback.
"""
import pytest

from vbwd.llm.client import LlmClient
from vbwd.llm.errors import AdapterError, LlmError


class _FakeAdapter:
    """A fake LlmAdapter that records calls and returns canned content."""

    def __init__(self, *, generate_result=None, chat_result=None, raises=None):
        self._generate_result = generate_result
        self._chat_result = chat_result
        self._raises = raises
        self.generate_calls = []
        self.chat_calls = []

    def generate(
        self,
        system_content,
        user_content,
        *,
        model,
        temperature,
        json_schema=None,
        json_retry_max=3,
    ):
        if self._raises is not None:
            raise self._raises
        self.generate_calls.append(
            {
                "system": system_content,
                "user": user_content,
                "model": model,
                "temperature": temperature,
                "json_schema": json_schema,
            }
        )
        return self._generate_result

    def chat(self, messages, *, model, temperature, system_prompt=None):
        if self._raises is not None:
            raise self._raises
        self.chat_calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "system_prompt": system_prompt,
            }
        )
        return self._chat_result


def _make_client(adapter, *, on_success=None):
    return LlmClient(
        adapter=adapter,
        model="gpt-4o-mini",
        default_temperature=0.2,
        on_success=on_success,
    )


def test_generate_returns_parsed_dict():
    adapter = _FakeAdapter(generate_result={"title": "Hello", "body": "World"})
    client = _make_client(adapter)

    result = client.generate(
        "You are a writer", "Write a post", json_schema={"title": "string"}
    )

    assert result == {"title": "Hello", "body": "World"}
    assert adapter.generate_calls[0]["json_schema"] == {"title": "string"}


def test_chat_returns_plain_text():
    adapter = _FakeAdapter(chat_result="Hi there!")
    client = _make_client(adapter)

    reply = client.chat(
        [{"role": "user", "content": "Hello"}], system_prompt="Be friendly"
    )

    assert reply == "Hi there!"
    assert adapter.chat_calls[0]["system_prompt"] == "Be friendly"


def test_adapter_failure_surfaces_llm_error_without_key():
    secret_key = "sk-super-secret-token-value"
    adapter = _FakeAdapter(raises=AdapterError(f"boom {secret_key}"))
    client = LlmClient(
        adapter=adapter,
        model="gpt-4o-mini",
        default_temperature=0.2,
        api_key=secret_key,
    )

    with pytest.raises(LlmError) as exc_info:
        client.generate("sys", "user")

    assert secret_key not in str(exc_info.value)


def test_successful_call_stamps_last_active():
    stamped = []
    adapter = _FakeAdapter(chat_result="ok")
    client = _make_client(adapter, on_success=lambda: stamped.append(True))

    client.chat([{"role": "user", "content": "hi"}], system_prompt="x")

    assert stamped == [True]
