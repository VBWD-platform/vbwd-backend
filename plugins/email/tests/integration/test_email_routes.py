"""Integration tests for email admin routes.

Covers: auth, authorization, CRUD, preview rendering, edge cases, security.
"""
import pytest
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"


def _test_db_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_test"


def _ensure_test_db(url: str) -> None:
    from sqlalchemy import create_engine, text
    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app():
    from src.app import create_app
    url = _test_db_url()
    _ensure_test_db(url)
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URL": "memory://",
        "SECRET_KEY": "test-secret-key",
        "JWT_SECRET_KEY": "test-jwt-secret-key",
        "FLASK_SECRET_KEY": "test-secret-key",
    }
    app = create_app(test_config)
    from src.extensions import limiter
    limiter.reset()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from src.extensions import db
    with app.app_context():
        from plugins.email.src.models.email_template import EmailTemplate  # noqa: F401
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


def _make_user(app, db_session, email: str, role: str = "ADMIN", active: bool = True):
    from src.models.user import User
    from src.models.enums import UserRole, UserStatus
    import bcrypt
    pw = bcrypt.hashpw(b"TestPass123@", bcrypt.gensalt()).decode()
    user = User(
        email=email,
        password_hash=pw,
        role=UserRole[role],
        status=UserStatus.ACTIVE if active else UserStatus.PENDING,
    )
    db_session.session.add(user)
    db_session.session.commit()
    return user


