"""Core LLM client (S97).

Generic, domain-agnostic LLM infrastructure — the same class of capability as
``TokenService`` or ``CurrencyService``. Core knows *how to talk to an LLM*; it
knows nothing about any plugin's domain. This package imports no plugin (the
core-agnosticism oracle stays green).
"""
from vbwd.llm.adapter import (
    AnthropicAdapter,
    LlmAdapter,
    OpenAiAdapter,
    select_adapter,
)
from vbwd.llm.client import LlmClient
from vbwd.llm.errors import AdapterError, InvalidJsonError, LlmError

__all__ = [
    "LlmAdapter",
    "OpenAiAdapter",
    "AnthropicAdapter",
    "select_adapter",
    "LlmClient",
    "LlmError",
    "AdapterError",
    "InvalidJsonError",
]
