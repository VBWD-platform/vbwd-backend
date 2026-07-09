"""Core RBAC default seeder — Sprint S38.

Idempotently syncs the permission catalog into ``vbwd_permission`` and
upserts the 2 default admin system roles (``super_admin``, ``admin``).
A regular account is identified by the ``UserRole.USER`` enum on the user
record, not a redundant ``user`` RBAC role (removed: it held no permissions
and only created ambiguity in the admin Access-Levels UI). Safe to
re-run on every deploy (ungated). Reads the plugin permission catalog via
the injected ``plugin_manager`` (DI) — core never imports a plugin module.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from vbwd.models.role import Role, Permission
from vbwd.models.user_access_level import AccessLevel
from vbwd.services.permission_catalog import (
    collect_permission_catalog,
    collect_user_permission_catalog,
)

logger = logging.getLogger(__name__)

WILDCARD_PERMISSION = "*"

# The 2 default ADMIN system roles. Each maps a slug to (name, description).
# Name == slug so role lookups by name (the existing RBACService convention,
# e.g. assign_role / user_has_role) resolve. Permission assignment is resolved
# below so it stays in lock-step with the live catalog. A regular account is
# identified by the UserRole.USER enum on the user record — there is no
# redundant "user" RBAC role (it held no permissions and only created ambiguity
# in the admin Access-Levels UI).
DEFAULT_ROLES = (
    ("super_admin", "super_admin", "Full system access (all permissions)."),
    ("admin", "admin", "Administrative access to all core features."),
)


# The default fe-user access levels (permission tiers). These are foundational
# data seeded on EVERY install — not only when demo data runs — so a fresh
# instance always has the tiers the fe-user app and the plugins expect. Their
# permission keys reference plugin surfaces that do NOT exist on a core-only
# install; seeding resolves them leniently (attach what exists, skip the rest)
# and NEVER creates them. Level seeding is create-only: an existing slug is left
# completely untouched.
#
# The level DEFINITIONS live in a shipped JSON data file, not as Python literals
# — those permission keys are plugin domain vocabulary that core CODE must not
# name (the S50 core-agnosticism oracle scans .py only, so the data belongs in a
# data file, exactly like the email templates and settings JSON). An operator
# can override the shipped defaults with a var/ JSON (see
# ``resolve_user_access_levels``), mirroring ``core_rate_limits_store``.
_DEFAULT_LEVELS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "default_user_access_levels.json",
)

# The operator override lives at ``${VBWD_VAR_DIR}/core/user_access_levels.json``
# (host-mounted, tunable without an image rebuild).
_CORE_NAMESPACE = "core"
_USER_ACCESS_LEVELS_FILE = "user_access_levels.json"


def _load_default_user_access_levels() -> Tuple[Dict[str, Any], ...]:
    """Load the shipped default access levels from the bundled JSON data file."""
    with open(_DEFAULT_LEVELS_FILE, encoding="utf-8") as handle:
        return tuple(json.load(handle))


DEFAULT_USER_ACCESS_LEVELS: Tuple[
    Dict[str, Any], ...
] = _load_default_user_access_levels()


def resolve_user_access_levels() -> Tuple[Dict[str, Any], ...]:
    """Return the access levels to seed: operator override if present, else defaults.

    A deployment may drop a JSON array at
    ``${VBWD_VAR_DIR}/core/user_access_levels.json`` to replace the shipped
    defaults (tuning without an image rebuild). A missing / corrupt / non-list
    file degrades to the shipped defaults (logged) and never raises.
    """
    from vbwd.services.filesystem import LocalFilesystemManager

    loaded = LocalFilesystemManager().read_json(
        _CORE_NAMESPACE, _USER_ACCESS_LEVELS_FILE, default=None
    )
    if isinstance(loaded, list) and loaded:
        return tuple(loaded)
    if loaded is not None:
        logger.warning(
            "Core user-access-levels override %s/%s is not a non-empty JSON list; "
            "using shipped defaults.",
            _CORE_NAMESPACE,
            _USER_ACCESS_LEVELS_FILE,
        )
    return DEFAULT_USER_ACCESS_LEVELS


@dataclass(frozen=True)
class RbacSeedResult:
    """Counts of rows created during a seeder run (idempotent re-runs = 0)."""

    roles_created: int = 0
    roles_updated: int = 0
    permissions_created: int = 0
    user_access_levels_created: int = 0


def _permission_keys_from_catalog(catalog: dict) -> list:
    """Flatten the catalog into an ordered, de-duplicated list of keys.

    Fails fast on a malformed entry (missing ``key``) so a broken plugin
    catalog surfaces immediately instead of silently dropping permissions.
    """
    keys: list = []
    seen = set()
    for source, entries in catalog.items():
        for entry in entries:
            if "key" not in entry:
                raise ValueError(
                    f"Malformed permission entry in '{source}': missing 'key' ({entry!r})"
                )
            key = entry["key"]
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _upsert_permission(session, name: str) -> bool:
    """Ensure a Permission row exists for ``name``. Returns True if created."""
    existing = session.query(Permission).filter_by(name=name).first()
    if existing:
        return False

    parts = name.rsplit(".", 1)
    permission = Permission(
        id=uuid4(),
        name=name,
        resource=parts[0] if len(parts) > 1 else name,
        action=parts[1] if len(parts) > 1 else WILDCARD_PERMISSION,
        description=name,
    )
    session.add(permission)
    session.flush()
    return True


def _permissions_for_role(slug: str, core_keys: list) -> list:
    """Resolve the permission name list for a default role slug."""
    if slug == "super_admin":
        return [WILDCARD_PERMISSION]
    if slug == "admin":
        return list(core_keys)
    return []


def _resolve_existing_permissions(session, permission_keys: list) -> list:
    """Return the Permission rows that already exist for ``permission_keys``.

    Lenient by design (S-RBAC): a default access level references plugin
    permission keys that do NOT exist on a core-only install. We attach the
    ones that DO exist and silently skip the rest — never creating a row and
    never raising (``.first()``, not ``.one()``), so a core-only install can
    seed cleanly.
    """
    resolved = []
    for key in permission_keys:
        permission = session.query(Permission).filter_by(name=key).first()
        if permission is not None:
            resolved.append(permission)
    return resolved


def _seed_user_access_levels(session) -> int:
    """Create the default user access levels. Returns the count created.

    Create-only / prod-safe: an existing level (matched by slug) is left
    completely untouched — its permission grants are never cleared or
    reassigned. New levels are ``is_system=True`` and get only the subset of
    permissions that already exist (see :func:`_resolve_existing_permissions`).
    """
    levels_created = 0
    for level_data in resolve_user_access_levels():
        slug = level_data["slug"]
        existing = session.query(AccessLevel).filter_by(slug=slug).first()
        if existing is not None:
            continue

        level = AccessLevel(
            id=uuid4(),
            name=level_data.get("name") or slug,
            slug=slug,
            description=level_data.get("description"),
            is_system=True,
            linked_plan_slug=level_data.get("linked_plan_slug"),
        )
        session.add(level)
        # Attach only the permissions that already exist (lenient), mutating the
        # relationship collection in place rather than reassigning it.
        level.permissions.extend(
            _resolve_existing_permissions(session, level_data.get("permissions") or [])
        )
        session.flush()
        levels_created += 1
    return levels_created


def seed_default_rbac(
    session, *, plugin_manager: Optional[object] = None
) -> RbacSeedResult:
    """Idempotently sync the permission catalog, roles, and user access levels.

    Steps:
        1. Collect the catalog (core + enabled plugins, via the shared
           collector) and upsert each permission by name.
        2. Upsert the 2 default system roles by slug — never overwriting a
           pre-existing non-system role of the same slug.
        3. Create the default user access levels (create-only: an existing
           slug is left untouched), attaching only the permissions that exist.

    Safe to re-run; a second run creates nothing new.
    """
    catalog = collect_permission_catalog(plugin_manager=plugin_manager)
    core_keys = [entry["key"] for entry in catalog["core"]]

    # User-facing permissions (core ``CORE_USER_PERMISSIONS`` — e.g.
    # ``manage_api`` — PLUS every enabled plugin's ``user_permissions``, e.g.
    # subscription's ``user.profile.view``) need Permission rows so the default
    # access levels' grants resolve (and an admin can assign them). They are NOT
    # admin permissions, so they stay out of ``core_keys`` (the ``admin`` role's
    # set). Read via the shared collector (DRY) — core stays agnostic.
    user_catalog = collect_user_permission_catalog(plugin_manager=plugin_manager)
    user_permission_keys = _permission_keys_from_catalog(user_catalog)

    permissions_created = 0
    catalog_keys = _permission_keys_from_catalog(catalog)
    for name in [WILDCARD_PERMISSION, *catalog_keys, *user_permission_keys]:
        if _upsert_permission(session, name):
            permissions_created += 1

    roles_created = 0
    roles_updated = 0
    for slug, name, description in DEFAULT_ROLES:
        existing = session.query(Role).filter_by(slug=slug).first()
        if existing and not existing.is_system:
            # Never clobber an operator's hand-made role of the same slug.
            continue

        permission_names = _permissions_for_role(slug, core_keys)
        permissions = [
            session.query(Permission).filter_by(name=permission_name).one()
            for permission_name in permission_names
        ]

        if existing:
            existing.name = name
            existing.description = description
            existing.permissions = permissions
            roles_updated += 1
        else:
            session.add(
                Role(
                    id=uuid4(),
                    name=name,
                    slug=slug,
                    description=description,
                    is_system=True,
                    permissions=permissions,
                )
            )
            roles_created += 1

    user_access_levels_created = _seed_user_access_levels(session)

    session.commit()

    return RbacSeedResult(
        roles_created=roles_created,
        roles_updated=roles_updated,
        permissions_created=permissions_created,
        user_access_levels_created=user_access_levels_created,
    )
