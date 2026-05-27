"""S23 — PaymentMethodService unit tests."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from vbwd.services.payment_method_service import (
    PaymentMethodService,
    PaymentMethodValidationError,
)


@pytest.fixture
def repo():
    repository = MagicMock()
    repository.code_exists.return_value = False
    repository.save.side_effect = lambda model: model
    return repository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def service(repo, session):
    return PaymentMethodService(repository=repo, session=session)


def test_create_raises_when_code_missing(service):
    with pytest.raises(PaymentMethodValidationError, match="Code"):
        service.create({"name": "Stripe Checkout"})


def test_create_raises_when_name_missing(service):
    with pytest.raises(PaymentMethodValidationError, match="Name"):
        service.create({"code": "stripe"})


def test_create_raises_when_code_already_exists(service, repo):
    repo.code_exists.return_value = True
    with pytest.raises(PaymentMethodValidationError, match="already exists"):
        service.create({"code": "stripe", "name": "Stripe"})


def test_create_returns_persisted_method(service, repo):
    result = service.create(
        {"code": "stripe", "name": "Stripe Checkout", "min_amount": "1.50"}
    )
    repo.save.assert_called_once()
    assert result.code == "stripe"
    assert result.name == "Stripe Checkout"
    assert result.min_amount == Decimal("1.50")


def test_create_with_decimals_parses_correctly(service):
    result = service.create(
        {
            "code": "stripe",
            "name": "Stripe",
            "min_amount": "0.50",
            "max_amount": "10000",
            "fee_amount": "0.30",
        }
    )
    assert result.min_amount == Decimal("0.50")
    assert result.max_amount == Decimal("10000")
    assert result.fee_amount == Decimal("0.30")


def test_create_with_no_default_does_not_touch_other_defaults(service, session):
    service.create({"code": "stripe", "name": "Stripe", "is_default": False})
    session.query.assert_not_called()


def test_create_with_default_clears_other_defaults(service, session):
    service.create({"code": "stripe", "name": "Stripe", "is_default": True})
    session.query.assert_called_once()


def test_create_default_kwargs_match_route_contract(service):
    """Sanity: when no optional fields supplied, the saved object has the
    defaults the route used to apply inline."""
    result = service.create({"code": "stripe", "name": "Stripe"})
    assert result.is_active is True
    assert result.is_default is False
    assert result.position == 0
    assert result.currencies == []
    assert result.countries == []
    assert result.fee_type == "none"
    assert result.fee_charged_to == "customer"
    assert result.config == {}
