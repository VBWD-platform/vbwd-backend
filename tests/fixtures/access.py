"""Shared test utilities for access control tests."""
from unittest.mock import MagicMock
from vbwd.models.enums import UserRole


def make_user_with_permissions(*permissions):
    """Create a mock user with specific RBAC permissions."""
    user = MagicMock()
    user.role = UserRole.USER
    user.status.value = "ACTIVE"

    role = MagicMock()
    role.is_admin = True
    perms = []
    for perm_name in permissions:
        p = MagicMock()
        p.name = perm_name
        perms.append(p)
    role.permissions = perms

    from vbwd.models.role import Role

    role.has_permission = lambda pn, r=role: Role.has_permission(r, pn)
    user.assigned_roles = [role]
    user.is_admin = True

    # Bind internal methods so User.has_permission works on the mock
    from vbwd.models.user import User

    user._get_access_levels = lambda: User._get_access_levels(user)
    user.has_permission = lambda pn: User.has_permission(user, pn)
    user.effective_permissions = [p for p in permissions]
    return user


def make_user_no_permissions():
    """Create a mock user with no permissions (regular user)."""
    user = MagicMock()
    user.role = UserRole.USER
    user.status.value = "ACTIVE"
    user.assigned_roles = []
    user.is_admin = False
    user.has_permission = lambda pn: False
    user.effective_permissions = []
    return user


def make_admin_user():
    """Create a mock legacy admin user (no RBAC roles, uses enum fallback)."""
    user = MagicMock()
    user.role = UserRole.ADMIN
    user.status.value = "ACTIVE"
    user.assigned_roles = []
    user.is_admin = True

    from vbwd.models.user import User

    user._get_access_levels = lambda: User._get_access_levels(user)
    user.has_permission = lambda pn: User.has_permission(user, pn)
    return user


def assert_forbidden(response, required_permission):
    """Assert 403 with correct error body."""
    assert response.status_code == 403, f"Expected 403 but got {response.status_code}"
    data = response.get_json()
    assert data["error"] == "Permission denied"
    assert data["required"] == required_permission
