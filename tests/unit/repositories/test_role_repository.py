"""S16 — RoleRepository + PermissionRepository contract tests."""
from unittest.mock import MagicMock

import pytest

from vbwd.models import Permission, Role
from vbwd.repositories.role_repository import PermissionRepository, RoleRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def role_repo(session):
    return RoleRepository(session)


@pytest.fixture
def permission_repo(session):
    return PermissionRepository(session)


def test_role_find_by_name_returns_first(session, role_repo):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert role_repo.find_by_name("admin") is sentinel
    session.query.assert_called_with(Role)


def test_role_find_by_name_returns_none_when_absent(session, role_repo):
    session.query.return_value.filter.return_value.first.return_value = None
    assert role_repo.find_by_name("nope") is None


def test_permission_find_by_name(session, permission_repo):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert permission_repo.find_by_name("users.manage") is sentinel
    session.query.assert_called_with(Permission)


def test_permission_find_by_resource_returns_list(session, permission_repo):
    session.query.return_value.filter.return_value.all.return_value = ["p1", "p2"]
    assert permission_repo.find_by_resource("users") == ["p1", "p2"]
