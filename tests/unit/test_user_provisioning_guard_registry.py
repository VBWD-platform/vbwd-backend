"""Unit oracle for the user-provisioning guard seam (core, agnostic).

Core owns the mechanism — a ``UserProvisioningRequest`` handed to each guard
and the ``UserProvisioningBlocked`` veto a guard raises. A plugin registers a
guard to enforce its own policy (seat count / token balance); core names none.
"""
import dataclasses

import pytest

from vbwd.models.enums import UserRole
from vbwd.registries.user_provisioning_guard_registry import (
    UserProvisioningBlocked,
    UserProvisioningRequest,
    clear_user_provisioning_guards,
    register_user_provisioning_guard,
    run_user_provisioning_guards,
    user_provisioning_guards,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_user_provisioning_guards()
    yield
    clear_user_provisioning_guards()


def _request() -> UserProvisioningRequest:
    return UserProvisioningRequest(
        action="create",
        email="new@example.com",
        role=UserRole.USER,
        acting_user_id="admin-1",
        session=object(),
    )


def test_no_guards_registered_runs_clean():
    # Nothing registered → run is a no-op, no raise (core-only path unchanged).
    run_user_provisioning_guards(_request())
    assert user_provisioning_guards() == []


def test_guard_runs_for_side_effect_on_success():
    calls = []

    def counting_guard(request):
        calls.append(request)

    register_user_provisioning_guard(counting_guard)
    request = _request()
    run_user_provisioning_guards(request)

    assert calls == [request]


def test_guard_raise_vetoes():
    def blocking_guard(_request):
        raise UserProvisioningBlocked(
            "no", code="X", status=402, action_label="Buy", action_url="/buy"
        )

    register_user_provisioning_guard(blocking_guard)

    with pytest.raises(UserProvisioningBlocked) as excinfo:
        run_user_provisioning_guards(_request())

    blocked = excinfo.value
    assert blocked.message == "no"
    assert blocked.code == "X"
    assert blocked.status == 402
    assert blocked.action_label == "Buy"
    assert blocked.action_url == "/buy"


def test_first_raise_wins_later_guards_skipped():
    ran = []

    def first_guard(_request):
        ran.append("first")
        raise UserProvisioningBlocked("stop", code="FIRST")

    def second_guard(_request):
        ran.append("second")

    register_user_provisioning_guard(first_guard)
    register_user_provisioning_guard(second_guard)

    with pytest.raises(UserProvisioningBlocked) as excinfo:
        run_user_provisioning_guards(_request())

    assert excinfo.value.code == "FIRST"
    assert ran == ["first"]  # second guard never ran


def test_blocked_defaults_to_403_without_action():
    blocked = UserProvisioningBlocked("denied", code="SEAT_LIMIT_REACHED")
    assert blocked.status == 403
    assert blocked.action_label is None
    assert blocked.action_url is None


def test_request_is_frozen():
    request = _request()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.action = "mutate"  # type: ignore[misc]
