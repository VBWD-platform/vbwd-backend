"""Repository for TaroCardDraw data access."""
from typing import Optional, List
from src.extensions import db
from plugins.taro.src.models.taro_card_draw import TaroCardDraw
from plugins.taro.src.enums import CardPosition, CardOrientation


class TaroCardDrawRepository:
    """Repository for TaroCardDraw model database operations."""

    def __init__(self, session):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session

    def create(self, **kwargs) -> TaroCardDraw:
        """Create new TaroCardDraw."""
        card = TaroCardDraw(**kwargs)
        self.session.add(card)
        self.session.commit()
        return card

    def get_by_id(self, card_id: str) -> Optional[TaroCardDraw]:
        """Get TaroCardDraw by ID."""
        return (
            self.session.query(TaroCardDraw).filter(TaroCardDraw.id == card_id).first()
        )

    def get_session_cards(self, session_id: str) -> List[TaroCardDraw]:
        """Get all cards in a session, ordered by position (PAST, PRESENT, FUTURE)."""
        position_order = {
            CardPosition.PAST.value: 1,
            CardPosition.PRESENT.value: 2,
            CardPosition.FUTURE.value: 3,
        }

        cards = (
            self.session.query(TaroCardDraw)
            .filter(TaroCardDraw.session_id == session_id)
            .all()
        )

        # Sort by position order
        return sorted(cards, key=lambda c: position_order.get(c.position, 99))

    def get_by_session_and_position(
        self,
        session_id: str,
        position: CardPosition,
    ) -> Optional[TaroCardDraw]:
        """Get specific card from session by position."""
        return (
            self.session.query(TaroCardDraw)
            .filter(
                TaroCardDraw.session_id == session_id,
                TaroCardDraw.position == position.value,
            )
            .first()
        )

    def get_by_arcana(self, arcana_id: str) -> List[TaroCardDraw]:
        """Get all card draws for specific Arcana."""
        return (
            self.session.query(TaroCardDraw)
            .filter(TaroCardDraw.arcana_id == arcana_id)
            .order_by(TaroCardDraw.created_at.desc())
            .all()
        )

    def get_by_orientation(self, orientation: CardOrientation) -> List[TaroCardDraw]:
        """Get all cards with specific orientation."""
        return (
            self.session.query(TaroCardDraw)
            .filter(TaroCardDraw.orientation == orientation.value)
            .order_by(TaroCardDraw.created_at.desc())
            .all()
        )

    def count_session_cards(self, session_id: str) -> int:
        """Count cards in session. Typically 3 (PAST, PRESENT, FUTURE)."""
        return (
            self.session.query(TaroCardDraw)
            .filter(TaroCardDraw.session_id == session_id)
            .count()
        )

    def update_interpretation(self, card_id: str, interpretation: str) -> bool:
        """Update card's AI interpretation. Returns True if updated."""
        card = self.get_by_id(card_id)
        if not card:
            return False

        card.ai_interpretation = interpretation
        self.session.commit()
        return True

    def delete(self, card_id: str) -> bool:
        """Delete TaroCardDraw. Returns True if deleted."""
        card = self.get_by_id(card_id)
        if card:
            self.session.delete(card)
            self.session.commit()
            return True
        return False

    def delete_session_cards(self, session_id: str) -> int:
        """Delete all cards in session. Returns count deleted."""
        count = (
            self.session.query(TaroCardDraw)
            .filter(TaroCardDraw.session_id == session_id)
            .delete()
        )
        self.session.commit()
        return count
