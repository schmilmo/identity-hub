"""Generation and hashing of opaque tokens: session IDs and API keys.

API keys follow the ``ih_live_<random>`` convention. We store only a SHA-256
hash (keys are high-entropy random values, so a fast hash with constant-time
comparison is sufficient — unlike low-entropy passwords which need argon2).
"""
import hashlib
import hmac
import secrets

API_KEY_PREFIX = "ih_live_"


def generate_session_id() -> str:
    return secrets.token_urlsafe(48)


def generate_api_key() -> str:
    """Full plaintext key, shown to the user exactly once."""
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def key_prefix_for_display(api_key: str) -> str:
    # e.g. "ih_live_a1b2c3" — enough to identify a key without revealing it.
    return api_key[: len(API_KEY_PREFIX) + 6]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
