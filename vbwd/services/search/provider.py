"""The search provider port + the neutral hit shape.

A ``SearchProvider`` is contributed by a plugin for ONE entity type. It must be
able to (1) find hits for a free-text query and (2) re-resolve a single hit by
its stable ``key`` (so the bot can show an in-chat detail card when a result is
tapped). Everything is provider-neutral: core never imports a plugin model.
"""
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchHit:
    """One provider-neutral search result.

    ``entity_type`` is the provider's unique key (e.g. ``"shop_product"``);
    ``entity_label`` is its human label (e.g. ``"Shop"``). ``key`` is the stable
    identifier (id or slug) the provider uses to re-resolve the hit on tap.
    ``url`` is the PUBLIC fe-user route to the entity (the plugin owns its own
    routes — core just carries the string). ``price`` is a pre-formatted display
    string (no client-side math).
    """

    entity_type: str
    entity_label: str
    key: str
    title: str
    snippet: str = ""
    url: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_label": self.entity_label,
            "key": self.key,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "image_url": self.image_url,
            "price": self.price,
        }


@runtime_checkable
class SearchProvider(Protocol):
    """A plugin's searchable-entity adapter (one per entity type)."""

    #: Unique, stable key for this entity type (e.g. ``"shop_product"``).
    entity_type: str
    #: Human-readable label shown next to results (e.g. ``"Shop"``).
    entity_label: str

    def search(self, query: str, *, limit: int = 5) -> List[SearchHit]:
        """Return up to ``limit`` hits matching ``query`` (case-insensitive over
        the entity's public, non-personal fields). A blank query returns []."""
        ...

    def get_detail(self, key: str) -> Optional[SearchHit]:
        """Re-resolve a single hit by its ``key`` for the in-chat detail card,
        or ``None`` if it no longer exists."""
        ...
