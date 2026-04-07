"""Unit tests for RBAC permission system — Sprint 12a."""
from unittest.mock import MagicMock


class TestRoleHasPermission:
    """Test Role.has_permission with wildcard support."""

    def _make_role(self, permission_names):
        role = MagicMock()
        perms = []
        for name in permission_names:
            perm = MagicMock()
            perm.name = name
            perms.append(perm)
        role.permissions = perms

        # Use the real has_permission logic
        from vbwd.models.role import Role

        role.has_permission = lambda perm_name: Role.has_permission(role, perm_name)
        return role

    def test_exact_match(self):
        role = self._make_role(["shop.products.view"])
        assert role.has_permission("shop.products.view")

    def test_no_match(self):
        role = self._make_role(["shop.products.view"])
        assert not role.has_permission("shop.orders.view")

    def test_wildcard_all(self):
        role = self._make_role(["*"])
        assert role.has_permission("shop.products.view")
        assert role.has_permission("cms.pages.manage")
        assert role.has_permission("anything.at.all")

    def test_wildcard_plugin(self):
        role = self._make_role(["shop.*"])
        assert role.has_permission("shop.products.view")
        assert role.has_permission("shop.orders.manage")
        assert not role.has_permission("cms.pages.view")

    def test_empty_permissions(self):
        role = self._make_role([])
        assert not role.has_permission("anything")

    def test_multiple_permissions(self):
        role = self._make_role(["shop.products.view", "cms.pages.view"])
        assert role.has_permission("shop.products.view")
        assert role.has_permission("cms.pages.view")
        assert not role.has_permission("shop.orders.view")


class TestUserHasPermission:
    """Test User.has_permission with multi-role union."""

    def _make_user(self, roles_with_perms):
        from vbwd.models.enums import UserRole

        user = MagicMock()
        user.role = UserRole.USER

        assigned_roles = []
        for perm_names in roles_with_perms:
            role = MagicMock()
            perms = []
            for n in perm_names:
                perm = MagicMock()
                perm.name = n
                perms.append(perm)
            role.permissions = perms
            from vbwd.models.role import Role

            role.has_permission = lambda perm_name, r=role: Role.has_permission(
                r, perm_name
            )
            assigned_roles.append(role)

        user.assigned_roles = assigned_roles

        from vbwd.models.user import User

        user._get_access_levels = lambda: User._get_access_levels(user)
        user.has_permission = lambda perm: User.has_permission(user, perm)
        return user

    def test_single_role_match(self):
        user = self._make_user([["shop.products.view"]])
        assert user.has_permission("shop.products.view")

    def test_single_role_no_match(self):
        user = self._make_user([["shop.products.view"]])
        assert not user.has_permission("cms.pages.view")

    def test_multi_role_union(self):
        user = self._make_user(
            [
                ["shop.products.view"],
                ["cms.pages.view", "cms.pages.manage"],
            ]
        )
        assert user.has_permission("shop.products.view")
        assert user.has_permission("cms.pages.view")
        assert user.has_permission("cms.pages.manage")
        assert not user.has_permission("booking.resources.view")

    def test_super_admin_wildcard(self):
        user = self._make_user([["*"]])
        assert user.has_permission("anything")
        assert user.has_permission("shop.products.manage")

    def test_legacy_admin_fallback(self):
        """Legacy ADMIN users (no RBAC roles) get all permissions."""
        from vbwd.models.enums import UserRole
        from vbwd.models.user import User

        user = MagicMock()
        user.role = UserRole.ADMIN
        user.assigned_roles = []

        user._get_access_levels = lambda: User._get_access_levels(user)
        user.has_permission = lambda perm: User.has_permission(user, perm)
        assert user.has_permission("anything")
