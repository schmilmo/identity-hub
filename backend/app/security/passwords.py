"""Password hashing with argon2id (memory-hard, current OWASP recommendation).

The argon2 verify call is constant-time and raises on mismatch, so login
timing does not leak whether the email exists (the router also hashes a dummy
password when the user is missing — see auth router)."""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed hash, etc. — treat as failed auth, never raise to caller.
        return False
