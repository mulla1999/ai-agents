"""Password hashing with scrypt (standard library). Format: ``scrypt$n$r$p$salt$hash`` (base64)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**15, 8, 1
MIN_LENGTH = 12
_COMMON = frozenset({"password1234", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345", "password@123",
                     "admin1234567", "iloveyou1234", "passwordpassword"})


class WeakPassword(ValueError):
    pass


def check_strength(password: str, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"use at least {MIN_LENGTH} characters")
    if len(password) > 256:
        raise WeakPassword("use at most 256 characters")
    if password.lower() in _COMMON or len(set(password)) < 5:
        raise WeakPassword("this password is too easy to guess")
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        raise WeakPassword("do not include your email address in the password")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    enc = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        hashlib.scrypt(b"x", salt=b"0" * 16, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)  # same timing
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=64 * 1024 * 1024, dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
