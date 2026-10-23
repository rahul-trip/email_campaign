"""Encryption for the secrets a workspace gives us: mailbox tokens and passwords, webhook keys.

AES-256-GCM (``cryptography``). Each secret is sealed with a fresh 96-bit nonce and with
*associated data* naming where it lives (``workspace_id|credential_id``), so a ciphertext copied
into another row, or another workspace, does not decrypt. The keys come from the environment
(``SECRETS_KEYS``, kept in Doppler), shaped ``{"1": "<base64 of 32 bytes>", "2": ...}``; the
highest version seals new secrets, and every listed version can still open old ones until
``outbound secrets rotate`` has re-sealed them.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from outbound.domain.errors import ConfigurationError

NONCE_BYTES = 12
KEY_BYTES = 32


class SecretUnreadable(Exception):
    """The ciphertext was altered, moved to another row, or sealed with a key we no longer have."""


@dataclass(frozen=True)
class Sealed:
    key_version: int
    nonce: bytes
    ciphertext: bytes


def associated_data(workspace_id: str, credential_id: str) -> bytes:
    return f"{workspace_id}|{credential_id}".encode()


def new_key() -> str:
    """A fresh key, base64, for ``SECRETS_KEYS``."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode()


class Keyring:
    def __init__(self, keys: dict[int, bytes]) -> None:
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ConfigurationError(f"SECRETS_KEYS: key {version} is not 32 bytes")
        self._keys = dict(keys)

    @classmethod
    def from_setting(cls, value: str) -> Keyring:
        """Parse ``SECRETS_KEYS``. An empty value gives a keyring that refuses to be used."""
        if not value.strip():
            return cls({})
        try:
            raw = json.loads(value)
            keys = {int(v): base64.b64decode(k, validate=True) for v, k in raw.items()}
        except (ValueError, TypeError, AttributeError, binascii.Error):
            raise ConfigurationError(
                'SECRETS_KEYS must be JSON like {"1": "<base64 of 32 bytes>"}; '
                "make a key with: uv run outbound secrets new-key"
            ) from None
        return cls(keys)

    @property
    def newest(self) -> int:
        if not self._keys:
            raise ConfigurationError(
                "SECRETS_KEYS is not set, so mailbox passwords and tokens cannot be stored. "
                "Make a key with `uv run outbound secrets new-key` and set "
                'SECRETS_KEYS={"1": "<key>"}.'
            )
        return max(self._keys)

    def seal(self, plaintext: str, aad: bytes) -> Sealed:
        version = self.newest
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self._keys[version]).encrypt(nonce, plaintext.encode(), aad)
        return Sealed(version, nonce, sealed)

    def open(self, sealed: Sealed, aad: bytes) -> str:
        key = self._keys.get(sealed.key_version)
        if key is None:
            raise SecretUnreadable(f"key version {sealed.key_version} is not in SECRETS_KEYS")
        try:
            return AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, aad).decode()
        except InvalidTag:
            raise SecretUnreadable("the secret does not belong here or was altered") from None
