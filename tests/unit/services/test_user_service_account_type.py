"""S74 — account_type validation across the UserService write paths."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user_details import AccountTypeValidationError
from vbwd.services.user_service import UserService


def _details_stub(**overrides):
    base = dict(
        first_name=None,
        last_name=None,
        phone=None,
        address_line_1=None,
        address_line_2=None,
        city=None,
        postal_code=None,
        country=None,
        company=None,
        tax_number=None,
        account_type="private",
        balance=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def session():
    return MagicMock()


# ── self-service path: update_user_details ────────────────────────────────


def _self_service(existing_details):
    details_repo = MagicMock()
    details_repo.find_by_user_id.return_value = existing_details
    details_repo.update.side_effect = lambda d: d
    details_repo.save.side_effect = lambda d: d
    service = UserService(
        user_repository=MagicMock(),
        user_details_repository=details_repo,
        token_service=MagicMock(),
    )
    return service


def test_self_service_persists_account_type():
    existing = _details_stub(company="Acme Corp")
    service = _self_service(existing)
    result = service.update_user_details(
        "user-1", {"account_type": "business", "company": "Acme Corp"}
    )
    assert result.account_type == "business"


def test_self_service_rejects_unknown_account_type():
    service = _self_service(_details_stub())
    with pytest.raises(AccountTypeValidationError, match="Invalid account type"):
        service.update_user_details("user-1", {"account_type": "enterprise"})


def test_self_service_business_without_company_rejected():
    service = _self_service(_details_stub(company=None))
    with pytest.raises(AccountTypeValidationError, match="Company is required"):
        service.update_user_details("user-1", {"account_type": "business"})


def test_self_service_business_with_existing_company_allowed():
    # Company already on the row; flipping to business is fine.
    existing = _details_stub(company="Acme Corp")
    service = _self_service(existing)
    result = service.update_user_details("user-1", {"account_type": "business"})
    assert result.account_type == "business"


def test_self_service_untouched_account_type_skips_validation():
    # Business row with no company would be invalid, but the payload does not
    # touch account_type → no validation (only updates first_name).
    existing = _details_stub(account_type="business", company=None)
    service = _self_service(existing)
    result = service.update_user_details("user-1", {"first_name": "Ada"})
    assert result.first_name == "Ada"


# ── admin path: admin_update ──────────────────────────────────────────────


def _admin_service(user_stub):
    user_repo = MagicMock()
    user_repo.find_by_id.return_value = user_stub
    user_repo.save.side_effect = lambda u: u
    return UserService(
        user_repository=user_repo,
        user_details_repository=MagicMock(),
        token_service=MagicMock(),
    )


def _admin_user(details):
    user = MagicMock()
    user.id = "user-1"
    user.status = UserStatus.ACTIVE
    user.role = UserRole.USER
    user.details = details
    return user


def test_admin_update_persists_account_type(session):
    details = _details_stub(company="Acme Corp")
    service = _admin_service(_admin_user(details))
    service.admin_update(
        "user-1", {"account_type": "business", "company": "Acme Corp"}, session
    )
    assert details.account_type == "business"


def test_admin_update_business_without_company_rejected(session):
    details = _details_stub(company=None)
    service = _admin_service(_admin_user(details))
    with pytest.raises(AccountTypeValidationError, match="Company is required"):
        service.admin_update("user-1", {"account_type": "business"}, session)


def test_admin_update_unknown_account_type_rejected(session):
    details = _details_stub()
    service = _admin_service(_admin_user(details))
    with pytest.raises(AccountTypeValidationError, match="Invalid account type"):
        service.admin_update("user-1", {"account_type": "enterprise"}, session)


# ── admin path: admin_create ──────────────────────────────────────────────


def test_admin_create_business_without_company_rejected(session):
    user_repo = MagicMock()
    user_repo.find_by_email.return_value = None
    user_repo.save.side_effect = lambda u: u
    service = UserService(
        user_repository=user_repo,
        user_details_repository=MagicMock(),
        token_service=MagicMock(),
    )
    with pytest.raises(AccountTypeValidationError, match="Company is required"):
        service.admin_create(
            {
                "email": "new@x.io",
                "password": "longenough",
                "details": {"account_type": "business"},
            },
            session,
        )


def test_admin_create_business_with_company_succeeds(session):
    user_repo = MagicMock()
    user_repo.find_by_email.return_value = None
    user_repo.save.side_effect = lambda u: u
    service = UserService(
        user_repository=user_repo,
        user_details_repository=MagicMock(),
        token_service=MagicMock(),
    )
    created = service.admin_create(
        {
            "email": "new@x.io",
            "password": "longenough",
            "details": {"account_type": "business", "company": "Acme Corp"},
        },
        session,
    )
    assert created.details.account_type == "business"
    assert created.details.company == "Acme Corp"
