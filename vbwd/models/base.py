"""Base model with common fields and optimistic locking."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, event
from sqlalchemy.dialects.postgresql import UUID

from vbwd.extensions import db
from vbwd.utils.datetime_utils import utcnow


def _utcnow_aware() -> datetime:
    """Timezone-aware ``datetime.now(timezone.utc)`` — distinct from the
    naive ``utcnow`` BaseModel uses; payment plugin models persist their
    timestamps as ``TIMESTAMPTZ`` and want TZ-aware Python objects.
    """
    return datetime.now(timezone.utc)


class TzAwareTimestampMixin:
    """SQLAlchemy mixin providing TZ-aware ``created_at`` / ``updated_at``.

    S20 — extracted from the six payment plugin models that each
    redeclared these columns identically (conekta, mercado_pago,
    truemoney, toss_payments, c2p2, promptpay).

    Use as ``class MyOrder(TzAwareTimestampMixin, db.Model)`` — mixin
    first so SQLAlchemy picks up the columns before the declarative
    metaclass runs. NOT compatible with ``BaseModel``, which uses
    timezone-NAIVE ``DateTime`` columns (intentional — core schema is
    naive UTC; payment plugins chose TZ-aware separately).
    """

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow_aware,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow_aware,
        onupdate=_utcnow_aware,
    )


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
