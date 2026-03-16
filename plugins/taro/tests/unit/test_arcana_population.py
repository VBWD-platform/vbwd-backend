"""Tests for Arcana table population and image file consistency."""
import pytest
from pathlib import Path
from src.extensions import db
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType


@pytest.fixture(autouse=True)
def populated_db(db):
    """Seed the database with all 78 arcana cards."""
    from plugins.taro.src.bin.populate_arcanas import populate_arcanas

    populate_arcanas()
    yield db


class TestArcanaPopulation:
    """Test Arcana table population and data integrity."""

    def test_arcana_count(self, db):
        """Test that all 78 arcana cards are populated."""
        total_count = db.session.query(Arcana).count()
        assert total_count == 78, f"Expected 78 arcana cards, got {total_count}"

    def test_major_arcana_count(self, db):
        """Test that exactly 22 major arcana cards are populated."""
        major_count = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value)
            .count()
        )
        assert major_count == 22, f"Expected 22 major arcana, got {major_count}"

    def test_minor_arcana_suits(self, db):
        """Test that each minor arcana suit has exactly 14 cards."""
        suits = ["CUPS", "WANDS", "SWORDS", "PENTACLES"]
        for suit in suits:
            suit_count = db.session.query(Arcana).filter(Arcana.suit == suit).count()
            assert suit_count == 14, f"Expected 14 {suit} cards, got {suit_count}"

    def test_major_arcana_numbers(self, db):
        """Test that major arcana cards have sequential numbers 0-21."""
        major_arcana = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value)
            .order_by(Arcana.number)
            .all()
        )
        numbers = [card.number for card in major_arcana]
        expected = list(range(22))
        assert numbers == expected, f"Major arcana numbers mismatch: {numbers}"

    def test_all_cards_have_image_urls(self, db):
        """Test that all arcana cards have valid image URLs."""
        all_cards = db.session.query(Arcana).all()
        for card in all_cards:
            assert card.image_url, f"Card '{card.name}' has no image_url"
            assert isinstance(
                card.image_url, str
            ), f"Card '{card.name}' image_url is not a string"
            assert card.image_url.startswith(
                "/api/v1/taro/assets/arcana/"
            ), f"Card '{card.name}' has invalid image URL: {card.image_url}"

    def test_major_arcana_image_paths(self, db):
        """Test that major arcana image URLs follow correct naming pattern."""
        major_arcana = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value)
            .all()
        )
        for card in major_arcana:
            expected_pattern = f"/api/v1/taro/assets/arcana/major/{card.number:02d}-"
            assert card.image_url.startswith(
                expected_pattern
            ), f"Card '{card.name}' URL doesn't match pattern: {card.image_url}"

    def test_minor_arcana_image_paths(self, db):
        """Test that minor arcana image URLs follow correct naming pattern."""
        minor_arcana = db.session.query(Arcana).filter(Arcana.suit.isnot(None)).all()
        for card in minor_arcana:
            suit_lower = card.suit.lower()
            rank_lower = card.rank.lower()
            expected_pattern = f"/api/v1/taro/assets/arcana/minor/{suit_lower}/{rank_lower}-of-{suit_lower}.svg"
            assert (
                card.image_url == expected_pattern
            ), f"Card '{card.name}' URL mismatch.\nExpected: {expected_pattern}\nGot: {card.image_url}"

    def test_image_files_exist(self, db):
        """Test that all image files referenced in database actually exist."""
        all_cards = db.session.query(Arcana).all()
        assets_dir = Path(__file__).parent.parent.parent / "assets" / "arcana"

        for card in all_cards:
            # Extract file path from URL
            # URL format: /api/v1/taro/assets/arcana/major/00-the-fool.svg
            # File path should be: assets/arcana/major/00-the-fool.svg
            url_parts = card.image_url.split("/api/v1/taro/assets/arcana/")[1]
            file_path = assets_dir / url_parts

            assert (
                file_path.exists()
            ), f"Image file not found for card '{card.name}': {file_path}"

    def test_image_files_are_svg(self, db):
        """Test that all image files have .svg extension."""
        all_cards = db.session.query(Arcana).all()
        for card in all_cards:
            assert card.image_url.endswith(
                ".svg"
            ), f"Card '{card.name}' image is not SVG: {card.image_url}"

    def test_all_meanings_present(self, db):
        """Test that all cards have upright and reversed meanings."""
        all_cards = db.session.query(Arcana).all()
        for card in all_cards:
            assert card.upright_meaning, f"Card '{card.name}' has no upright meaning"
            assert card.reversed_meaning, f"Card '{card.name}' has no reversed meaning"
            assert isinstance(card.upright_meaning, str)
            assert isinstance(card.reversed_meaning, str)
            assert len(card.upright_meaning) > 0
            assert len(card.reversed_meaning) > 0

    def test_major_arcana_names_unique(self, db):
        """Test that all major arcana cards have unique names."""
        major_arcana = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value)
            .all()
        )
        names = [card.name for card in major_arcana]
        assert len(names) == len(set(names)), "Duplicate major arcana card names found"

    def test_minor_arcana_rank_suit_unique(self, db):
        """Test that minor arcana cards have unique rank+suit combinations."""
        minor_arcana = db.session.query(Arcana).filter(Arcana.suit.isnot(None)).all()
        combinations = [(card.rank, card.suit) for card in minor_arcana]
        assert len(combinations) == len(
            set(combinations)
        ), "Duplicate minor arcana rank+suit combinations found"

    def test_no_null_suit_for_minor_arcana(self, db):
        """Test that all minor arcana cards have a suit."""
        minor_without_suit = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type.in_(["CUPS", "WANDS", "SWORDS", "PENTACLES"]))
            .filter(Arcana.suit.is_(None))
            .count()
        )
        assert minor_without_suit == 0, "Found minor arcana cards without suit"

    def test_no_number_for_minor_arcana(self, db):
        """Test that all minor arcana cards have no number."""
        minor_with_number = (
            db.session.query(Arcana)
            .filter(Arcana.suit.isnot(None))
            .filter(Arcana.number.isnot(None))
            .count()
        )
        assert minor_with_number == 0, "Found minor arcana cards with numbers"

    def test_unique_image_urls(self, db):
        """Test that no two cards have the same image URL."""
        all_cards = db.session.query(Arcana).all()
        urls = [card.image_url for card in all_cards]
        assert len(urls) == len(
            set(urls)
        ), f"Found {len(urls) - len(set(urls))} duplicate image URLs"

    def test_arcana_to_dict(self, db):
        """Test that arcana.to_dict() includes all required fields."""
        card = db.session.query(Arcana).first()
        card_dict = card.to_dict()

        required_fields = [
            "id",
            "number",
            "name",
            "suit",
            "rank",
            "arcana_type",
            "upright_meaning",
            "reversed_meaning",
            "image_url",
            "created_at",
            "updated_at",
        ]

        for field in required_fields:
            assert field in card_dict, f"Missing field in to_dict(): {field}"
            if field not in ["created_at", "updated_at", "number", "suit", "rank"]:
                assert card_dict[field] is not None, f"Field {field} is None"

    def test_populate_idempotency(self, db):
        """Test that running populator twice doesn't create duplicates."""
        # Get initial count
        initial_count = db.session.query(Arcana).count()

        # Import and run populator again
        from plugins.taro.src.bin.populate_arcanas import populate_arcanas

        populate_arcanas()

        # Check count remains the same
        final_count = db.session.query(Arcana).count()
        assert (
            initial_count == final_count
        ), f"Populator created duplicates: {initial_count} -> {final_count}"


