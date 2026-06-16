"""Repository for :class:`~vbwd.models.llm_connection.LlmConnection` (S97.1)."""
from typing import List, Optional

from vbwd.models.llm_connection import LlmConnection
from vbwd.repositories.base import BaseRepository


class LlmConnectionRepository(BaseRepository[LlmConnection]):
    """Data access for admin-managed LLM connections."""

    def __init__(self, session):
        super().__init__(session, LlmConnection)

    def find_by_slug(self, slug: str) -> Optional[LlmConnection]:
        """Return the connection with this slug, or ``None``."""
        return self._session.query(LlmConnection).filter_by(slug=slug).first()

    def list_all(self) -> List[LlmConnection]:
        """Return every connection ordered by connection_name."""
        return (
            self._session.query(LlmConnection)
            .order_by(LlmConnection.connection_name)
            .all()
        )

    def list_active(self) -> List[LlmConnection]:
        """Return the active connections ordered by connection_name."""
        return (
            self._session.query(LlmConnection)
            .filter_by(is_active=True)
            .order_by(LlmConnection.connection_name)
            .all()
        )

    def find_default(self) -> Optional[LlmConnection]:
        """Return the connection flagged as default, or ``None``."""
        return self._session.query(LlmConnection).filter_by(is_default=True).first()