def _login(client, email: str, password: str = "TestPass123@"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    data = resp.json
    return data.get("token") or data.get("access_token")


@pytest.fixture
def admin_token(client, db, app):
    with app.app_context():
        _make_user(app, db, "admin@email.test")
    return _login(client, "admin@email.test")


@pytest.fixture
def user_token(client, db, app):
    with app.app_context():
        _make_user(app, db, "user@email.test", role="USER")
    return _login(client, "user@email.test")


def _seed_template(app, db, event_type: str = "subscription.activated") -> str:
    with app.app_context():
        from plugins.email.src.models.email_template import EmailTemplate
        tpl = EmailTemplate(
            event_type=event_type,
            subject="Hello {{ user_name }}",
            html_body="<p>Hi {{ user_name }}</p>",
            text_body="Hi {{ user_name }}",
            is_active=True,
        )
        db.session.add(tpl)
        db.session.commit()
        return str(tpl.id)


# ===========================================================================
# Auth / security
# ===========================================================================


class TestEmailRoutesSecurity:
    def test_list_requires_auth(self, client, db):
        assert client.get("/api/v1/admin/email/templates").status_code == 401

    def test_get_requires_auth(self, client, db):
        assert client.get(f"/api/v1/admin/email/templates/{uuid.uuid4()}").status_code == 401

    def test_put_requires_auth(self, client, db):
        assert client.put(f"/api/v1/admin/email/templates/{uuid.uuid4()}", json={}).status_code == 401

    def test_preview_requires_auth(self, client, db):
        assert client.post("/api/v1/admin/email/templates/preview", json={}).status_code == 401

    def test_event_types_requires_auth(self, client, db):
        assert client.get("/api/v1/admin/email/event-types").status_code == 401

    def test_test_send_requires_auth(self, client, db):
        assert client.post("/api/v1/admin/email/test-send", json={}).status_code == 401

    def test_non_admin_user_gets_403_on_list(self, client, db, user_token):
        resp = client.get(
            "/api/v1/admin/email/templates",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    def test_non_admin_user_gets_403_on_event_types(self, client, db, user_token):
        resp = client.get(
            "/api/v1/admin/email/event-types",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    def test_invalid_token_rejected(self, client, db):
        resp = client.get(
            "/api/v1/admin/email/templates",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert resp.status_code == 401


# ===========================================================================
# List templates
# ===========================================================================


class TestListTemplates:
    def test_returns_empty_list(self, client, db, admin_token):
        resp = client.get(
            "/api/v1/admin/email/templates",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json == []

    def test_returns_seeded_templates(self, client, db, admin_token, app):
        _seed_template(app, db, "subscription.activated")
        _seed_template(app, db, "user.registered")
        resp = client.get(
            "/api/v1/admin/email/templates",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json) == 2
        # Ordered alphabetically by event_type
        assert resp.json[0]["event_type"] == "subscription.activated"

    def test_template_shape(self, client, db, admin_token, app):
        _seed_template(app, db)
        resp = client.get(
            "/api/v1/admin/email/templates",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        tpl = resp.json[0]
        for key in ("id", "event_type", "subject", "html_body", "text_body", "is_active", "created_at", "updated_at"):
            assert key in tpl


# ===========================================================================
# Get one template
# ===========================================================================


class TestGetTemplate:
    def test_returns_404_for_unknown_id(self, client, db, admin_token):
        resp = client.get(
            f"/api/v1/admin/email/templates/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_returns_400_for_invalid_uuid(self, client, db, admin_token):
        # Path-traversal attempts with '/' are rejected by Flask routing (404)
        # Single-segment invalid UUIDs must return 400
        for bad_id in ("not-a-uuid", "123", "hello-world-not-uuid"):
            resp = client.get(
                f"/api/v1/admin/email/templates/{bad_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 400, f"Expected 400 for id={bad_id!r}"

    def test_returns_template_by_id(self, client, db, admin_token, app):
        tpl_id = _seed_template(app, db)
        resp = client.get(
            f"/api/v1/admin/email/templates/{tpl_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json["id"] == tpl_id
        assert resp.json["event_type"] == "subscription.activated"


# ===========================================================================
# Update template
# ===========================================================================


class TestUpdateTemplate:
    def test_updates_subject_and_is_active(self, client, db, admin_token, app):
        tpl_id = _seed_template(app, db)
        resp = client.put(
            f"/api/v1/admin/email/templates/{tpl_id}",
            json={"subject": "New subject {{ user_name }}", "is_active": False},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json["subject"] == "New subject {{ user_name }}"
        assert resp.json["is_active"] is False

    def test_updates_html_body(self, client, db, admin_token, app):
        tpl_id = _seed_template(app, db)
        resp = client.put(
            f"/api/v1/admin/email/templates/{tpl_id}",
            json={"html_body": "<h1>Updated</h1>"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json["html_body"] == "<h1>Updated</h1>"

    def test_ignores_unknown_fields(self, client, db, admin_token, app):
        tpl_id = _seed_template(app, db)
        resp = client.put(
            f"/api/v1/admin/email/templates/{tpl_id}",
            json={"event_type": "HACKED", "subject": "ok"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        # event_type must NOT have changed
        assert resp.json["event_type"] == "subscription.activated"
        assert resp.json["subject"] == "ok"

    def test_returns_404_for_unknown_id(self, client, db, admin_token):
        resp = client.put(
            f"/api/v1/admin/email/templates/{uuid.uuid4()}",
            json={"subject": "x"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_returns_400_for_invalid_uuid(self, client, db, admin_token):
        resp = client.put(
            "/api/v1/admin/email/templates/not-a-uuid",
            json={"subject": "x"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


# ===========================================================================
# Preview
# ===========================================================================


class TestPreviewTemplate:
    def test_renders_with_context(self, client, db, admin_token, app):
        _seed_template(app, db, "user.registered")
        resp = client.post(
            "/api/v1/admin/email/templates/preview",
            json={"event_type": "user.registered", "context": {"user_name": "Alice"}},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json["subject"] == "Hello Alice"
        assert "Alice" in resp.json["html_body"]

    def test_empty_event_type_returns_400(self, client, db, admin_token):
        resp = client.post(
            "/api/v1/admin/email/templates/preview",
            json={"context": {}},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_missing_body_returns_400(self, client, db, admin_token):
        resp = client.post(
            "/api/v1/admin/email/templates/preview",
            headers={"Authorization": f"Bearer {admin_token}"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_nonexistent_template_returns_empty(self, client, db, admin_token):
        resp = client.post(
            "/api/v1/admin/email/templates/preview",
            json={"event_type": "does.not.exist", "context": {}},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json == {"subject": "", "html_body": "", "text_body": ""}


# ===========================================================================
# Event types catalogue
# ===========================================================================


class TestEventTypes:
    def test_returns_all_8_event_types(self, client, db, admin_token):
        resp = client.get(
            "/api/v1/admin/email/event-types",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        event_types = {e["event_type"] for e in resp.json}
        expected = {
            "subscription.activated",
            "subscription.cancelled",
            "subscription.payment_failed",
            "subscription.renewed",
            "trial.started",
            "trial.expiring_soon",
            "user.registered",
            "user.password_reset",
        }
        assert event_types == expected

    def test_each_event_type_has_description_and_variables(self, client, db, admin_token):
        resp = client.get(
            "/api/v1/admin/email/event-types",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        for item in resp.json:
            assert "description" in item
            assert "variables" in item
            assert len(item["variables"]) > 0


# ===========================================================================
# Migration: email_template table exists and has correct schema
# ===========================================================================


class TestEmailTemplateMigration:
    def test_table_exists_with_correct_columns(self, db, app):
        from sqlalchemy import text
        with app.app_context():
            result = db.session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'email_template' ORDER BY column_name"
                )
            ).fetchall()
            columns = {row[0] for row in result}
            required = {"id", "event_type", "subject", "html_body", "text_body", "is_active", "created_at", "updated_at", "version"}
            assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_event_type_unique_constraint(self, db, app):
        from plugins.email.src.models.email_template import EmailTemplate
        with app.app_context():
            t1 = EmailTemplate(event_type="dupe.test", subject="a", html_body="a", text_body="")
            t2 = EmailTemplate(event_type="dupe.test", subject="b", html_body="b", text_body="")
            db.session.add(t1)
            db.session.commit()
            db.session.add(t2)
            from sqlalchemy.exc import IntegrityError
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
