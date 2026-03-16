"""Repository for Arcana data access."""
from typing import Optional, List, Dict
from random import sample
from src.extensions import db
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType


class ArcanaRepository:
    """Repository for Arcana model database operations."""

    def __init__(self, session):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session

    def get_by_id(self, arcana_id: str) -> Optional[Arcana]:
        """Get Arcana by ID."""
        return self.session.query(Arcana).filter(Arcana.id == arcana_id).first()

    def get_all(self) -> List[Arcana]:
        """Get all Arcanas, ordered by type then number/name."""
        return (
            self.session.query(Arcana)
            .order_by(Arcana.arcana_type, Arcana.number, Arcana.name)
            .all()
        )

    def get_random(self, count: int = 3) -> List[Arcana]:
        """Get random Arcanas for card draw.

        Returns up to `count` random cards. If fewer than `count` exist,
        returns all available cards.
        """
        all_arcanas = self.get_all()
        if len(all_arcanas) <= count:
            return all_arcanas
        return sample(all_arcanas, count)

    def filter_by_type(self, arcana_type: ArcanaType) -> List[Arcana]:
        """Filter Arcanas by type (MAJOR_ARCANA, CUPS, WANDS, SWORDS, PENTACLES)."""
        return (
            self.session.query(Arcana)
            .filter(Arcana.arcana_type == arcana_type.value)
            .order_by(Arcana.number, Arcana.name)
            .all()
        )

    def count_by_type(self) -> Dict[str, int]:
        """Count Arcanas for each type."""
        results = (
            self.session.query(Arcana.arcana_type, db.func.count(Arcana.id))
            .group_by(Arcana.arcana_type)
            .all()
        )
        return {arcana_type: count for arcana_type, count in results}

    def get_by_name(self, name: str) -> Optional[Arcana]:
        """Get Arcana by exact name."""
        return self.session.query(Arcana).filter(Arcana.name == name).first()

    def get_by_suit_and_rank(self, suit: str, rank: str) -> Optional[Arcana]:
        """Get Minor Arcana by suit and rank."""
        return (
            self.session.query(Arcana)
            .filter(Arcana.suit == suit, Arcana.rank == rank)
            .first()
        )

    def get_by_number(self, number: int) -> Optional[Arcana]:
        """Get Major Arcana by number (0-21)."""
        return self.session.query(Arcana).filter(Arcana.number == number).first()

    def create(self, **kwargs) -> Arcana:
        """Create new Arcana."""
        arcana = Arcana(**kwargs)
        self.session.add(arcana)
        self.session.commit()
        return arcana

    def delete(self, arcana_id: str) -> bool:
        """Delete Arcana by ID. Returns True if deleted, False if not found."""
        arcana = self.get_by_id(arcana_id)
        if arcana:
            self.session.delete(arcana)
            self.session.commit()
            return True
        return False
