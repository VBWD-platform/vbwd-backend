"""Tests for TaroCardDrawRepository."""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.models.taro_session import TaroSession
from plugins.taro.src.models.taro_card_draw import TaroCardDraw
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.enums import (
    ArcanaType,
    CardPosition,
    CardOrientation,
    TaroSessionStatus,
)


@pytest.fixture
def card_draw_repo(db):
    """Fixture providing TaroCardDrawRepository instance."""
    return TaroCardDrawRepository(db.session)


@pytest.fixture
def sample_cards(db):
    """Fixture creating sample TaroCardDraw records."""
    user_id = str(uuid4())
    session_id = str(uuid4())

    # Create Arcanas for the cards
    fool = Arcana(
        number=0,
        name="The Fool",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="New beginnings",
        reversed_meaning="Recklessness",
        image_url="https://example.com/fool.jpg",
    )
    magician = Arcana(
        number=1,
        name="The Magician",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="Creativity",
        reversed_meaning="Manipulation",
        image_url="https://example.com/magician.jpg",
    )
    priestess = Arcana(
        number=2,
        name="The High Priestess",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="Intuition",
        reversed_meaning="Secrets",
        image_url="https://example.com/priestess.jpg",
    )

    db.session.add_all([fool, magician, priestess])
    db.session.commit()

    # Create session
    session = TaroSession(
        user_id=user_id,
        status=TaroSessionStatus.ACTIVE.value,
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        spread_id="spread-001",
    )
    db.session.add(session)
    db.session.commit()

    # Create 3-card spread
    past_card = TaroCardDraw(
        session_id=str(session.id),
        arcana_id=str(fool.id),
        position=CardPosition.PAST.value,
        orientation=CardOrientation.UPRIGHT.value,
        ai_interpretation="In the past, you took a bold leap of faith...",
    )
    present_card = TaroCardDraw(
        session_id=str(session.id),
        arcana_id=str(magician.id),
        position=CardPosition.PRESENT.value,
        orientation=CardOrientation.REVERSED.value,
        ai_interpretation="Currently, your creative energy is blocked...",
    )
    future_card = TaroCardDraw(
        session_id=str(session.id),
        arcana_id=str(priestess.id),
        position=CardPosition.FUTURE.value,
        orientation=CardOrientation.UPRIGHT.value,
        ai_interpretation="In the future, trust your intuition...",
    )

    db.session.add_all([past_card, present_card, future_card])
    db.session.commit()

    return {
        "session_id": str(session.id),
        "user_id": user_id,
        "fool_id": str(fool.id),
        "magician_id": str(magician.id),
        "priestess_id": str(priestess.id),
        "past_card": past_card,
        "present_card": present_card,
        "future_card": future_card,
    }


