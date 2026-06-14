"""Repository for Currency model."""
from typing import Optional, List
from vbwd.repositories.base import BaseRepository
from vbwd.models.currency import Currency


class CurrencyRepository(BaseRepository[Currency]):
    """Repository for managing currencies."""

    def __init__(self, session):
        """Initialize repository.

        Args:
            session: SQLAlchemy database session (or Flask-SQLAlchemy
                scoped session proxy), matching the sibling repositories.
        """
        super().__init__(session, Currency)

    def find_by_code(self, code: str) -> Optional[Currency]:
        """Find currency by ISO code.

        Args:
            code: ISO 4217 currency code (e.g., EUR, USD)

        Returns:
            Currency if found, None otherwise
        """
        return self._session.query(Currency).filter_by(code=code.upper()).first()

    def list_all(self) -> List[Currency]:
        """Return the full currency catalog ordered by code.

        S84: there is no ``is_active``/``is_default`` column — the active set
        and default live in the core settings JSON. This returns every
        catalog row; the service derives the active/default views from
        settings.
        """
        return self._session.query(Currency).order_by(Currency.code).all()

    def delete_by_code(self, code: str) -> bool:
        """Delete the catalog row with the given ISO code.

        Args:
            code: ISO 4217 currency code (case-insensitive).

        Returns:
            True if a row was deleted, False if no row matched.
        """
        currency = self.find_by_code(code)
        if not currency:
            return False
        self._session.delete(currency)
        self._session.commit()
        return True
