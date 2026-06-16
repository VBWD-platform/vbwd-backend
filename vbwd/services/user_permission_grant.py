"""Core write port for plan/add-on driven user permissions (S69).

Core owns RBAC (``UserAccessLevel`` / ``Role`` / ``Permission``); plugins must
not import those models. This module exposes one narrow write port,
``IUserPermissionGrant``, that the subscription plugin resolves to grant/revoke
the permissions a plan or add-on declares. The default implementation delegates
to the existing ``UserAccessLevelService`` / ``RBACService`` / repositories — it
adds no new data access of its own beyond find-or-create of the managed entity.

Registry mirrors ``vbwd.services.entitlement`` exactly: a module global plus
``register_*`` / ``clear_*`` / ``resolve_*`` helpers. ``resolve_*`` returns a
default instance when none is registered, so callers never branch on wiring.

D4 security guardrail (mirrors S51 D3's three layers):
  1. ``allow_plan_special_permissions`` core setting (default ``False``) gates the
     entire admin-track *role* path — when off, ``ensure_role`` / ``assign_role``
     are no-ops.
  2. Even when on, the wildcard ``*`` and a deny-list of dangerous permissions
     are stripped at sync time so a plan config can never escalate to super-admin.
  3. The user-facing *access-level* path (``permissions_enable``) is never gated.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence
from uuid import UUID, uuid4

from flask import current_app

logger = logging.getLogger(__name__)

# D4 layer 2: permissions that must never be granted via plan/add-on config,
# even when ``allow_plan_special_permissions`` is on. ``settings.system`` is the
# core super-admin lever; the wildcard ``*`` is handled separately (it is the
# super-admin grant itself). Kept as a small module constant (clean code: no
# magic strings scattered through the sync path).
WILDCARD_PERMISSION = "*"
DEFAULT_SPECIAL_PERMISSION_DENY_LIST = frozenset({"settings.system"})

# Core setting key for the D4 layer-1 flag.
ALLOW_PLAN_SPECIAL_PERMISSIONS_SETTING = "allow_plan_special_permissions"


class IUserPermissionGrant(ABC):
    """Narrow write port (ISP) — only the methods the consumer needs.

    ``ensure_*`` find-or-create a managed entity (slug-keyed, ``is_system``) and
    sync its permission set to ``permission_names`` (idempotent). ``assign_*`` /
    ``revoke_*`` are no-ops when the user is already in / out of the desired
    state.
    """

    @abstractmethod
    def ensure_user_access_level(
        self,
        slug: str,
        name: str,
        permission_names: Sequence[str],
        *,
        linked_plan_slug: Optional[str] = None,
    ) -> UUID:
        """Find-or-create the managed access level and sync its permissions.

        Returns the level id."""

    @abstractmethod
    def assign_level(self, user_id: UUID, level_id: UUID) -> None:
        """Assign the level to the user (no-op if already assigned)."""

    @abstractmethod
    def revoke_level(self, user_id: UUID, level_id: UUID) -> None:
        """Revoke the level from the user (no-op if not assigned)."""

    @abstractmethod
    def ensure_role(
        self, slug: str, name: str, permission_names: Sequence[str]
    ) -> Optional[UUID]:
        """Find-or-create the managed admin-track role and sync its permissions.

        Returns the role id, or ``None`` when the special-permission path is
        gated off (D4)."""

    @abstractmethod
    def assign_role(self, user_id: UUID, role_slug: str) -> None:
        """Assign the managed role to the user (no-op if gated off / already)."""

    @abstractmethod
    def revoke_role(self, user_id: UUID, role_slug: str) -> None:
        """Revoke the managed role from the user (no-op if not assigned)."""

    @abstractmethod
    def list_assigned_levels(self, user_id: UUID) -> dict:
        """Map slug -> level id for the access levels assigned to the user.

        The consumer needs this to revoke managed (``auto-*``) levels whose
        source is no longer active (reconcile diff)."""

    @abstractmethod
    def list_assigned_roles(self, user_id: UUID) -> dict:
        """Map slug -> role id for the roles assigned to the user (reconcile diff)."""


class DefaultUserPermissionGrant(IUserPermissionGrant):
    """Default impl backed by the existing core RBAC services / repositories."""

    def __init__(self, session=None):
        from vbwd.extensions import db

        self._session = session or db.session

    # ── access-level (user-facing) track — never gated (D4 layer 3) ──────────

    def ensure_user_access_level(
        self,
        slug: str,
        name: str,
        permission_names: Sequence[str],
        *,
        linked_plan_slug: Optional[str] = None,
    ) -> UUID:
        from vbwd.models.user_access_level import AccessLevel

        level = self._access_level_service().find_by_slug(slug)
        if level is None:
            level = AccessLevel(
                id=uuid4(),
                name=name,
                slug=slug,
                description=name,
                is_system=True,
                linked_plan_slug=linked_plan_slug,
            )
            self._session.add(level)
        else:
            # Keep the managed entity in lock-step with the source config.
            level.name = name
            level.linked_plan_slug = linked_plan_slug

        self._sync_permissions(level, permission_names)
        self._session.flush()
        return UUID(str(level.id))

    def assign_level(self, user_id: UUID, level_id: UUID) -> None:
        self._access_level_service().assign(user_id, level_id)

    def revoke_level(self, user_id: UUID, level_id: UUID) -> None:
        self._access_level_service().revoke(user_id, level_id)

    # ── role (admin) track — gated by D4 ─────────────────────────────────────

    def ensure_role(
        self, slug: str, name: str, permission_names: Sequence[str]
    ) -> Optional[UUID]:
        if not self._allow_plan_special_permissions():
            logger.info(
                "[permission-grant] special permissions disabled — "
                "skipping managed role '%s' (set %s=true to enable)",
                slug,
                ALLOW_PLAN_SPECIAL_PERMISSIONS_SETTING,
            )
            return None

        safe_permission_names = self._clamp_special_permissions(permission_names)
        return self._ensure_role_row(slug, name, safe_permission_names)

    def assign_role(self, user_id: UUID, role_slug: str) -> None:
        if not self._allow_plan_special_permissions():
            logger.info(
                "[permission-grant] special permissions disabled — "
                "skipping role assignment '%s'",
                role_slug,
            )
            return
        self._assign_role_row(user_id, role_slug)

    def revoke_role(self, user_id: UUID, role_slug: str) -> None:
        self._rbac_service().revoke_role(user_id, role_slug)

    # ── reconcile read helpers ───────────────────────────────────────────────

    def list_assigned_levels(self, user_id: UUID) -> dict:
        return {
            level.slug: UUID(str(level.id))
            for level in self._access_level_service().get_user_levels(user_id)
        }

    def list_assigned_roles(self, user_id: UUID) -> dict:
        return {
            role.slug: UUID(str(role.id))
            for role in self._role_repository().get_user_roles(user_id)
        }

    # ── D4 helpers ───────────────────────────────────────────────────────────

    def _allow_plan_special_permissions(self) -> bool:
        try:
            return bool(
                current_app.config.get(ALLOW_PLAN_SPECIAL_PERMISSIONS_SETTING, False)
            )
        except RuntimeError:
            # No app context — be safe and refuse special permissions (D4).
            return False

    def _clamp_special_permissions(self, permission_names: Sequence[str]) -> List[str]:
        """Strip the wildcard + deny-listed permissions (D4 layer 2)."""
        clamped: List[str] = []
        for permission_name in permission_names:
            if permission_name == WILDCARD_PERMISSION:
                logger.warning(
                    "[permission-grant] refusing wildcard permission in special set"
                )
                continue
            if permission_name in DEFAULT_SPECIAL_PERMISSION_DENY_LIST:
                logger.warning(
                    "[permission-grant] refusing deny-listed permission '%s'",
                    permission_name,
                )
                continue
            clamped.append(permission_name)
        return clamped

    # ── role row helpers (find-or-create + sync) ─────────────────────────────

    def _ensure_role_row(
        self, slug: str, name: str, permission_names: Sequence[str]
    ) -> UUID:
        from vbwd.models.role import Role

        role = self._role_repository().find_by_name(slug)
        if role is None:
            role = Role(
                id=uuid4(),
                name=slug,
                slug=slug,
                description=name,
                is_system=True,
            )
            self._session.add(role)
        else:
            role.description = name

        self._sync_permissions(role, permission_names)
        self._session.flush()
        return UUID(str(role.id))

    def _assign_role_row(self, user_id: UUID, role_slug: str) -> None:
        self._rbac_service().assign_role(user_id, role_slug)

    # ── shared permission sync ───────────────────────────────────────────────

    def _sync_permissions(self, entity, permission_names: Sequence[str]) -> None:
        """Replace ``entity.permissions`` with the rows for ``permission_names``.

        Adds missing, removes extra (D2 "synced"). Unknown ids are skipped via
        ``_resolve_permission_rows``.
        """
        entity.permissions = self._resolve_permission_rows(permission_names)

    def _resolve_permission_rows(self, permission_names: Sequence[str]) -> list:
        """Resolve dotted permission ids to existing ``Permission`` rows.

        Unknown ids are skipped with a logged warning — never auto-created
        (the catalog/seeder owns Permission creation).
        """
        rows = []
        for permission_name in permission_names:
            permission = self._permission_repository().find_by_name(permission_name)
            if permission is None:
                logger.warning(
                    "[permission-grant] unknown permission id '%s' — skipped",
                    permission_name,
                )
                continue
            rows.append(permission)
        return rows

    # ── lazily-built collaborators (DI through the session) ──────────────────

    def _access_level_service(self):
        from vbwd.services.user_access_level_service import UserAccessLevelService

        return UserAccessLevelService(session=self._session)

    def _rbac_service(self):
        from vbwd.services.rbac_service import RBACService

        return RBACService(self._role_repository())

    def _role_repository(self):
        if not hasattr(self, "_role_repository_instance"):
            from vbwd.repositories.role_repository import RoleRepository

            self._role_repository_instance = RoleRepository(self._session)
        return self._role_repository_instance

    def _permission_repository(self):
        if not hasattr(self, "_permission_repository_instance"):
            from vbwd.repositories.role_repository import PermissionRepository

            self._permission_repository_instance = PermissionRepository(self._session)
        return self._permission_repository_instance


_grant: Optional[IUserPermissionGrant] = None


def register_user_permission_grant(grant: IUserPermissionGrant) -> None:
    """Register a custom grant impl (composition root / tests)."""
    global _grant
    _grant = grant


def clear_user_permission_grant() -> None:
    """Reset to the default (test teardown)."""
    global _grant
    _grant = None


def resolve_user_permission_grant() -> IUserPermissionGrant:
    """The registered grant, or a fresh default when none is registered."""
    return _grant if _grant is not None else DefaultUserPermissionGrant()
