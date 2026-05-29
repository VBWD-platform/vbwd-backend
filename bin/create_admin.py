#!/usr/bin/env python
"""Create or promote a user to admin role.
Usage: python /app/bin/create_admin.py --email admin@example.com --password Secret123!
"""
import sys
import argparse

sys.path.insert(0, "/app")

import bcrypt

from vbwd.models.user import User
from vbwd.models.role import Role
from vbwd.models.enums import UserStatus, UserRole


SUPER_ADMIN_ROLE_SLUG = "super_admin"


def create_or_promote_admin(session, email, password, *, plugin_manager=None):
    """Ensure an active SUPER_ADMIN user exists and holds the granular role.

    Belt-and-suspenders during the RBAC transition: sets the coarse
    ``UserRole.SUPER_ADMIN`` enum AND assigns the seeded ``super_admin``
    granular role. If the default roles are absent (fresh box), seeds them
    first so the script is self-sufficient — it depends on the seeder, it
    does not own the roles.

    Returns the user.
    """
    from vbwd.repositories.role_repository import RoleRepository
    from vbwd.services.rbac_service import RBACService

    user = session.query(User).filter_by(email=email).first()
    if user:
        if user.role != UserRole.SUPER_ADMIN:
            user.role = UserRole.SUPER_ADMIN
        if user.status != UserStatus.ACTIVE:
            user.status = UserStatus.ACTIVE
    else:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(
            email=email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            role=UserRole.SUPER_ADMIN,
        )
        session.add(user)
    session.commit()

    # Self-heal: seed the default roles if missing, then assign super_admin.
    if not session.query(Role).filter_by(slug=SUPER_ADMIN_ROLE_SLUG).first():
        from vbwd.services.rbac_seeder import seed_default_rbac

        seed_default_rbac(session, plugin_manager=plugin_manager)

    rbac_service = RBACService(RoleRepository(session))
    rbac_service.assign_role(user.id, SUPER_ADMIN_ROLE_SLUG)

    return user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="admin@vbwd.local")
    parser.add_argument("--password", default="ChangeMe123!")
    args = parser.parse_args()

    from vbwd.extensions import Session

    session = Session()
    try:
        user = create_or_promote_admin(session, args.email, args.password)
        print(f"Admin ready: {user.email} (id={user.id}) -> SUPER_ADMIN / ACTIVE")
    except Exception as error:
        session.rollback()
        print(f"Error: {error}")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
