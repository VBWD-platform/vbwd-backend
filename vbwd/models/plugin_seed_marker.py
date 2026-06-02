"""Seed-marker model (S30).

One row per plugin that ``flask seed`` has successfully populated. The
``/api/v1/_seed_status`` endpoint diffs the enabled plugin set against these
rows so the load-test harness can assert ``unseeded == []`` after seeding.

A standalone core table (PK = plugin name) — deliberately NOT a ``BaseModel``
subclass: there is no UUID identity, no optimistic-locking version, and the
natural key is the plugin name.
"""
from vbwd.extensions import db
from vbwd.utils.datetime_utils import utcnow


class PluginSeedMarker(db.Model):  # type: ignore[name-defined]
    """Records that a plugin's demo data has been seeded."""

    __tablename__ = "vbwd_plugin_seed_marker"

    plugin_name = db.Column(db.String(255), primary_key=True)
    populated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def to_dict(self) -> dict:
        """Serialise to a plain dict with an ISO timestamp."""
        return {
            "plugin_name": self.plugin_name,
            "populated_at": (
                self.populated_at.isoformat() if self.populated_at else None
            ),
        }
