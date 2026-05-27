"""Shared limit/offset parser for admin list routes (S22 — DRY).

One home for the ``limit = min(int(request.args.get("limit", 20)), 100)``
dance, plus consistent error responses for non-integer params.
"""
from typing import Tuple

from werkzeug.exceptions import BadRequest


DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100


def parse_pagination_params(
    request,
    default_limit: int = DEFAULT_PAGE_SIZE,
    max_limit: int = MAX_PAGE_SIZE,
) -> Tuple[int, int]:
    """Return ``(limit, offset)`` from query params.

    ``limit`` is clamped to ``[1, max_limit]``; ``offset`` is clamped to
    ``[0, +∞]``. Non-integer values raise ``BadRequest`` (HTTP 400)
    rather than silently coercing.
    """
    try:
        raw_limit = int(request.args.get("limit", default_limit))
        raw_offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"limit and offset must be integers: {exc}")
    limit = min(max(raw_limit, 1), max_limit)
    offset = max(raw_offset, 0)
    return limit, offset
