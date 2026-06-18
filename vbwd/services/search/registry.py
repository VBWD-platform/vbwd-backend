"""The cross-entity search provider registry (agnostic singleton).

Plugins register a :class:`SearchProvider` per entity type in their
``on_enable``; core aggregates them. Mirrors ``data_exchange_registry``.

GDPR: providers for personal-data entities are refused at registration — there
is no code path by which ``user`` / ``user_details`` / ``invoice`` become
searchable, even if a plugin tried to register one.
"""
from typing import Dict, List, Optional

from vbwd.services.search.provider import SearchHit, SearchProvider

# Personal-data entities that must NEVER be exposed to free-text search.
GDPR_BLOCKED_ENTITY_TYPES = frozenset({"user", "user_details", "invoice"})


class SearchProviderRegistry:
    """Keyed set of search providers, one per ``entity_type``."""

    def __init__(self) -> None:
        self._providers: Dict[str, SearchProvider] = {}

    def register(self, provider: SearchProvider) -> None:
        """Register (or replace) a provider. Refuses GDPR-blocked entity types."""
        entity_type = provider.entity_type
        if entity_type in GDPR_BLOCKED_ENTITY_TYPES:
            raise ValueError(
                f"search provider for personal-data entity '{entity_type}' is "
                "blocked (GDPR): users / user details / invoices are never searchable"
            )
        self._providers[entity_type] = provider

    def unregister(self, entity_type: str) -> None:
        """Remove a provider (plugin disable)."""
        self._providers.pop(entity_type, None)

    def clear(self) -> None:
        """Reset all providers (test teardown)."""
        self._providers.clear()

    def get(self, entity_type: str) -> Optional[SearchProvider]:
        return self._providers.get(entity_type)

    def all(self) -> List[SearchProvider]:
        return list(self._providers.values())

    def entity_types(self) -> List[str]:
        return list(self._providers.keys())

    def search(
        self,
        query: str,
        *,
        entity_types: Optional[List[str]] = None,
        limit_per_provider: int = 5,
    ) -> List[SearchHit]:
        """Aggregate hits across providers.

        ``entity_types`` (when given) restricts to those keys — unknown keys are
        ignored and GDPR-blocked keys can never appear (none are registered). A
        blank query yields no hits. A provider that raises is skipped (one bad
        provider never breaks the whole search).
        """
        if not query or not query.strip():
            return []
        hits: List[SearchHit] = []
        for provider in self._providers.values():
            if entity_types is not None and provider.entity_type not in entity_types:
                continue
            try:
                hits.extend(provider.search(query, limit=limit_per_provider))
            except Exception:  # noqa: BLE001 — one provider must not break search
                continue
        return hits


# Module-level singleton (mirrors data_exchange_registry).
search_provider_registry = SearchProviderRegistry()
