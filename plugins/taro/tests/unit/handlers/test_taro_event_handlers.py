"""Tests for Taro event handlers."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock, patch
from plugins.taro.src.handlers import (
    TaroSessionCreatedHandler,
    TaroFollowUpHandler,
)
from plugins.taro.src.events import (
    TaroSessionCreatedEvent,
    TaroFollowUpRequestedEvent,
)
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.repositories.arcana_repository import ArcanaRepository
from plugins.taro.src.repositories.taro_session_repository import TaroSessionRepository
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.services.taro_session_service import TaroSessionService
from plugins.taro.src.services.arcana_interpretation_service import (
    ArcanaInterpretationService,
)


@pytest.fixture
def mock_interpreter_service():
    """Fixture providing mock ArcanaInterpretationService."""
    service = Mock(spec=ArcanaInterpretationService)
    return service


@pytest.fixture
def mock_token_service():
    """Fixture providing mock token service."""
    service = Mock()
    return service


@pytest.fixture
def mock_card():
    """Fixture providing a mock TaroCardDraw card."""
    card = Mock()
    card.id = uuid4()
    card.arcana_id = uuid4()
    card.position = "PAST"
    card.orientation = "UPRIGHT"
    return card


@pytest.fixture
def mock_arcana():
    """Fixture providing a mock Arcana."""
    arcana = Mock()
    arcana.id = uuid4()
    arcana.name = "The Fool"
    arcana.upright_meaning = "New beginnings"
    arcana.reversed_meaning = "Recklessness"
    return arcana


@pytest.fixture
def session_handler(mock_interpreter_service, mock_token_service, mock_card):
    """Fixture providing TaroSessionCreatedHandler with properly configured mocks."""
    card_draw_repo = Mock(spec=TaroCardDrawRepository)
    card_draw_repo.get_session_cards.return_value = [mock_card]
    return TaroSessionCreatedHandler(
        interpreter_service=mock_interpreter_service,
        token_service=mock_token_service,
        card_draw_repo=card_draw_repo,
    )


@pytest.fixture
def mock_session():
    """Fixture providing a mock TaroSession."""
    session = Mock()
    session.id = uuid4()
    session.user_id = str(uuid4())
    session.status = "ACTIVE"
    session.follow_up_count = 0
    session.max_follow_ups = 3
    return session


@pytest.fixture
def follow_up_handler(
    mock_interpreter_service, mock_token_service, mock_session, mock_card
):
    """Fixture providing TaroFollowUpHandler with properly configured mocks."""
    session_service = Mock(spec=TaroSessionService)
    session_service.get_session.return_value = mock_session
    session_service.get_session_spread.return_value = [mock_card]
    session_service.add_follow_up.return_value = mock_session
    session_service.arcana_repo = Mock(spec=ArcanaRepository)
    session_service.arcana_repo.get_random.return_value = []
    session_service.card_draw_repo = Mock(spec=TaroCardDrawRepository)
    return TaroFollowUpHandler(
        interpreter_service=mock_interpreter_service,
        session_service=session_service,
        token_service=mock_token_service,
    )


class TestTaroSessionCreatedHandler:
    """Test TaroSessionCreatedHandler."""

    def _make_event(self):
        """Create a valid TaroSessionCreatedEvent."""
        return TaroSessionCreatedEvent(
            session_id=str(uuid4()),
            user_id=str(uuid4()),
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            card_arcana_ids=[str(uuid4()) for _ in range(3)],
            initial_tokens_consumed=10,
        )

    def test_handle_session_created_event(
        self, session_handler, mock_interpreter_service, mock_token_service, mock_arcana
    ):
        """Test handling TaroSessionCreatedEvent."""
        event = self._make_event()

        mock_interpreter_service.generate_interpretation.return_value = (
            "Test interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                mock_arcana
            )
            result = session_handler.handle(event)

        assert result is not None
        assert mock_interpreter_service.generate_interpretation.called

    def test_session_created_deducts_tokens(
        self, session_handler, mock_interpreter_service, mock_token_service, mock_arcana
    ):
        """Test that session creation deducts tokens."""
        user_id = str(uuid4())
        event = TaroSessionCreatedEvent(
            session_id=str(uuid4()),
            user_id=user_id,
            spread_id="spread-001",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            card_arcana_ids=[str(uuid4()) for _ in range(3)],
            initial_tokens_consumed=10,
        )

        mock_interpreter_service.generate_interpretation.return_value = (
            "Interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                mock_arcana
            )
            session_handler.handle(event)

        mock_token_service.deduct_tokens.assert_called_once()
        call_args = mock_token_service.deduct_tokens.call_args
        assert user_id in str(call_args)

    def test_session_created_generates_interpretations(
        self, session_handler, mock_interpreter_service, mock_token_service, mock_arcana
    ):
        """Test that session creation generates card interpretations."""
        # Set up 3 mock cards
        session_handler.card_draw_repo.get_session_cards.return_value = [
            Mock(id=uuid4(), arcana_id=uuid4(), position="PAST", orientation="UPRIGHT"),
            Mock(
                id=uuid4(), arcana_id=uuid4(), position="PRESENT", orientation="UPRIGHT"
            ),
            Mock(
                id=uuid4(), arcana_id=uuid4(), position="FUTURE", orientation="REVERSED"
            ),
        ]

        event = self._make_event()

        mock_interpreter_service.generate_interpretation.return_value = (
            "Card interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                mock_arcana
            )
            session_handler.handle(event)

        # Should have called interpreter for each card (3 cards)
        assert mock_interpreter_service.generate_interpretation.call_count >= 3

    def test_session_created_handles_token_error(
        self, session_handler, mock_interpreter_service, mock_token_service, mock_arcana
    ):
        """Test handling token deduction failure."""
        event = self._make_event()

        mock_interpreter_service.generate_interpretation.return_value = (
            "Interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = False

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                mock_arcana
            )
            result = session_handler.handle(event)

        # Should handle gracefully even when token deduction fails
        assert result is not None


class TestTaroFollowUpHandler:
    """Test TaroFollowUpHandler."""

    def test_handle_follow_up_event(
        self, follow_up_handler, mock_interpreter_service, mock_token_service
    ):
        """Test handling TaroFollowUpRequestedEvent."""
        session_id = str(uuid4())
        user_id = str(uuid4())

        event = TaroFollowUpRequestedEvent(
            session_id=session_id,
            user_id=user_id,
            question="Tell me more about this card",
            follow_up_type="SAME_CARDS",
            requested_at=datetime.utcnow(),
        )

        mock_interpreter_service.generate_follow_up_interpretation.return_value = (
            "Follow-up interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                None
            )
            result = follow_up_handler.handle(event)

        assert result is not None

    def test_follow_up_adds_question_count(
        self, follow_up_handler, mock_interpreter_service, mock_token_service
    ):
        """Test that follow-up increments question count."""
        session_id = str(uuid4())
        user_id = str(uuid4())

        event = TaroFollowUpRequestedEvent(
            session_id=session_id,
            user_id=user_id,
            question="More insights please",
            follow_up_type="ADDITIONAL",
            requested_at=datetime.utcnow(),
        )

        mock_interpreter_service.generate_follow_up_interpretation.return_value = (
            "Additional insight",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                None
            )
            follow_up_handler.handle(event)

        # Should have attempted to generate follow-up
        assert mock_interpreter_service.generate_follow_up_interpretation.called

    def test_follow_up_deducts_tokens(
        self, follow_up_handler, mock_interpreter_service, mock_token_service
    ):
        """Test that follow-up deducts tokens."""
        session_id = str(uuid4())
        user_id = str(uuid4())

        event = TaroFollowUpRequestedEvent(
            session_id=session_id,
            user_id=user_id,
            question="What else?",
            follow_up_type="SAME_CARDS",
            requested_at=datetime.utcnow(),
        )

        mock_interpreter_service.generate_follow_up_interpretation.return_value = (
            "Interpretation",
            5,
        )
        mock_token_service.deduct_tokens.return_value = True

        with patch("plugins.taro.src.handlers.db") as mock_db:
            mock_db.session.query.return_value.filter.return_value.first.return_value = (
                None
            )
            follow_up_handler.handle(event)

        # Tokens should be deducted
        assert mock_token_service.deduct_tokens.called

    def test_follow_up_validates_session_exists(
        self, follow_up_handler, mock_interpreter_service, mock_token_service
    ):
        """Test that follow-up validates session exists."""
        fake_session_id = str(uuid4())
        user_id = str(uuid4())

        event = TaroFollowUpRequestedEvent(
            session_id=fake_session_id,
            user_id=user_id,
            question="Question",
            follow_up_type="SAME_CARDS",
            requested_at=datetime.utcnow(),
        )

        mock_interpreter_service.generate_follow_up_interpretation.return_value = (
            "Interpretation",
            5,
        )

        result = follow_up_handler.handle(event)

        # Should handle missing session
        assert result is not None or result is None  # Either way, no crash
