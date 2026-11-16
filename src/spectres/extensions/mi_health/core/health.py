"""Pure Mi Fitness health-request signing and response decryption."""

import base64
import hashlib
import json
import os
import struct
import time
from typing import Any


class _Rc4:
    def __init__(self, key: bytes) -> None:
        state = list(range(256))
        j = 0
        for i in range(256):
            j = (j + state[i] + key[i % len(key)]) & 0xFF
            state[i], state[j] = state[j], state[i]
        self._state = state
        self._i = 0
        self._j = 0
        self.apply(bytes(1024))

    def apply(self, data: bytes) -> bytes:
        output = bytearray()
        for value in data:
            self._i = (self._i + 1) & 0xFF
            self._j = (self._j + self._state[self._i]) & 0xFF
            self._state[self._i], self._state[self._j] = self._state[self._j], self._state[self._i]
            output.append(value ^ self._state[(self._state[self._i] + self._state[self._j]) & 0xFF])
        return bytes(output)


def generate_nonce() -> str:
    """Generate eight random bytes followed by whole Unix minutes."""
    payload = os.urandom(8) + struct.pack(">i", int(time.time()) // 60)
    return base64.b64encode(payload).decode("ascii")


def signed_nonce(ssecurity: str, nonce: str) -> str:
    """Derive the health transport key from the session secret and nonce."""
    digest = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce)).digest()
    return base64.b64encode(digest).decode("ascii")


def build_signature(method: str, path: str, params: dict[str, str], signed_nonce_value: str) -> str:
    """Build the plaintext or encrypted parameter-set SHA-1 signature."""
    parts = [method.upper(), path]
    parts.extend(f"{key}={params[key]}" for key in sorted(params))
    parts.append(signed_nonce_value)
    return base64.b64encode(hashlib.sha1("&".join(parts).encode("utf-8")).digest()).decode("ascii")


def encrypt_query_params(
    *,
    path: str,
    signature_path: str,
    nonce: str,
    ssecurity: str,
    params: dict[str, str] | None = None,
) -> dict[str, str]:
    """Sign and encrypt one GET parameter set with a continuous RC4 stream."""
    signed_nonce_value = signed_nonce(ssecurity, nonce)
    plain = dict(params or {})
    plain["rc4_hash__"] = build_signature("GET", signature_path, plain, signed_nonce_value)
    cipher = _Rc4(base64.b64decode(signed_nonce_value))
    encrypted = {key: base64.b64encode(cipher.apply(value.encode("utf-8"))).decode("ascii") for key, value in sorted(plain.items())}
    encrypted["signature"] = build_signature("GET", signature_path, encrypted, signed_nonce_value)
    encrypted["_nonce"] = nonce
    return encrypted


def decrypt_response(body: str, *, nonce: str, ssecurity: str) -> dict[str, Any]:
    """Decrypt and parse one encrypted health response object."""
    key = base64.b64decode(signed_nonce(ssecurity, nonce))
    plaintext = _Rc4(key).apply(base64.b64decode(body))
    payload: Any = json.loads(plaintext.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("health response is not an object")
    return payload