class TestTaroAssetServing:
    """Test Taro plugin asset serving and availability."""

    def test_arcana_asset_endpoint_returns_svg(self, client):
        """Test that arcana asset endpoint returns valid SVG file."""
        response = client.get("/api/v1/taro/assets/arcana/major/00-the-fool.svg")
        assert response.status_code == 200
        assert "image/svg+xml" in response.content_type
        assert b"<?xml" in response.data
        assert b"<svg" in response.data

    def test_minor_arcana_asset_endpoint(self, client):
        """Test that minor arcana asset endpoint works."""
        response = client.get("/api/v1/taro/assets/arcana/minor/cups/ace-of-cups.svg")
        assert response.status_code == 200
        assert "image/svg+xml" in response.content_type
        assert b"Ace of Cups" in response.data or b"of Cups" in response.data

    def test_nonexistent_asset_returns_404(self, client):
        """Test that requesting non-existent asset returns 404."""
        response = client.get("/api/v1/taro/assets/arcana/major/99-nonexistent.svg")
        assert response.status_code == 404

    def test_directory_traversal_attack_prevented(self, client):
        """Test that directory traversal attempts are blocked."""
        # Attempt to traverse directories
        response = client.get("/api/v1/taro/assets/arcana/../../etc/passwd")
        assert response.status_code in [400, 403, 404]

    def test_all_major_arcana_assets_accessible(self, client, db):
        """Test that all major arcana assets are accessible via API."""
        major_arcana = (
            db.session.query(Arcana)
            .filter(Arcana.arcana_type == ArcanaType.MAJOR_ARCANA.value)
            .all()
        )
        for card in major_arcana:
            # Use the full image_url path as registered on the blueprint
            path = card.image_url
            response = client.get(path)
            assert (
                response.status_code == 200
            ), f"Failed to fetch asset for {card.name}: {path}"

    def test_all_minor_arcana_assets_accessible(self, client, db):
        """Test that all minor arcana assets are accessible via API."""
        minor_arcana = db.session.query(Arcana).filter(Arcana.suit.isnot(None)).all()
        for card in minor_arcana:
            # Use the full image_url path as registered on the blueprint
            path = card.image_url
            response = client.get(path)
            assert (
                response.status_code == 200
            ), f"Failed to fetch asset for {card.name}: {path}"
