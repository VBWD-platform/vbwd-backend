"""``UserService.admin_create`` must run the provisioning guards before save.

No guards registered → creation is unchanged. A registered guard may veto
(raise ``UserProvisioningBlocked``, no user saved) or perform a side effect on
success. Core runs the guards; the policy lives in the plugin that registers
one.
"""
from unittest.mock import MagicMock

import pytest

from vbwd.models.enums import UserRole
from vbwd.registries.user_provisioning_guard_registry import (
    UserProvisioningBlocked,
    clear_user_provisioning_guards,
    register_user_provisioning_guard,
)
from vbwd.services.user_service import UserService


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_user_provisioning_guards()
    yield
    clear_user_provisioning_guards()


def _service_with_repo():
    user_repo = MagicMock()
    user_repo.find_by_email.return_value = None
    user_repo.save.side_effect = lambda user: user
    return (
        UserService(
            user_repository=user_repo,
            user_details_repository=MagicMock(),
            token_service=MagicMock(),
        ),
        user_repo,
    )


def _payload():
    return {"email": "new@example.com", "password": "password123", "role": "USER"}


def test_no_guards_creates_as_today():
    service, user_repo = _service_with_repo()

    created = service.admin_create(_payload(), MagicMock())

    assert created.email == "new@example.com"
    assert created.role == UserRole.USER
    user_repo.save.assert_called_once()


def test_guard_veto_blocks_and_skips_save():
    service, user_repo = _service_with_repo()

    def blocking_guard(_request):
        raise UserProvisioningBlocked("no seats", code="SEAT_LIMIT_REACHED")

    register_user_provisioning_guard(blocking_guard)

    with pytest.raises(UserProvisioningBlocked) as excinfo:
        service.admin_create(_payload(), MagicMock())

    assert excinfo.value.code == "SEAT_LIMIT_REACHED"
    user_repo.save.assert_not_called()


def test_side_effect_guard_runs_on_success():
    service, _user_repo = _service_with_repo()
    seen = []

    def counting_guard(request):
        seen.append((request.action, request.email, request.role))

    register_user_provisioning_guard(counting_guard)

    service.admin_create(_payload(), MagicMock())

    assert seen == [("create", "new@example.com", UserRole.USER)]
