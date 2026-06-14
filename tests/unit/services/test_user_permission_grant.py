"""Unit tests for the S69 core write port ``IUserPermissionGrant``.

These cover the logic that does not require real ORM relationship behaviour:
the D4 security guardrail (``allow_plan_special_permissions`` flag + deny-list),
the skip-unknown-permission rule, and the module-level registry. The stateful
ensure/sync/assign/revoke behaviour against real rows is covered by the
subscription plugin integration tests (which have a real ``db`` fixture).
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.user_permission_grant import (
    DEFAULT_SPECIAL_PERMISSION_DENY_LIST,
    DefaultUserPermissionGrant,
    IUserPermissionGrant,
    clear_user_permission_grant,
    register_user_permission_grant,
    resolve_user_permission_grant,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_user_permission_grant()
    yield
    clear_user_permission_grant()


class TestRegistry:
    def test_resolve_returns_default_when_none_registered(self):
        grant = resolve_user_permission_grant()
        assert isinstance(grant, DefaultUserPermissionGrant)

    def test_resolve_returns_registered_provider(self):
        custom = MagicMock(spec=IUserPermissionGrant)
        register_user_permission_grant(custom)
        assert resolve_user_permission_grant() is custom

    def test_clear_resets_to_default(self):
        register_user_permission_grant(MagicMock(spec=IUserPermissionGrant))
        clear_user_permission_grant()
        assert isinstance(resolve_user_permission_grant(), DefaultUserPermissionGrant)


class TestSpecialPermissionGuardrail:
    """D4 — the special (admin-track) role path is gated and clamped."""

    def _grant_with_flag(self, allow_special, monkeypatch):
        grant = DefaultUserPermissionGrant(session=MagicMock())
        monkeypatch.setattr(
            grant, "_allow_plan_special_permissions", lambda: allow_special
        )
        return grant

    def test_ensure_role_is_noop_when_flag_off(self, monkeypatch):
        grant = self._grant_with_flag(False, monkeypatch)
        ensure_called = MagicMock()
        monkeypatch.setattr(grant, "_ensure_role_row", ensure_called)

        result = grant.ensure_role("auto-plan-x", "Auto x", ["analytics.view"])

        assert result is None
        ensure_called.assert_not_called()

    def test_assign_role_is_noop_when_flag_off(self, monkeypatch):
        grant = self._grant_with_flag(False, monkeypatch)
        assign_called = MagicMock()
        monkeypatch.setattr(grant, "_assign_role_row", assign_called)

        grant.assign_role(uuid4(), "auto-plan-x")

        assign_called.assert_not_called()

    def test_wildcard_rejected_when_flag_on(self, monkeypatch):
        grant = self._grant_with_flag(True, monkeypatch)
        captured = {}
        monkeypatch.setattr(
            grant,
            "_ensure_role_row",
            lambda slug, name, permission_names: captured.update(
                names=permission_names
            ),
        )

        grant.ensure_role("auto-plan-x", "Auto x", ["*", "analytics.view"])

        assert "*" not in captured["names"]
        assert "analytics.view" in captured["names"]

    def test_deny_listed_permission_rejected_when_flag_on(self, monkeypatch):
        grant = self._grant_with_flag(True, monkeypatch)
        captured = {}
        monkeypatch.setattr(
            grant,
            "_ensure_role_row",
            lambda slug, name, permission_names: captured.update(
                names=permission_names
            ),
        )

        grant.ensure_role(
            "auto-plan-x", "Auto x", ["settings.system", "analytics.view"]
        )

        assert "settings.system" not in captured["names"]
        assert "analytics.view" in captured["names"]

    def test_settings_system_is_in_default_deny_list(self):
        assert "settings.system" in DEFAULT_SPECIAL_PERMISSION_DENY_LIST


class TestUnknownPermissionSkipped:
    """Unknown permission ids are skipped (no Permission row), never created."""

    def test_resolve_permission_rows_skips_unknown(self):
        session = MagicMock()

        def _find_by_name(name):
            if name == "analytics.view":
                known = MagicMock()
                known.name = "analytics.view"
                return known
            return None

        grant = DefaultUserPermissionGrant(session=session)
        # Permission lookup goes through the repository; patch the accessor.
        repository = MagicMock()
        repository.find_by_name.side_effect = _find_by_name
        grant._permission_repository = lambda: repository

        rows = grant._resolve_permission_rows(["analytics.view", "does.not.exist"])

        resolved_names = [row.name for row in rows]
        assert resolved_names == ["analytics.view"]
