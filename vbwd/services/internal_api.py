"""In-process dispatch to the app's own ``/api/v1/*`` endpoints (S152 C2).

A server-side consumer (a renderer, a bot, a worker) calls the SAME public API
the browser calls, without opening a socket: the request is built with
Werkzeug's ``EnvironBuilder`` and run through ``app.wsgi_app``, so it gets its
own app/request context, its own Flask-SQLAlchemy scoped session and its own
``g``. Business rules, RBAC and rate limits therefore apply exactly as they do
to a browser call — there is no exemption flag.

Rules:

* only ``/api/v1/`` paths are dispatched (``ValueError`` otherwise);
* ``forward_from=<flask request>`` copies an allow-list of headers and of
  cookies; explicit ``headers=`` are merged on top;
* the client IP / host / scheme are rebuilt from the environ ProxyFix saved
  before rewriting it, and the ``X-Forwarded-*`` headers are copied verbatim,
  so the inner pass through ProxyFix recomputes the same values without the
  headers ever being appended to twice;
* the inner environ is marked with ``vbwd.internal_depth``; dispatching from
  inside an inner request raises ``InternalApiRecursionError``.
"""
import json as json_module
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from flask import Flask, Request, current_app, has_request_context
from flask import request as current_request
from werkzeug.datastructures import Headers
from werkzeug.test import EnvironBuilder, run_wsgi_app

logger = logging.getLogger(__name__)

EXTENSION_NAME = "internal_api"
API_PATH_PREFIX = "/api/v1/"
INTERNAL_DEPTH_ENVIRON_KEY = "vbwd.internal_depth"
PROXY_FIX_ORIGINAL_ENVIRON_KEY = "werkzeug.proxy_fix.orig"
REQUEST_ID_HEADER = "X-Request-ID"
DEFAULT_FORWARDED_COOKIE_NAMES = frozenset({"vbwd_lang"})

FORWARDED_HEADER_NAMES = (
    "Authorization",
    "Accept-Language",
    "Origin",
    "Referer",
    "User-Agent",
    REQUEST_ID_HEADER,
)
# Copied verbatim (never appended to) so the inner ProxyFix pass sees the
# same chain the outer pass saw.
PROXY_HEADER_NAMES = (
    "X-Forwarded-For",
    "X-Forwarded-Proto",
    "X-Forwarded-Host",
    "X-Forwarded-Port",
    "X-Forwarded-Prefix",
)
# The pre-ProxyFix connection values the inner environ is rebuilt from.
CONNECTION_ENVIRON_KEYS = (
    "REMOTE_ADDR",
    "wsgi.url_scheme",
    "HTTP_HOST",
    "SERVER_NAME",
    "SERVER_PORT",
)


class InternalApiRecursionError(RuntimeError):
    """An in-process API call tried to dispatch another in-process call."""


@dataclass(frozen=True)
class InternalResponse:
    """The immutable result of one in-process API call."""

    status: int
    headers: Headers
    text: str

    def json(self) -> Any:
        """The decoded JSON body, or ``None`` for an empty body."""
        return json_module.loads(self.text) if self.text else None


