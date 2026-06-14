"""S66 — device-token route specs (wire contract for S67.2 iOS).

POST /api/v1/devices/register (JWT auth) → 201, idempotent.
DELETE /api/v1/devices/<token> (JWT auth, owner-only → 403) → 204.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

from dependency_injector import providers


@contextmanager
def override_device_token_service(client, mock_service):
    """Routes pull the service from the container; tests override the provider."""
    container = client.application.container
    container.device_token_service.override(providers.Object(mock_service))
    try:
        yield
    finally:
        container.device_token_service.reset_override()


@contextmanager
def authenticated_as(user_id):
    """Patch the auth middleware so `Bearer valid_token` resolves to user_id."""
    with patch("vbwd.middleware.auth.AuthService") as mock_auth_class, patch(
        "vbwd.middleware.auth.UserRepository"
    ) as mock_user_repo_class:
        mock_user = MagicMock()
        mock_user.status.value = "ACTIVE"
        mock_user.id = user_id

        mock_user_repo = MagicMock()
        mock_user_repo.find_by_id.return_value = mock_user
        mock_user_repo_class.return_value = mock_user_repo

        mock_auth = MagicMock()
        mock_auth.verify_token.return_value = str(user_id)
        mock_auth_class.return_value = mock_auth
        yield


AUTH_HEADERS = {"Authorization": "Bearer valid_token"}

VALID_BODY = {
    "token": "abc123devicetoken",
    "platform": "ios",
    "bundle_id": "com.vbwd.app",
    "app": "meinchat",
}


class TestRegisterDevice:
    def test_register_persists_and_returns_201(self, client):
        user_id = uuid4()
        saved_row = MagicMock()
        saved_row.to_dict.return_value = {"token": "abc123devicetoken"}
        mock_service = MagicMock()
        mock_service.register.return_value = saved_row

        with authenticated_as(user_id), override_device_token_service(
            client, mock_service
        ):
            response = client.post(
                "/api/v1/devices/register", json=VALID_BODY, headers=AUTH_HEADERS
            )

        assert response.status_code == 201
        assert response.get_json()["device"]["token"] == "abc123devicetoken"
        mock_service.register.assert_called_once_with(
            user_id=str(user_id),
            token="abc123devicetoken",
            platform="ios",
            bundle_id="com.vbwd.app",
            app="meinchat",
        )

    def test_register_requires_auth(self, client):
        response = client.post("/api/v1/devices/register", json=VALID_BODY)

        assert response.status_code == 401

    def test_register_rejects_invalid_platform_with_400(self, client):
        from vbwd.services.device_token_service import UnsupportedPlatformError

        mock_service = MagicMock()
        mock_service.register.side_effect = UnsupportedPlatformError(
            "platform must be one of: ios"
        )

        with authenticated_as(uuid4()), override_device_token_service(
            client, mock_service
        ):
            response = client.post(
                "/api/v1/devices/register",
                json={**VALID_BODY, "platform": "android"},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 400

    def test_register_rejects_missing_token_with_400(self, client):
        mock_service = MagicMock()

        with authenticated_as(uuid4()), override_device_token_service(
            client, mock_service
        ):
            response = client.post(
                "/api/v1/devices/register",
                json={**VALID_BODY, "token": "   "},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 400
        mock_service.register.assert_not_called()


class TestUnregisterDevice:
    def test_delete_own_token_returns_204(self, client):
        user_id = uuid4()
        owned_row = MagicMock()
        owned_row.user_id = user_id
        mock_service = MagicMock()
        mock_service.find_by_token.return_value = owned_row

        with authenticated_as(user_id), override_device_token_service(
            client, mock_service
        ):
            response = client.delete(
                "/api/v1/devices/abc123devicetoken", headers=AUTH_HEADERS
            )

        assert response.status_code == 204
        mock_service.unregister.assert_called_once_with("abc123devicetoken")

    def test_delete_only_owner_can_revoke(self, client):
        owner_id = uuid4()
        intruder_id = uuid4()
        owned_row = MagicMock()
        owned_row.user_id = owner_id
        mock_service = MagicMock()
        mock_service.find_by_token.return_value = owned_row

        with authenticated_as(intruder_id), override_device_token_service(
            client, mock_service
        ):
            response = client.delete(
                "/api/v1/devices/abc123devicetoken", headers=AUTH_HEADERS
            )

        assert response.status_code == 403
        mock_service.unregister.assert_not_called()

    def test_delete_unknown_token_returns_404(self, client):
        mock_service = MagicMock()
        mock_service.find_by_token.return_value = None

        with authenticated_as(uuid4()), override_device_token_service(
            client, mock_service
        ):
            response = client.delete(
                "/api/v1/devices/missingtoken", headers=AUTH_HEADERS
            )

        assert response.status_code == 404

    def test_delete_requires_auth(self, client):
        response = client.delete("/api/v1/devices/abc123devicetoken")

        assert response.status_code == 401
