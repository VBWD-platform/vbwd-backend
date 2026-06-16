"""Decorators package.

The live authorization decorators live in ``vbwd/middleware/auth.py``. This
package exposes only the entitlement-port guards (``require_feature`` /
``check_usage_limit``); the dead duplicate permission/role decorators were
removed in S90 Slice 2 / S94 G4.
"""
from vbwd.decorators.permissions import (
    require_feature,
    check_usage_limit,
)

__all__ = [
    "require_feature",
    "check_usage_limit",
]