class InternalApiClient:
    """Dispatch requests to this app's ``/api/v1/*`` endpoints in-process."""

    def __init__(
        self,
        app: Flask,
        forwarded_cookie_names: Iterable[str] = DEFAULT_FORWARDED_COOKIE_NAMES,
    ) -> None:
        self._app = app
        self._forwarded_cookie_names = frozenset(forwarded_cookie_names)

    def get(self, path: str, **options: Any) -> InternalResponse:
        return self.request("GET", path, **options)

    def post(self, path: str, **options: Any) -> InternalResponse:
        return self.request("POST", path, **options)

    def put(self, path: str, **options: Any) -> InternalResponse:
        return self.request("PUT", path, **options)

    def delete(self, path: str, **options: Any) -> InternalResponse:
        return self.request("DELETE", path, **options)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        query: Optional[Mapping[str, Any]] = None,
        forward_from: Optional[Request] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> InternalResponse:
        """Run one request through ``app.wsgi_app`` and return its response."""
        if not path.startswith(API_PATH_PREFIX):
            raise ValueError(
                f"InternalApiClient only dispatches {API_PATH_PREFIX}* paths, "
                f"got {path!r}"
            )
        _refuse_nested_dispatch(forward_from)

        request_headers = self._build_headers(forward_from, headers)
        environ = _build_environ(
            method.upper(), path, json, query, request_headers, forward_from
        )
        logger.debug(
            "internal api %s %s request_id=%s",
            method.upper(),
            path,
            request_headers.get(REQUEST_ID_HEADER),
        )
        # Flask reuses an already-active app context of the same app for a new
        # request context, which would share the outer ``g`` and scoped
        # session. A fresh app context gives the inner request its own.
        with self._app.app_context():
            body_chunks, status_line, response_headers = run_wsgi_app(
                self._app.wsgi_app, environ, buffered=True
            )
        return InternalResponse(
            status=int(status_line.split(" ", 1)[0]),
            headers=Headers(response_headers),
            text=b"".join(body_chunks).decode("utf-8", errors="replace"),
        )

    def _build_headers(
        self,
        forward_from: Optional[Request],
        explicit_headers: Optional[Mapping[str, str]],
    ) -> Headers:
        request_headers = Headers()
        if forward_from is not None:
            for header_name in FORWARDED_HEADER_NAMES + PROXY_HEADER_NAMES:
                header_value = forward_from.headers.get(header_name)
                if header_value is not None:
                    request_headers[header_name] = header_value
            cookie_header = self._allowed_cookie_header(forward_from)
            if cookie_header:
                request_headers["Cookie"] = cookie_header
        if explicit_headers:
            request_headers.update(explicit_headers)
        return request_headers

    def _allowed_cookie_header(self, forward_from: Request) -> str:
        return "; ".join(
            f"{cookie_name}={cookie_value}"
            for cookie_name, cookie_value in forward_from.cookies.items()
            if cookie_name in self._forwarded_cookie_names
        )


def _refuse_nested_dispatch(forward_from: Optional[Request]) -> None:
    outer_environs = []
    if forward_from is not None:
        outer_environs.append(forward_from.environ)
    if has_request_context():
        outer_environs.append(current_request.environ)
    if any(
        environ.get(INTERNAL_DEPTH_ENVIRON_KEY, 0) >= 1 for environ in outer_environs
    ):
        raise InternalApiRecursionError(
            "InternalApiClient may not be called from inside an in-process API call"
        )


def _build_environ(
    method: str,
    path: str,
    json: Any,
    query: Optional[Mapping[str, Any]],
    request_headers: Headers,
    forward_from: Optional[Request],
) -> dict:
    """The inner WSGI environ, marked as an in-process call."""
    builder = EnvironBuilder(
        path=path,
        method=method,
        json=json,
        query_string=dict(query) if query else None,
        headers=request_headers,
    )
    try:
        environ = builder.get_environ()
    finally:
        builder.close()
    if forward_from is not None:
        environ.update(_original_connection_environ(forward_from.environ))
    environ[INTERNAL_DEPTH_ENVIRON_KEY] = 1
    return environ


def _original_connection_environ(outer_environ: Mapping[str, Any]) -> dict:
    """The outer connection values as they were BEFORE ProxyFix rewrote them."""
    original_values = outer_environ.get(PROXY_FIX_ORIGINAL_ENVIRON_KEY) or outer_environ
    return {
        environ_key: original_values[environ_key]
        for environ_key in CONNECTION_ENVIRON_KEYS
        if original_values.get(environ_key) is not None
    }


def resolve_internal_api_client() -> InternalApiClient:
    """The app's registered client (``app.extensions['internal_api']``)."""
    client: InternalApiClient = current_app.extensions[EXTENSION_NAME]
    return client
