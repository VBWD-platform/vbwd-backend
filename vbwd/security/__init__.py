"""Core security introspection helpers (S90).

Houses the route-exposure audit logic (``route_audit``) so both the
route-exposure oracle (``tests/unit/security/test_route_exposure_oracle.py``)
and the future ``flask prod-readiness`` command share one source of truth
(DRY). This package is core-agnostic: it only walks a Flask ``app.url_map``
and reads the generic auth/permission/debug markers that core middleware
stamps on view functions — it never imports or reads a plugin domain field.
"""
