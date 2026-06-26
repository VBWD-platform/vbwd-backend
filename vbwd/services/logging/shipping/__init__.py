"""Log ship-out seam (Sprint 106, Phase 2) — agnostic port + registry + buffer.

Core defines the :class:`LogShipper` port and a :data:`log_shipper_registry`
that plugins populate; the :data:`log_ship_dispatcher` buffers emitted records
(fed by the router) and a TESTING-guarded scheduler fans batches to every
registered shipper with per-shipper backoff + auto-disable. Core ships nothing
until a shipper plugin registers — it names no vendor.
"""
from .dispatcher import (
    DispatcherStats,
    LogShipDispatcher,
    ShippingConfig,
    load_shipping_config,
    log_ship_dispatcher,
    run_log_ship_job,
    start_log_ship_scheduler,
)
from .port import LogShipper, ShipResult
from .registry import LogShipperRegistry, log_shipper_registry

__all__ = [
    "LogShipper",
    "ShipResult",
    "LogShipperRegistry",
    "log_shipper_registry",
    "LogShipDispatcher",
    "ShippingConfig",
    "DispatcherStats",
    "load_shipping_config",
    "log_ship_dispatcher",
    "run_log_ship_job",
    "start_log_ship_scheduler",
]
