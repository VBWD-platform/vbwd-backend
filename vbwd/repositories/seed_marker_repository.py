"""Repository for plugin seed markers (S30).

Encapsulates the single source of truth for "has this plugin been seeded?":
upsert on success, read for the status endpoint, clear on ``--reset``.
"""
from datetime import datetime
from typing import Optional

from vbwd.models.plugin_seed_marker import PluginSeedMarker
from vbwd.utils.datetime_utils import utcnow


class SeedMarkerRepository:
    """Reads and writes ``vbwd_plugin_seed_marker`` rows by plugin name."""

    def __init__(self, session):
        """Initialize repository.

        Args:
            session: SQLAlchemy session (Flask-SQLAlchemy ``db.session``).
        """
        self._session = session

    def get(self, plugin_name: str) -> Optional[PluginSeedMarker]:
        """Return the marker for ``plugin_name`` or ``None``."""
        return (
            self._session.query(PluginSeedMarker)
            .filter_by(plugin_name=plugin_name)
            .first()
        )

    def get_populated_at(self, plugin_name: str) -> Optional[datetime]:
        """Return the seed timestamp for ``plugin_name`` or ``None``."""
        marker = self.get(plugin_name)
        return marker.populated_at if marker else None

    def upsert(self, plugin_name: str) -> PluginSeedMarker:
        """Create or refresh the marker for ``plugin_name``."""
        marker = self.get(plugin_name)
        if marker is None:
            marker = PluginSeedMarker(plugin_name=plugin_name, populated_at=utcnow())
            self._session.add(marker)
        else:
            marker.populated_at = utcnow()
        return marker

    def clear(self, plugin_name: str) -> None:
        """Delete the marker for ``plugin_name`` if present."""
        self._session.query(PluginSeedMarker).filter_by(
            plugin_name=plugin_name
        ).delete()
