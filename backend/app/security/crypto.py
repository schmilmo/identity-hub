"""AES-256-GCM encryption for Jira API tokens at rest.

GCM is authenticated encryption: tampering with the ciphertext is detected on
decrypt. A fresh random 96-bit nonce is generated per encryption and stored
alongside the ciphertext (nonces need not be secret, only unique per key).

The master key comes from APP_ENCRYPTION_KEY. We derive a stable 32-byte key
from it via SHA-256 so any sufficiently-long passphrase works in dev, while a
proper 32-byte secret should be supplied in production.
"""
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_NONCE_BYTES = 12


def _key() -> bytes:
    raw = get_settings().app_encryption_key.encode("utf-8")
    return hashlib.sha256(raw).digest()  # 32 bytes


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Return (ciphertext, nonce)."""
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    aesgcm = AESGCM(_key())
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
