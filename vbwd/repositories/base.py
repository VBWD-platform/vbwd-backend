"""Base repository implementation with optimistic locking."""
from typing import Any, Generic, TypeVar, Optional, List, Type, Union
from uuid import UUID
from sqlalchemy.orm.exc import StaleDataError
from vbwd.models.base import ConcurrentModificationError

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """
    Base repository with optimistic locking support.

    All save operations check version numbers.
    """

    def __init__(self, session, model: Type[T]):
        """
        Initialize repository.

        Args:
            session: SQLAlchemy session.
            model: SQLAlchemy model class.
        """
        self._session = session
        self._model = model

    def find_by_id(self, id: Union[UUID, str]) -> Optional[T]:
        """Find entity by ID."""
        return self._session.get(self._model, id)

    def find_by_ids(self, ids: List[Union[UUID, str]]) -> List[T]:
        """Find entities for a set of IDs in a single query.

        Used to batch-fetch related rows when enriching a list page, avoiding
        the per-row ``find_by_id`` N+1. Returns the rows that exist; missing
        IDs are simply absent (callers map by id and default the rest).
        """
        if not ids:
            return []
        primary_key = self._model.id  # type: ignore[attr-defined]
        return self._session.query(self._model).filter(primary_key.in_(ids)).all()

    def find_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Find all entities with pagination."""
        return self._session.query(self._model).limit(limit).offset(offset).all()

    def count(self) -> int:
        """Count total entities."""
        return self._session.query(self._model).count()

    def save(self, entity: Any, expected_version: Optional[int] = None) -> Any:
        """
        Save entity with optimistic locking.

        Args:
            entity: Entity to save
            expected_version: Expected version number (for updates)

        Returns:
            Saved entity with incremented version

        Raises:
            ConcurrentModificationError: If version mismatch detected
        """
        if entity.id and expected_version is not None:
            # Update with version check
            current = self.find_by_id(entity.id)
            if current is None:
                raise ValueError(f"Entity {entity.id} not found")

            if current.version != expected_version:  # type: ignore[attr-defined]
                raise ConcurrentModificationError(
                    f"Entity {entity.id} was modified by another transaction. "
                    f"Expected version {expected_version}, found {current.version}"  # type: ignore[attr-defined]
                )

        try:
            # Add entity to session if it's not already tracked
            from sqlalchemy.orm import object_session
            from sqlalchemy.inspection import inspect

            if object_session(entity) is None or inspect(entity).transient:  # type: ignore[union-attr]
                self._session.add(entity)
            self._session.commit()
            self._session.refresh(entity)
            return entity
        except StaleDataError:
            self._session.rollback()
            raise ConcurrentModificationError(
                "Concurrent modification detected during save"
            )

    def update(self, entity: T) -> T:
        """
        Update entity (alias for save).

        Args:
            entity: Entity to update

        Returns:
            Updated entity
        """
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def delete(self, id: Union[UUID, str]) -> bool:
        """Delete entity by ID."""
        entity = self.find_by_id(id)
        if entity:
            self._session.delete(entity)
            self._session.commit()
            return True
        return False
