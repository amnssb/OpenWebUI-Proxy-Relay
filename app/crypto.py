"""Symmetric encryption for secrets stored at rest (OpenWebUI account passwords).

The proxy must send the cleartext password to OpenWebUI to log in, so passwords
cannot be hashed — they are encrypted with Fernet (AES-128-CBC + HMAC) and
decrypted on use.

Stored values are tagged with ``enc:v1:`` so legacy plaintext rows (saved before
encryption was added) are detected and returned as-is, then transparently
upgraded to ciphertext the next time the account is edited.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    # Derive a valid 32-byte urlsafe-base64 Fernet key from the configured
    # secret so deployments don't need to manage a separate key by default.
    secret = settings.encryption_key or settings.session_secret
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage, returning an ``enc:v1:`` tagged token."""
    token = _fernet().encrypt((plaintext or "").encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(stored: str) -> str:
    """Decrypt a stored secret. Untagged (legacy plaintext) values pass through."""
    if not stored or not stored.startswith(_PREFIX):
        return stored or ""
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError("无法解密账号密码（加密密钥可能已更改）") from e


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(_PREFIX)
