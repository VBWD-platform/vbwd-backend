"""S17 — demo_data_registry contract tests.

Multi-list registry (catalog seeders, catalog clearers, test data seeders,
test data cleaners). Hooks run in registration order.
"""
from unittest.mock import MagicMock

import pytest

from vbwd.services.demo_data_registry import (
    clear_demo_data_hooks,
    register_catalog_clearer,
    register_catalog_seeder,
    register_test_data_cleaner,
    register_test_data_seeder,
    run_catalog_clearers,
    run_catalog_seeders,
    run_test_data_cleaners,
    run_test_data_seeders,
)


@pytest.fixture(autouse=True)
def _isolate():
    clear_demo_data_hooks()
    yield
    clear_demo_data_hooks()


@pytest.fixture
def session():
    return MagicMock()


def test_run_catalog_seeders_with_no_hooks_is_noop(session):
    run_catalog_seeders(session)  # must not raise


def test_register_catalog_seeder_then_run_invokes_it(session):
    hook = MagicMock()
    register_catalog_seeder(hook)
    run_catalog_seeders(session)
    hook.assert_called_once_with(session)


def test_register_catalog_clearer_then_run_invokes_it(session):
    hook = MagicMock()
    register_catalog_clearer(hook)
    run_catalog_clearers(session)
    hook.assert_called_once_with(session)


def test_register_test_data_seeder_then_run_invokes_it(session):
    """``run_test_data_seeders`` requires a session AND a test_user object."""
    hook = MagicMock()
    register_test_data_seeder(hook)
    test_user = MagicMock()
    run_test_data_seeders(session, test_user)
    hook.assert_called_once_with(session, test_user)


def test_register_test_data_cleaner_then_run_invokes_it(session):
    hook = MagicMock()
    register_test_data_cleaner(hook)
    run_test_data_cleaners(session)
    hook.assert_called_once_with(session)


def test_clear_demo_data_hooks_removes_all_lists(session):
    catalog_hook = MagicMock()
    clearer_hook = MagicMock()
    register_catalog_seeder(catalog_hook)
    register_catalog_clearer(clearer_hook)

    clear_demo_data_hooks()
    run_catalog_seeders(session)
    run_catalog_clearers(session)
    catalog_hook.assert_not_called()
    clearer_hook.assert_not_called()


def test_seeders_run_in_registration_order(session):
    call_order: list[str] = []
    register_catalog_seeder(lambda _session: call_order.append("first"))
    register_catalog_seeder(lambda _session: call_order.append("second"))
    register_catalog_seeder(lambda _session: call_order.append("third"))
    run_catalog_seeders(session)
    assert call_order == ["first", "second", "third"]
