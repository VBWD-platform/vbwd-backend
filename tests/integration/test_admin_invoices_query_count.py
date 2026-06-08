"""S48.3 — N+1 guard for GET /api/v1/admin/invoices/.

The admin invoice list enriches every row with the user email. Before S48.3
this was a per-row ``find_by_id`` lookup (N+1 queries). The fix batch-fetches
the users for the page, so the number of SQL statements the route emits must be
a small constant independent of page size.

Pure-performance guard: it asserts the SQL *count* is bounded and pins the
enrichment shape so behaviour is unchanged. Uses the live integration DB
(create_app against ``get_database_url()``) and cleans up its own rows.
"""
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import event

from vbwd.models.enums import InvoiceStatus, UserRole, UserStatus
from vbwd.models.invoice import UserInvoice
from vbwd.models.user import User


# Upper bound on SELECTs for one admin invoice list page, independent of page
# size: the paginated query (line items eager-joined), the COUNT, the batch
# user fetch, plus a small allowance for auth/middleware lookups.
MAX_LIST_SELECTS = 8


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
def _seeded(app, *, invoice_count):
    """Create one admin, ``invoice_count`` users each with one invoice, yield
    them, then delete everything so the live integration DB is left clean."""
    from vbwd.extensions import db

    created_user_ids = []
    invoice_ids = []
    with app.app_context():
        admin = User(
            id=uuid4(),
            email=f"s483-admin-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            status=UserStatus.ACTIVE,
            role=UserRole.ADMIN,
        )
        db.session.add(admin)
        for index in range(invoice_count):
            user = User(
                id=uuid4(),
                email=f"s483-inv-{index}-{uuid4().hex[:8]}@example.com",
                password_hash="x",
                status=UserStatus.ACTIVE,
            )
            db.session.add(user)
            db.session.flush()
            invoice = UserInvoice(
                id=uuid4(),
                user_id=user.id,
                invoice_number=UserInvoice.generate_invoice_number(),
                amount=Decimal("9.99"),
                currency="EUR",
                status=InvoiceStatus.PENDING,
            )
            db.session.add(invoice)
            created_user_ids.append(user.id)
            invoice_ids.append(invoice.id)
        db.session.commit()
        admin_id = admin.id
        try:
            yield admin, created_user_ids, invoice_ids
        finally:
            for invoice_id in invoice_ids:
                obj = db.session.get(UserInvoice, invoice_id)
                if obj:
                    db.session.delete(obj)
            for user_id in created_user_ids + [admin_id]:
                obj = db.session.get(User, user_id)
                if obj:
                    db.session.delete(obj)
            db.session.commit()


@contextmanager
def _count_selects(app):
    from vbwd.extensions import db

    counter = {"selects": 0}
    with app.app_context():
        engine = db.session.get_bind()

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["selects"] += 1

    event.listen(engine, "after_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "after_cursor_execute", _on_execute)


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


def _list_select_count(app, monkeypatch, *, page_size):
    with _seeded(app, invoice_count=page_size) as (admin, user_ids, _invoice_ids):
        _auth_as_admin(monkeypatch, admin)
        client = app.test_client()
        with _count_selects(app) as counter:
            resp = client.get(
                f"/api/v1/admin/invoices/?limit={page_size}",
                headers={"Authorization": "Bearer valid"},
            )
        assert resp.status_code == 200, resp.get_json()
        payload = resp.get_json()
        # Restrict to the rows this test seeded (live DB may hold others).
        seeded = {str(uid) for uid in user_ids}
        mine = [row for row in payload["invoices"] if row["user_id"] in seeded]
        return counter["selects"], mine


def test_admin_list_invoices_is_not_n_plus_one(app, monkeypatch):
    selects, _ = _list_select_count(app, monkeypatch, page_size=10)
    assert selects <= MAX_LIST_SELECTS, (
        f"admin invoice list emitted {selects} SELECTs for a 10-row page; "
        f"expected <= {MAX_LIST_SELECTS} (N+1 regression)"
    )


def test_admin_list_invoices_query_count_independent_of_page_size(app, monkeypatch):
    small, _ = _list_select_count(app, monkeypatch, page_size=3)
    large, _ = _list_select_count(app, monkeypatch, page_size=15)
    assert (
        large <= small + 1
    ), f"query count grew with page size ({small} -> {large}); list is N+1"


def test_admin_list_invoices_enrichment_unchanged(app, monkeypatch):
    with _seeded(app, invoice_count=1) as (admin, user_ids, _invoice_ids):
        _auth_as_admin(monkeypatch, admin)
        client = app.test_client()
        resp = client.get(
            "/api/v1/admin/invoices/",
            headers={"Authorization": "Bearer valid"},
        )
        assert resp.status_code == 200, resp.get_json()
        seeded_user_id = str(user_ids[0])
        rows = resp.get_json()["invoices"]
        target = next(row for row in rows if row["user_id"] == seeded_user_id)
        assert target["user_email"].startswith("s483-inv-")
        assert target["created_at"] is not None
