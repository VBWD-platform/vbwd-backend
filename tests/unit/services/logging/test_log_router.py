"""Sprint 58.5 — acceptance tests for the unified logging layer (D9).

These tests are the contract for :class:`VbwdLogRouter` and
:class:`EventLogSubscriber`. They drive the router/subscriber DIRECTLY with a
``tmp_path``-rooted :class:`LocalFilesystemManager` (and the in-memory double
where round-trips suffice) — they do NOT rely on the TESTING-guarded boot path,
which deliberately does not attach the disk router during pytest.

Covered behaviours mirror the sprint's TDD plan:
  * scope+stream routing (logger-name -> scope, level -> stream);
  * per-scope stream allowlist folds a disallowed (scope, stream) into the
    core file for that stream while preserving ``scope`` in the JSON line;
  * every emitted line parses as JSON with ts/level/scope/logger/msg;
  * an EventBus publish appends a JSON line to ``core/events.log``;
  * redaction masks secret-named keys (incl. nested) before write;
  * size rotation rolls a file to ``.1`` and caps backups;
  * resilience: a failing underlying append never propagates out of ``emit()``.
"""
import json
import logging

import pytest

from vbwd.events.bus import EventBus
from vbwd.services.filesystem import (
    InMemoryFilesystemManager,
    LocalFilesystemManager,
)
from vbwd.services.logging import (
    EventLogSubscriber,
    LoggingConfig,
    VbwdLogRouter,
    parse_log_level,
    redact,
)


@pytest.fixture
def local_manager(tmp_path, monkeypatch):
    """A LocalFilesystemManager rooted entirely under a throwaway tmp dir."""
    var_root = tmp_path / "var"
    uploads_root = tmp_path / "uploads"
    var_root.mkdir()
    uploads_root.mkdir()
    monkeypatch.setenv("VBWD_VAR_DIR", str(var_root))
    monkeypatch.setenv("UPLOADS_BASE_PATH", str(uploads_root))
    monkeypatch.setenv("UPLOADS_BASE_URL", "/uploads")
    return LocalFilesystemManager()


@pytest.fixture
def memory_manager():
    return InMemoryFilesystemManager(uploads_base_url="/uploads")


@pytest.fixture(params=["local", "memory"])
def rotating_manager(request, local_manager, memory_manager):
    """Both impls must honour the rotation contract (Liskov)."""
    return local_manager if request.param == "local" else memory_manager


def _make_record(name, level, msg, **extra):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _read_lines(manager, rel):
    return [
        line for line in manager.read_text("logs", rel).splitlines() if line.strip()
    ]


# ---------------------------------------------------------------------------
# Scope + stream routing
# ---------------------------------------------------------------------------


def test_plugin_error_routes_to_plugin_error_log(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("plugins.cms.service", logging.ERROR, "boom"))

    lines = _read_lines(memory_manager, "cms/error.log")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["scope"] == "cms"
    assert payload["stream"] == "error"
    assert payload["logger"] == "plugins.cms.service"
    assert payload["msg"] == "boom"


def test_core_logger_info_routes_to_core_info_log(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("vbwd.routes.user", logging.INFO, "served"))

    lines = _read_lines(memory_manager, "core/info.log")
    assert len(lines) == 1
    assert json.loads(lines[0])["scope"] == "core"


def test_root_and_unknown_logger_map_to_core(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("werkzeug", logging.ERROR, "third-party"))

    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    assert payload["scope"] == "core"
    assert payload["logger"] == "werkzeug"


def test_below_info_is_ignored(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("vbwd.x", logging.DEBUG, "noise"))
    assert not memory_manager.exists("logs", "core/info.log")


# ---------------------------------------------------------------------------
# S90 G2 — app-log verbosity floor (VBWD_LOG_LEVEL)
# ---------------------------------------------------------------------------


