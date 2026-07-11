"""Shared limit/offset parser for admin list routes (S22 — DRY).

One home for the ``limit = min(int(request.args.get("limit", 20)), 100)``
dance, plus consistent error responses for non-integer params.

Also home to :func:`paginate`, the vocabulary-free helper that wraps an
already-fetched page slice + filtered total in the catalogue list wire
envelope (``docs/architecture/catalogue-list-contract.md``). It carries no
domain vocabulary so every vertical's "browse many" route shapes its response
identically through one core helper.
"""
from typing import Any, Dict, List, Tuple

from werkzeug.exceptions import BadRequest


DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100


def paginate(items: List[Any], total: int, page: int, per_page: int) -> Dict[str, Any]:
    """Wrap a page slice + filtered total in the catalogue list envelope.

    ``items`` is the already-fetched, already-sliced page (the caller owns the
    query and the sort). ``total`` is the count of rows matching the *effective
    filter* across all pages — NOT the whole collection. ``pages`` is
    ``ceil(total / per_page)`` and is never ``0``: an empty result set is
    ``pages == 1`` with ``items == []``.

    Returns ``{"items", "total", "page", "per_page", "pages"}`` exactly.
    """
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


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
