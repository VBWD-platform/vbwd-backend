"""Datetime utilities.

The codebase uses naive UTC datetimes throughout to stay consistent with
SQLAlchemy ``DateTime`` (without timezone) columns.  The Python built-in
``datetime.utcnow()`` is deprecated since Python 3.12; this module provides
a drop-in replacement that uses the recommended ``datetime.now(timezone.utc)``
internally but strips the tzinfo before returning so existing DB comparisons
continue to work.

TODO: Migrate to fully timezone-aware datetimes:
  1. Change all ``DateTime`` columns to ``DateTime(timezone=True)``
  2. Write an Alembic migration that converts existing rows
  3. Remove the ``.replace(tzinfo=None)`` call below
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-naive datetime.

    Internally uses ``datetime.now(timezone.utc)`` to avoid the deprecated
    ``datetime.utcnow()``.  The tzinfo is stripped so the result is
    compatible with naive ``DateTime`` DB columns.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
