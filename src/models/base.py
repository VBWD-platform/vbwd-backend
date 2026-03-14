"""Base model with common fields and optimistic locking."""
from src.utils.datetime_utils import utcnow
from uuid import uuid4
from sqlalchemy import Column, DateTime, Integer, event
from sqlalchemy.dialects.postgresql import UUID
from src.extensions import db


class ConcurrentModificationError(Exception):
    """Raised when optimistic locking detects concurrent modification."""

    pass


class BaseModel(db.Model):  # type: ignore[name-defined]
    """
    Abstract base model with common fields and optimistic locking.

    All models inherit:
    - UUID primary key
    - Created/updated timestamps
    - Version column for optimistic locking
    """

    __abstract__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(
        DateTime,
        nullable=False,
        default=utcnow,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
    version = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }


# Auto-increment version on update
@event.listens_for(BaseModel, "before_update", propagate=True)
def increment_version(mapper, connection, target):
    """Increment version before update."""
    target.version += 1