def test_min_level_warning_drops_info_keeps_warning_and_error(memory_manager):
    """At min_level=WARNING the info stream stops; warning/error still route."""
    config = LoggingConfig(min_level=logging.WARNING)
    router = VbwdLogRouter(filesystem_manager=memory_manager, config=config)

    router.emit(_make_record("vbwd.x", logging.INFO, "chatter"))
    router.emit(_make_record("vbwd.x", logging.WARNING, "heads up"))
    router.emit(_make_record("vbwd.x", logging.ERROR, "boom"))

    assert not memory_manager.exists("logs", "core/info.log")
    assert json.loads(_read_lines(memory_manager, "core/warnings.log")[0])["msg"] == (
        "heads up"
    )
    assert json.loads(_read_lines(memory_manager, "core/error.log")[0])["msg"] == "boom"


def test_min_level_error_drops_info_and_warnings(memory_manager):
    config = LoggingConfig(min_level=logging.ERROR)
    router = VbwdLogRouter(filesystem_manager=memory_manager, config=config)

    router.emit(_make_record("vbwd.x", logging.INFO, "chatter"))
    router.emit(_make_record("vbwd.x", logging.WARNING, "heads up"))
    router.emit(_make_record("vbwd.x", logging.ERROR, "boom"))

    assert not memory_manager.exists("logs", "core/info.log")
    assert not memory_manager.exists("logs", "core/warnings.log")
    assert json.loads(_read_lines(memory_manager, "core/error.log")[0])["msg"] == "boom"


def test_default_min_level_writes_all_three_streams_as_today(memory_manager):
    """Unset/default (INFO) is identical to the original behaviour."""
    router = VbwdLogRouter(filesystem_manager=memory_manager)

    router.emit(_make_record("vbwd.x", logging.INFO, "i"))
    router.emit(_make_record("vbwd.x", logging.WARNING, "w"))
    router.emit(_make_record("vbwd.x", logging.ERROR, "e"))

    assert memory_manager.exists("logs", "core/info.log")
    assert memory_manager.exists("logs", "core/warnings.log")
    assert memory_manager.exists("logs", "core/error.log")


def test_parse_log_level_maps_names_and_falls_back_on_garbage():
    assert parse_log_level("warning") == logging.WARNING
    assert parse_log_level("ERROR") == logging.ERROR
    assert parse_log_level("debug") == logging.DEBUG
    assert parse_log_level("info") == logging.INFO
    # An invalid value never crashes — it falls back to INFO (today's default).
    assert parse_log_level("loud") == logging.INFO
    assert parse_log_level("") == logging.INFO
    assert parse_log_level(None) == logging.INFO


def test_event_stream_is_exempt_from_the_min_level_floor(local_manager):
    """events.log is a security/audit record, NOT app verbosity — it must be
    written even when the app-log floor is at error."""
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=local_manager).register(bus)
    # The router floor is irrelevant to the subscriber path, but assert the
    # two are independent by configuring the strictest floor alongside.
    VbwdLogRouter(
        filesystem_manager=local_manager,
        config=LoggingConfig(min_level=logging.ERROR),
    )
    bus.publish("contact.submitted", {"email": "a@b.c"})

    assert local_manager.exists("logs", "core/events.log")


# ---------------------------------------------------------------------------
# Per-scope allowlist folding
# ---------------------------------------------------------------------------


def test_plugin_warning_folds_to_core_warnings_keeping_scope(memory_manager):
    """A plugin WARNING is not in the plugin allowlist -> core/warnings.log,
    but the JSON line still carries scope=cms for attribution."""
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("plugins.cms.x", logging.WARNING, "deprecated"))

    assert not memory_manager.exists("logs", "cms/warnings.log")
    payload = json.loads(_read_lines(memory_manager, "core/warnings.log")[0])
    assert payload["scope"] == "cms"
    assert payload["logger"] == "plugins.cms.x"


def test_plugin_info_folds_to_core_info(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("plugins.booking.svc", logging.INFO, "booked"))

    assert not memory_manager.exists("logs", "booking/info.log")
    payload = json.loads(_read_lines(memory_manager, "core/info.log")[0])
    assert payload["scope"] == "booking"


def test_allowlist_is_configurable(memory_manager):
    """A config that grants a plugin the warnings stream keeps it in-scope."""
    config = LoggingConfig(scope_streams={"cms": {"error", "warnings"}})
    router = VbwdLogRouter(filesystem_manager=memory_manager, config=config)
    router.emit(_make_record("plugins.cms.x", logging.WARNING, "kept"))

    payload = json.loads(_read_lines(memory_manager, "cms/warnings.log")[0])
    assert payload["scope"] == "cms"


