"""S135-CLIENT — boot behaviour: open, licensed-pass, and degraded modes.

Boots a real app with different license config and asserts the request-level
consequences: the CE default is open (NullLicenseContext), a covering key lets a
``@requires_license`` route pass, and enforcement with no key degrades — the
licensed route returns 402 while a core public route is unaffected.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from flask import jsonify

from vbwd.security.licensing.decorator import requires_license
from vbwd.security.licensing.license_context import NullLicenseContext
from vbwd.security.licensing.license_key import (
    LicenseKey,
    encode_envelope,
    encode_license_payload,
)
from vbwd.security.licensing.ports import ISignatureVerifier

INSTANCE_ID = "boot-test-instance"


class _FixtureSigner(ISignatureVerifier):
    def sign(self, message: bytes) -> bytes:
        return hmac.new(b"boot-secret", message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


def _write_covering_key(keys_dir, signer):
    os.makedirs(keys_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    key = LicenseKey(
        key_id="boot-platform",
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
    payload = encode_license_payload(key)
    envelope = encode_envelope(payload, signer.sign(payload))
    with open(os.path.join(keys_dir, "boot-platform.vbwd"), "w", encoding="utf-8") as f:
        f.write(envelope)


def _build_app(config):
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    base = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
    }
    base.update(config)
    app = create_app(base)

    # A licensed test route to observe the gate at request time.
    @app.route("/api/v1/_boot_test/licensed")
    @requires_license(feature="marketplace")
    def _licensed():
        return jsonify({"ok": True})

    return app


def test_not_required_boots_open_with_null_context(tmp_path):
    app = _build_app(
        {"LICENSE_REQUIRED": False, "LICENSE_KEYS_DIR": str(tmp_path / "keys")}
    )
    assert isinstance(app.license_context, NullLicenseContext)
    assert app.config["LICENSE_DEGRADED"] is False
    # The gate is inert: the licensed route passes.
    assert app.test_client().get("/api/v1/_boot_test/licensed").status_code == 200


def test_required_with_covering_key_lets_licensed_route_pass(tmp_path):
    signer = _FixtureSigner()
    keys_dir = str(tmp_path / "keys")
    _write_covering_key(keys_dir, signer)
    app = _build_app(
        {
            "LICENSE_REQUIRED": True,
            "LICENSE_KEYS_DIR": keys_dir,
            "LICENSE_INSTANCE_ID": INSTANCE_ID,
            "LICENSE_SIGNATURE_VERIFIER": signer,
        }
    )
    assert app.config["LICENSE_DEGRADED"] is False
    assert app.test_client().get("/api/v1/_boot_test/licensed").status_code == 200


def test_required_without_key_degrades(tmp_path):
    signer = _FixtureSigner()
    app = _build_app(
        {
            "LICENSE_REQUIRED": True,
            "LICENSE_KEYS_DIR": str(tmp_path / "keys"),
            "LICENSE_INSTANCE_ID": INSTANCE_ID,
            "LICENSE_SIGNATURE_VERIFIER": signer,
        }
    )
    client = app.test_client()
    assert app.config["LICENSE_DEGRADED"] is True
    # Licensed route blocked, but a core public route is unaffected.
    assert client.get("/api/v1/_boot_test/licensed").status_code == 402
    assert client.get("/api/v1/health").status_code == 200
