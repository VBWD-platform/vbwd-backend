"""S16 — InvoiceLineItemRepository contract tests."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.invoice_line_item import InvoiceLineItem
from vbwd.repositories.invoice_line_item_repository import InvoiceLineItemRepository


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def repository(session):
    return InvoiceLineItemRepository(session)


def test_find_by_invoice_filters_on_invoice_id(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    repository.find_by_invoice(uuid4())
    session.query.assert_called_with(InvoiceLineItem)


def test_find_by_item_filters_on_item_id(session, repository):
    session.query.return_value.filter.return_value.all.return_value = []
    repository.find_by_item(uuid4())
    session.query.assert_called_with(InvoiceLineItem)


def test_save_persists_via_session(session, repository):
    line_item = MagicMock()
    saved = repository.save(line_item)
    session.add.assert_called_once_with(line_item)
    assert saved is line_item
