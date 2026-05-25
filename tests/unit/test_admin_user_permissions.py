"""Admins implicitly hold all user-facing permissions.

Regression guard: a SUPER_ADMIN (or ADMIN with no user access level) logging
into the fe-user app must receive `["*"]` so the permission-gated nav routes
(plans / add-ons / invoices / tokens / subscription) are navigable. Without
this they get an empty `user_permissions` and every route silently bounces
back to the dashboard ("nothing happens on click").
"""
from vbwd.models.user import User
from vbwd.models.enums import UserRole


def _user(role: UserRole) -> User:
    return User(email="x@example.com", password_hash="x", role=role)


def test_super_admin_user_permissions_is_wildcard():
    user = _user(UserRole.SUPER_ADMIN)
    assert user.effective_user_permissions == ["*"]
    assert user.has_user_permission("subscription.plans.view") is True


def test_admin_without_user_access_levels_is_wildcard():
    user = _user(UserRole.ADMIN)
    assert user.effective_user_permissions == ["*"]
    assert user.has_user_permission("subscription.invoices.view") is True


def test_plain_user_without_access_levels_has_none():
    user = _user(UserRole.USER)
    assert user.effective_user_permissions == []
    assert user.has_user_permission("subscription.plans.view") is False
