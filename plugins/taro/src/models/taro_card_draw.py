"""TaroCardDraw domain model - card within a session."""
from sqlalchemy.dialects.postgresql import UUID
from src.extensions import db
from src.models.base import BaseModel
from plugins.taro.src.enums import CardPosition, CardOrientation


class TaroCardDraw(BaseModel):
    """
    TaroCardDraw model represents a single card within a Tarot session.

    Every TaroSession has 3 TaroCardDraw records:
    - One card for PAST position
    - One card for PRESENT position
    - One card for FUTURE position

    Each card has:
    - Reference to the Arcana (the card definition)
    - Position in spread (PAST/PRESENT/FUTURE)
    - Orientation (UPRIGHT/REVERSED)
    - AI-generated interpretation (unique per draw)
    """

    __tablename__ = "taro_card_draw"

    # References
    session_id = db.Column(db.UUID, nullable=False, index=True)  # FK to taro_session
    arcana_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("arcana.id"),
        nullable=False,
        index=True,
    )

    # Spread context
    position = db.Column(
        db.String(50),
        nullable=False,
        index=True,
    )  # PAST, PRESENT, FUTURE

    # Card state
    orientation = db.Column(
        db.String(50),
        nullable=False,
    )  # UPRIGHT, REVERSED

    # Interpretation
    ai_interpretation = db.Column(db.Text, nullable=False)  # LLM-generated

    # Relationships
    arcana = db.relationship(
        "Arcana",
        backref="card_draws",
        lazy="joined",
        foreign_keys=[arcana_id],
    )

    def to_dict(self) -> dict:
        """Convert TaroCardDraw to dictionary for API response."""
        return {
            "id": str(self.id),
            "card_id": str(self.id),  # Frontend expects card_id
            "session_id": str(self.session_id) if self.session_id else None,
            "arcana_id": str(self.arcana_id) if self.arcana_id else None,
            "position": self.position.value
            if isinstance(self.position, CardPosition)
            else self.position,
            "orientation": self.orientation.value
            if isinstance(self.orientation, CardOrientation)
            else self.orientation,
            "ai_interpretation": self.ai_interpretation,
            "arcana": self.arcana.to_dict() if self.arcana else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<TaroCardDraw(session_id='{self.session_id}', position='{self.position}', orientation='{self.orientation}')>"
