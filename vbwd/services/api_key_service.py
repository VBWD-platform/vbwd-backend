"""Core API-key service (S52).

Pure auth-mechanism logic — no Flask import, repo injected (SRP/DI/testable).
Generates / hashes / verifies keys, enforces the IP whitelist and scope
allow-list, and revokes (owner-guarded).

Security:
- The plaintext token is returned **once** at creation and **never** stored;
  only its sha256 hash is persisted.
- Lookups compare hashes in **constant time** (``hmac.compare_digest``).
- The IP whitelist supports exact IPs and CIDRs (stdlib ``ipaddress``); an
  empty whitelist allows any IP.
- Scope membership is **exact**; an empty allow-list authorizes nothing (deny).
"""
import hashlib
import hmac
import ipaddress
import secrets
from typing import List, Optional, Tuple, Union
from uuid import UUID

from vbwd.models.api_key import ApiKey
from vbwd.repositories.api_key_repository import ApiKeyRepository
from vbwd.utils.datetime_utils import utcnow

TOKEN_PREFIX = "vbwdk_"
TOKEN_ENTROPY_BYTES = 32
PREFIX_DISPLAY_LENGTH = 10


class ApiKeyService:
    """Generate, verify, scope, and revoke API keys."""

    def __init__(self, repository: ApiKeyRepository):
        self._repository = repository

    @staticmethod
    def hash_token(plaintext: str) -> str:
        """Return the sha256 hex digest used as the stored ``key_hash``."""
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

    def generate(
        self,
        *,
        user_id: Union[UUID, str],
        label: str,
        scopes: List[str],
        ip_whitelist: Optional[List[str]] = None,
        created_by_user_id: Optional[Union[UUID, str]] = None,
    ) -> Tuple[ApiKey, str]:
        """Create a key. Returns the persisted row + the plaintext token (once).

        The plaintext is the only time the secret is visible; thereafter only
        ``key_prefix`` is shown.
        """
        plaintext = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)

        api_key = ApiKey()
        api_key.user_id = user_id
        api_key.label = label
        api_key.key_hash = self.hash_token(plaintext)
        api_key.key_prefix = plaintext[:PREFIX_DISPLAY_LENGTH]
        api_key.scopes = list(scopes or [])
        api_key.ip_whitelist = list(ip_whitelist or [])
        api_key.is_active = True
        api_key.created_by_user_id = created_by_user_id or user_id

        self._repository.save(api_key)
        return api_key, plaintext

    def list_for_user(self, user_id: Union[UUID, str]) -> List[ApiKey]:
        """List a user's keys (newest first)."""
        return self._repository.find_by_user(user_id)

    def get(self, key_id: Union[UUID, str]) -> Optional[ApiKey]:
        """Fetch a key by id, or None."""
        return self._repository.find_by_id(key_id)

    def delete(self, key_id: Union[UUID, str]) -> bool:
        """Hard-delete a key by id."""
        return self._repository.delete(key_id)

    def verify(self, plaintext: Optional[str]) -> Optional[ApiKey]:
        """Resolve a presented token to its active key, or None.

        Constant-time hash compare guards against timing attacks even though the
        primary lookup is already an indexed hash equality.
        """
        if not plaintext:
            return None
        presented_hash = self.hash_token(plaintext)
        candidate = self._repository.find_by_hash(presented_hash)
        if candidate is None or not candidate.is_active:
            return None
        if not hmac.compare_digest(candidate.key_hash, presented_hash):
            return None
        return candidate

    def is_ip_allowed(self, api_key: ApiKey, client_ip: Optional[str]) -> bool:
        """True when ``client_ip`` matches the key's whitelist (empty ⇒ any)."""
        whitelist = list(api_key.ip_whitelist or [])
        if not whitelist:
            return True
        if not client_ip:
            return False
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        for entry in whitelist:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                continue
            if address in network:
                return True
        return False

    def has_scope(self, api_key: ApiKey, required_scope: str) -> bool:
        """True only when the key explicitly lists ``required_scope``."""
        return required_scope in (api_key.scopes or [])

    def touch(self, api_key: ApiKey) -> None:
        """Stamp ``last_used_at`` and persist."""
        api_key.last_used_at = utcnow()
        self._repository.save(api_key)

    def revoke(
        self,
        key_id: Union[UUID, str],
        *,
        owner_id: Optional[Union[UUID, str]] = None,
    ) -> bool:
        """Deactivate a key. When ``owner_id`` is given, the key must belong to
        that user (self-service guard) — else ``PermissionError``.

        Returns False when the key does not exist.
        """
        api_key = self._repository.find_by_id(key_id)
        if api_key is None:
            return False
        if owner_id is not None and str(api_key.user_id) != str(owner_id):
            raise PermissionError("API key does not belong to the requesting user")
        return self._repository.revoke(key_id)
