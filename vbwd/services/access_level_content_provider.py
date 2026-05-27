"""Generic access-level content port — core stays content-plugin-agnostic.

Core's admin route ``GET /api/v1/admin/access/user-levels/<id>/content``
used to ``from plugins.cms.src.models import …`` to list CMS pages and
widgets restricted to a given user-access level. That hard-coupled core
to the CMS plugin's ORM models. S01 replaces it with this multi-provider
registry: any plugin owning access-restricted content registers a
provider on enable; the core route iterates all registered providers
and merges their categorised results.

Contract (intentionally narrow per ISP):
  ``list_restricted_content_for_level(level_id) -> Mapping[category, list[item]]``

Each provider returns content grouped by a category string (e.g. CMS
returns ``{"pages": [...], "widgets": [...]}``). Core concatenates the
per-category lists across providers, so two providers contributing
``"pages"`` will both show up under that key in the response. The item
shape is plugin-decided — core does not interpret it, it just forwards.
"""
from abc import ABC, abstractmethod
from typing import Any, Mapping


class IAccessLevelContentProvider(ABC):
    """A plugin that owns access-restricted content (pages, widgets, …)."""

    @abstractmethod
    def list_restricted_content_for_level(
        self, level_id: str
    ) -> Mapping[str, list[Mapping[str, Any]]]:
        """Return content this provider restricts to the given access level,
        grouped by category. An empty mapping is fine when nothing is restricted.
        """


_providers: list[IAccessLevelContentProvider] = []


def register_access_level_content_provider(
    provider: IAccessLevelContentProvider,
) -> None:
    """Called by a content-owning plugin on enable."""
    _providers.append(provider)


def clear_access_level_content_providers() -> None:
    """Reset the registry (plugin disable / test teardown)."""
    _providers.clear()


def resolve_access_level_content_providers() -> list[IAccessLevelContentProvider]:
    """Every currently registered provider — empty list when nothing is registered
    (Liskov-safe null default: core's route returns ``{}`` instead of 500)."""
    return list(_providers)
