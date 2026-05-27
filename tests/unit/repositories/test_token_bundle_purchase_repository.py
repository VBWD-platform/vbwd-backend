"""S16 — TokenBundlePurchaseRepository contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models import TokenBundlePurchase
from vbwd.repositories.token_bundle_purchase_repository import (
    TokenBundlePurchaseRepository,
)


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return TokenBundlePurchaseRepository(session)


def test_find_by_user_queries_purchases(session, repository):
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )
    repository.find_by_user(uuid4())
    session.query.assert_called_with(TokenBundlePurchase)


def test_find_by_invoice_returns_list(session, repository):
    session.query.return_value.filter.return_value.all.return_value = ["purchase-1"]
    assert repository.find_by_invoice(uuid4()) == ["purchase-1"]


def test_find_pending_by_user_returns_list(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    assert repository.find_pending_by_user(uuid4()) == []


def test_find_completed_uncredited_returns_list(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    assert repository.find_completed_uncredited() == []
