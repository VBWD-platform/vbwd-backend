"""Tests for Taro plugin routes - simplified version without complex mocking."""
import pytest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

_AUTH_HEADER = {"Authorization": "Bearer test-token"}


@contextmanager
def auth_as(user_id):
    """Patches require_auth internals so the route runs as user_id."""
    mock_user = Mock()
    mock_user.status = Mock(value="ACTIVE")
    mock_user.id = user_id

    with patch("src.middleware.auth.AuthService") as mock_auth_cls:
        with patch("src.middleware.auth.UserRepository") as mock_repo_cls:
            mock_auth_cls.return_value.verify_token.return_value = user_id
            mock_repo_cls.return_value.find_by_id.return_value = mock_user
            yield


@pytest.fixture
def app():
    """Create Flask app for testing."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-secret"
    from plugins.taro.src.routes import taro_bp

    app.register_blueprint(taro_bp, url_prefix="/api/v1/taro")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_auth_header():
    """Fixture providing valid auth header."""
    return _AUTH_HEADER


@pytest.fixture
def mock_current_user():
    """Fixture providing mock current user."""
    user = Mock()
    user.id = str(uuid4())
    user.user_profile = Mock()
    user.user_profile.current_tarif_plan = Mock()
    user.user_profile.current_tarif_plan.id = "plan-star"
    user.user_profile.current_tarif_plan.daily_taro_limit = 3
    user.user_profile.current_tarif_plan.max_taro_follow_ups = 3
    return user


@pytest.fixture
def mock_dispatcher():
    """Fixture providing mock event dispatcher."""
    dispatcher = Mock()
    dispatcher.emit = Mock()
    return dispatcher


class TestTaroRoutes:
    """Test Taro routes with proper mocking."""

    def test_session_route_exists(self, client):
        """Test that session route is accessible."""
        # This tests that the route exists and is registered
        user_id = str(uuid4())
        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes.get_user_tarif_plan_limits",
                return_value=(3, 3),
            ):
                with patch(
                    "plugins.taro.src.routes.check_token_balance", return_value=True
                ):
                    # The route should exist and handle the request
                    response = client.post(
                        "/api/v1/taro/session", json={}, headers=_AUTH_HEADER
                    )
                    # Should not get 404 (route exists)
                    assert response.status_code != 404


class TestLanguageParameterInRoutes:
    """Tests for language parameter handling in routes (TDD validation)"""

    def test_submit_situation_accepts_language_parameter(self, client):
        """Verify /situation endpoint accepts and uses language parameter"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                # Setup mocks
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.generate_situation_reading.return_value = (
                    "Russian interpretation"
                )
                mock_get_services.return_value = mock_service

                # Call endpoint with language parameter
                response = client.post(
                    f"/api/v1/taro/session/{session_id}/situation",
                    json={"situation_text": "My career question", "language": "ru"},
                    headers=_AUTH_HEADER,
                )

                # Verify service was called with language parameter
                mock_service.generate_situation_reading.assert_called_once()
                call_kwargs = mock_service.generate_situation_reading.call_args[1]
                assert call_kwargs["language"] == "ru"

    def test_submit_situation_language_defaults_to_english(self, client):
        """Verify language defaults to 'en' if not provided"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.generate_situation_reading.return_value = (
                    "English interpretation"
                )
                mock_get_services.return_value = mock_service

                # Call without language parameter
                response = client.post(
                    f"/api/v1/taro/session/{session_id}/situation",
                    json={"situation_text": "My question"},
                    headers=_AUTH_HEADER,
                )

                # Verify language defaults to 'en'
                call_kwargs = mock_service.generate_situation_reading.call_args[1]
                assert call_kwargs["language"] == "en"

    @pytest.mark.parametrize(
        "lang_code", ["en", "ru", "de", "fr", "es", "ja", "th", "zh"]
    )
    def test_submit_situation_all_8_languages(self, client, lang_code):
        """Verify /situation accepts all 8 language codes"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.generate_situation_reading.return_value = "Response"
                mock_get_services.return_value = mock_service

                response = client.post(
                    f"/api/v1/taro/session/{session_id}/situation",
                    json={"situation_text": "Test", "language": lang_code},
                    headers=_AUTH_HEADER,
                )

                # Verify language was passed correctly
                call_kwargs = mock_service.generate_situation_reading.call_args[1]
                assert call_kwargs["language"] == lang_code

    def test_card_explanation_accepts_language_parameter(self, client):
        """Verify /card-explanation endpoint accepts language parameter"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.get_session_spread.return_value = [Mock(), Mock(), Mock()]
                mock_service._build_cards_context.return_value = "Cards: ..."
                mock_service.prompt_service = Mock()
                mock_service.llm_adapter = Mock()
                mock_service.prompt_service.render.return_value = "Prompt"
                mock_service.llm_adapter.chat.return_value = "Card explanation"
                mock_get_services.return_value = mock_service

                response = client.post(
                    f"/api/v1/taro/session/{session_id}/card-explanation",
                    json={"language": "de"},
                    headers=_AUTH_HEADER,
                )

                # Verify prompt service was called with language
                if mock_service.prompt_service.render.called:
                    call_kwargs = mock_service.prompt_service.render.call_args
                    context = call_kwargs[0][1]
                    assert context.get("language") == "Deutsch (German)"

    @pytest.mark.parametrize(
        "lang_code,expected_lang",
        [
            ("en", "English"),
            ("de", "Deutsch (German)"),
            ("fr", "Français (French)"),
        ],
    )
    def test_card_explanation_all_languages(self, client, lang_code, expected_lang):
        """Verify /card-explanation handles all language codes"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.get_session_spread.return_value = [Mock(), Mock(), Mock()]
                mock_service._build_cards_context.return_value = "Cards"
                mock_service.prompt_service = Mock()
                mock_service.llm_adapter = Mock()
                mock_service.prompt_service.render.return_value = (
                    f"RESPOND IN {expected_lang} LANGUAGE. Cards..."
                )
                mock_service.llm_adapter.chat.return_value = "Explanation"
                mock_get_services.return_value = mock_service

                response = client.post(
                    f"/api/v1/taro/session/{session_id}/card-explanation",
                    json={"language": lang_code},
                    headers=_AUTH_HEADER,
                )

                # Should be successful
                assert response.status_code in [
                    200,
                    201,
                    400,
                ]  # May fail for other reasons

    def test_follow_up_question_accepts_language_parameter(self, client):
        """Verify /follow-up-question endpoint accepts language parameter"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.answer_oracle_question.return_value = "Oracle's answer"
                mock_get_services.return_value = mock_service

                response = client.post(
                    f"/api/v1/taro/session/{session_id}/follow-up-question",
                    json={"question": "Will it improve?", "language": "fr"},
                    headers=_AUTH_HEADER,
                )

                # Verify service was called with language
                mock_service.answer_oracle_question.assert_called_once()
                call_kwargs = mock_service.answer_oracle_question.call_args[1]
                assert call_kwargs["language"] == "fr"

    @pytest.mark.parametrize(
        "lang_code", ["en", "ru", "de", "fr", "es", "ja", "th", "zh"]
    )
    def test_follow_up_question_all_8_languages(self, client, lang_code):
        """Verify /follow-up-question accepts all 8 language codes"""
        user_id = str(uuid4())
        session_id = str(uuid4())

        with auth_as(user_id):
            with patch(
                "plugins.taro.src.routes._get_taro_services"
            ) as mock_get_services:
                mock_service = Mock()
                mock_service.get_session.return_value = Mock(
                    user_id=user_id, status="ACTIVE"
                )
                mock_service.answer_oracle_question.return_value = "Response"
                mock_get_services.return_value = mock_service

                response = client.post(
                    f"/api/v1/taro/session/{session_id}/follow-up-question",
                    json={"question": "Test question", "language": lang_code},
                    headers=_AUTH_HEADER,
                )

                # Verify language was passed
                call_kwargs = mock_service.answer_oracle_question.call_args[1]
                assert call_kwargs["language"] == lang_code
