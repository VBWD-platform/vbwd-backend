"""Unit tests for the S73 core write port ``IUserGroupMembership``.

Covers the module-level registry (mirrors ``IUserPermissionGrant``) and the
idempotency / unknown-slug-skip logic that does not require a real DB. The
stateful add/remove/set behaviour against real rows is covered by the
subscription plugin integration tests (which have a real ``db`` fixture).
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.user_group_membership import (
    DefaultUserGroupMembership,
    IUserGroupMembership,
    clear_user_group_membership,
    register_user_group_membership,
    resolve_user_group_membership,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_user_group_membership()
    yield
    clear_user_group_membership()


class TestRegistry:
    def test_resolve_returns_default_when_none_registered(self):
        membership = resolve_user_group_membership()
        assert isinstance(membership, DefaultUserGroupMembership)

    def test_resolve_returns_registered_impl(self):
        custom = MagicMock(spec=IUserGroupMembership)
        register_user_group_membership(custom)
        assert resolve_user_group_membership() is custom

    def test_clear_resets_to_default(self):
        register_user_group_membership(MagicMock(spec=IUserGroupMembership))
        clear_user_group_membership()
        assert isinstance(resolve_user_group_membership(), DefaultUserGroupMembership)


class TestIdempotency:
    """add/remove/set are idempotent and slug-keyed (no DB needed)."""

    def _membership(self):
        return DefaultUserGroupMembership(session=MagicMock())

    def test_add_is_noop_when_already_member(self, monkeypatch):
        membership = self._membership()
        monkeypatch.setattr(
            membership, "list_user_group_slugs", lambda user_id: {"vip"}
        )
        executed = MagicMock()
        membership._session.execute = executed

        membership.add(uuid4(), "vip")

        executed.assert_not_called()

    def test_add_skips_unknown_slug(self, monkeypatch):
        membership = self._membership()
        monkeypatch.setattr(membership, "list_user_group_slugs", lambda user_id: set())
        monkeypatch.setattr(membership, "_known_group_slugs", lambda: {"vip"})
        executed = MagicMock()
        membership._session.execute = executed

        membership.add(uuid4(), "ghost")

        executed.assert_not_called()

    def test_set_user_groups_diffs_current_against_desired(self, monkeypatch):
        membership = self._membership()
        user_id = uuid4()
        monkeypatch.setattr(
            membership, "list_user_group_slugs", lambda uid: {"trial", "old"}
        )
        added: list = []
        removed: list = []
        monkeypatch.setattr(membership, "add", lambda uid, slug: added.append(slug))
        monkeypatch.setattr(
            membership, "remove", lambda uid, slug: removed.append(slug)
        )

        membership.set_user_groups(user_id, ["trial", "vip"])

        assert added == ["vip"]
        assert removed == ["old"]
