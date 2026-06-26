"""``LogShipper`` port — the agnostic ship-out seam (Sprint 106, Phase 2).

Core defines the contract; concrete shippers (Loki / Sentry / generic webhook)
are **plugins** that register a :class:`LogShipper` into the
:data:`log_shipper_registry`. Core names no vendor and ships nothing by default
— with no shipper registered the whole mechanism is inert.

A shipper receives a batch of already-**redacted** log-record dicts (the exact
JSON shape the on-disk router writes: ``ts``/``level``/``scope``/``stream``/
``logger``/``msg`` + any extra) and forwards them to its backend. It returns a
:class:`ShipResult` rather than raising, so one failing backend never breaks the
ship scheduler (which additionally guards every call). Shipping is best-effort:
the on-disk logs remain the durable source of truth.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class ShipResult:
    """Outcome of one :meth:`LogShipper.ship` call.

    Attributes:
        ok: True when the batch was accepted by the backend.
        detail: short human-readable reason (used for the failure log line);
            empty on success.
    """

    ok: bool
    detail: str = ""

    @classmethod
    def success(cls) -> "ShipResult":
        return cls(ok=True)

    @classmethod
    def failure(cls, detail: str) -> "ShipResult":
        return cls(ok=False, detail=detail)


class LogShipper(abc.ABC):
    """A pluggable destination for shipped log records.

    Implementations live in plugins and register themselves via the registry on
    ``on_enable`` (unregister on ``on_disable``). The implementation owns its own
    config/credentials (e.g. read from the plugin's ``config.json``); core passes
    only the record batch.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable identifier (the registry key + the per-shipper backoff key)."""

    @abc.abstractmethod
    def ship(self, records: List[Dict[str, Any]]) -> ShipResult:
        """Forward a batch of redacted log-record dicts to the backend.

        MUST NOT raise for an expected transport/backend error — return
        ``ShipResult.failure(...)`` instead so the scheduler can apply backoff.
        The dispatcher guards the call regardless, but a well-behaved shipper
        reports failures as results.
        """
