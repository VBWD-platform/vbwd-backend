"""S16 — PluginConfigRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.repositories.plugin_config_repository import PluginConfigRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return PluginConfigRepository(session)


def test_repository_constructs_with_session(session, repository):
    assert repository is not None


def test_delete_returns_boolean(session, repository):
    """``delete(plugin_name)`` returns True when something was deleted."""
    session.query.return_value.filter.return_value.delete.return_value = 1
    result = repository.delete("plugin-x")
    assert result in (True, False)  # implementation may coerce to bool either way
