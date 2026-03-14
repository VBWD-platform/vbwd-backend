"""TaroSession domain model - user Tarot reading session."""
from src.utils.datetime_utils import utcnow
from src.extensions import db
from src.models.base import BaseModel
from plugins.taro.src.enums import TaroSessionStatus


class TaroSession(BaseModel):
    """
    TaroSession model represents an active or completed Tarot reading session.

    A session:
    - Contains one 3-card spread (Past, Present, Future)
    - Expires after 30 minutes
    - Can have follow-up questions (limited by tarif plan or add-ons)
    - Tracks token consumption
    - Stores session state for history/revisiting

    Lifecycle:
    1. ACTIVE: Just created, user viewing/asking follow-ups
    2. EXPIRED: 30 minutes have passed without closing
    3. CLOSED: User explicitly ended session or expired naturally
    """

    __tablename__ = "taro_session"

    # User reference
    user_id = db.Column(db.UUID, nullable=False, index=True)  # FK to user

    # Session state
    status = db.Column(
        db.String(50),
        nullable=False,
        default=TaroSessionStatus.ACTIVE.value,
        index=True,
    )

    # Timing
    started_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow,
    )
    expires_at = db.Column(db.DateTime, nullable=False, index=True)  # started_at + 30 minutes
    ended_at = db.Column(db.DateTime, nullable=True)  # When user closed or session expired

    # Card spread
    spread_id = db.Column(db.String(50), nullable=False, index=True)  # Unique ID for this 3-card spread

    # Token tracking
    tokens_consumed = db.Column(db.Integer, nullable=False, default=0)

    # Follow-up tracking
    follow_up_count = db.Column(db.Integer, nullable=False, default=0)  # How many follow-ups asked
    max_follow_ups = db.Column(db.Integer, nullable=False, default=3)  # From tarif plan/add-ons

    # Relationships
    cards = db.relationship(
        "TaroCardDraw",
        foreign_keys="TaroCardDraw.session_id",
        primaryjoin="TaroSession.id == TaroCardDraw.session_id",
        backref="session",
        lazy="joined",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Convert TaroSession to dictionary for API response."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "spread_id": self.spread_id,
            "tokens_consumed": self.tokens_consumed,
            "follow_up_count": self.follow_up_count,
            "max_follow_ups": self.max_follow_ups,
            "cards": [card.to_dict() for card in self.cards] if self.cards else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<TaroSession(user_id='{self.user_id}', status='{self.status}', spread_id='{self.spread_id}')>"
