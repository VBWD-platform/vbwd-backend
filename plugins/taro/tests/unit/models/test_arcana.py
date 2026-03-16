"""Tests for Arcana model."""
import pytest
from uuid import uuid4
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType


class TestArcanaCreation:
    """Test Arcana model creation and validation."""

    def test_arcana_creation_with_all_fields(self):
        """Test creating an Arcana with all fields."""
        arcana = Arcana(
            number=0,
            name="The Fool",
            suit=None,
            rank=None,
            arcana_type=ArcanaType.MAJOR_ARCANA,
            upright_meaning="New beginnings, taking risks, innocence",
            reversed_meaning="Recklessness, naivety, carelessness",
            image_url="https://example.com/fool.jpg",
        )

        assert arcana.number == 0
        assert arcana.name == "The Fool"
        assert arcana.suit is None
        assert arcana.rank is None
        assert arcana.arcana_type == ArcanaType.MAJOR_ARCANA
        assert arcana.upright_meaning == "New beginnings, taking risks, innocence"
        assert arcana.reversed_meaning == "Recklessness, naivety, carelessness"
        assert arcana.image_url == "https://example.com/fool.jpg"

    def test_arcana_requires_name(self, db):
        """Test that Arcana requires a name at database level."""
        from sqlalchemy.exc import IntegrityError

        arcana = Arcana(
            number=0,
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_arcana_requires_arcana_type(self, db):
        """Test that Arcana defaults to MAJOR_ARCANA when arcana_type is not provided."""
        arcana = Arcana(
            number=0,
            name="The Fool",
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        db.session.commit()
        assert arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value

    def test_major_arcana_number_range(self):
        """Test that Major Arcana numbers are 0-21."""
        # Valid: 0
        arcana = Arcana(
            number=0,
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        assert arcana.number == 0

        # Valid: 21
        arcana = Arcana(
            number=21,
            name="The World",
            arcana_type=ArcanaType.MAJOR_ARCANA,
            upright_meaning="Test",
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        assert arcana.number == 21

    def test_minor_arcana_cups_with_suit_and_rank(self):
        """Test Minor Arcana Cups have suit and rank."""
        arcana = Arcana(
            suit="CUPS",
            rank="ACE",
            arcana_type=ArcanaType.CUPS,
            name="Ace of Cups",
            upright_meaning="New love, new opportunity",
            reversed_meaning="Heartbreak, emotional loss",
            image_url="https://example.com/ace_cups.jpg",
        )

        assert arcana.suit == "CUPS"
        assert arcana.rank == "ACE"
        assert arcana.arcana_type == ArcanaType.CUPS
        assert arcana.name == "Ace of Cups"

    def test_minor_arcana_wands(self):
        """Test Minor Arcana Wands."""
        arcana = Arcana(
            suit="WANDS",
            rank="TWO",
            arcana_type=ArcanaType.WANDS,
            name="Two of Wands",
            upright_meaning="Planning, making decisions",
            reversed_meaning="Lack of direction, procrastination",
            image_url="https://example.com/two_wands.jpg",
        )

        assert arcana.arcana_type == ArcanaType.WANDS

    def test_minor_arcana_swords(self):
        """Test Minor Arcana Swords."""
        arcana = Arcana(
            suit="SWORDS",
            rank="THREE",
            arcana_type=ArcanaType.SWORDS,
            name="Three of Swords",
            upright_meaning="Difficulty, separation, heartbreak",
            reversed_meaning="Healing, forgiveness, recovery",
            image_url="https://example.com/three_swords.jpg",
        )

        assert arcana.arcana_type == ArcanaType.SWORDS

    def test_minor_arcana_pentacles(self):
        """Test Minor Arcana Pentacles."""
        arcana = Arcana(
            suit="PENTACLES",
            rank="FOUR",
            arcana_type=ArcanaType.PENTACLES,
            name="Four of Pentacles",
            upright_meaning="Security, control, possessiveness",
            reversed_meaning="Generosity, freedom, abundance",
            image_url="https://example.com/four_pentacles.jpg",
        )

        assert arcana.arcana_type == ArcanaType.PENTACLES

    def test_arcana_upright_meaning_not_empty(self, db):
        """Test that upright_meaning is required at database level."""
        from sqlalchemy.exc import IntegrityError

        arcana = Arcana(
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            reversed_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_arcana_reversed_meaning_not_empty(self, db):
        """Test that reversed_meaning is required at database level."""
        from sqlalchemy.exc import IntegrityError

        arcana = Arcana(
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            image_url="https://example.com/test.jpg",
        )
        db.session.add(arcana)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_arcana_image_url_not_empty(self, db):
        """Test that image_url is required at database level."""
        from sqlalchemy.exc import IntegrityError

        arcana = Arcana(
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="Test",
            reversed_meaning="Test",
        )
        db.session.add(arcana)
        with pytest.raises(IntegrityError):
            db.session.commit()

    def test_arcana_to_dict(self):
        """Test Arcana.to_dict() method."""
        arcana = Arcana(
            number=0,
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA,
            upright_meaning="New beginnings",
            reversed_meaning="Recklessness",
            image_url="https://example.com/fool.jpg",
        )

        result = arcana.to_dict()

        assert result["name"] == "The Fool"
        assert result["arcana_type"] == ArcanaType.MAJOR_ARCANA.value
        assert result["upright_meaning"] == "New beginnings"
        assert result["reversed_meaning"] == "Recklessness"
        assert result["image_url"] == "https://example.com/fool.jpg"

    def test_arcana_id_is_uuid(self, db):
        """Test that Arcana gets a UUID id on creation."""
        from uuid import UUID

        arcana = Arcana(
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="New beginnings",
            reversed_meaning="Recklessness",
            image_url="https://example.com/fool.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        assert arcana.id is not None
        assert isinstance(arcana.id, UUID)

    def test_arcana_timestamps(self, db):
        """Test that created_at and updated_at are set."""
        arcana = Arcana(
            name="The Fool",
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning="New beginnings",
            reversed_meaning="Recklessness",
            image_url="https://example.com/fool.jpg",
        )
        db.session.add(arcana)
        db.session.commit()

        assert arcana.created_at is not None
        assert arcana.updated_at is not None