# ---------------------------------------------------------------------------
# JSON-line shape
# ---------------------------------------------------------------------------


def test_emitted_line_has_required_fields(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("vbwd.x", logging.ERROR, "hello %s", args=()))

    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    for field in ("ts", "level", "scope", "logger", "msg"):
        assert field in payload
    assert payload["level"] == "ERROR"


def test_record_extra_dict_is_merged(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(
        _make_record("vbwd.x", logging.INFO, "ctx", vbwd_extra={"order_id": 42})
    )
    payload = json.loads(_read_lines(memory_manager, "core/info.log")[0])
    assert payload["order_id"] == 42


# ---------------------------------------------------------------------------
# Exception traceback capture (Flask ``app.log_exception`` passes exc_info=True)
# ---------------------------------------------------------------------------


def test_exception_record_captures_traceback(memory_manager):
    """An ERROR record carrying ``exc_info`` (how Flask logs unhandled 500s)
    must persist the formatted stack — type + message — under ``traceback`` so
    the *.log files and /admin/logs are actually diagnosable, not just a
    one-liner ``Exception on ... [POST]``."""
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    try:
        raise ValueError("kaboom from the import path")
    except ValueError:
        import sys

        record = _make_record(
            "vbwd.routes.admin", logging.ERROR, "Exception on /import [POST]"
        )
        record.exc_info = sys.exc_info()

    router.emit(record)

    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    assert "traceback" in payload
    traceback_text = payload["traceback"]
    assert "ValueError" in traceback_text
    assert "kaboom from the import path" in traceback_text
    assert "Traceback (most recent call last)" in traceback_text


def test_exception_traceback_survives_cached_exc_text(memory_manager):
    """A record whose ``exc_text`` was already formatted (by an earlier handler)
    is reused verbatim — mirrors stdlib caching, no double formatting."""
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    record = _make_record("vbwd.x", logging.ERROR, "boom")
    record.exc_text = "ValueError: pre-formatted stack"

    router.emit(record)

    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    assert payload["traceback"] == "ValueError: pre-formatted stack"


def test_normal_record_has_no_traceback_field(memory_manager):
    """No regression: a record WITHOUT ``exc_info`` never gains a traceback."""
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(_make_record("vbwd.x", logging.ERROR, "plain error line"))

    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    assert "traceback" not in payload


# ---------------------------------------------------------------------------
# Event audit stream
# ---------------------------------------------------------------------------


def test_event_publish_appends_to_core_events_log(memory_manager):
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=memory_manager).register(bus)

    bus.publish("contact_form.received", {"email": "a@b.de", "message": "hi"})

    lines = _read_lines(memory_manager, "core/events.log")
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "contact_form.received"
    assert payload["payload"]["email"] == "a@b.de"
    assert "ts" in payload


def test_namespaced_event_is_attributed_to_plugin_events_log(memory_manager):
    """When the event name is namespaced ``plugins.<id>.…`` the subscriber also
    writes the plugin's own events.log (the only reliable origin signal)."""
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=memory_manager).register(bus)

    bus.publish("plugins.cms.page_published", {"slug": "home"})

    assert (
        json.loads(_read_lines(memory_manager, "core/events.log")[0])["event"]
        == "plugins.cms.page_published"
    )
    plugin_line = json.loads(_read_lines(memory_manager, "cms/events.log")[0])
    assert plugin_line["event"] == "plugins.cms.page_published"


def test_event_with_explicit_origin_key_is_attributed(memory_manager):
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=memory_manager).register(bus)

    bus.publish("payment.captured", {"_origin": "booking", "amount": 10})

    plugin_line = json.loads(_read_lines(memory_manager, "booking/events.log")[0])
    assert plugin_line["event"] == "payment.captured"


def test_non_attributable_event_stays_core_only(memory_manager):
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=memory_manager).register(bus)

    bus.publish("payment.captured", {"amount": 10})

    assert memory_manager.exists("logs", "core/events.log")
    # no plugin dir created for an un-attributable event
    assert not memory_manager.exists("logs", "booking/events.log")


