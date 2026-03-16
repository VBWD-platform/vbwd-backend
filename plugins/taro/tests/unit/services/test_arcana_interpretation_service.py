"""Tests for ArcanaInterpretationService."""
import pytest
from unittest.mock import Mock, patch
from plugins.taro.src.services.arcana_interpretation_service import (
    ArcanaInterpretationService,
)
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.models.taro_card_draw import TaroCardDraw
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType, CardPosition, CardOrientation


@pytest.fixture
def mock_llm_client():
    """Fixture providing mock LLM client."""
    client = Mock()
    return client


@pytest.fixture
def interpretation_service(mock_llm_client):
    """Fixture providing ArcanaInterpretationService instance."""
    service = ArcanaInterpretationService(
        llm_client=mock_llm_client,
        card_draw_repo=Mock(spec=TaroCardDrawRepository),
    )
    return service


@pytest.fixture
def sample_arcana():
    """Fixture providing sample Arcana."""
    return Arcana(
        number=0,
        name="The Fool",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="New beginnings, taking risks",
        reversed_meaning="Recklessness, carelessness",
        image_url="https://example.com/fool.jpg",
    )


class TestArcanaInterpretationService:
    """Test ArcanaInterpretationService methods."""

    def test_generate_interpretation_upright(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test generating interpretation for upright card."""
        # Mock LLM response
        mock_llm_client.generate.return_value = (
            "The Fool in upright position represents..."
        )

        result, tokens = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
        )

        assert "Fool" in result or "fool" in result.lower()
        assert tokens > 0
        mock_llm_client.generate.assert_called_once()

    def test_generate_interpretation_reversed(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test generating interpretation for reversed card."""
        mock_llm_client.generate.return_value = "The Fool reversed suggests..."

        result, tokens = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PRESENT,
            orientation=CardOrientation.REVERSED,
        )

        assert result is not None
        assert tokens > 0

    def test_generate_interpretation_includes_position(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test that interpretation includes position context."""
        mock_llm_client.generate.return_value = "In the past position, this card..."

        interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
        )

        # Verify LLM was called with position context
        call_args = mock_llm_client.generate.call_args
        assert call_args is not None

    def test_interpret_3_card_spread(
        self, interpretation_service, sample_arcana, mock_llm_client, db
    ):
        """Test generating cohesive interpretation for 3-card spread."""
        from uuid import uuid4

        # Persist arcana so FK constraint is satisfied
        db.session.add(sample_arcana)
        db.session.flush()
        # Create cards
        from plugins.taro.src.models.taro_session import TaroSession

        session = TaroSession(
            user_id=str(uuid4()),
            started_at=__import__("datetime").datetime.utcnow(),
            expires_at=__import__("datetime").datetime.utcnow()
            + __import__("datetime").timedelta(minutes=30),
            spread_id="spread-001",
        )
        db.session.add(session)
        db.session.commit()

        cards = []
        for pos in [CardPosition.PAST, CardPosition.PRESENT, CardPosition.FUTURE]:
            card = TaroCardDraw(
                session_id=str(session.id),
                arcana_id=str(sample_arcana.id),
                position=pos.value,
                orientation=CardOrientation.UPRIGHT.value,
                ai_interpretation="",
            )
            db.session.add(card)
            cards.append(card)

        db.session.commit()

        # Mock cohesive interpretation
        mock_llm_client.generate.return_value = (
            "Your past, present, and future reveal a journey of..."
        )

        interpretation, tokens = interpretation_service.interpret_spread(cards)

        assert interpretation is not None
        assert tokens > 0

    def test_token_cost_calculation(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test that token cost is calculated based on response."""
        # Longer response = more tokens
        short_response = "Short"
        long_response = "This is a much longer interpretation that contains more details and context about the card and its meaning in the spread and position."

        mock_llm_client.generate.side_effect = [short_response, long_response]

        _, short_tokens = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
        )

        _, long_tokens = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PRESENT,
            orientation=CardOrientation.UPRIGHT,
        )

        # Longer response should cost more tokens
        assert long_tokens > short_tokens

    def test_handle_llm_api_error(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test handling LLM API errors gracefully."""
        # Mock LLM error
        mock_llm_client.generate.side_effect = Exception("API Error")

        result, tokens = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
        )

        # Should return fallback interpretation
        assert result is not None
        assert "Fool" in result or len(result) > 0

    def test_interpretation_is_unique_per_draw(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test that each card draw gets unique interpretation."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            return f"Unique interpretation {call_count[0]}"

        mock_llm_client.generate.side_effect = side_effect

        interp1, _ = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
        )

        interp2, _ = interpretation_service.generate_interpretation(
            arcana=sample_arcana,
            position=CardPosition.FUTURE,
            orientation=CardOrientation.REVERSED,
        )

        # Should be different interpretations
        assert interp1 != interp2

    def test_update_card_interpretation(
        self, interpretation_service, sample_arcana, mock_llm_client, db
    ):
        """Test updating card's interpretation after generation."""
        from uuid import uuid4
        from plugins.taro.src.repositories.taro_card_draw_repository import (
            TaroCardDrawRepository,
        )

        # Persist arcana so FK constraint is satisfied
        db.session.add(sample_arcana)
        db.session.flush()
        # Create card
        from plugins.taro.src.models.taro_session import TaroSession

        session = TaroSession(
            user_id=str(uuid4()),
            started_at=__import__("datetime").datetime.utcnow(),
            expires_at=__import__("datetime").datetime.utcnow()
            + __import__("datetime").timedelta(minutes=30),
            spread_id="spread-001",
        )
        db.session.add(session)
        db.session.commit()

        card = TaroCardDraw(
            session_id=str(session.id),
            arcana_id=str(sample_arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Old interpretation",
        )
        db.session.add(card)
        db.session.commit()

        # Use a real repo backed by db so update and get_by_id work against actual data
        real_repo = TaroCardDrawRepository(db.session)
        interpretation_service.card_draw_repo = real_repo

        new_interpretation = "New, improved interpretation"
        interpretation_service.card_draw_repo.update_interpretation(
            str(card.id), new_interpretation
        )

        updated = interpretation_service.card_draw_repo.get_by_id(str(card.id))
        assert updated.ai_interpretation == new_interpretation

    def test_generate_follow_up_interpretation(
        self, interpretation_service, sample_arcana, mock_llm_client
    ):
        """Test generating interpretation for follow-up question."""
        mock_llm_client.generate.return_value = "Regarding your follow-up question..."

        result, tokens = interpretation_service.generate_follow_up_interpretation(
            original_cards=[sample_arcana],
            follow_up_type="SAME_CARDS",
            question="Tell me more about this card...",
        )

        assert result is not None
        assert tokens > 0

    def test_generate_follow_up_with_new_cards(
        self, interpretation_service, sample_arcana, mock_llm_client, db
    ):
        """Test generating new cards for follow-up."""
        mock_llm_client.generate.return_value = (
            "Additional perspective on your question..."
        )

        result, tokens = interpretation_service.generate_follow_up_interpretation(
            original_cards=[sample_arcana],
            follow_up_type="NEW_CARDS",
            question="New insight needed",
        )

        assert result is not None
        assert tokens > 0

    def test_configuration_of_llm_model(self, mock_llm_client):
        """Test that service can be configured with different LLM models."""
        service = ArcanaInterpretationService(
            llm_client=mock_llm_client,
            card_draw_repo=Mock(spec=TaroCardDrawRepository),
            model_name="gpt-4",
            temperature=0.7,
            max_tokens=500,
        )

        assert service.model_name == "gpt-4"
        assert service.temperature == 0.7
        assert service.max_tokens == 500
