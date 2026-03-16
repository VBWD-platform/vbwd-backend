"""Arcana domain model - Tarot card representation."""
from src.extensions import db
from src.models.base import BaseModel
from plugins.taro.src.enums import ArcanaType


class Arcana(BaseModel):
    """
    Arcana model represents a single Tarot card from the 78-card deck.

    Includes:
    - 22 Major Arcana (0-21): The Fool through The World
    - 56 Minor Arcana: 4 suits (Cups, Wands, Swords, Pentacles) × 14 ranks each
      - Ranks: Ace, Two, Three, Four, Five, Six, Seven, Eight, Nine, Ten, Page, Knight, Queen, King

    Each card has:
    - Upright meaning: Positive/primary interpretation
    - Reversed meaning: Negative/alternative interpretation
    - Image URL: For display in UI
    """

    __tablename__ = "arcana"

    # Card identity
    number = db.Column(db.Integer, nullable=True, index=True)  # 0-21 for Major Arcana
    name = db.Column(
        db.String(255), nullable=False, index=True
    )  # "The Fool", "Ace of Cups", etc.
    suit = db.Column(
        db.String(50), nullable=True, index=True
    )  # "CUPS", "WANDS", "SWORDS", "PENTACLES"
    rank = db.Column(
        db.String(50), nullable=True, index=True
    )  # "ACE", "TWO", ..., "KING"
    arcana_type = db.Column(
        db.String(50),
        nullable=False,
        index=True,
        default=ArcanaType.MAJOR_ARCANA.value,
    )

    # Meanings
    upright_meaning = db.Column(db.Text, nullable=False)
    reversed_meaning = db.Column(db.Text, nullable=False)

    # Media
    image_url = db.Column(db.String(512), nullable=False)

    def to_dict(self) -> dict:
        """Convert Arcana to dictionary for API response."""
        return {
            "id": str(self.id),
            "number": self.number,
            "name": self.name,
            "suit": self.suit,
            "rank": self.rank,
            "arcana_type": self.arcana_type.value
            if isinstance(self.arcana_type, ArcanaType)
            else self.arcana_type,
            "upright_meaning": self.upright_meaning,
            "reversed_meaning": self.reversed_meaning,
            "image_url": self.image_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Arcana(name='{self.name}', arcana_type='{self.arcana_type}')>"
