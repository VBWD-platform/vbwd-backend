"""Admin access — a SUPER_ADMIN may delete system roles + user access levels.

System roles/levels (`is_system=True`, e.g. the default ``admin`` role) are
protected from deletion for ordinary admins, but a SUPER_ADMIN can remove them.
Mirrors the token-bundle delete-guard harness (mock auth → ``g.user``, real
test client + DB).
"""
from uuid import uuid4
from unittest.mock import patch

from vbwd.models.enums import UserRole
from tests.fixtures.access import make_user_with_permissions


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


def _actor(role):
    user = make_user_with_permissions("settings.system")
    user.role = role
    return user


def _make_system_role(app):
    from vbwd.extensions import db
    from vbwd.models.role import Role

    with app.app_context():
        role = Role(
            name=f"sysrole_{uuid4().hex[:8]}",
            slug=f"sysrole-{uuid4().hex[:8]}",
            description="temp system role",
            is_system=True,
        )
        db.session.add(role)
        db.session.commit()
        return str(role.id)


def _make_system_user_level(app):
    from vbwd.extensions import db
    from vbwd.models.user_access_level import UserAccessLevel

    with app.app_context():
        level = UserAccessLevel(
            name=f"syslvl_{uuid4().hex[:8]}",
            slug=f"syslvl-{uuid4().hex[:8]}",
            description="temp system level",
            is_system=True,
        )
        db.session.add(level)
        db.session.commit()
        return str(level.id)


def _cleanup(app, model_name, obj_id):
    from vbwd.extensions import db
    from vbwd.models.role import Role
    from vbwd.models.user_access_level import UserAccessLevel

    model = {"role": Role, "level": UserAccessLevel}[model_name]
    with app.app_context():
        obj = db.session.get(model, obj_id)
        if obj:
            db.session.delete(obj)
            db.session.commit()


# ── System ROLE deletion ──────────────────────────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_super_admin_can_delete_system_role(mock_repo_cls, mock_auth_cls, app, client):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor(UserRole.SUPER_ADMIN))
    role_id = _make_system_role(app)
    try:
        resp = client.delete(
            f"/api/v1/admin/access/roles/{role_id}", headers=_auth_headers()
        )
        assert resp.status_code == 200, resp.get_json()
        from vbwd.extensions import db
        from vbwd.models.role import Role

        with app.app_context():
            assert db.session.get(Role, role_id) is None
    finally:
        _cleanup(app, "role", role_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_admin_cannot_delete_system_role(mock_repo_cls, mock_auth_cls, app, client):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor(UserRole.ADMIN))
    role_id = _make_system_role(app)
    try:
        resp = client.delete(
            f"/api/v1/admin/access/roles/{role_id}", headers=_auth_headers()
        )
        assert resp.status_code == 400, resp.get_json()
        from vbwd.extensions import db
        from vbwd.models.role import Role

        with app.app_context():
            assert db.session.get(Role, role_id) is not None
    finally:
        _cleanup(app, "role", role_id)


# ── System USER ACCESS LEVEL deletion ─────────────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_super_admin_can_delete_system_user_level(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor(UserRole.SUPER_ADMIN))
    level_id = _make_system_user_level(app)
    try:
        resp = client.delete(
            f"/api/v1/admin/access/levels/{level_id}", headers=_auth_headers()
        )
        assert resp.status_code == 200, resp.get_json()
        from vbwd.extensions import db
        from vbwd.models.user_access_level import UserAccessLevel

        with app.app_context():
            assert db.session.get(UserAccessLevel, level_id) is None
    finally:
        _cleanup(app, "level", level_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_admin_cannot_delete_system_user_level(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor(UserRole.ADMIN))
    level_id = _make_system_user_level(app)
    try:
        resp = client.delete(
            f"/api/v1/admin/access/levels/{level_id}", headers=_auth_headers()
        )
        assert resp.status_code == 400, resp.get_json()
        from vbwd.extensions import db
        from vbwd.models.user_access_level import UserAccessLevel

        with app.app_context():
            assert db.session.get(UserAccessLevel, level_id) is not None
    finally:
        _cleanup(app, "level", level_id)
