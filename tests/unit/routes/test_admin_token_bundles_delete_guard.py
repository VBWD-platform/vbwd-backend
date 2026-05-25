"""Admin token-bundle DELETE guard.

A token bundle that has purchase history must NOT be hard-deleted — the
vbwd_token_bundle_purchase.bundle_id FK is NOT NULL, so deleting the bundle
used to 500 (IntegrityError: null value in column "bundle_id"). The route now
returns 400 ("deactivate instead"), mirroring the plan-delete guard.
"""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from tests.fixtures.access import make_user_with_permissions


def _auth_headers():
    return {"Authorization": "Bearer valid"}


def _mock_auth(mock_repo_cls, mock_auth_cls, user):
    mock_repo_cls.return_value.find_by_id.return_value = user
    mock_auth_cls.return_value.verify_token.return_value = str(uuid4())


def _make_bundle_with_purchase(app):
    """Create a TokenBundle + one purchase referencing it. Returns ids."""
    from vbwd.extensions import db
    from vbwd.models.user import User
    from vbwd.models.token_bundle import TokenBundle
    from vbwd.models.token_bundle_purchase import TokenBundlePurchase

    with app.app_context():
        existing_user = db.session.query(User).first()
        if existing_user is None:
            return None, None
        bundle = TokenBundle(
            name=f"Guard {uuid4().hex[:8]}",
            token_amount=1000,
            price=Decimal("10.00"),
            is_active=True,
        )
        db.session.add(bundle)
        db.session.flush()
        purchase = TokenBundlePurchase(
            user_id=existing_user.id,
            bundle_id=bundle.id,
            token_amount=1000,
            price=Decimal("10.00"),
        )
        db.session.add(purchase)
        db.session.commit()
        return str(bundle.id), str(purchase.id)


def _cleanup(app, bundle_id, purchase_id):
    from vbwd.extensions import db
    from vbwd.models.token_bundle import TokenBundle
    from vbwd.models.token_bundle_purchase import TokenBundlePurchase

    with app.app_context():
        if purchase_id:
            purchase = db.session.get(TokenBundlePurchase, purchase_id)
            if purchase:
                db.session.delete(purchase)
        if bundle_id:
            bundle = db.session.get(TokenBundle, bundle_id)
            if bundle:
                db.session.delete(bundle)
        db.session.commit()


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_delete_bundle_with_purchases_returns_400_not_500(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(
        mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
    )

    bundle_id, purchase_id = _make_bundle_with_purchase(app)
    if bundle_id is None:
        pytest.skip("No user in DB to attach a purchase to")

    try:
        response = client.delete(
            f"/api/v1/admin/token-bundles/{bundle_id}", headers=_auth_headers()
        )
        assert response.status_code == 400, response.get_json()
        assert "deactivate" in response.get_json()["error"].lower()

        # The bundle must still exist (delete refused, not partially applied).
        from vbwd.extensions import db
        from vbwd.models.token_bundle import TokenBundle

        with app.app_context():
            assert db.session.get(TokenBundle, bundle_id) is not None
    finally:
        _cleanup(app, bundle_id, purchase_id)


@patch("vbwd.middleware.auth.AuthService")
@patch("vbwd.middleware.auth.UserRepository")
def test_delete_bundle_without_purchases_succeeds(
    mock_repo_cls, mock_auth_cls, app, client
):
    _mock_auth(
        mock_repo_cls, mock_auth_cls, make_user_with_permissions("settings.manage")
    )

    from vbwd.extensions import db
    from vbwd.models.token_bundle import TokenBundle

    with app.app_context():
        bundle = TokenBundle(
            name=f"NoPurch {uuid4().hex[:8]}",
            token_amount=500,
            price=Decimal("5.00"),
            is_active=True,
        )
        db.session.add(bundle)
        db.session.commit()
        bundle_id = str(bundle.id)

    response = client.delete(
        f"/api/v1/admin/token-bundles/{bundle_id}", headers=_auth_headers()
    )
    assert response.status_code == 200, response.get_json()

    with app.app_context():
        assert db.session.get(TokenBundle, bundle_id) is None
