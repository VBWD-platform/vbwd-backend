"""S17 meta-oracle — every core port service must ship a unit test.

Mirrors the [[s16]] meta pattern: a single test that fails with the
current backlog. Each entry in ``EXPECTED_GAPS`` is pruned as the
matching test file ships.

"Port services" = the agnosticism-port surfaces that plugins register
implementations against. They MUST have characterisation tests of:
  - null default behaviour (Liskov-safe when no plugin is registered),
  - register / resolve round-trip,
  - clear / reset (test teardown hook).
"""
import os


# Pruned as test files land. ``access_level_content_provider`` was
# tested as part of S01 — not on this backlog.
EXPECTED_GAPS: set[str] = set()
# All 7 port services now have tests (S17 worked example + S17 sweep
# completed 2026-05-27).

PORT_SERVICES = {
    "access_level_content_provider",
    "activity_logger",
    "deletion_dependency_registry",
    "demo_data_registry",
    "entitlement",
    "invoice_extra_fields_registry",
    # ``subscription_lifecycle`` removed in S50.4 — the lifecycle port was
    # deleted; payment↔subscription is now event-driven (payment plugins
    # publish domain-neutral facts, subscription subscribes). No core port.
}


def _backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _service_test_files() -> set[str]:
    test_dir = os.path.join(_backend_root(), "tests", "unit", "services")
    if not os.path.isdir(test_dir):
        return set()
    return {
        filename[len("test_") : -3]
        for filename in os.listdir(test_dir)
        if filename.startswith("test_") and filename.endswith(".py")
    }


def test_port_service_test_coverage_progress():
    tested = _service_test_files()
    actual_gap = PORT_SERVICES - tested
    unexpected_new = actual_gap - EXPECTED_GAPS
    closed_since = EXPECTED_GAPS - actual_gap
    assert not unexpected_new, (
        "Core port services without unit tests:\n  - "
        + "\n  - ".join(sorted(unexpected_new))
        + "\nWrite a test file under tests/unit/services/test_<service>.py or "
        "update EXPECTED_GAPS to acknowledge the deferral."
    )
    assert not closed_since, (
        "Tests have been written for port services still listed in "
        "EXPECTED_GAPS:\n  - "
        + "\n  - ".join(sorted(closed_since))
        + "\nPrune those entries from EXPECTED_GAPS."
    )
