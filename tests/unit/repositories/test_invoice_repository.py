"""S16 — InvoiceRepository contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.invoice import UserInvoice
from vbwd.repositories.invoice_repository import InvoiceRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return InvoiceRepository(session)


def test_find_by_user_filters_on_user_id(session, repository):
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )
    repository.find_by_user(uuid4())
    session.query.assert_called_with(UserInvoice)


def test_find_by_invoice_number_returns_first(session, repository):
    sentinel = object()
    session.query.return_value.filter.return_value.first.return_value = sentinel
    assert repository.find_by_invoice_number("INV-001") is sentinel


def test_find_by_invoice_number_returns_none_when_absent(session, repository):
    session.query.return_value.filter.return_value.first.return_value = None
    assert repository.find_by_invoice_number("INV-MISSING") is None


def test_find_pending_returns_list(session, repository):
    session.query.return_value.filter.return_value.all.return_value = ["inv1"]
    assert repository.find_pending() == ["inv1"]


def test_find_unpaid_by_user_filters_on_user(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    repository.find_unpaid_by_user(uuid4())
    session.query.assert_called_with(UserInvoice)
