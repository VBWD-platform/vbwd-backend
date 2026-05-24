"""Generic plan-catalog read port — core stays subscription-agnostic.

Some feature plugins (e.g. ghrm — a software store keyed to plans/categories)
need to read the plan catalog without importing the subscription models. Core
defines this narrow read port; the subscription plugin supplies the concrete
read model on enable. When no provider is registered (subscription plugin
disabled) the null default yields empty results — no error.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from uuid import UUID


class ICatalogReadModel(ABC):
    """Narrow read-only port (ISP) — only what catalog consumers need."""

    @abstractmethod
    def category_labels_by_slugs(self, slugs: List[str]) -> Dict[str, str]:
        """Map of {category_slug: display_name} for the given slugs."""

    @abstractmethod
    def plan_ids_in_category(self, category_slug: str) -> List[UUID]:
        """Plan ids belonging to the category, or [] if unknown."""


class _NullCatalogReadModel(ICatalogReadModel):
    """Used when the subscription plugin is disabled — empty catalog."""

    def category_labels_by_slugs(self, slugs: List[str]) -> Dict[str, str]:
        return {}

    def plan_ids_in_category(self, category_slug: str) -> List[UUID]:
        return []


_read_model: Optional[ICatalogReadModel] = None


def register_catalog_read_model(read_model: ICatalogReadModel) -> None:
    """Called by the subscription plugin on enable."""
    global _read_model
    _read_model = read_model


def clear_catalog_read_model() -> None:
    """Reset to the null default (plugin disable / test teardown)."""
    global _read_model
    _read_model = None


def resolve_catalog_read_model() -> ICatalogReadModel:
    """The registered read model, or the empty null default."""
    return _read_model if _read_model is not None else _NullCatalogReadModel()
