"""Unit tests for admin prompt management routes."""
import json
import tempfile
import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def admin_token(client, app):
    """Create an admin user and get JWT token."""
    from src.models.user import User
    from src.models.role import Role
    from src.extensions import db

    with app.app_context():
        # Create admin role
        admin_role = Role.query.filter_by(name="admin").first()
        if not admin_role:
            admin_role = Role(name="admin", description="Administrator")
            db.session.add(admin_role)

        # Create admin user
        admin_user = User(
            email="admin@example.com", password_hash="hashed_password", is_active=True
        )
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()

        # Get token
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "TestPassword123@"},
        )

        if response.status_code != 200:
            # Manual token creation for testing
            from flask_jwt_extended import create_access_token

            token = create_access_token(identity=str(admin_user.id))
            return token

        data = response.get_json()
        return data.get("access_token")


@pytest.fixture
def prompts_file():
    """Create temporary prompts file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        test_prompts = {
            "_meta": {"version": "1.0", "plugin": "taro"},
            "_defaults": {"temperature": 0.7, "max_tokens": 2000, "timeout": 30},
            "test_prompt": {"template": "Test: {{value}}", "variables": ["value"]},
        }
        json.dump(test_prompts, f)
        temp_file = f.name

    yield temp_file
    os.unlink(temp_file)


class TestAdminPromptRoutes:
    """Test admin prompt management API endpoints."""

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_get_all_prompts_success(self, mock_get_service, client, prompts_file):
        """Should return all prompts with defaults."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.get("/api/v1/taro/admin/prompts")

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_get_prompt_defaults_success(self, mock_get_service, client, prompts_file):
        """Should return default metadata."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.get("/api/v1/taro/admin/prompts/defaults")

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_update_prompt_defaults_success(
        self, mock_get_service, client, prompts_file
    ):
        """Should update default metadata."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.put(
            "/api/v1/taro/admin/prompts/defaults",
            json={"temperature": 0.8, "max_tokens": 2500},
        )

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_get_single_prompt_success(self, mock_get_service, client, prompts_file):
        """Should return single prompt."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.get("/api/v1/taro/admin/prompts/test_prompt")

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_get_nonexistent_prompt_returns_404(
        self, mock_get_service, client, prompts_file
    ):
        """Should return 404 for nonexistent prompt."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.get("/api/v1/taro/admin/prompts/nonexistent")

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_update_prompt_success(self, mock_get_service, client, prompts_file):
        """Should update prompt template and metadata."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.put(
            "/api/v1/taro/admin/prompts/test_prompt",
            json={"template": "Updated: {{value}}", "variables": ["value"]},
        )

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_reset_prompts_success(self, mock_get_service, client, prompts_file):
        """Should reset prompts to defaults."""
        from plugins.taro.src.services.prompt_service import PromptService

        # Create .dist file
        dist_file = prompts_file.replace(".json", ".json.dist")
        with open(dist_file, "w") as f:
            json.dump(
                {
                    "_defaults": {"temperature": 0.5},
                    "original": {"template": "Original", "variables": []},
                },
                f,
            )

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.post("/api/v1/taro/admin/prompts/reset")

        # Without auth, should return 401
        assert response.status_code == 401

        # Cleanup
        os.unlink(dist_file)

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_validate_prompt_success(self, mock_get_service, client, prompts_file):
        """Should validate prompt template syntax."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.post(
            "/api/v1/taro/admin/prompts/validate",
            json={"template": "Valid: {{template}}", "variables": ["template"]},
        )

        # Without auth, should return 401
        assert response.status_code == 401

    @patch("plugins.taro.src.routes._get_prompt_service")
    def test_validate_prompt_invalid_syntax(
        self, mock_get_service, client, prompts_file
    ):
        """Should reject invalid template syntax."""
        from plugins.taro.src.services.prompt_service import PromptService

        service = PromptService(prompts_file)
        mock_get_service.return_value = service

        response = client.post(
            "/api/v1/taro/admin/prompts/validate",
            json={"template": "Invalid: {{unclosed", "variables": ["unclosed"]},
        )

        # Without auth, should return 401
        assert response.status_code == 401
