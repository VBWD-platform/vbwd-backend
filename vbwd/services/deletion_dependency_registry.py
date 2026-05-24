"""Registry of user-deletion dependency providers (plugin-contributed).

Core's ``/admin/users/<id>/deletion-info`` reports what cascades when a user is
deleted as a generic ``dependencies: [{type, count, label}]`` list. Core
contributes its own dependencies (e.g. invoices); plugins register a provider
for theirs (e.g. subscriptions), so core names no plugin domain. With nothing
registered (subscription plugin disabled) the list carries only the core
dependencies — the disabled-plugin path degrades gracefully.
"""
from typing import Callable, Dict, List, Optional
from uuid import UUID

# A provider maps a user id to a {type, count, label} dict, or None when the
# user has none of that dependency.
DeletionDependencyProvider = Callable[[UUID], Optional[Dict]]

_providers: Dict[str, DeletionDependencyProvider] = {}


def register_deletion_dependency_provider(
    key: str, provider: DeletionDependencyProvider
) -> None:
    """Register (or replace) a plugin's deletion-dependency provider."""
    _providers[key] = provider


def unregister_deletion_dependency_provider(key: str) -> None:
    """Remove a plugin's provider (plugin disable)."""
    _providers.pop(key, None)


def clear_deletion_dependency_providers() -> None:
    """Reset all providers (test teardown)."""
    _providers.clear()


def resolve_deletion_dependencies(user_id: UUID) -> List[Dict]:
    """Collect non-empty {type, count, label} dependencies from all providers."""
    dependencies: List[Dict] = []
    for provider in _providers.values():
        dependency = provider(user_id)
        if dependency and dependency.get("count", 0) > 0:
            dependencies.append(dependency)
    return dependencies
