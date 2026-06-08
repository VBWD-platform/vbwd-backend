"""Sprint 58.5 — boot-wiring guard for the unified logging layer.

Drives :func:`_install_unified_logging` directly with a fake Flask-app stand-in
and a fake DI container so we can assert the TESTING guard without booting the
whole Flask app (which needs a DB). The contract:

  * under ``TESTING`` the disk router is NOT attached to the root logger and the
    event subscriber is NOT registered (pytest must not write ``/app/var/logs``);
  * outside ``TESTING`` exactly one :class:`VbwdLogRouter` is attached and the
    subscriber is registered on the bus;
  * a manager that explodes on resolution does not break boot (best-effort).
"""
import logging

from vbwd.app import _install_unified_logging
from vbwd.events.bus import EventBus
from vbwd.services.filesystem import InMemoryFilesystemManager
from vbwd.services.logging import VbwdLogRouter


class _FakeApp:
    def __init__(self, config):
        self.config = config


class _FakeContainer:
    def __init__(self, manager):
        self._manager = manager

    def filesystem_manager(self):
        return self._manager


def _count_routers():
    return [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, VbwdLogRouter)
    ]


def _detach_routers():
    root = logging.getLogger()
    for handler in _count_routers():
        root.removeHandler(handler)


def test_testing_guard_skips_disk_router(monkeypatch):
    _detach_routers()
    monkeypatch.setattr(EventBus, "subscribe_all", _fail_if_called)
    app = _FakeApp({"TESTING": True})
    container = _FakeContainer(InMemoryFilesystemManager(uploads_base_url="/u"))

    _install_unified_logging(app, container)

    assert _count_routers() == []


def test_non_testing_attaches_router_once(monkeypatch):
    _detach_routers()
    registered = []
    monkeypatch.setattr(
        "vbwd.events.bus.event_bus.subscribe_all",
        lambda callback: registered.append(callback),
    )
    app = _FakeApp({"TESTING": False})
    container = _FakeContainer(InMemoryFilesystemManager(uploads_base_url="/u"))

    _install_unified_logging(app, container)
    # Idempotent — a second call must not attach a second router.
    _install_unified_logging(app, container)

    try:
        assert len(_count_routers()) == 1
        assert len(registered) >= 1
    finally:
        _detach_routers()


def test_boot_survives_exploding_manager():
    _detach_routers()

    class _ExplodingContainer:
        def filesystem_manager(self):
            raise OSError("var not writable")

    app = _FakeApp({"TESTING": False})
    # Must not raise.
    _install_unified_logging(app, _ExplodingContainer())
    _detach_routers()


def _fail_if_called(*args, **kwargs):  # pragma: no cover - guard helper
    raise AssertionError("subscriber must not register under TESTING")
