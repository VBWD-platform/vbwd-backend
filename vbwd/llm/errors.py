"""Error types for the core LLM client (S97).

Every failure that crosses the LLM-client boundary surfaces as an
:class:`LlmError` (or a subtype) so callers depend on a single, narrow error
contract and never have to catch a provider SDK's transport exception
directly. No provider api_key is ever placed into an error message.
"""
from __future__ import annotations


class LlmError(Exception):
    """Base error for every recoverable core LLM failure."""


class InvalidJsonError(LlmError):
    """Raised when model output cannot be parsed/repaired into valid JSON."""


class AdapterError(LlmError):
    """Raised when an LLM provider SDK call fails or returns no content."""
