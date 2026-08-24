"""``LlmConnectionService`` — admin-managed LLM connections + the client resolver.

The core, domain-agnostic registry service (sibling of ``CurrencyService``):
CRUD over :class:`~vbwd.models.llm_connection.LlmConnection`, the single-default
invariant, the active-default rule (D-DefaultActive), masking (one shared path),
and the resolver :meth:`llm_client` that every consuming plugin calls.

The resolver builds a connection-bound :class:`~vbwd.llm.client.LlmClient` over
``select_adapter`` from the connection's endpoint + decrypted key + model. The
client's ``on_success`` callback stamps ``last_active_at`` through this service,
so the client never imports the model layer.
"""
from datetime import datetime, timezone
from typing import List, Optional, Union
from uuid import UUID

from vbwd.llm.adapter import select_adapter
from vbwd.llm.client import LlmClient
from vbwd.models.llm_connection import LlmConnection, mask_api_key
from vbwd.repositories.llm_connection_repository import LlmConnectionRepository

ConnectionId = Union[str, UUID]

# Anthropic's native SDK needs a per-request max_tokens; use the connection's own
# value when set, else this safe default (mirrors the adapter's own default).
_DEFAULT_MAX_TOKENS = 4096


class NoActiveLlmConnectionError(Exception):
    """Raised when no active connection can be resolved for a slug (or default).

    The plugin-facing signal that an admin must activate/set a default
    connection (D-DefaultActive); plugins surface it as a clear config error.
    """


class LlmConnectionService:
    """Admin LLM connection registry + the plugin-facing client resolver."""

    def __init__(self, repository: LlmConnectionRepository) -> None:
        self._repository = repository

    # ── reads ─────────────────────────────────────────────────────────────

    def list_all(self) -> List[LlmConnection]:
        return self._repository.list_all()

    def list_active(self) -> List[LlmConnection]:
        return self._repository.list_active()

    def get_by_id(self, connection_id: str) -> Optional[LlmConnection]:
        return self._repository.find_by_id(connection_id)

    def get_by_slug(self, slug: str) -> Optional[LlmConnection]:
        return self._repository.find_by_slug(slug)

    def get_default(self) -> Optional[LlmConnection]:
        """Return the ACTIVE default connection (an inactive default counts as none)."""
        default = self._repository.find_default()
        if default is None or not default.is_active:
            return None
        return default

    def mask(self, api_key: str) -> str:
        """Return the masked preview (first 16 chars then an ellipsis) — DRY."""
        return mask_api_key(api_key)

    # ── mutations ─────────────────────────────────────────────────────────

    def create(self, **fields) -> LlmConnection:
        """Create a new connection. A new connection is never the default."""
        slug = fields.get("slug")
        if slug and self._repository.find_by_slug(slug):
            raise ValueError(f"Connection slug already exists: {slug}")
        fields.pop("is_default", None)
        connection = LlmConnection(**fields)
        return self._repository.save(connection)

    def update(self, connection_id: str, **fields) -> LlmConnection:
        """Update mutable fields on a connection (the default flag is not touched)."""
        connection = self._require(connection_id)
        fields.pop("is_default", None)
        new_slug = fields.get("slug")
        if new_slug and new_slug != connection.slug:
            existing = self._repository.find_by_slug(new_slug)
            if existing is not None and existing.id != connection.id:
                raise ValueError(f"Connection slug already exists: {new_slug}")
        for field_name, value in fields.items():
            setattr(connection, field_name, value)
        return self._repository.update(connection)

    def delete(self, connection_id: str) -> None:
        """Delete a connection. Deleting the default simply clears the default."""
        self._repository.delete(connection_id)

    def bulk_delete(self, connection_ids: List[str]) -> int:
        """Delete several connections; return the count actually deleted."""
        deleted = 0
        for connection_id in connection_ids:
            if self._repository.delete(connection_id):
                deleted += 1
        return deleted

    def set_active(
        self, connection_ids: List[ConnectionId], active: bool
    ) -> List[LlmConnection]:
        """Activate/deactivate connections.

        Deactivating a connection that is the default also clears its default
        flag (D-DefaultActive) so an empty-slug consumer gets a clear
        :class:`NoActiveLlmConnectionError` until an admin sets a new default.
        """
        connections = self._repository.find_by_ids(connection_ids)
        for connection in connections:
            connection.is_active = active
            if not active and connection.is_default:
                connection.is_default = False
            self._repository.update(connection)
        return connections

    def set_default(self, connection_id: str) -> LlmConnection:
        """Make a connection the single, active default (flips the previous off)."""
        target = self._require(connection_id)
        if not target.is_active:
            raise ValueError("Only an active connection can become the default")

        current_default = self._repository.find_default()
        if current_default is not None and current_default.id != target.id:
            current_default.is_default = False
            self._repository.update(current_default)

        target.is_default = True
        return self._repository.update(target)

    def stamp_last_active(self, connection_id: str) -> None:
        """Stamp ``last_active_at`` = now on the connection (called per LLM call)."""
        connection = self._repository.find_by_id(connection_id)
        if connection is None:
            return
        connection.last_active_at = datetime.now(timezone.utc)
        self._repository.update(connection)

    # ── the plugin-facing resolver ────────────────────────────────────────

    def llm_client(self, slug: Optional[str] = None) -> LlmClient:
        """Resolve a ready :class:`LlmClient` for ``slug`` (else the default).

        Raises :class:`NoActiveLlmConnectionError` when the named slug is
        missing/inactive, or when no active default exists for an empty slug.
        """
        connection = self._repository.find_by_slug(slug) if slug else self.get_default()
        if connection is None or not connection.is_active:
            target = f"slug '{slug}'" if slug else "default"
            raise NoActiveLlmConnectionError(f"No active LLM connection for {target}")
        return self._build_client(connection)

    def _build_client(self, connection: LlmConnection) -> LlmClient:
        connection_id = str(connection.id)
        max_tokens = connection.max_tokens or _DEFAULT_MAX_TOKENS
        adapter = select_adapter(
            model=connection.model,
            api_key=connection.api_key,
            endpoint=connection.api_endpoint or "",
            max_tokens=max_tokens,
        )
        default_temperature = (
            connection.temperature if connection.temperature is not None else 0.7
        )
        return LlmClient(
            adapter=adapter,
            model=connection.model,
            default_temperature=default_temperature,
            on_success=lambda: self.stamp_last_active(connection_id),
            api_key=connection.api_key,
        )

    def test_connection(
        self,
        *,
        model: str,
        api_endpoint: str,
        api_key: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Make a minimal live call to verify an endpoint/model/key triple.

        Builds a throwaway client from the supplied values (never persisted) and
        sends a one-token prompt; returns the sample reply on success. Any
        provider/transport failure surfaces as the adapter's typed
        :class:`~vbwd.llm.errors.LlmError`, whose message NEVER contains the key.
        Used by the admin "Test Connection" action to validate a connection
        before it is saved — including a self-hosted endpoint such as Ollama.
        """
        adapter = select_adapter(
            model=model,
            api_key=api_key,
            endpoint=api_endpoint or "",
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
        )
        client = LlmClient(
            adapter=adapter,
            model=model,
            default_temperature=temperature if temperature is not None else 0.7,
        )
        return client.chat([{"role": "user", "content": "ping"}])

    def _require(self, connection_id: str) -> LlmConnection:
        connection = self._repository.find_by_id(connection_id)
        if connection is None:
            raise LookupError(f"LLM connection not found: {connection_id}")
        return connection
