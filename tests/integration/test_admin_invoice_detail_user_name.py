"""Regression — GET /api/v1/admin/invoices/<id> must not 500 when the owner's
UserDetails row exists but ``first_name``/``last_name`` are None.

Prod bug: ``user.details.first_name + " " + user.details.last_name`` raised
``TypeError`` (None + str) -> HTTP 500. The route must build ``user_name``
safely from possibly-None parts.

Uses the live integration DB (create_app against ``get_database_url()``) and
cleans up its own rows via per-test ORM delete.
"""
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import InvoiceStatus, UserRole, UserStatus
from vbwd.models.invoice import UserInvoice
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": get_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
    }
    return create_app(test_config)


@contextmanager
def _seeded_invoice(app, *, first_name, last_name):
    """Create one admin plus one user (with a UserDetails row carrying the
    given name parts) owning one invoice; yield them, then delete everything."""
    from vbwd.extensions import db

    with app.app_context():
        admin = User(
            id=uuid4(),
            email=f"invname-admin-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        owner = User(
            id=uuid4(),
            email=f"invname-owner-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
        )
        db.session.add(admin)
        db.session.add(owner)
        db.session.flush()
        details = UserDetails(
            id=uuid4(),
            user_id=owner.id,
            first_name=first_name,
            last_name=last_name,
        )
        db.session.add(details)
        invoice = UserInvoice(
            id=uuid4(),
            user_id=owner.id,
            invoice_number=UserInvoice.generate_invoice_number(),
            amount=Decimal("9.99"),
            currency="EUR",
            status=InvoiceStatus.PENDING,
        )
        db.session.add(invoice)
        db.session.commit()
        admin_id = admin.id
        owner_id = owner.id
        details_id = details.id
        invoice_id = invoice.id
        try:
            yield admin, invoice_id
        finally:
            for model, obj_id in (
                (UserInvoice, invoice_id),
                (UserDetails, details_id),
                (User, owner_id),
                (User, admin_id),
            ):
                obj = db.session.get(model, obj_id)
                if obj:
                    db.session.delete(obj)
            db.session.commit()


def _auth_as_admin(monkeypatch, admin):
    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    monkeypatch.setattr(type(admin), "has_permission", lambda self, perm: True)


def _get_detail(app, monkeypatch, admin, invoice_id):
    _auth_as_admin(monkeypatch, admin)
    client = app.test_client()
    return client.get(
        f"/api/v1/admin/invoices/{invoice_id}",
        headers={"Authorization": "Bearer valid"},
    )


def test_invoice_detail_both_names_none(app, monkeypatch):
    with _seeded_invoice(app, first_name=None, last_name=None) as (admin, invoice_id):
        resp = _get_detail(app, monkeypatch, admin, invoice_id)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["invoice"]["user_name"] == ""


def test_invoice_detail_first_name_only(app, monkeypatch):
    with _seeded_invoice(app, first_name="Ada", last_name=None) as (admin, invoice_id):
        resp = _get_detail(app, monkeypatch, admin, invoice_id)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["invoice"]["user_name"] == "Ada"


def test_invoice_detail_both_names_present(app, monkeypatch):
    with _seeded_invoice(app, first_name="Ada", last_name="Lovelace") as (
        admin,
        invoice_id,
    ):
        resp = _get_detail(app, monkeypatch, admin, invoice_id)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["invoice"]["user_name"] == "Ada Lovelace"
