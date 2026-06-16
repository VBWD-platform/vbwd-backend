"""``LlmConnection`` — an admin-managed LLM provider connection (S97.1).

A core, domain-agnostic registry row (sibling of ``Currency`` / ``Tax``): the
admin configures endpoint + key + model once, and every LLM-consuming plugin
resolves a connection from core instead of holding its own credentials.

The ``api_key`` column is an :class:`~vbwd.utils.crypto.EncryptedString`, so it
is transparently encrypted at rest (D-KeyAtRest); :meth:`to_dict` only ever
returns a 16-char preview, never the full key (the API/exports must not leak a
live key).
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.utils.crypto import EncryptedString

# How many leading characters of the api_key the masked preview reveals.
KEY_PREVIEW_LENGTH = 16
KEY_PREVIEW_SUFFIX = "…"  # an ellipsis "…"
_ANTHROPIC_MODEL_PREFIX = "claude-"
_PROVIDER_ANTHROPIC = "anthropic"
_PROVIDER_OPENAI = "openai"


def mask_api_key(api_key: str) -> str:
    """Return the masked preview of ``api_key`` (first 16 chars then an ellipsis).

    The single shared mask path used by ``to_dict``, the admin routes, and the
    data-exchange export (DRY — one mask implementation). A short key shorter
    than the preview length is returned whole-then-ellipsis; ``None``/empty maps
    to an empty string.
    """
    if not api_key:
        return ""
    return api_key[:KEY_PREVIEW_LENGTH] + KEY_PREVIEW_SUFFIX


class LlmConnection(BaseModel):
    """An admin-managed connection to an LLM provider."""

    __tablename__ = "vbwd_llm_connection"

    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    connection_name = db.Column(db.String(200), nullable=False)
    api_endpoint = db.Column(db.String(500), nullable=False, default="")
    api_key = db.Column(EncryptedString, nullable=False)
    model = db.Column(db.String(200), nullable=False)
    # Explicit provider override; when NULL the provider is derived from ``model``
    # (``claude-*`` -> anthropic else openai — D-Provider).
    provider = db.Column(db.String(50), nullable=True)
    temperature = db.Column(db.Float, nullable=True)
    max_tokens = db.Column(db.Integer, nullable=True)
    timeout = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    last_active_at = db.Column(db.DateTime, nullable=True)

    @property
    def resolved_provider(self) -> str:
        """The provider for this connection: the override, else derived from model."""
        if self.provider:
            return self.provider
        if (self.model or "").startswith(_ANTHROPIC_MODEL_PREFIX):
            return _PROVIDER_ANTHROPIC
        return _PROVIDER_OPENAI

    def to_dict(self) -> dict:
        """Serialise with a MASKED api_key — never the full key."""
        return {
            "id": str(self.id),
            "slug": self.slug,
            "connection_name": self.connection_name,
            "api_endpoint": self.api_endpoint,
            "api_key": mask_api_key(self.api_key),
            "model": self.model,
            "provider": self.resolved_provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "last_active_at": (
                self.last_active_at.isoformat() if self.last_active_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<LlmConnection(slug='{self.slug}', model='{self.model}')>"
