"""Datetime utilities.

The codebase currently uses naive UTC datetimes for core ``DateTime``
columns; payment plugins already use TZ-aware via
``vbwd.models.base.TzAwareTimestampMixin`` (S20). The end state is
fully TZ-aware everywhere — tracked by S19 with a meta backlog
oracle at ``tests/meta/test_datetime_tz_backlog.py``.

This module provides two helpers — pick the one that matches the
column's tzinfo:
  * ``utcnow()`` — naive (current core default).
  * ``utcnow_aware()`` — TZ-aware (new code; S20 plugins; future core).

Migration end state:
  1. Switch core ``DateTime`` columns to ``DateTime(timezone=True)``.
  2. Write an Alembic migration converting existing naive rows.
  3. Delete ``utcnow`` and ``.replace(tzinfo=None)`` everywhere.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-naive datetime.

    Internally uses ``datetime.now(timezone.utc)`` to avoid the deprecated
    ``datetime.utcnow()``. The tzinfo is stripped so the result is
    compatible with naive ``DateTime`` DB columns.

    **Prefer :func:`utcnow_aware` in new code** — see module docstring.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Return the current UTC time as a timezone-AWARE datetime (S19).

    Use this for any new column declared with ``DateTime(timezone=True)``
    (the convention payment plugins already follow via
    ``TzAwareTimestampMixin``). The two helpers exist side-by-side until
    the migration to fully aware columns lands — see module docstring
    for the end state.
    """
    return datetime.now(timezone.utc)
