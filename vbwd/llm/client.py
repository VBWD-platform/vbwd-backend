"""``LlmClient`` — a connection-bound LLM client (S97.0).

The client is bound to a single resolved connection (model + adapter + the
per-connection defaults). It exposes the two call shapes every consumer needs:

* :meth:`generate` — structured JSON (cms-ai / the s98 bot);
* :meth:`chat` — plain text (chat / taro).

On a successful call it invokes the injected ``on_success`` callback so the
service layer can stamp the connection's ``last_active_at`` without the client
importing the model layer (no circular dependency). Any adapter/SDK failure is
re-raised as a typed :class:`LlmError`; the api_key is never placed into the
message.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Union

from vbwd.llm.adapter import LlmAdapter
from vbwd.llm.errors import LlmError

_DEFAULT_TEMPERATURE = 0.7


class LlmClient:
    """A provider-agnostic client bound to one resolved connection."""

    def __init__(
        self,
        *,
        adapter: LlmAdapter,
        model: str,
        default_temperature: float = _DEFAULT_TEMPERATURE,
        on_success: Optional[Callable[[], None]] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Bind the client to a resolved connection.

        Args:
            adapter: The provider adapter (OpenAI/Anthropic) already built with
                this connection's endpoint + key + max_tokens.
            model: The model name to send on every call.
            default_temperature: Per-connection temperature default; an explicit
                ``temperature=`` argument on a call overrides it.
            on_success: Optional callback invoked once after every successful
                call (the service stamps ``last_active_at`` here).
            api_key: Retained only so :meth:`_guard` can scrub it from any error
                message; never sent anywhere by the client itself.
        """
        self._adapter = adapter
        self._model = model
        self._default_temperature = default_temperature
        self._on_success = on_success
        self._api_key = api_key

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: Optional[dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Union[dict, str]:
        """Return a structured JSON object for the system/user prompt pair.

        ``max_tokens`` is accepted for call-site symmetry; the per-connection
        max-tokens is already baked into the adapter at build time.
        """
        resolved_temperature = (
            temperature if temperature is not None else self._default_temperature
        )
        result = self._guard(
            lambda: self._adapter.generate(
                system,
                user,
                model=self._model,
                temperature=resolved_temperature,
                json_schema=json_schema,
            )
        )
        return result

    def chat(
        self,
        messages: List[dict],
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Return a plain-text reply for a multi-turn message list."""
        resolved_temperature = (
            temperature if temperature is not None else self._default_temperature
        )
        return self._guard(
            lambda: self._adapter.chat(
                messages,
                model=self._model,
                temperature=resolved_temperature,
                system_prompt=system_prompt,
            )
        )

    def _guard(self, call: Callable):
        """Run ``call``, stamp on success, and re-raise any failure as LlmError.

        The api_key is scrubbed from the raised message as defence-in-depth even
        though the adapters already never include it.
        """
        try:
            result = call()
        except LlmError as llm_error:
            raise self._scrub(llm_error)
        except Exception as unexpected_error:
            raise self._scrub(LlmError("LLM call failed"), cause=unexpected_error)
        if self._on_success is not None:
            self._on_success()
        return result

    def _scrub(self, error: LlmError, *, cause: Optional[Exception] = None) -> LlmError:
        """Return an LlmError whose message cannot contain the api_key."""
        message = str(error)
        if self._api_key and self._api_key in message:
            message = message.replace(self._api_key, "***")
        scrubbed = LlmError(message)
        if cause is not None:
            scrubbed.__cause__ = cause
        return scrubbed
