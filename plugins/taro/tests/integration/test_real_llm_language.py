"""Integration tests for real LLM communication with language parameters.

These tests use actual LLM API to validate language parameter flow end-to-end.
Requires valid API credentials in vbwd-backend/plugins/config.json.

To run:
    pytest plugins/taro/tests/integration/test_real_llm_language.py -v -s

Environment variables:
    SKIP_LLM_TESTS=1  - Skip real LLM tests (useful for CI without API keys)
"""
import pytest
import json
import os
from uuid import uuid4

from plugins.taro.src.services.taro_session_service import TaroSessionService
from plugins.taro.src.services.prompt_service import PromptService
from plugins.taro.src.repositories.arcana_repository import ArcanaRepository
from plugins.taro.src.repositories.taro_session_repository import TaroSessionRepository
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType
from plugins.chat.src.llm_adapter import LLMAdapter, LLMError


def load_taro_config():
    """Load Taro configuration from plugins/config.json"""
    config_path = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        "config.json",
    )

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        config = json.load(f)

    return config.get("taro", {})


@pytest.fixture
def taro_config():
    """Fixture providing loaded Taro configuration"""
    try:
        return load_taro_config()
    except FileNotFoundError:
        pytest.skip("plugins/config.json not found — skipping config-dependent test")


@pytest.fixture
def llm_adapter(taro_config):
    """Fixture providing real LLM adapter with actual credentials"""
    api_endpoint = taro_config.get("llm_api_endpoint")
    api_key = taro_config.get("llm_api_key")
    model = taro_config.get("llm_model", "deepseek-reasoner")

    if not api_endpoint or not api_key:
        pytest.skip("LLM credentials not configured")

    return LLMAdapter(
        api_endpoint=api_endpoint,
        api_key=api_key,
        model=model,
        system_prompt="You are an expert Tarot card reader providing mystical insights.",
        timeout=60,
    )


@pytest.fixture
def prompt_service(taro_config):
    """Fixture providing PromptService with config templates"""
    prompts_data = {
        "situation_reading": {
            "template": "You are an expert Tarot card reader.\n\nRESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}\n\nCards:\n{{cards_context}}\n\nProvide a brief reading:",
            "variables": ["language", "situation_text", "cards_context"],
        },
        "card_explanation": {
            "template": "You are an expert.\n\nRESPOND IN {{language}} LANGUAGE.\n\nCards: {{cards_context}}\n\nExplain the cards:",
            "variables": ["language", "cards_context"],
        },
        "follow_up_question": {
            "template": "You are oracle.\n\nRESPOND IN {{language}} LANGUAGE.\n\nQuestion: {{question}}\n\nAnswer:",
            "variables": ["language", "question"],
        },
    }

    return PromptService.from_dict(prompts_data)


