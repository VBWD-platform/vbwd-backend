"""S135-CLIENT — admin license routes over a real app (in-process client).

Exercises GET status, POST offline-envelope (201 + persisted), POST tampered
(422 INVALID_SIGNATURE), DELETE, and permission gating. A fixture signature
verifier is injected via config so keys are minted deterministically — no real
Ed25519 key at test time.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from vbwd.security.licensing.license_key import (
    LicenseKey,
    encode_envelope,
    encode_license_payload,
)
from vbwd.security.licensing.ports import ISignatureVerifier

INSTANCE_ID = "route-test-instance"


class _FixtureSigner(ISignatureVerifier):
    def sign(self, message: bytes) -> bytes:
        return hmac.new(b"route-secret", message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


def _mint(signer, **overrides) -> str:
    now = datetime.now(timezone.utc)
    defaults = dict(
        key_id="route-key",
        customer="acme",
        instance_id=INSTANCE_ID,
        edition="ME",
        scope=("*",),
        seat_limit=25,
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=365),
        grace_days=14,
        nonce="n",
    )
    defaults.update(overrides)
    payload = encode_license_payload(LicenseKey(**defaults))
    return encode_envelope(payload, signer.sign(payload))


@pytest.fixture
def signer():
    return _FixtureSigner()


@pytest.fixture
def app(tmp_path, signer):
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
            "LICENSE_REQUIRED": False,
            "LICENSE_KEYS_DIR": str(tmp_path / "keys"),
            "LICENSE_INSTANCE_ID": INSTANCE_ID,
            "LICENSE_SIGNATURE_VERIFIER": signer,
        }
    )
    # Ensure the standard admin/user accounts exist so the permission-gated
    # routes can be exercised in-process (create-if-absent via the ORM).
    with application.app_context():
        _ensure_account("admin@example.com", "ADMIN")
        _ensure_account("test@example.com", "USER")
    return application


def _ensure_account(email, role_name):
    import bcrypt

    from vbwd.extensions import db
    from vbwd.models.enums import UserRole, UserStatus
    from vbwd.models.user import User

    if db.session.query(User).filter_by(email=email).first() is not None:
        return
    password_hash = bcrypt.hashpw(b"Passw0rd123@", bcrypt.gensalt()).decode("utf-8")
    db.session.add(
        User(
            email=email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            role=UserRole[role_name],
        )
    )
    db.session.commit()


def _token_for(app, email):
    from vbwd.extensions import db
    from vbwd.models.user import User
    from vbwd.repositories.user_repository import UserRepository
    from vbwd.services.auth_service import AuthService

    with app.app_context():
        user = db.session.query(User).filter_by(email=email).first()
        if user is None:
            pytest.skip(f"Seed user {email} not present; skipping route test")
        service = AuthService(user_repository=UserRepository(db.session))
        return service.generate_access_token(user.id, user.email)


@pytest.fixture
def admin_headers(app):
    token = _token_for(app, "admin@example.com")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(app):
    token = _token_for(app, "test@example.com")
    return {"Authorization": f"Bearer {token}"}


def test_get_requires_permission(app, user_headers):
    response = app.test_client().get("/api/v1/admin/license", headers=user_headers)
    assert response.status_code == 403


def test_get_returns_status_payload(app, admin_headers):
    response = app.test_client().get("/api/v1/admin/license", headers=admin_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["required"] is False
    assert "keys" in body and "seats" in body


def test_post_valid_envelope_persists_and_lists(app, admin_headers, signer):
    client = app.test_client()
    envelope = _mint(signer, key_id="added-key", scope=("marketplace",))
    created = client.post(
        "/api/v1/admin/license/keys",
        json={"envelope": envelope},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["key_id"] == "added-key"

    listed = client.get("/api/v1/admin/license", headers=admin_headers).get_json()
    assert any(row["key_id"] == "added-key" for row in listed["keys"])


def test_post_tampered_envelope_is_422(app, admin_headers, signer):
    envelope = _mint(signer)
    tampered = envelope[:-2] + ("A" if envelope[-1] != "A" else "B")
    response = app.test_client().post(
        "/api/v1/admin/license/keys",
        json={"envelope": tampered},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert response.get_json()["status"] == "invalid_signature"


def test_delete_removes_key(app, admin_headers, signer):
    client = app.test_client()
    envelope = _mint(signer, key_id="deletable")
    client.post(
        "/api/v1/admin/license/keys",
        json={"envelope": envelope},
        headers=admin_headers,
    )
    removed = client.delete(
        "/api/v1/admin/license/keys/deletable", headers=admin_headers
    )
    assert removed.status_code == 200
    missing = client.delete(
        "/api/v1/admin/license/keys/deletable", headers=admin_headers
    )
    assert missing.status_code == 404


def test_post_code_uses_injected_activation_client(app, admin_headers, signer):
    """The online ``{code}`` path redeems via the activation client, then stores."""

    class _FakeActivationClient:
        def activate(self, code, instance_id):
            assert code == "DASH-CODE" and instance_id == INSTANCE_ID
            return _mint(signer, key_id="code-key", scope=("analytics",))

    app.license_activation_client = _FakeActivationClient()
    response = app.test_client().post(
        "/api/v1/admin/license/keys",
        json={"code": "DASH-CODE"},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["key_id"] == "code-key"
