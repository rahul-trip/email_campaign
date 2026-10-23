"""Password rules (Phase 6b), after NIST SP 800-63B-4 for a password that is the only factor:
at least 15 characters, long passphrases welcome, no composition rules, and not a known
common password. Nothing here calls the network."""

from __future__ import annotations

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
