"""S66 — DeviceTokenService unit specs (MagicMock repository, no DB).

The service is the core, domain-neutral device-token mechanism: idempotent
register (upsert by token — latest user wins), platform validation,
revocation via ``unregister``, and active-token lookup that excludes
revoked rows.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.services.device_token_service import (
    DeviceTokenService,
    UnsupportedPlatformError,
)


def _service_with_repo(existing_row=None):
    repository = MagicMock()
    repository.find_by_token.return_value = existing_row
    repository.save.side_effect = lambda row: row
    return DeviceTokenService(repository=repository), repository


class TestRegister:
    def test_register_creates_row_and_trims_token(self):
        service, repository = _service_with_repo()
        user_id = uuid4()

        row = service.register(
            user_id=user_id,
            token="  abc123token  ",
            platform="ios",
            bundle_id="com.vbwd.app",
            app="meinchat",
        )

        assert row.token == "abc123token"
        assert row.user_id == user_id
        assert row.platform == "ios"
        assert row.bundle_id == "com.vbwd.app"
        assert row.app == "meinchat"
        assert row.last_seen_at is not None
        assert row.revoked_at is None
        repository.find_by_token.assert_called_once_with("abc123token")
        repository.save.assert_called_once()

    def test_register_upserts_by_token_and_refreshes_last_seen(self):
        existing = MagicMock()
        existing.token = "sametoken"
        existing.last_seen_at = None
        existing.revoked_at = None
        service, repository = _service_with_repo(existing_row=existing)
        latest_user_id = uuid4()

        row = service.register(
            user_id=latest_user_id,
            token="sametoken",
            platform="ios",
            bundle_id="com.vbwd.app",
            app="meinchat",
        )

        # Upsert: the existing row is reused (no duplicate insert) and the
        # latest user wins (device handoff after wipe-and-reinstall).
        assert row is existing
        assert row.user_id == latest_user_id
        assert row.last_seen_at is not None
        repository.save.assert_called_once_with(existing)

    def test_register_reactivates_a_previously_revoked_token(self):
        existing = MagicMock()
        existing.token = "sametoken"
        existing.revoked_at = object()
        service, _ = _service_with_repo(existing_row=existing)

        row = service.register(
            user_id=uuid4(),
            token="sametoken",
            platform="ios",
            bundle_id="com.vbwd.app",
            app="meinchat",
        )

        assert row.revoked_at is None

    def test_register_rejects_unknown_platform(self):
        service, repository = _service_with_repo()

        with pytest.raises(UnsupportedPlatformError):
            service.register(
                user_id=uuid4(),
                token="sometoken",
                platform="android",
                bundle_id="com.vbwd.app",
                app="meinchat",
            )
        repository.save.assert_not_called()

    def test_register_rejects_empty_token(self):
        service, repository = _service_with_repo()

        with pytest.raises(ValueError):
            service.register(
                user_id=uuid4(),
                token="   ",
                platform="ios",
                bundle_id="com.vbwd.app",
                app="meinchat",
            )
        repository.save.assert_not_called()


class TestUnregister:
    def test_unregister_marks_revoked_at(self):
        existing = MagicMock()
        existing.revoked_at = None
        service, repository = _service_with_repo(existing_row=existing)

        row = service.unregister("sometoken")

        assert row is existing
        assert row.revoked_at is not None
        repository.save.assert_called_once_with(existing)

    def test_unregister_is_idempotent_for_already_revoked_token(self):
        already_revoked_marker = object()
        existing = MagicMock()
        existing.revoked_at = already_revoked_marker
        service, repository = _service_with_repo(existing_row=existing)

        row = service.unregister("sometoken")

        assert row is existing
        assert row.revoked_at is already_revoked_marker
        repository.save.assert_not_called()

    def test_unregister_unknown_token_returns_none(self):
        service, repository = _service_with_repo(existing_row=None)

        assert service.unregister("missing") is None
        repository.save.assert_not_called()


class TestMarkSeen:
    def test_mark_seen_refreshes_last_seen_at(self):
        existing = MagicMock()
        existing.last_seen_at = None
        service, repository = _service_with_repo(existing_row=existing)

        service.mark_seen("sometoken")

        assert existing.last_seen_at is not None
        repository.save.assert_called_once_with(existing)

    def test_mark_seen_unknown_token_is_a_noop(self):
        service, repository = _service_with_repo(existing_row=None)

        service.mark_seen("missing")

        repository.save.assert_not_called()


class TestFindActive:
    def test_find_active_delegates_to_repository(self):
        service, repository = _service_with_repo()
        active_rows = [MagicMock(), MagicMock()]
        repository.find_active_by_user_and_app.return_value = active_rows
        user_id = uuid4()

        result = service.find_active(user_id, "meinchat")

        assert result == active_rows
        repository.find_active_by_user_and_app.assert_called_once_with(
            user_id, "meinchat"
        )
