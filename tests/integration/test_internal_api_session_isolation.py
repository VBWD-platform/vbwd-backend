"""S152 C2 — an in-process API call runs in its OWN SQLAlchemy session.

Real PostgreSQL. The outer request flushes (never commits) a user; the inner
request, dispatched through ``InternalApiClient``, must not see it, and its own
rollback must leave the outer session's pending work untouched. The outer
request rolls back at the end, so nothing persists.
"""
from uuid import uuid4

import pytest
from flask import Blueprint, jsonify, request

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.services.internal_api import resolve_internal_api_client

INNER_PATH = "/api/v1/test-internal-api/session-probe"
OUTER_PATH = "/test-internal-api/session-outer"


def _build_isolation_blueprint() -> Blueprint:
    from vbwd.extensions import db

    blueprint = Blueprint("test_internal_api_session", __name__)

    @blueprint.route(INNER_PATH)
    def session_probe():
        email = request.args["email"]
        visible_in_inner = db.session.query(User).filter_by(email=email).count()
        db.session.add(_unsaved_user(f"inner-{email}"))
        db.session.flush()
        db.session.rollback()
        return jsonify(
            {"visible_in_inner": visible_in_inner, "session_id": id(db.session())}
        )

    @blueprint.route(OUTER_PATH)
    def session_outer():
        email = f"internal-api-{uuid4().hex[:8]}@example.com"
        outer_user = _unsaved_user(email)
        db.session.add(outer_user)
        db.session.flush()
        try:
            inner = (
                resolve_internal_api_client()
                .get(INNER_PATH, query={"email": email}, forward_from=request)
                .json()
            )
            return jsonify(
                {
                    "inner": inner,
                    "outer_session_id": id(db.session()),
                    "outer_still_pending": outer_user in db.session,
                    "visible_in_outer": db.session.query(User)
                    .filter_by(email=email)
                    .count(),
                }
            )
        finally:
            db.session.rollback()

    return blueprint


def _unsaved_user(email: str) -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.USER,
    )


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    app.register_blueprint(_build_isolation_blueprint())
    return app


def test_inner_session_isolated_from_outer(app):
    body = app.test_client().get(OUTER_PATH).get_json()

    assert body["inner"]["visible_in_inner"] == 0
    assert body["inner"]["session_id"] != body["outer_session_id"]
    assert body["outer_still_pending"] is True
    assert body["visible_in_outer"] == 1
