"""S22 — pagination helper contract tests."""
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import BadRequest

from vbwd.utils.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    parse_pagination_params,
)


def _fake_request(args: dict):
    request = MagicMock()
    request.args.get.side_effect = lambda key, default=None: args.get(key, default)
    return request


def test_defaults_when_no_query_params():
    request = _fake_request({})
    limit, offset = parse_pagination_params(request)
    assert limit == DEFAULT_PAGE_SIZE
    assert offset == 0


def test_explicit_values_passed_through():
    request = _fake_request({"limit": "50", "offset": "100"})
    limit, offset = parse_pagination_params(request)
    assert limit == 50
    assert offset == 100


def test_limit_clamped_to_max():
    request = _fake_request({"limit": "9999"})
    limit, _ = parse_pagination_params(request)
    assert limit == MAX_PAGE_SIZE


def test_limit_floor_is_one():
    request = _fake_request({"limit": "0"})
    limit, _ = parse_pagination_params(request)
    assert limit == 1


def test_negative_offset_clamped_to_zero():
    request = _fake_request({"offset": "-50"})
    _, offset = parse_pagination_params(request)
    assert offset == 0


def test_non_integer_raises_bad_request():
    request = _fake_request({"limit": "abc"})
    with pytest.raises(BadRequest):
        parse_pagination_params(request)


def test_custom_default_and_max_honoured():
    request = _fake_request({"limit": "5000"})
    limit, _ = parse_pagination_params(request, default_limit=10, max_limit=500)
    assert limit == 500
