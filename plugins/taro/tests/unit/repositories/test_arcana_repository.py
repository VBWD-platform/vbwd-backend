"""Tests for ArcanaRepository."""
import pytest
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.repositories.arcana_repository import ArcanaRepository
from plugins.taro.src.enums import ArcanaType


@pytest.fixture
def arcana_repo(db):
    """Fixture providing ArcanaRepository instance."""
    return ArcanaRepository(db.session)


@pytest.fixture
def sample_arcanas(db):
    """Fixture creating sample Arcana cards in database."""
    # Major Arcana
    fool = Arcana(
        number=0,
        name="The Fool",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="New beginnings, taking risks",
        reversed_meaning="Recklessness, carelessness",
        image_url="https://example.com/fool.jpg",
    )
    magician = Arcana(
        number=1,
        name="The Magician",
        arcana_type=ArcanaType.MAJOR_ARCANA.value,
        upright_meaning="Creativity, resourcefulness",
        reversed_meaning="Manipulation, misdirection",
        image_url="https://example.com/magician.jpg",
    )

    # Minor Arcana - Cups
    ace_cups = Arcana(
        suit="CUPS",
        rank="ACE",
        name="Ace of Cups",
        arcana_type=ArcanaType.CUPS.value,
        upright_meaning="New love, opportunity",
        reversed_meaning="Heartbreak, emotional loss",
        image_url="https://example.com/ace_cups.jpg",
    )
    two_cups = Arcana(
        suit="CUPS",
        rank="TWO",
        name="Two of Cups",
        arcana_type=ArcanaType.CUPS.value,
        upright_meaning="Partnership, connection",
        reversed_meaning="Disharmony, separation",
        image_url="https://example.com/two_cups.jpg",
    )

    # Minor Arcana - Wands
    three_wands = Arcana(
        suit="WANDS",
        rank="THREE",
        name="Three of Wands",
        arcana_type=ArcanaType.WANDS.value,
        upright_meaning="Exploration, expansion",
        reversed_meaning="Delays, lack of progress",
        image_url="https://example.com/three_wands.jpg",
    )

    db.session.add_all([fool, magician, ace_cups, two_cups, three_wands])
    db.session.commit()

    return {
        "fool": fool,
        "magician": magician,
        "ace_cups": ace_cups,
        "two_cups": two_cups,
        "three_wands": three_wands,
    }


class TestArcanaRepository:
    """Test ArcanaRepository methods."""

    def test_get_arcana_by_id(self, arcana_repo, sample_arcanas):
        """Test retrieving Arcana by ID."""
        fool = sample_arcanas["fool"]
        result = arcana_repo.get_by_id(str(fool.id))

        assert result is not None
        assert result.id == fool.id
        assert result.name == "The Fool"
        assert result.number == 0

    def test_get_arcana_by_id_not_found(self, arcana_repo):
        """Test retrieving non-existent Arcana returns None."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = arcana_repo.get_by_id(fake_id)

        assert result is None

    def test_get_all_arcanas(self, arcana_repo, sample_arcanas):
        """Test retrieving all Arcanas."""
        results = arcana_repo.get_all()

        assert len(results) == 5
        names = {a.name for a in results}
        assert "The Fool" in names
        assert "Ace of Cups" in names

    def test_get_random_arcanas_single(self, arcana_repo, sample_arcanas):
        """Test getting single random Arcana."""
        result = arcana_repo.get_random(count=1)

        assert len(result) == 1
        assert isinstance(result[0], Arcana)

    def test_get_random_arcanas_three_card_spread(self, arcana_repo, sample_arcanas):
        """Test getting 3 random Arcanas for spread."""
        result = arcana_repo.get_random(count=3)

        assert len(result) == 3
        # All should be Arcana instances
        for card in result:
            assert isinstance(card, Arcana)

    def test_get_random_arcanas_all(self, arcana_repo, sample_arcanas):
        """Test getting all available Arcanas as random."""
        result = arcana_repo.get_random(count=5)

        assert len(result) == 5

    def test_get_random_arcanas_more_than_available(self, arcana_repo, sample_arcanas):
        """Test requesting more random cards than available."""
        # Should return all available cards
        result = arcana_repo.get_random(count=100)

        assert len(result) == 5

    def test_filter_by_arcana_type_major(self, arcana_repo, sample_arcanas):
        """Test filtering by MAJOR_ARCANA type."""
        results = arcana_repo.filter_by_type(ArcanaType.MAJOR_ARCANA)

        assert len(results) == 2
        names = {a.name for a in results}
        assert "The Fool" in names
        assert "The Magician" in names

    def test_filter_by_arcana_type_cups(self, arcana_repo, sample_arcanas):
        """Test filtering by CUPS type."""
        results = arcana_repo.filter_by_type(ArcanaType.CUPS)

        assert len(results) == 2
        names = {a.name for a in results}
        assert "Ace of Cups" in names
        assert "Two of Cups" in names

    def test_filter_by_arcana_type_wands(self, arcana_repo, sample_arcanas):
        """Test filtering by WANDS type."""
        results = arcana_repo.filter_by_type(ArcanaType.WANDS)

        assert len(results) == 1
        assert results[0].name == "Three of Wands"

    def test_filter_by_arcana_type_empty(self, arcana_repo):
        """Test filtering by type returns empty list if none match."""
        results = arcana_repo.filter_by_type(ArcanaType.SWORDS)

        assert len(results) == 0

    def test_count_by_type(self, arcana_repo, sample_arcanas):
        """Test counting Arcanas by type."""
        counts = arcana_repo.count_by_type()

        assert counts.get(ArcanaType.MAJOR_ARCANA.value) == 2
        assert counts.get(ArcanaType.CUPS.value) == 2
        assert counts.get(ArcanaType.WANDS.value) == 1
        assert counts.get(ArcanaType.SWORDS.value, 0) == 0
        assert counts.get(ArcanaType.PENTACLES.value, 0) == 0

    def test_get_by_name(self, arcana_repo, sample_arcanas):
        """Test retrieving Arcana by name."""
        result = arcana_repo.get_by_name("The Fool")

        assert result is not None
        assert result.name == "The Fool"
        assert result.number == 0

    def test_get_by_name_not_found(self, arcana_repo):
        """Test retrieving non-existent Arcana by name."""
        result = arcana_repo.get_by_name("Non-Existent Card")

        assert result is None

    def test_get_by_suit_and_rank(self, arcana_repo, sample_arcanas):
        """Test retrieving Minor Arcana by suit and rank."""
        result = arcana_repo.get_by_suit_and_rank("CUPS", "ACE")

        assert result is not None
        assert result.name == "Ace of Cups"
        assert result.suit == "CUPS"
        assert result.rank == "ACE"

    def test_get_by_suit_and_rank_not_found(self, arcana_repo):
        """Test retrieving non-existent suit/rank combination."""
        result = arcana_repo.get_by_suit_and_rank("PENTACLES", "KING")

        assert result is None

    def test_get_by_number(self, arcana_repo, sample_arcanas):
        """Test retrieving Major Arcana by number."""
        result = arcana_repo.get_by_number(0)

        assert result is not None
        assert result.number == 0
        assert result.name == "The Fool"

    def test_get_by_number_not_found(self, arcana_repo):
        """Test retrieving non-existent card number."""
        result = arcana_repo.get_by_number(99)

        assert result is None
