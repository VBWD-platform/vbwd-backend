"""Cross-entity search seam (agnostic).

Core owns a generic ``SearchProviderRegistry`` into which plugins register a
``SearchProvider`` for each non-core entity they expose to search (e.g. shop
products, booking resources, ghrm packages, subscription plans). Core names no
plugin domain — it only aggregates whatever providers register, exactly like
``data_exchange_registry`` / ``deletion_dependency_registry``.

GDPR: personal-data entities (``user`` / ``user_details`` / ``invoice``) are
hard-blocked at registration so no provider can ever expose them to search.
"""
from vbwd.services.search.provider import SearchHit, SearchProvider
from vbwd.services.search.registry import (
    GDPR_BLOCKED_ENTITY_TYPES,
    SearchProviderRegistry,
    search_provider_registry,
)

__all__ = [
    "SearchHit",
    "SearchProvider",
    "SearchProviderRegistry",
    "search_provider_registry",
    "GDPR_BLOCKED_ENTITY_TYPES",
]