@pytest.mark.skipif(
    os.getenv("SKIP_LLM_TESTS") == "1",
    reason="Skipping real LLM tests (set SKIP_LLM_TESTS=1 to skip)",
)
class TestRealLLMLanguageCommunication:
    """Integration tests with real LLM API communication"""

    def _create_sample_arcanas(self, db):
        """Helper to create sample Arcana cards"""
        arcanas = []
        for i in range(3):
            arcana = Arcana(
                number=i,
                name=f"The {['Magician', 'High Priestess', 'Empress'][i]}",
                arcana_type=ArcanaType.MAJOR_ARCANA.value,
                upright_meaning="Upright meaning",
                reversed_meaning="Reversed meaning",
                image_url="https://example.com/card.jpg",
            )
            arcanas.append(arcana)
        db.session.add_all(arcanas)
        db.session.commit()
        return arcanas

    def test_real_llm_situation_reading_with_russian_language(
        self, db, llm_adapter, prompt_service
    ):
        """Test real LLM communication with Russian language instruction"""
        # Setup: Real repositories
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        # Setup: Service with real LLM adapter
        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=llm_adapter,
            prompt_service=prompt_service,
        )

        # Create session
        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        # Call service with Russian language
        try:
            result = service.generate_situation_reading(
                session_id=str(session.id),
                situation_text="I am facing a major life decision",
                language="ru",
            )

            # Validate: Got a response
            assert result is not None
            assert len(result) > 0

            # Validate: Response is substantial (not just echo)
            assert len(result) > 10

            # Log the response for manual inspection
            print(f"\n✅ Russian LLM Response:\n{result}\n")

        except LLMError as e:
            pytest.fail(f"LLM API call failed: {e}")

    def test_real_llm_with_german_language(self, db, llm_adapter, prompt_service):
        """Test real LLM communication with German language instruction"""
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=llm_adapter,
            prompt_service=prompt_service,
        )

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        try:
            result = service.generate_situation_reading(
                session_id=str(session.id),
                situation_text="Ich habe eine wichtige Entscheidung zu treffen",
                language="de",
            )

            assert result is not None
            assert len(result) > 10

            print(f"\n✅ German LLM Response:\n{result}\n")

        except LLMError as e:
            pytest.fail(f"LLM API call failed: {e}")

    def test_real_llm_with_french_language(self, db, llm_adapter, prompt_service):
        """Test real LLM communication with French language instruction"""
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=llm_adapter,
            prompt_service=prompt_service,
        )

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        try:
            result = service.generate_situation_reading(
                session_id=str(session.id),
                situation_text="Je dois prendre une décision importante",
                language="fr",
            )

            assert result is not None
            assert len(result) > 10

            print(f"\n✅ French LLM Response:\n{result}\n")

        except LLMError as e:
            pytest.fail(f"LLM API call failed: {e}")

    def test_real_llm_follow_up_question_with_language(
        self, db, llm_adapter, prompt_service
    ):
        """Test real LLM communication for follow-up questions with language"""
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=llm_adapter,
            prompt_service=prompt_service,
        )

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        try:
            # Test with Spanish language
            result = service.answer_oracle_question(
                session_id=str(session.id),
                question="¿Cuál es el siguiente paso?",
                language="es",
            )

            assert result is not None
            assert len(result) > 10

            print(f"\n✅ Spanish Follow-up Response:\n{result}\n")

        except LLMError as e:
            pytest.fail(f"LLM API call failed: {e}")

    def test_real_llm_language_instruction_in_response(
        self, db, llm_adapter, prompt_service
    ):
        """Test that LLM actually receives and respects language instruction"""
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=llm_adapter,
            prompt_service=prompt_service,
        )

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        try:
            # Get Russian response
            russian_result = service.generate_situation_reading(
                session_id=str(session.id),
                situation_text="A career question",
                language="ru",
            )

            # Get English response (for comparison)
            english_result = service.generate_situation_reading(
                session_id=str(session.id),
                situation_text="A career question",
                language="en",
            )

            # Validate both got responses
            assert russian_result is not None
            assert english_result is not None
            assert len(russian_result) > 10
            assert len(english_result) > 10

            print(f"\n✅ Russian Response:\n{russian_result}\n")
            print(f"\n✅ English Response:\n{english_result}\n")

            # Note: We can't easily programmatically validate language detection
            # for non-English responses, but manual inspection will confirm

        except LLMError as e:
            pytest.fail(f"LLM API call failed: {e}")

    def test_real_llm_error_handling(self, db, prompt_service):
        """Test error handling with invalid LLM credentials"""
        from plugins.chat.src.llm_adapter import LLMAdapter as BadLLMAdapter

        # Create adapter with invalid credentials
        bad_llm = BadLLMAdapter(
            api_endpoint="https://api.invalid.com",
            api_key="invalid-key-12345",
            model="invalid-model",
            timeout=5,
        )

        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        self._create_sample_arcanas(db)

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=bad_llm,
            prompt_service=prompt_service,
        )

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        # Should raise LLMError with invalid credentials
        with pytest.raises(LLMError):
            service.generate_situation_reading(
                session_id=str(session.id), situation_text="Test", language="ru"
            )


class TestLLMConfigurationLoading:
    """Tests for loading and validating LLM configuration"""

    def test_load_taro_config_from_file(self):
        """Test loading Taro config from plugins/config.json"""
        try:
            config = load_taro_config()
        except FileNotFoundError:
            pytest.skip("plugins/config.json not found — skipping config loading test")

        # Validate required fields exist
        assert "llm_api_endpoint" in config
        assert "llm_api_key" in config
        assert "llm_model" in config
        assert "system_prompt" in config

    def test_taro_config_has_language_templates(self):
        """Test that config has templates with language support"""
        try:
            config = load_taro_config()
        except FileNotFoundError:
            pytest.skip("plugins/config.json not found — skipping config loading test")

        # Note: The current config may not have {{language}} yet
        # This test documents what we expect after the fix
        assert "situation_reading_template" in config
        assert "card_explanation_template" in config
        assert "follow_up_question_template" in config

    def test_create_llm_adapter_from_config(self, taro_config):
        """Test creating LLMAdapter from actual config"""
        api_endpoint = taro_config.get("llm_api_endpoint")
        api_key = taro_config.get("llm_api_key")
        model = taro_config.get("llm_model")

        if not api_endpoint or not api_key:
            pytest.skip("LLM credentials not configured")

        # Should be able to create adapter without errors
        adapter = LLMAdapter(
            api_endpoint=api_endpoint,
            api_key=api_key,
            model=model,
            timeout=30,
        )

        assert adapter is not None
        assert adapter.api_endpoint is not None
        assert adapter.model == model

    def test_prompt_service_loads_from_config_templates(self, taro_config):
        """Test that PromptService can be created from config templates"""
        prompts_data = {
            "situation_reading": {
                "template": taro_config.get("situation_reading_template", ""),
                "variables": ["language", "situation_text", "cards_context"],
            }
        }

        # Should be able to create PromptService from config
        service = PromptService.from_dict(prompts_data)

        assert service is not None
        assert "situation_reading" in service.prompts
