"""Unit tests for the core payment-method seeder (S43 follow-up).

The manual ``invoice`` method is foundational, plugin-independent reference
data, seeded by default on every instance (ungated, like the country catalog
and the RBAC roles). These tests exercise ``seed_payment_methods`` against the
live test DB session (real SQLAlchemy insert + commit semantics, which a
MagicMock cannot model), isolating by wiping the table before and after.
"""
import pytest

from vbwd.extensions import db
from vbwd.models.payment_method import PaymentMethod
from vbwd.services.payment_method_seeder import (
    DEFAULT_PAYMENT_METHODS,
    PaymentMethodSeedResult,
    seed_payment_methods,
)


def _wipe_payment_methods(session):
    """Remove all payment-method rows so each test starts clean."""
    session.query(PaymentMethod).delete()
    session.commit()


@pytest.fixture
def session(app):
    """Live test-DB session inside an app context, methods wiped clean."""
    with app.app_context():
        _wipe_payment_methods(db.session)
        try:
            yield db.session
        finally:
            db.session.rollback()
            _wipe_payment_methods(db.session)


class TestSeedPaymentMethods:
    def test_seeds_all_default_methods(self, session):
        result = seed_payment_methods(session)

        assert isinstance(result, PaymentMethodSeedResult)
        assert result.created == len(DEFAULT_PAYMENT_METHODS)
        assert session.query(PaymentMethod).count() == len(DEFAULT_PAYMENT_METHODS)

    def test_invoice_method_is_active_default(self, session):
        seed_payment_methods(session)

        invoice = session.query(PaymentMethod).filter_by(code="invoice").one()
        assert invoice.name == "Invoice"
        assert invoice.is_active is True
        assert invoice.is_default is True

    def test_idempotent_rerun_creates_nothing(self, session):
        seed_payment_methods(session)
        result = seed_payment_methods(session)

        assert result.created == 0
        assert session.query(PaymentMethod).count() == len(DEFAULT_PAYMENT_METHODS)

    def test_existing_method_is_left_untouched(self, session):
        seed_payment_methods(session)
        # Operator renames the seeded method; a re-run must not revert it.
        invoice = session.query(PaymentMethod).filter_by(code="invoice").one()
        invoice.name = "Bank Transfer"
        session.commit()

        seed_payment_methods(session)

        invoice = session.query(PaymentMethod).filter_by(code="invoice").one()
        assert invoice.name == "Bank Transfer"
