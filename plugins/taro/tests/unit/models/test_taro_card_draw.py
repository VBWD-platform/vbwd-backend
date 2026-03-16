"""Tests for TaroCardDraw model."""
import pytest
from uuid import uuid4
from plugins.taro.src.models.taro_card_draw import TaroCardDraw
from plugins.taro.src.enums import ArcanaType, CardPosition, CardOrientation


class TestTaroCardDrawCreation:
    """Test TaroCardDraw model creation and validation."""

    def test_card_draw_creation(self):
        """Test creating a TaroCardDraw with all fields."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="This card represents...",
        )

        assert card_draw.session_id == "session-123"
        assert card_draw.arcana_id == "arcana-456"
        assert card_draw.position == CardPosition.PAST
        assert card_draw.orientation == CardOrientation.UPRIGHT
        assert card_draw.ai_interpretation == "This card represents..."

    def test_card_draw_requires_session_id(self, db):
        """Test that TaroCardDraw requires a session_id at database level."""
        from sqlalchemy.exc import IntegrityError
        from plugins.taro.src.models.arcana import Arcana

        arcana = Arcana(
            name="Test Card",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        card = TaroCardDraw(
            arcana_id=str(arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Test",
        )
        db.session.add(card)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_card_draw_requires_arcana_id(self, db):
        """Test that TaroCardDraw requires an arcana_id at database level."""
        from sqlalchemy.exc import IntegrityError

        card = TaroCardDraw(
            session_id=str(uuid4()),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Test",
        )
        db.session.add(card)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_card_position_past(self):
        """Test card position PAST."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Test",
        )

        assert card_draw.position == CardPosition.PAST

    def test_card_position_present(self):
        """Test card position PRESENT."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PRESENT,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Test",
        )

        assert card_draw.position == CardPosition.PRESENT

    def test_card_position_future(self):
        """Test card position FUTURE."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.FUTURE,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Test",
        )

        assert card_draw.position == CardPosition.FUTURE

    def test_card_orientation_upright(self):
        """Test card orientation UPRIGHT."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Test",
        )

        assert card_draw.orientation == CardOrientation.UPRIGHT

    def test_card_orientation_reversed(self):
        """Test card orientation REVERSED."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PAST,
            orientation=CardOrientation.REVERSED,
            ai_interpretation="Test",
        )

        assert card_draw.orientation == CardOrientation.REVERSED

    def test_ai_interpretation_required(self, db):
        """Test that ai_interpretation is required at database level."""
        from sqlalchemy.exc import IntegrityError
        from plugins.taro.src.models.arcana import Arcana

        arcana = Arcana(
            name="Test Card",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        card = TaroCardDraw(
            session_id=str(uuid4()),
            arcana_id=str(arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
        )
        db.session.add(card)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_three_card_spread_with_different_positions(self):
        """Test a complete 3-card spread."""
        past_card = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-1",
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Past interpretation",
        )

        present_card = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-2",
            position=CardPosition.PRESENT,
            orientation=CardOrientation.REVERSED,
            ai_interpretation="Present interpretation",
        )

        future_card = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-3",
            position=CardPosition.FUTURE,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Future interpretation",
        )

        # All 3 cards belong to same session
        assert past_card.session_id == present_card.session_id == future_card.session_id
        # Each has unique position
        positions = {past_card.position, present_card.position, future_card.position}
        assert len(positions) == 3

    def test_card_draw_to_dict(self):
        """Test TaroCardDraw.to_dict() method."""
        card_draw = TaroCardDraw(
            session_id="session-123",
            arcana_id="arcana-456",
            position=CardPosition.PAST,
            orientation=CardOrientation.UPRIGHT,
            ai_interpretation="Card interpretation",
        )

        result = card_draw.to_dict()

        assert result["session_id"] == "session-123"
        assert result["arcana_id"] == "arcana-456"
        assert result["position"] == CardPosition.PAST.value
        assert result["orientation"] == CardOrientation.UPRIGHT.value
        assert result["ai_interpretation"] == "Card interpretation"

    def test_card_draw_timestamps(self, db):
        """Test that created_at is set after persisting."""
        from plugins.taro.src.models.arcana import Arcana

        arcana = Arcana(
            name="Test Card",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        card_draw = TaroCardDraw(
            session_id=str(uuid4()),
            arcana_id=str(arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Test",
        )
        db.session.add(card_draw)
        db.session.commit()

        assert card_draw.created_at is not None

    def test_card_draw_id_is_uuid(self, db):
        """Test that TaroCardDraw gets a UUID id after persisting."""
        from uuid import UUID
        from plugins.taro.src.models.arcana import Arcana

        arcana = Arcana(
            name="Test Card",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        card_draw = TaroCardDraw(
            session_id=str(uuid4()),
            arcana_id=str(arcana.id),
            position=CardPosition.PAST.value,
            orientation=CardOrientation.UPRIGHT.value,
            ai_interpretation="Test",
        )
        db.session.add(card_draw)
        db.session.commit()

        assert card_draw.id is not None
        assert isinstance(card_draw.id, UUID)
