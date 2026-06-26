"""``LogShipperRegistry`` — the open/closed seam plugins populate (Phase 2).

A module-level singleton (mirroring ``search_provider_registry`` /
``line_item_registry``) keyed by the shipper's ``name``. A plugin registers its
:class:`LogShipper` on ``on_enable`` and unregisters on ``on_disable``;
registration is idempotent (re-enable replaces by key). Core ships nothing until
a plugin registers here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .port import LogShipper


class LogShipperRegistry:
    """Holds the registered shippers; agnostic to any concrete backend."""

    def __init__(self) -> None:
        self._shippers: Dict[str, LogShipper] = {}

    def register(self, shipper: LogShipper) -> None:
        """Register (or replace) a shipper by its ``name`` (idempotent)."""
        self._shippers[shipper.name] = shipper

    def unregister(self, name: str) -> None:
        """Remove a shipper (plugin disable); a no-op if absent."""
        self._shippers.pop(name, None)

    def get(self, name: str) -> Optional[LogShipper]:
        return self._shippers.get(name)

    def all(self) -> List[LogShipper]:
        return list(self._shippers.values())

    def clear(self) -> None:
        """Reset all shippers (test teardown)."""
        self._shippers.clear()


# Module-level singleton — the single home plugins register into.
log_shipper_registry = LogShipperRegistry()
