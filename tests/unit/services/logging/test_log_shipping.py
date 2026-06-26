"""Sprint 106 Phase 2 — acceptance tests for the log ship-out seam.

Drives the agnostic core machinery directly (no app boot, no real scheduler):
  * :class:`LogShipperRegistry` register/unregister/replace/clear;
  * :class:`LogShipDispatcher` buffer (floor, capacity drop-oldest, inert with no
    shipper), drain + fan-out, per-shipper exponential backoff + auto-disable,
    and the "no ready shipper -> don't drain" buffering behaviour;
  * :func:`load_shipping_config` reads the ``shipping`` block of logging.json;
  * the router ``ship_hook`` receives the redacted payload and never propagates.

A fake in-memory shipper records the batches it is handed so the tests assert on
what would have been shipped.
"""
import logging

import pytest

from vbwd.services.logging.reader import level_to_value
from vbwd.services.logging.router import VbwdLogRouter
from vbwd.services.logging.shipping import (
    LogShipDispatcher,
    LogShipper,
    LogShipperRegistry,
    ShipResult,
    ShippingConfig,
    load_shipping_config,
)


class FakeShipper(LogShipper):
    """Records batches; ``fail`` makes every ship return a failure."""

    def __init__(self, name="fake", fail=False, raises=False):
        self._name = name
        self.fail = fail
        self.raises = raises
        self.batches = []

    @property
    def name(self):
        return self._name

    def ship(self, records):
        if self.raises:
            raise RuntimeError("boom")
        self.batches.append(list(records))
        if self.fail:
            return ShipResult.failure("backend 500")
        return ShipResult.success()


def _payload(level="ERROR", msg="x"):
    return {"ts": 1.0, "level": level, "scope": "core", "stream": "error", "msg": msg}


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_register_get_all_unregister():
    registry = LogShipperRegistry()
    shipper = FakeShipper("loki")
    registry.register(shipper)
    assert registry.get("loki") is shipper
    assert registry.all() == [shipper]
    registry.unregister("loki")
    assert registry.get("loki") is None
    assert registry.all() == []


def test_registry_register_is_idempotent_by_name():
    registry = LogShipperRegistry()
    first = FakeShipper("loki")
    second = FakeShipper("loki")
    registry.register(first)
    registry.register(second)
    assert registry.all() == [second]  # replaced, not duplicated


# --------------------------------------------------------------------------
# Dispatcher — buffering
# --------------------------------------------------------------------------


def test_enqueue_is_inert_without_a_registered_shipper():
    registry = LogShipperRegistry()
    dispatcher = LogShipDispatcher(registry=registry)
    dispatcher.enqueue(_payload())
    assert dispatcher.stats().buffered == 0  # nothing buffered until a shipper exists


def test_enqueue_respects_the_min_level_floor():
    registry = LogShipperRegistry()
    registry.register(FakeShipper())
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(min_level="warning")
    )
    dispatcher.enqueue(_payload(level="INFO"))  # below floor -> dropped
    dispatcher.enqueue(_payload(level="ERROR"))  # at/above floor -> kept
    assert dispatcher.stats().buffered == 1


def test_enqueue_events_record_without_level_is_kept():
    # Level-less audit records must not be filtered out by the floor.
    registry = LogShipperRegistry()
    registry.register(FakeShipper())
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(min_level="error")
    )
    dispatcher.enqueue({"ts": 1.0, "event": "payment.captured", "scope": "core"})
    assert dispatcher.stats().buffered == 1


def test_buffer_capacity_drops_oldest_and_counts():
    registry = LogShipperRegistry()
    registry.register(FakeShipper())
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(buffer_capacity=3, min_level="info")
    )
    for index in range(5):
        dispatcher.enqueue(_payload(msg=f"line-{index}"))
    stats = dispatcher.stats()
    assert stats.buffered == 3
    assert stats.dropped == 2


def test_disabled_config_makes_enqueue_inert():
    registry = LogShipperRegistry()
    registry.register(FakeShipper())
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(enabled=False)
    )
    dispatcher.enqueue(_payload())
    assert dispatcher.stats().buffered == 0


# --------------------------------------------------------------------------
# Dispatcher — drain + fan-out
# --------------------------------------------------------------------------


def test_run_once_ships_buffered_batch_to_every_shipper():
    registry = LogShipperRegistry()
    one, two = FakeShipper("one"), FakeShipper("two")
    registry.register(one)
    registry.register(two)
    dispatcher = LogShipDispatcher(registry=registry, config=ShippingConfig())
    dispatcher.enqueue(_payload(msg="a"))
    dispatcher.enqueue(_payload(msg="b"))

    shipped = dispatcher.run_once(now=100.0)

    assert shipped == 2
    assert [r["msg"] for r in one.batches[0]] == ["a", "b"]
    assert [r["msg"] for r in two.batches[0]] == ["a", "b"]
    assert dispatcher.stats().buffered == 0  # batch consumed


def test_run_once_respects_max_batch():
    registry = LogShipperRegistry()
    shipper = FakeShipper()
    registry.register(shipper)
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(max_batch=2)
    )
    for index in range(5):
        dispatcher.enqueue(_payload(msg=f"l{index}"))

    assert dispatcher.run_once(now=1.0) == 2
    assert dispatcher.stats().buffered == 3


# --------------------------------------------------------------------------
# Dispatcher — backoff + auto-disable
# --------------------------------------------------------------------------


