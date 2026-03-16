"""End-to-end tests for complete language flow through entire system (TDD validation)"""
import pytest
from unittest.mock import Mock
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


class TestCompleteLanguageFlow:
    """Tests validating complete end-to-end language parameter flow"""

    def _create_sample_arcanas(self, db):
        """Helper to create sample Arcana cards"""
        arcanas = []
        for i in range(3):
            arcana = Arcana(
                number=i,
                name=f"Card {i}",
                arcana_type=ArcanaType.MAJOR_ARCANA.value,
                upright_meaning="Upright meaning",
                reversed_meaning="Reversed meaning",
                image_url="https://example.com/card.jpg",
            )
            arcanas.append(arcana)
        db.session.add_all(arcanas)
        db.session.commit()
        return arcanas

    def test_complete_language_flow_situation_reading(self, db):
        """Test complete flow: route → service → prompt → LLM with language instruction"""
        # Setup: Mocked LLM adapter
        mock_llm = Mock()
        mock_llm.chat.return_value = "Ответ на русском языке"

        # Setup: Real repositories
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        # Create sample arcanas
        self._create_sample_arcanas(db)

        # Setup: Real PromptService with language templates
        prompt_service = PromptService.from_dict(
            {
                "situation_reading": {
                    "template": "You are an expert Tarot card reader.\n\nRESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}\n\nCards:\n{{cards_context}}\n\nProvide comprehensive reading:",
                    "variables": ["language", "situation_text", "cards_context"],
                }
            }
        )

        # Setup: Service with real components + mocked LLM
        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=mock_llm,
            prompt_service=prompt_service,
        )

        # Create session
        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        # Call with Russian language
        result = service.generate_situation_reading(
            session_id=str(session.id),
            situation_text="I'm facing a career decision between staying or moving forward",
            language="ru",
        )

        # Validate: LLM was called
        assert mock_llm.chat.called
        assert result == "Ответ на русском языке"

        # Validate: Language instruction in prompt
        call_args = mock_llm.chat.call_args
        prompt_sent = call_args[1]["messages"][0]["content"]
        assert "RESPOND IN Русский (Russian) LANGUAGE." in prompt_sent
        assert "I'm facing a career decision" in prompt_sent
        assert "Card" in prompt_sent  # Cards context

    @pytest.mark.parametrize(
        "lang_code,lang_name,expected_in_prompt",
        [
            ("en", "English", "RESPOND IN English LANGUAGE."),
            ("ru", "Русский (Russian)", "RESPOND IN Русский (Russian) LANGUAGE."),
            ("de", "Deutsch (German)", "RESPOND IN Deutsch (German) LANGUAGE."),
            ("fr", "Français (French)", "RESPOND IN Français (French) LANGUAGE."),
            ("es", "Español (Spanish)", "RESPOND IN Español (Spanish) LANGUAGE."),
            ("ja", "日本語 (Japanese)", "RESPOND IN 日本語 (Japanese) LANGUAGE."),
            ("th", "ไทย (Thai)", "RESPOND IN ไทย (Thai) LANGUAGE."),
            ("zh", "中文 (Chinese)", "RESPOND IN 中文 (Chinese) LANGUAGE."),
        ],
    )
    def test_all_8_languages_in_complete_flow(
        self, db, lang_code, lang_name, expected_in_prompt
    ):
        """Validate language flow works for all 8 supported languages"""
        # Setup: Mocked LLM
        mock_llm = Mock()
        mock_llm.chat.return_value = f"Response in {lang_name}"

        # Setup: Real components
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)
        self._create_sample_arcanas(db)

        prompt_service = PromptService.from_dict(
            {
                "situation_reading": {
                    "template": "RESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}\n\nCards: {{cards_context}}",
                    "variables": ["language", "situation_text", "cards_context"],
                }
            }
        )

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=mock_llm,
            prompt_service=prompt_service,
        )

        # Create session and call with language
        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        result = service.generate_situation_reading(
            session_id=str(session.id),
            situation_text="Test situation",
            language=lang_code,
        )

        # Verify language instruction in prompt
        call_args = mock_llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert expected_in_prompt in prompt

    def test_complete_flow_follow_up_question(self, db):
        """Test complete flow for follow-up question with language"""
        # Setup: Mocked LLM
        mock_llm = Mock()
        mock_llm.chat.return_value = "Oracle's French response"

        # Setup: Real components
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)
        self._create_sample_arcanas(db)

        prompt_service = PromptService.from_dict(
            {
                "follow_up_question": {
                    "template": "You are oracle.\n\nRESPOND IN {{language}} LANGUAGE.\n\nQuestion: {{question}}\n\nCards: {{cards_context}}",
                    "variables": ["language", "question", "cards_context"],
                }
            }
        )

        service = TaroSessionService(
            arcana_repo=arcana_repo,
            session_repo=session_repo,
            card_draw_repo=card_draw_repo,
            llm_adapter=mock_llm,
            prompt_service=prompt_service,
        )

        # Create session
        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        # Call with French language
        result = service.answer_oracle_question(
            session_id=str(session.id),
            question="Will my situation improve?",
            language="fr",
        )

        # Verify language instruction
        call_args = mock_llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "RESPOND IN Français (French) LANGUAGE." in prompt
        assert "Will my situation improve?" in prompt


class TestLanguageCodeConversion:
    """Tests for language code to full name conversion"""

    @pytest.mark.parametrize(
        "lang_code,expected_name",
        [
            ("en", "English"),
            ("ru", "Русский (Russian)"),
            ("de", "Deutsch (German)"),
            ("fr", "Français (French)"),
            ("es", "Español (Spanish)"),
            ("ja", "日本語 (Japanese)"),
            ("th", "ไทย (Thai)"),
            ("zh", "中文 (Chinese)"),
        ],
    )
    def test_language_code_to_name_conversion(self, lang_code, expected_name):
        """Validate language code conversion for all 8 languages"""
        result = TaroSessionService._get_language_name(lang_code)
        assert result == expected_name

    def test_language_code_uppercase_handling(self):
        """Should handle uppercase language codes"""
        assert TaroSessionService._get_language_name("RU") == "Русский (Russian)"
        assert TaroSessionService._get_language_name("DE") == "Deutsch (German)"
        assert TaroSessionService._get_language_name("FR") == "Français (French)"

    def test_language_code_mixed_case_handling(self):
        """Should handle mixed case language codes"""
        assert TaroSessionService._get_language_name("Ru") == "Русский (Russian)"
        assert TaroSessionService._get_language_name("De") == "Deutsch (German)"

    def test_invalid_language_code_defaults_to_english(self):
        """Should default to English for invalid language codes"""
        assert TaroSessionService._get_language_name("invalid") == "English"
        assert TaroSessionService._get_language_name("xx") == "English"
        assert TaroSessionService._get_language_name("") == "English"

    def test_language_conversion_preserves_special_characters(self):
        """Should preserve special characters in language names"""
        # Russian Cyrillic
        assert "Русский" in TaroSessionService._get_language_name("ru")
        # French accent
        assert "Français" in TaroSessionService._get_language_name("fr")
        # Spanish tilde
        assert "Español" in TaroSessionService._get_language_name("es")
        # Japanese characters
        assert "日本語" in TaroSessionService._get_language_name("ja")
        # Thai characters
        assert "ไทย" in TaroSessionService._get_language_name("th")
        # Chinese characters
        assert "中文" in TaroSessionService._get_language_name("zh")
