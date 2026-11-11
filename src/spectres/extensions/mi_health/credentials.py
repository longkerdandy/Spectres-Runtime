"""Authenticated encryption for Mi Health credentials and transient secrets."""

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialProtectionError(Exception):
    """Credential protection is unavailable or stored data cannot be decrypted."""


class CredentialCipher:
    """Encrypt owner- and purpose-bound values with a configured AES-256 key."""

    def __init__(self, key: str | None) -> None:
        """Retain the optional key without blocking unrelated Runtime startup."""
        self._encoded_key = key

    def _key(self) -> bytes:
        if not self._encoded_key:
            raise CredentialProtectionError("Mi Health credential protection is not configured")
        try:
            key = base64.b64decode(self._encoded_key.encode("ascii"), altchars=b"-_", validate=True)
        except (ValueError, UnicodeEncodeError):
            raise CredentialProtectionError("Mi Health credential protection is not configured correctly") from None
        if len(key) != 32:
            raise CredentialProtectionError("Mi Health credential protection is not configured correctly")
        return key

    def encrypt(self, *, user_id: str, purpose: str, value: str) -> str:
        """Encrypt one value into a versioned JSON envelope."""
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key()).encrypt(nonce, value.encode("utf-8"), self._associated_data(user_id, purpose))
        return json.dumps(
            {
                "v": 1,
                "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
                "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            },
            separators=(",", ":"),
        )

    def decrypt(self, *, user_id: str, purpose: str, envelope: str) -> str:
        """Decrypt one value and enforce its owner, purpose, and envelope version."""
        try:
            payload: Any = json.loads(envelope)
            if not isinstance(payload, dict) or payload.get("v") != 1:
                raise ValueError
            nonce = base64.urlsafe_b64decode(payload["nonce"].encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(payload["ciphertext"].encode("ascii"))
            plaintext = AESGCM(self._key()).decrypt(nonce, ciphertext, self._associated_data(user_id, purpose))
            return plaintext.decode("utf-8")
        except (ValueError, KeyError, TypeError, AttributeError, InvalidTag, UnicodeDecodeError):
            raise CredentialProtectionError("Mi Health stored credentials cannot be decrypted") from None

    @staticmethod
    def _associated_data(user_id: str, purpose: str) -> bytes:
        return f"mi_health:v1:{user_id}:{purpose}".encode()
