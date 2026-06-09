"""Unit tests for the security primitives."""
import pytest

from app.security.crypto import decrypt, encrypt
from app.security.passwords import hash_password, verify_password
from app.security.tokens import (
    generate_api_key,
    hash_api_key,
    key_prefix_for_display,
)


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery")
    assert h != "correct horse battery"  # never stored in clear
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)


def test_password_hash_is_salted():
    # Same password hashes to different values (random salt).
    assert hash_password("same") != hash_password("same")


def test_crypto_roundtrip():
    ciphertext, nonce = encrypt("super-secret-token")
    assert b"super-secret-token" not in ciphertext
    assert decrypt(ciphertext, nonce) == "super-secret-token"


def test_crypto_uses_fresh_nonce():
    c1, n1 = encrypt("x")
    c2, n2 = encrypt("x")
    assert n1 != n2 and c1 != c2  # nondeterministic encryption


def test_crypto_rejects_tampering():
    ciphertext, nonce = encrypt("x")
    tampered = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
    with pytest.raises(Exception):
        decrypt(tampered, nonce)


def test_api_key_format_and_hash():
    key = generate_api_key()
    assert key.startswith("ih_live_")
    assert key_prefix_for_display(key).startswith("ih_live_")
    # Hash is deterministic and not the key itself.
    assert hash_api_key(key) == hash_api_key(key)
    assert hash_api_key(key) != key
