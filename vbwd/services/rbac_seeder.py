"""Core RBAC default seeder — Sprint S38.

Idempotently syncs the permission catalog into ``vbwd_permission`` and
upserts the 2 default admin system roles (``super_admin``, ``admin``).
A regular account is identified by the ``UserRole.USER`` enum on the user
record, not a redundant ``user`` RBAC role (removed: it held no permissions
and only created ambiguity in the admin Access-Levels UI). Safe to
re-run on every deploy (ungated). Reads the plugin permission catalog via
the injected ``plugin_manager`` (DI) — core never imports a plugin module.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from vbwd.models.role import Role, Permission
from vbwd.services.permission_catalog import collect_permission_catalog


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


@dataclass(frozen=True)
class RbacSeedResult:
    """Counts of rows created during a seeder run (idempotent re-runs = 0)."""

    roles_created: int = 0
    roles_updated: int = 0
    permissions_created: int = 0


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


def seed_default_rbac(
    session, *, plugin_manager: Optional[object] = None
) -> RbacSeedResult:
    """Idempotently sync the permission catalog and upsert the 3 default roles.

    Steps:
        1. Collect the catalog (core + enabled plugins, via the shared
           collector) and upsert each permission by name.
        2. Upsert the 3 default system roles by slug — never overwriting a
           pre-existing non-system role of the same slug.

    Safe to re-run; a second run creates nothing new.
    """
    catalog = collect_permission_catalog(plugin_manager=plugin_manager)
    core_keys = [entry["key"] for entry in catalog["core"]]

    permissions_created = 0
    catalog_keys = _permission_keys_from_catalog(catalog)
    for name in [WILDCARD_PERMISSION, *catalog_keys]:
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

    session.commit()

    return RbacSeedResult(
        roles_created=roles_created,
        roles_updated=roles_updated,
        permissions_created=permissions_created,
    )
