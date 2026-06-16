"""S94 Slice 6a — admin/access terminology flip (DC-1).

After the flip:
  * ``/api/v1/admin/access/roles*``  manages **AdminRole** (System B).
  * ``/api/v1/admin/access/levels*`` manages **AccessLevel** (System C) —
    this path FLIPS meaning (it used to manage System B).
  * The vacated ``/api/v1/admin/access/user-levels*`` paths 308-redirect to
    the new ``/levels*`` paths for one release.

These tests pin the NEW behaviour (the prior inverted tests are updated
elsewhere in the same slice).
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


def _actor(role=UserRole.SUPER_ADMIN):
    user = make_user_with_permissions("settings.system")
    user.role = role
    return user


def _make_admin_role(app):
    from vbwd.extensions import db
    from vbwd.models.role import Role

    with app.app_context():
        role = Role(
            name=f"brole_{uuid4().hex[:8]}",
            slug=f"brole-{uuid4().hex[:8]}",
            description="temp admin role",
            is_system=False,
        )
        db.session.add(role)
        db.session.commit()
        return str(role.id)


def _make_access_level(app):
    from vbwd.extensions import db
    from vbwd.models import AccessLevel

    with app.app_context():
        level = AccessLevel(
            name=f"clvl_{uuid4().hex[:8]}",
            slug=f"clvl-{uuid4().hex[:8]}",
            description="temp access level",
            is_system=False,
        )
        db.session.add(level)
        db.session.commit()
        return str(level.id)


def _cleanup(app, model_name, obj_id):
    from vbwd.extensions import db
    from vbwd.models.role import Role
    from vbwd.models import AccessLevel

    model = {"role": Role, "level": AccessLevel}[model_name]
    with app.app_context():
        obj = db.session.get(model, obj_id)
        if obj:
            db.session.delete(obj)
            db.session.commit()


# ── System B (AdminRole) now lives at /roles ──────────────────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_roles_path_lists_admin_roles(mock_repo_cls, mock_auth_cls, app, client):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    role_id = _make_admin_role(app)
    try:
        resp = client.get("/api/v1/admin/access/roles", headers=_auth_headers())
        assert resp.status_code == 200, resp.get_json()
        ids = {row["id"] for row in resp.get_json()["levels"]}
        assert role_id in ids
    finally:
        _cleanup(app, "role", role_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_roles_detail_path_returns_admin_role(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    role_id = _make_admin_role(app)
    try:
        resp = client.get(
            f"/api/v1/admin/access/roles/{role_id}", headers=_auth_headers()
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["level"]["id"] == role_id
    finally:
        _cleanup(app, "role", role_id)


# ── System C (AccessLevel) now lives at /levels (FLIPPED meaning) ──────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_levels_path_now_lists_access_levels(mock_repo_cls, mock_auth_cls, app, client):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    level_id = _make_access_level(app)
    try:
        resp = client.get("/api/v1/admin/access/levels", headers=_auth_headers())
        assert resp.status_code == 200, resp.get_json()
        ids = {row["id"] for row in resp.get_json()["levels"]}
        assert level_id in ids
    finally:
        _cleanup(app, "level", level_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_levels_detail_path_now_returns_access_level(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    level_id = _make_access_level(app)
    try:
        resp = client.get(
            f"/api/v1/admin/access/levels/{level_id}", headers=_auth_headers()
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["level"]["id"] == level_id
    finally:
        _cleanup(app, "level", level_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_levels_content_path_serves_access_level_content(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    level_id = _make_access_level(app)
    try:
        resp = client.get(
            f"/api/v1/admin/access/levels/{level_id}/content",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert "pages" in body and "widgets" in body
    finally:
        _cleanup(app, "level", level_id)


# ── 308 redirects from the vacated /user-levels* family ───────────────────


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_user_levels_list_redirects_to_levels(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    resp = client.get(
        "/api/v1/admin/access/user-levels",
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 308, resp.status_code
    assert resp.headers["Location"].endswith("/api/v1/admin/access/levels")


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_user_levels_detail_redirects_to_levels_detail(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    lvl = str(uuid4())
    resp = client.get(
        f"/api/v1/admin/access/user-levels/{lvl}",
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 308, resp.status_code
    assert resp.headers["Location"].endswith(f"/api/v1/admin/access/levels/{lvl}")


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_user_levels_content_redirects_to_levels_content(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    lvl = str(uuid4())
    resp = client.get(
        f"/api/v1/admin/access/user-levels/{lvl}/content",
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 308, resp.status_code
    assert resp.headers["Location"].endswith(
        f"/api/v1/admin/access/levels/{lvl}/content"
    )


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_user_levels_redirect_preserves_query_string(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(mock_repo_cls, mock_auth_cls, _actor())
    resp = client.get(
        "/api/v1/admin/access/user-levels?foo=bar",
        headers=_auth_headers(),
        follow_redirects=False,
    )
    assert resp.status_code == 308, resp.status_code
    assert resp.headers["Location"].endswith("/api/v1/admin/access/levels?foo=bar")
