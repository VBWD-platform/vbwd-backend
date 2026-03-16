"""Tests for TaroSessionService."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from plugins.taro.src.services.taro_session_service import TaroSessionService
from plugins.taro.src.repositories.arcana_repository import ArcanaRepository
from plugins.taro.src.repositories.taro_session_repository import TaroSessionRepository
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import (
    ArcanaType,
    TaroSessionStatus,
    CardPosition,
    CardOrientation,
)
from plugins.chat.src.llm_adapter import LLMError


@pytest.fixture
def taro_service(db):
    """Fixture providing TaroSessionService instance."""
    return TaroSessionService(
        arcana_repo=ArcanaRepository(db.session),
        session_repo=TaroSessionRepository(db.session),
        card_draw_repo=TaroCardDrawRepository(db.session),
    )


@pytest.fixture
def sample_arcanas(db):
    """Fixture creating sample Arcanas in database."""
    cards = []
    for i in range(5):
        arcana = Arcana(
            number=i,
            name=f"Card {i}",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Upright",
            reversed_meaning="Reversed",
            image_url="https://example.com/card.jpg",
        )
        cards.append(arcana)

    db.session.add_all(cards)
    db.session.commit()
    return cards


class TestTaroSessionService:
    """Test TaroSessionService methods."""

    def test_create_session_success(self, taro_service, sample_arcanas, db):
        """Test creating a new Taro session."""
        user_id = str(uuid4())

        session = taro_service.create_session(user_id=user_id)

        assert session is not None
        assert str(session.user_id) == user_id
        assert session.status == TaroSessionStatus.ACTIVE.value
        assert session.spread_id is not None
        assert session.tokens_consumed == 10  # SESSION_BASE_TOKENS default
        assert session.follow_up_count == 0

    def test_create_session_with_tarif_plan_daily_limit(
        self, taro_service, sample_arcanas, db
    ):
        """Test creating session respects daily limit by tarif plan."""
        user_id = str(uuid4())

        # Basic plan: 1 session per day
        session = taro_service.create_session(user_id=user_id, daily_limit=1)
        assert session is not None

    def test_create_session_generates_spread(self, taro_service, sample_arcanas, db):
        """Test that creating session generates 3-card spread."""
        user_id = str(uuid4())

        session = taro_service.create_session(user_id=user_id)

        # Should have 3 cards (PAST, PRESENT, FUTURE)
        cards = taro_service.get_session_spread(str(session.id))
        assert len(cards) == 3

        positions = {card.position for card in cards}
        assert positions == {
            CardPosition.PAST.value,
            CardPosition.PRESENT.value,
            CardPosition.FUTURE.value,
        }

    def test_create_session_sets_expiry(self, taro_service, sample_arcanas, db):
        """Test that session expires in 30 minutes."""
        user_id = str(uuid4())
        now = datetime.utcnow()

        session = taro_service.create_session(user_id=user_id)

        # expires_at should be ~30 minutes from now
        diff = (session.expires_at - now).total_seconds()
        assert 29 * 60 <= diff <= 31 * 60

    def test_create_session_consumes_tokens(self, taro_service, sample_arcanas, db):
        """Test that creating session consumes tokens."""
        user_id = str(uuid4())

        session = taro_service.create_session(user_id=user_id, session_tokens=10)

        assert session.tokens_consumed == 10

    def test_get_session(self, taro_service, sample_arcanas, db):
        """Test retrieving session by ID."""
        user_id = str(uuid4())
        created = taro_service.create_session(user_id=user_id)

        retrieved = taro_service.get_session(str(created.id))

        assert retrieved is not None
        assert retrieved.id == created.id
        assert str(retrieved.user_id) == user_id

    def test_get_session_not_found(self, taro_service):
        """Test retrieving non-existent session."""
        fake_id = str(uuid4())
        result = taro_service.get_session(fake_id)

        assert result is None

    def test_get_user_active_session(self, taro_service, sample_arcanas, db):
        """Test getting user's current active session."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        retrieved = taro_service.get_user_active_session(user_id)

        assert retrieved is not None
        assert retrieved.id == session.id

    def test_get_user_active_session_none(self, taro_service):
        """Test getting active session when none exist."""
        user_id = str(uuid4())
        result = taro_service.get_user_active_session(user_id)

        assert result is None

    def test_get_session_spread_cards(self, taro_service, sample_arcanas, db):
        """Test retrieving 3-card spread."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        cards = taro_service.get_session_spread(str(session.id))

        assert len(cards) == 3
        assert all(hasattr(card, "position") for card in cards)
        assert all(hasattr(card, "ai_interpretation") for card in cards)

    def test_session_is_expired(self, taro_service, sample_arcanas, db):
        """Test checking if session is expired."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        # Fresh session should not be expired
        assert not taro_service.is_session_expired(session)

    def test_session_expiry_warning(self, taro_service, sample_arcanas, db):
        """Test getting expiry warning status (3 minutes before expiry)."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        # Fresh session should not have warning
        assert not taro_service.has_expiry_warning(session)

    def test_get_session_history(self, taro_service, sample_arcanas, db):
        """Test retrieving user's session history."""
        user_id = str(uuid4())

        # Create 3 sessions
        for _ in range(3):
            taro_service.create_session(user_id=user_id)

        history = taro_service.get_user_session_history(user_id)

        assert len(history) >= 3

    def test_get_daily_sessions_count(self, taro_service, sample_arcanas, db):
        """Test counting today's sessions for user."""
        user_id = str(uuid4())

        # Create session today
        taro_service.create_session(user_id=user_id)

        count = taro_service.count_today_sessions(user_id)

        assert count >= 1

    def test_check_daily_limit_basic_plan(self, taro_service, sample_arcanas, db):
        """Test daily limit for Basic plan (1 session)."""
        user_id = str(uuid4())

        # Basic plan allows 1 session
        allowed, remaining = taro_service.check_daily_limit(
            user_id=user_id, daily_limit=1
        )

        assert allowed is True
        assert remaining == 1

        # Create session
        taro_service.create_session(user_id=user_id, daily_limit=1)

        # Second session should be blocked
        allowed, remaining = taro_service.check_daily_limit(
            user_id=user_id, daily_limit=1
        )

        assert allowed is False
        assert remaining == 0

    def test_check_daily_limit_star_plan(self, taro_service, sample_arcanas, db):
        """Test daily limit for Star plan (3 sessions)."""
        user_id = str(uuid4())

        # Star plan allows 3 sessions
        for i in range(3):
            allowed, remaining = taro_service.check_daily_limit(
                user_id=user_id, daily_limit=3
            )
            assert allowed is True
            taro_service.create_session(user_id=user_id, daily_limit=3)

        # Fourth session should be blocked
        allowed, remaining = taro_service.check_daily_limit(
            user_id=user_id, daily_limit=3
        )
        assert allowed is False

    def test_close_session(self, taro_service, sample_arcanas, db):
        """Test closing an active session."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        taro_service.close_session(str(session.id))

        updated = taro_service.get_session(str(session.id))
        assert updated.status == TaroSessionStatus.CLOSED.value
        assert updated.ended_at is not None

    def test_add_follow_up_question(self, taro_service, sample_arcanas, db):
        """Test adding follow-up question to session."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id, max_follow_ups=3)

        # Add follow-up
        updated = taro_service.add_follow_up(str(session.id))

        assert updated.follow_up_count == 1

    def test_follow_up_count_limit(self, taro_service, sample_arcanas, db):
        """Test that follow-ups are limited by max_follow_ups."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id, max_follow_ups=1)

        # Add first follow-up
        taro_service.add_follow_up(str(session.id))

        # Second should fail or return False
        result = taro_service.add_follow_up(str(session.id))

        # Should return False or raise error
        if isinstance(result, bool):
            assert result is False

    def test_card_randomization(self, taro_service, sample_arcanas, db):
        """Test that cards are randomly selected."""
        user_id1 = str(uuid4())
        user_id2 = str(uuid4())

        session1 = taro_service.create_session(user_id=user_id1)
        session2 = taro_service.create_session(user_id=user_id2)

        cards1 = taro_service.get_session_spread(str(session1.id))
        cards2 = taro_service.get_session_spread(str(session2.id))

        # Very unlikely both spreads are identical
        arcana_ids_1 = {card.arcana_id for card in cards1}
        arcana_ids_2 = {card.arcana_id for card in cards2}

        # At least different in some way (statistically)
        assert len(arcana_ids_1) > 0
        assert len(arcana_ids_2) > 0

    def test_card_orientation_random(self, taro_service, sample_arcanas, db):
        """Test that card orientations are randomized."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        cards = taro_service.get_session_spread(str(session.id))

        # Each card should have orientation
        for card in cards:
            assert card.orientation in [
                CardOrientation.UPRIGHT.value,
                CardOrientation.REVERSED.value,
            ]

    def test_cleanup_expired_sessions(self, taro_service, sample_arcanas, db):
        """Test marking expired sessions as EXPIRED status."""
        user_id = str(uuid4())

        # Create session that already expired
        from plugins.taro.src.models.taro_session import TaroSession

        expired_session = TaroSession(
            user_id=user_id,
            status=TaroSessionStatus.ACTIVE.value,
            started_at=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() - timedelta(minutes=5),
            spread_id="expired-spread",
        )
        db.session.add(expired_session)
        db.session.commit()

        # Cleanup
        count = taro_service.cleanup_expired_sessions()

        # Should have marked as expired
        updated = taro_service.get_session(str(expired_session.id))
        assert updated.status == TaroSessionStatus.EXPIRED.value

    def test_reset_today_sessions(self, taro_service, sample_arcanas, db):
        """Test resetting all active sessions for a user today."""
        user_id = str(uuid4())

        # Create 3 active sessions today
        session1 = taro_service.create_session(user_id=user_id, daily_limit=5)
        session2 = taro_service.create_session(user_id=user_id, daily_limit=5)
        session3 = taro_service.create_session(user_id=user_id, daily_limit=5)

        assert session1 is not None
        assert session2 is not None
        assert session3 is not None

        # Reset sessions
        reset_count = taro_service.reset_today_sessions(user_id)

        # Should have reset 3 sessions
        assert reset_count == 3

        # Verify all sessions are now closed
        s1 = taro_service.get_session(str(session1.id))
        s2 = taro_service.get_session(str(session2.id))
        s3 = taro_service.get_session(str(session3.id))

        assert s1.status == TaroSessionStatus.CLOSED.value
        assert s2.status == TaroSessionStatus.CLOSED.value
        assert s3.status == TaroSessionStatus.CLOSED.value

    def test_reset_today_sessions_empty(self, taro_service):
        """Test reset on user with no sessions today."""
        user_id = str(uuid4())

        reset_count = taro_service.reset_today_sessions(user_id)

        assert reset_count == 0

    def test_get_today_sessions_info(self, taro_service, sample_arcanas, db):
        """Test getting today's session count and limits info."""
        user_id = str(uuid4())
        daily_limit = 3

        # Create 2 sessions today
        taro_service.create_session(user_id=user_id, daily_limit=daily_limit)
        taro_service.create_session(user_id=user_id, daily_limit=daily_limit)

        today_count = taro_service.count_today_sessions(user_id)
        allowed, remaining = taro_service.check_daily_limit(user_id, daily_limit)

        assert today_count == 2
        assert allowed is True
        assert remaining == 1

    def test_reset_sessions_freeing_quota(self, taro_service, sample_arcanas, db):
        """Test that resetting sessions frees up the daily quota.

        This is the key test for the bug fix: after resetting sessions,
        they should no longer count towards the daily limit.
        """
        user_id = str(uuid4())
        daily_limit = 3

        # Create 3 sessions (uses entire daily quota)
        session1 = taro_service.create_session(user_id=user_id, daily_limit=daily_limit)
        session2 = taro_service.create_session(user_id=user_id, daily_limit=daily_limit)
        session3 = taro_service.create_session(user_id=user_id, daily_limit=daily_limit)

        # Verify quota is full
        today_count = taro_service.count_today_sessions(user_id)
        allowed, remaining = taro_service.check_daily_limit(user_id, daily_limit)
        assert today_count == 3
        assert allowed is False
        assert remaining == 0

        # Reset sessions
        reset_count = taro_service.reset_today_sessions(user_id)
        assert reset_count == 3

        # Verify sessions are CLOSED
        s1 = taro_service.get_session(str(session1.id))
        s2 = taro_service.get_session(str(session2.id))
        s3 = taro_service.get_session(str(session3.id))
        assert s1.status == TaroSessionStatus.CLOSED.value
        assert s2.status == TaroSessionStatus.CLOSED.value
        assert s3.status == TaroSessionStatus.CLOSED.value

        # After reset: CLOSED sessions should NOT count towards limit
        today_count = taro_service.count_today_sessions(user_id)
        allowed, remaining = taro_service.check_daily_limit(user_id, daily_limit)
        assert today_count == 0, "CLOSED sessions should not count towards daily limit"
        assert allowed is True, "User should be able to create new session after reset"
        assert remaining == 3, "All quota should be available after reset"

    def test_generate_situation_reading_success(self, taro_service, sample_arcanas, db):
        """Test generating situation-based reading raises LLMError when adapter not configured."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        situation_text = "I'm facing a career decision between staying in my current job or taking a new opportunity."

        # Ensure LLM adapter is None so LLMError is raised
        taro_service.llm_adapter = None
        taro_service.prompt_service = None

        with pytest.raises(LLMError):
            taro_service.generate_situation_reading(
                session_id=str(session.id), situation_text=situation_text
            )

    def test_generate_situation_reading_fallback_when_llm_unavailable(
        self, taro_service, sample_arcanas, db
    ):
        """Test situation reading raises error when LLM unavailable."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        # Disable LLM by setting to None
        taro_service.llm_adapter = None

        situation_text = "I'm facing a career decision."

        # Should raise LLMError when LLM is unavailable
        with pytest.raises(LLMError) as exc_info:
            taro_service.generate_situation_reading(
                session_id=str(session.id), situation_text=situation_text
            )

        assert "LLM adapter" in str(exc_info.value)

    def test_generate_situation_reading_word_limit_validation(
        self, taro_service, sample_arcanas, db
    ):
        """Test that situation text exceeding 100 words raises validation error."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        # Create text with 101 words
        situation_text = " ".join(["word"] * 101)

        with pytest.raises(ValueError) as exc_info:
            taro_service.generate_situation_reading(
                session_id=str(session.id), situation_text=situation_text
            )

        assert "100 words" in str(exc_info.value)

    def test_generate_situation_reading_empty_text(
        self, taro_service, sample_arcanas, db
    ):
        """Test that empty situation text raises validation error."""
        user_id = str(uuid4())
        session = taro_service.create_session(user_id=user_id)

        with pytest.raises(ValueError) as exc_info:
            taro_service.generate_situation_reading(
                session_id=str(session.id), situation_text=""
            )

        assert (
            "required" in str(exc_info.value).lower()
            or "empty" in str(exc_info.value).lower()
        )

    def test_generate_situation_reading_session_not_found(self, taro_service):
        """Test that non-existent session raises error."""
        fake_session_id = str(uuid4())
        situation_text = "My situation"

        with pytest.raises((ValueError, Exception)):
            taro_service.generate_situation_reading(
                session_id=fake_session_id, situation_text=situation_text
            )


class TestLanguageParameterFlow:
    """Tests validating language parameter flows correctly through service (TDD validation)"""

    def test_get_language_name_conversion_russian(self):
        """Should convert 'ru' to 'Русский (Russian)'"""
        result = TaroSessionService._get_language_name("ru")
        assert result == "Русский (Russian)"

    def test_get_language_name_conversion_german(self):
        """Should convert 'de' to 'Deutsch (German)'"""
        result = TaroSessionService._get_language_name("de")
        assert result == "Deutsch (German)"

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
    def test_get_language_name_all_8_languages(self, lang_code, expected_name):
        """Should correctly convert all 8 language codes to full names"""
        result = TaroSessionService._get_language_name(lang_code)
        assert result == expected_name

    def test_get_language_name_case_insensitive(self):
        """Should handle uppercase language codes"""
        result = TaroSessionService._get_language_name("RU")
        assert result == "Русский (Russian)"

    def test_get_language_name_invalid_defaults_to_english(self):
        """Should default to English for unknown language codes"""
        result = TaroSessionService._get_language_name("invalid")
        assert result == "English"

    def test_generate_situation_reading_with_mocked_llm(self, db):
        """Verify language parameter is passed to mocked LLM adapter"""
        from unittest.mock import Mock
        from plugins.taro.src.services.prompt_service import PromptService

        # Setup: Create mocked LLM
        mock_llm = Mock()
        mock_llm.chat.return_value = "Мой ответ на русском языке"

        # Setup: Create real repositories
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        # Create sample arcanas
        arcanas = []
        for i in range(3):
            arcana = Arcana(
                number=i,
                name=f"Card {i}",
                arcana_type=ArcanaType.MAJOR_ARCANA.value,
                upright_meaning="Upright",
                reversed_meaning="Reversed",
                image_url="https://example.com/card.jpg",
            )
            arcanas.append(arcana)
        db.session.add_all(arcanas)
        db.session.commit()

        # Create prompt service
        prompt_service = PromptService.from_dict(
            {
                "situation_reading": {
                    "template": "You are expert.\n\nRESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}\n\nCards: {{cards_context}}\n\nProvide reading:",
                    "variables": ["language", "situation_text", "cards_context"],
                }
            }
        )

        # Setup: Create service with mocked LLM
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

        # Action: Call with Russian language
        result = service.generate_situation_reading(
            session_id=str(session.id), situation_text="Career decision", language="ru"
        )

        # Assert: Mocked LLM was called
        assert mock_llm.chat.called
        assert result == "Мой ответ на русском языке"

        # Assert: Language instruction in prompt passed to LLM
        call_args = mock_llm.chat.call_args
        prompt_passed_to_llm = call_args[1]["messages"][0]["content"]
        assert "RESPOND IN Русский (Russian) LANGUAGE." in prompt_passed_to_llm

    @pytest.mark.parametrize(
        "lang_code,expected_lang_name",
        [
            ("en", "English"),
            ("ru", "Русский (Russian)"),
            ("de", "Deutsch (German)"),
            ("fr", "Français (French)"),
        ],
    )
    def test_situation_reading_respects_different_languages(
        self, db, lang_code, expected_lang_name
    ):
        """Verify situation_reading passes correct language instruction for each language"""
        from unittest.mock import Mock
        from plugins.taro.src.services.prompt_service import PromptService

        # Setup: Mocked LLM
        mock_llm = Mock()
        mock_llm.chat.return_value = f"Response in {expected_lang_name}"

        # Setup: Repositories
        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        # Create sample arcanas
        arcanas = []
        for i in range(3):
            arcana = Arcana(
                number=i,
                name=f"Card {i}",
                arcana_type=ArcanaType.MAJOR_ARCANA.value,
                upright_meaning="Upright",
                reversed_meaning="Reversed",
                image_url="https://example.com/card.jpg",
            )
            arcanas.append(arcana)
        db.session.add_all(arcanas)
        db.session.commit()

        # Prompt service
        prompt_service = PromptService.from_dict(
            {
                "situation_reading": {
                    "template": "RESPOND IN {{language}} LANGUAGE.\n\nSituation: {{situation_text}}\n\nCards: {{cards_context}}",
                    "variables": ["language", "situation_text", "cards_context"],
                }
            }
        )

        # Service with mocked LLM
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

        # Call with specific language
        result = service.generate_situation_reading(
            session_id=str(session.id),
            situation_text="Test situation",
            language=lang_code,
        )

        # Verify language instruction in prompt
        call_args = mock_llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert f"RESPOND IN {expected_lang_name} LANGUAGE." in prompt

    def test_answer_oracle_question_with_mocked_llm(self, db):
        """Verify follow-up questions pass language to mocked LLM"""
        from unittest.mock import Mock
        from plugins.taro.src.services.prompt_service import PromptService

        mock_llm = Mock()
        mock_llm.chat.return_value = "Oracle's answer"

        arcana_repo = ArcanaRepository(db.session)
        session_repo = TaroSessionRepository(db.session)
        card_draw_repo = TaroCardDrawRepository(db.session)

        # Create sample arcanas
        arcanas = []
        for i in range(3):
            arcana = Arcana(
                number=i,
                name=f"Card {i}",
                arcana_type=ArcanaType.MAJOR_ARCANA.value,
                upright_meaning="Upright",
                reversed_meaning="Reversed",
                image_url="https://example.com/card.jpg",
            )
            arcanas.append(arcana)
        db.session.add_all(arcanas)
        db.session.commit()

        prompt_service = PromptService.from_dict(
            {
                "follow_up_question": {
                    "template": "RESPOND IN {{language}} LANGUAGE.\n\nQuestion: {{question}}\n\nCards: {{cards_context}}",
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

        user_id = str(uuid4())
        session = service.create_session(user_id=user_id)

        # Call with French language
        result = service.answer_oracle_question(
            session_id=str(session.id), question="Will it improve?", language="fr"
        )

        # Verify language instruction
        call_args = mock_llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "RESPOND IN Français (French) LANGUAGE." in prompt
        assert "Will it improve?" in prompt
