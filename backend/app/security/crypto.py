"""Encryption for Jira API tokens at rest.

Two pluggable backends behind one interface (``encrypt`` / ``decrypt``):

- **vault** (default): HashiCorp Vault's Transit engine performs the
  encryption — the key material never leaves Vault and never touches this
  process. We store the self-describing ``vault:v1:...`` ciphertext.
- **local**: AES-256-GCM with a key derived from ``APP_ENCRYPTION_KEY``. No
  external dependency; used by the test suite and for Vault-free local runs.

The backend is chosen by ``CRYPTO_BACKEND``. The rest of the app is unaware of
which is active: ``client_for()`` and the ORM models are unchanged. The
interface returns/accepts ``(ciphertext: bytes, nonce: bytes)``; the Vault
backend leaves ``nonce`` empty (its ciphertext is self-contained).
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_NONCE_BYTES = 12


# --------------------------------------------------------------------------- #
# Local AES-256-GCM backend
# --------------------------------------------------------------------------- #
def _local_key() -> bytes:
    raw = get_settings().app_encryption_key.encode("utf-8")
    return hashlib.sha256(raw).digest()  # 32 bytes


def _local_encrypt(plaintext: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_local_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def _local_decrypt(ciphertext: bytes, nonce: bytes) -> str:
    return AESGCM(_local_key()).decrypt(nonce, ciphertext, None).decode("utf-8")


# --------------------------------------------------------------------------- #
# Vault Transit backend (encryption-as-a-service)
# --------------------------------------------------------------------------- #
_vault_client = None


def _vault():
    """Lazily build the hvac client so the dependency is only imported/needed
    when the Vault backend is actually in use."""
    global _vault_client
    if _vault_client is None:
        import hvac  # imported lazily

        s = get_settings()
        _vault_client = hvac.Client(url=s.vault_addr, token=s.vault_token)
    return _vault_client


def _vault_encrypt(plaintext: str) -> tuple[bytes, bytes]:
    s = get_settings()
    resp = _vault().secrets.transit.encrypt_data(
        name=s.vault_transit_key,
        plaintext=base64.b64encode(plaintext.encode("utf-8")).decode("utf-8"),
        mount_point=s.vault_transit_mount,
    )
    ciphertext = resp["data"]["ciphertext"]  # "vault:v1:..."
    return ciphertext.encode("utf-8"), b""  # nonce unused for this backend


def _vault_decrypt(ciphertext: bytes, nonce: bytes) -> str:
    s = get_settings()
    resp = _vault().secrets.transit.decrypt_data(
        name=s.vault_transit_key,
        ciphertext=ciphertext.decode("utf-8"),
        mount_point=s.vault_transit_mount,
    )
    return base64.b64decode(resp["data"]["plaintext"]).decode("utf-8")


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #
def _use_vault() -> bool:
    return get_settings().crypto_backend == "vault"


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Return (ciphertext, nonce). nonce is empty for the Vault backend."""
    return _vault_encrypt(plaintext) if _use_vault() else _local_encrypt(plaintext)


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    return (
        _vault_decrypt(ciphertext, nonce)
        if _use_vault()
        else _local_decrypt(ciphertext, nonce)
    )


def ensure_ready() -> None:
    """Startup hook. For the Vault backend, make sure the Transit engine is
    mounted and the encryption key exists (both idempotent). No-op for local."""
    if not _use_vault():
        return
    s = get_settings()
    client = _vault()
    try:
        client.sys.enable_secrets_engine(
            backend_type="transit", path=s.vault_transit_mount
        )
    except Exception:
        pass  # already enabled
    # Creating an existing transit key is a safe no-op in Vault.
    client.secrets.transit.create_key(
        name=s.vault_transit_key, mount_point=s.vault_transit_mount
    )