class TestTaroCardDrawRepository:
    """Test TaroCardDrawRepository methods."""

    def test_create_card_draw(self, card_draw_repo, db):
        """Test creating a TaroCardDraw."""
        user_id = str(uuid4())

        # Create arcana first (FK constraint on arcana_id)
        arcana = Arcana(
            name="Test Card",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        # Create session
        session = TaroSession(
            user_id=user_id,
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            spread_id="spread-test",
        )
        db.session.add(session)
        db.session.commit()

        result = card_draw_repo.create(
            session_id=str(session.id),
            arcana_id=str(arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Test interpretation",
        )

        assert result.id is not None
        assert result.position == CardPosition.PAST.value

    def test_get_card_by_id(self, card_draw_repo, sample_cards):
        """Test retrieving TaroCardDraw by ID."""
        past_card = sample_cards["past_card"]
        result = card_draw_repo.get_by_id(str(past_card.id))

        assert result is not None
        assert result.id == past_card.id
        assert result.position == CardPosition.PAST.value

    def test_get_card_by_id_not_found(self, card_draw_repo):
        """Test retrieving non-existent card returns None."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = card_draw_repo.get_by_id(fake_id)

        assert result is None

    def test_get_session_cards(self, card_draw_repo, sample_cards):
        """Test retrieving all cards for a session."""
        session_id = sample_cards["session_id"]
        results = card_draw_repo.get_session_cards(session_id)

        assert len(results) == 3
        assert all(str(c.session_id) == session_id for c in results)

    def test_get_session_cards_ordered(self, card_draw_repo, sample_cards):
        """Test that session cards are ordered by position."""
        session_id = sample_cards["session_id"]
        results = card_draw_repo.get_session_cards(session_id)

        # Should be ordered: PAST, PRESENT, FUTURE
        positions = [c.position for c in results]
        assert positions == [
            CardPosition.PAST.value,
            CardPosition.PRESENT.value,
            CardPosition.FUTURE.value,
        ]

    def test_get_session_cards_empty(self, card_draw_repo):
        """Test getting cards for non-existent session."""
        fake_session_id = str(uuid4())
        results = card_draw_repo.get_session_cards(fake_session_id)

        assert len(results) == 0

    def test_get_card_by_position(self, card_draw_repo, sample_cards):
        """Test retrieving card by session and position."""
        session_id = sample_cards["session_id"]
        result = card_draw_repo.get_by_session_and_position(
            session_id, CardPosition.PAST
        )

        assert result is not None
        assert result.position == CardPosition.PAST.value
        assert str(result.session_id) == session_id

    def test_get_card_by_position_not_found(self, card_draw_repo):
        """Test getting card that doesn't exist."""
        fake_session_id = str(uuid4())
        result = card_draw_repo.get_by_session_and_position(
            fake_session_id, CardPosition.PAST
        )

        assert result is None

    def test_update_card_interpretation(self, card_draw_repo, sample_cards):
        """Test updating card interpretation."""
        past_card = sample_cards["past_card"]
        new_interpretation = "Updated interpretation text"

        card_draw_repo.update_interpretation(str(past_card.id), new_interpretation)

        updated = card_draw_repo.get_by_id(str(past_card.id))
        assert updated.ai_interpretation == new_interpretation

    def test_update_card_interpretation_not_found(self, card_draw_repo):
        """Test updating interpretation for non-existent card."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        # Should not raise error
        card_draw_repo.update_interpretation(fake_id, "New text")

    def test_delete_card(self, card_draw_repo, sample_cards):
        """Test deleting a card."""
        past_card = sample_cards["past_card"]
        card_draw_repo.delete(str(past_card.id))

        result = card_draw_repo.get_by_id(str(past_card.id))
        assert result is None

    def test_delete_card_not_found(self, card_draw_repo):
        """Test deleting non-existent card."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        # Should not raise error
        card_draw_repo.delete(fake_id)

    def test_get_cards_by_arcana(self, card_draw_repo, sample_cards):
        """Test getting all cards with specific Arcana."""
        fool_id = sample_cards["fool_id"]
        results = card_draw_repo.get_by_arcana(fool_id)

        assert len(results) >= 1
        assert str(results[0].arcana_id) == fool_id

    def test_delete_session_cards_cascade(self, card_draw_repo, sample_cards, db):
        """Test that deleting session cascades to cards."""
        session_id = sample_cards["session_id"]

        # Get session and delete it
        session = (
            db.session.query(TaroSession).filter(TaroSession.id == session_id).first()
        )
        db.session.delete(session)
        db.session.commit()

        # Cards should be deleted too (CASCADE)
        results = card_draw_repo.get_session_cards(session_id)
        assert len(results) == 0

    def test_count_session_cards(self, card_draw_repo, sample_cards):
        """Test counting cards in session."""
        session_id = sample_cards["session_id"]
        count = card_draw_repo.count_session_cards(session_id)

        assert count == 3

    def test_get_all_by_orientation(self, card_draw_repo, sample_cards):
        """Test getting cards by orientation (UPRIGHT/REVERSED)."""
        upright_cards = card_draw_repo.get_by_orientation(CardOrientation.UPRIGHT)
        assert len(upright_cards) >= 2

        reversed_cards = card_draw_repo.get_by_orientation(CardOrientation.REVERSED)
        assert len(reversed_cards) >= 1
