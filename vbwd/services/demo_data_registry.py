"""Generic demo/test data extension registry.

Core seeders own core data (users, token bundles). Feature plugins
contribute their own catalog/test data through this registry, so core
never imports plugin models. With nothing registered (plugin disabled) the
hooks are no-ops — core seeds only core data, no error.
"""
from typing import Callable, List

# Each hook takes the active SQLAlchemy session.
SeedHook = Callable[[object], None]
TestDataHook = Callable[[object, object], None]  # (session, test_user)

_catalog_seeders: List[SeedHook] = []
_catalog_clearers: List[SeedHook] = []
_test_data_seeders: List[TestDataHook] = []
_test_data_cleaners: List[SeedHook] = []


def register_catalog_seeder(hook: SeedHook) -> None:
    _catalog_seeders.append(hook)


def register_catalog_clearer(hook: SeedHook) -> None:
    _catalog_clearers.append(hook)


def register_test_data_seeder(hook: TestDataHook) -> None:
    _test_data_seeders.append(hook)


def register_test_data_cleaner(hook: SeedHook) -> None:
    _test_data_cleaners.append(hook)


def clear_demo_data_hooks() -> None:
    """Reset all registrations (plugin disable / test teardown)."""
    _catalog_seeders.clear()
    _catalog_clearers.clear()
    _test_data_seeders.clear()
    _test_data_cleaners.clear()


def run_catalog_seeders(session) -> None:
    for hook in _catalog_seeders:
        hook(session)


def run_catalog_clearers(session) -> None:
    for hook in _catalog_clearers:
        hook(session)


def run_test_data_seeders(session, test_user) -> None:
    for hook in _test_data_seeders:
        hook(session, test_user)


def run_test_data_cleaners(session) -> None:
    for hook in _test_data_cleaners:
        hook(session)
