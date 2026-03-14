"""Shared validation helpers for route handlers."""
import uuid
from flask import abort


def parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string and return a UUID object, or abort with 400."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        abort(400, description="Invalid ID format")


def parse_uuid_or_none(value) -> "uuid.UUID | None":
    """Parse a UUID string, returning None on failure instead of aborting."""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None
