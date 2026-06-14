"""S74 — account_type persists against the real (migration-built) schema.

Proves the additive migration applied (the column exists) and that the
``server_default='private'`` backfills rows that omit it.
"""
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


def _make_user(session, email):
    user = User(id=uuid4(), email=email, password_hash="x")
    session.add(user)
    session.flush()
    return user


def test_account_type_defaults_to_private_when_omitted(session):
    user = _make_user(session, f"acct-default-{uuid4().hex[:8]}@example.com")
    details = UserDetails(user_id=user.id, first_name="Ada")
    session.add(details)
    session.commit()
    try:
        session.refresh(details)
        assert details.account_type == "private"
    finally:
        session.delete(details)
        session.delete(user)
        session.commit()


def test_account_type_business_persists(session):
    user = _make_user(session, f"acct-biz-{uuid4().hex[:8]}@example.com")
    details = UserDetails(user_id=user.id, account_type="business", company="Acme Corp")
    session.add(details)
    session.commit()
    try:
        session.refresh(details)
        assert details.account_type == "business"
        assert details.to_dict()["account_type"] == "business"
    finally:
        session.delete(details)
        session.delete(user)
        session.commit()