def test_failure_backs_off_then_recovers():
    registry = LogShipperRegistry()
    shipper = FakeShipper(fail=True)
    registry.register(shipper)
    dispatcher = LogShipDispatcher(
        registry=registry,
        config=ShippingConfig(backoff_base_seconds=30, auto_disable_threshold=5),
    )
    dispatcher.enqueue(_payload())
    dispatcher.run_once(now=100.0)  # fails -> backoff 30s, next_attempt=130

    # Within the backoff window the shipper is not ready -> nothing drained.
    dispatcher.enqueue(_payload())
    assert dispatcher.run_once(now=110.0) == 0
    assert dispatcher.stats().buffered == 1  # held, not lost

    # After the window, it retries; flip it healthy so it succeeds + resets.
    shipper.fail = False
    assert dispatcher.run_once(now=131.0) == 1
    assert dispatcher.stats().shippers["fake"]["consecutive_failures"] == 0


def test_auto_disable_after_threshold():
    registry = LogShipperRegistry()
    shipper = FakeShipper(fail=True)
    registry.register(shipper)
    dispatcher = LogShipDispatcher(
        registry=registry,
        config=ShippingConfig(backoff_base_seconds=1, auto_disable_threshold=3),
    )
    now = 0.0
    for _ in range(3):
        dispatcher.enqueue(_payload())
        dispatcher.run_once(now=now)
        now += 10000  # always past the backoff window so each tick attempts
    state = dispatcher.stats().shippers["fake"]
    assert state["disabled"] is True
    # A disabled shipper is never ready again -> buffer holds, nothing drained.
    dispatcher.enqueue(_payload())
    assert dispatcher.run_once(now=now + 10000) == 0


def test_a_raising_shipper_is_treated_as_a_failure_not_a_crash():
    registry = LogShipperRegistry()
    shipper = FakeShipper(raises=True)
    registry.register(shipper)
    dispatcher = LogShipDispatcher(registry=registry, config=ShippingConfig())
    dispatcher.enqueue(_payload())
    dispatcher.run_once(now=1.0)  # must not raise
    assert dispatcher.stats().shippers["fake"]["consecutive_failures"] == 1


def test_reset_shipper_clears_disabled_state():
    registry = LogShipperRegistry()
    shipper = FakeShipper(fail=True)
    registry.register(shipper)
    dispatcher = LogShipDispatcher(
        registry=registry, config=ShippingConfig(auto_disable_threshold=1)
    )
    dispatcher.enqueue(_payload())
    dispatcher.run_once(now=1.0)
    assert dispatcher.stats().shippers["fake"]["disabled"] is True
    dispatcher.reset_shipper("fake")
    assert "fake" not in dispatcher.stats().shippers


# --------------------------------------------------------------------------
# Config loader
# --------------------------------------------------------------------------


class FakeManager:
    def __init__(self, data):
        self._data = data

    def read_json(self, namespace, relative_path, default=None):
        return self._data if self._data is not None else default


def test_load_shipping_config_reads_block_with_defaults():
    config = load_shipping_config(
        FakeManager({"shipping": {"enabled": False, "max_batch": 42}})
    )
    assert config.enabled is False
    assert config.max_batch == 42
    assert config.flush_interval_seconds == ShippingConfig().flush_interval_seconds


def test_load_shipping_config_missing_block_is_defaults():
    config = load_shipping_config(FakeManager({}))
    assert config == ShippingConfig()


# --------------------------------------------------------------------------
# Router ship-hook integration
# --------------------------------------------------------------------------


@pytest.fixture
def memory_manager():
    from vbwd.services.filesystem import InMemoryFilesystemManager

    return InMemoryFilesystemManager(uploads_base_url="/uploads")


def test_router_ship_hook_receives_redacted_payload(memory_manager):
    shipped = []
    router = VbwdLogRouter(filesystem_manager=memory_manager, ship_hook=shipped.append)
    record = logging.makeLogRecord(
        {
            "name": "plugins.shop.x",
            "levelno": logging.ERROR,
            "levelname": "ERROR",
            "msg": "checkout failed",
            "vbwd_extra": {"api_key": "secret-value"},
        }
    )
    router.emit(record)

    assert len(shipped) == 1
    assert shipped[0]["scope"] == "shop"
    assert shipped[0]["msg"] == "checkout failed"
    assert shipped[0]["api_key"] == "***"  # redaction applied before shipping


def test_router_ship_hook_failure_never_propagates(memory_manager):
    def boom(_payload):
        raise RuntimeError("hook blew up")

    router = VbwdLogRouter(filesystem_manager=memory_manager, ship_hook=boom)
    record = logging.makeLogRecord(
        {"name": "core", "levelno": logging.ERROR, "levelname": "ERROR", "msg": "x"}
    )
    router.emit(record)  # must not raise


def test_router_below_floor_record_is_not_shipped(memory_manager):
    shipped = []
    router = VbwdLogRouter(filesystem_manager=memory_manager, ship_hook=shipped.append)
    record = logging.makeLogRecord(
        {"name": "core", "levelno": logging.DEBUG, "levelname": "DEBUG", "msg": "x"}
    )
    router.emit(record)
    assert shipped == []  # DEBUG is below INFO -> no disk write, no ship


def test_level_to_value_helper():
    assert level_to_value("ERROR") == logging.ERROR
    assert level_to_value(None) is None
    assert level_to_value("nope") is None
