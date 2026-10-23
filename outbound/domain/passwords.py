"""Password rules (Phase 6b), after NIST SP 800-63B-4 for a password that is the only factor:
at least 15 characters, long passphrases welcome, no composition rules, and not a known
common password. Nothing here calls the network."""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

MIN_LENGTH = 15
MAX_LENGTH = 256

# A few of the most common long passwords and patterns; length already rules out most lists.
_COMMON = frozenset(
    {
        "passwordpassword", "123456789012345", "1234567890123456", "qwertyuiopasdfgh",
        "iloveyouiloveyou", "passwordpassword1", "welcome12345678", "adminadminadmin",
        "letmeinletmein1", "changemechangeme", "abcdefghijklmnop", "qwertyqwertyqwerty",
        "000000000000000", "111111111111111", "password1234567", "correcthorsebatterystaple",
    }
)  # fmt: skip


def password_problem(password: str, *, email: str = "") -> str | None:
    """Why this password is not acceptable, or None if it is."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters. A few unrelated words work well."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    folded = password.casefold().replace(" ", "")
    if folded in _COMMON or len(set(folded)) <= 3:
        return "That password is too common or too simple. Choose another."
    local = email.split("@", 1)[0].casefold()
    if local and len(local) >= 4 and local in folded:
        return "Do not use your email address in the password."
    return None


def hash_password(password: str) -> str:
    """Argon2id, with the library's current recommended cost."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> tuple[str, str]:
    """A random single-use secret and the hash that is stored in its place."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