# ---------------------------------------------------------------------------
# Redaction (Security #6)
# ---------------------------------------------------------------------------


def test_redact_masks_secret_keys_recursively():
    raw = {
        "user": "alice",
        "password": "hunter2",
        "Token": "abc",
        "nested": {"client_secret": "xyz", "ok": 1},
        "list": [{"api_key": "k"}, "plain"],
    }
    cleaned = redact(raw)
    assert cleaned["user"] == "alice"
    assert cleaned["password"] == "***"
    assert cleaned["Token"] == "***"
    assert cleaned["nested"]["client_secret"] == "***"
    assert cleaned["nested"]["ok"] == 1
    assert cleaned["list"][0]["api_key"] == "***"
    assert cleaned["list"][1] == "plain"
    # original untouched
    assert raw["password"] == "hunter2"


def test_event_payload_is_redacted_on_disk(memory_manager):
    bus = EventBus()
    EventLogSubscriber(filesystem_manager=memory_manager).register(bus)

    bus.publish("user.login", {"email": "a@b.de", "access_token": "secret-jwt"})

    raw_text = memory_manager.read_text("logs", "core/events.log")
    assert "secret-jwt" not in raw_text
    payload = json.loads(_read_lines(memory_manager, "core/events.log")[0])
    assert payload["payload"]["access_token"] == "***"
    assert payload["payload"]["email"] == "a@b.de"


def test_log_extra_is_redacted_on_disk(memory_manager):
    router = VbwdLogRouter(filesystem_manager=memory_manager)
    router.emit(
        _make_record(
            "vbwd.x", logging.ERROR, "failed", vbwd_extra={"smtp_password": "p@ss"}
        )
    )
    raw_text = memory_manager.read_text("logs", "core/error.log")
    assert "p@ss" not in raw_text
    payload = json.loads(_read_lines(memory_manager, "core/error.log")[0])
    assert payload["smtp_password"] == "***"


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_rotation_rolls_file_past_max_bytes(rotating_manager):
    config = LoggingConfig(max_bytes=300, backups=3)
    router = VbwdLogRouter(filesystem_manager=rotating_manager, config=config)

    for index in range(40):
        router.emit(_make_record("vbwd.x", logging.ERROR, f"line-{index}"))

    # Active file exists and the first rollover was created.
    assert rotating_manager.exists("logs", "core/error.log")
    assert rotating_manager.exists("logs", "core/error.log.1")
    # Active file is below max_bytes (a fresh segment after the last roll).
    active = rotating_manager.read_bytes("logs", "core/error.log")
    assert len(active) <= 300


def test_rotation_caps_backups(rotating_manager):
    config = LoggingConfig(max_bytes=200, backups=2)
    router = VbwdLogRouter(filesystem_manager=rotating_manager, config=config)

    for index in range(80):
        router.emit(_make_record("vbwd.x", logging.ERROR, f"entry-{index}"))

    assert rotating_manager.exists("logs", "core/error.log.1")
    assert rotating_manager.exists("logs", "core/error.log.2")
    # backups=2 -> .3 must never appear.
    assert not rotating_manager.exists("logs", "core/error.log.3")


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


def test_emit_never_propagates_underlying_error():
    class ExplodingManager:
        def append_text(self, *args, **kwargs):
            raise OSError("disk full")

        def append_with_rotation(self, *args, **kwargs):
            raise OSError("disk full")

        def resolve(self, *args, **kwargs):
            raise OSError("disk full")

    router = VbwdLogRouter(filesystem_manager=ExplodingManager())
    # Must not raise.
    router.emit(_make_record("vbwd.x", logging.ERROR, "boom"))


def test_subscriber_never_propagates_underlying_error():
    class ExplodingManager:
        def append_text(self, *args, **kwargs):
            raise OSError("disk full")

        def append_with_rotation(self, *args, **kwargs):
            raise OSError("disk full")

        def resolve(self, *args, **kwargs):
            raise OSError("disk full")

    bus = EventBus()
    EventLogSubscriber(filesystem_manager=ExplodingManager()).register(bus)
    # Bus already swallows subscriber exceptions, but the subscriber itself
    # must also be defensive.
    bus.publish("anything.happened", {"x": 1})
