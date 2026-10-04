"""Password hashing (stdlib scrypt) and JWT access / refresh tokens.

scrypt from hashlib needs no native third-party wheel, which keeps the dependency
surface small and avoids platform-specific crypto builds.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    salt, expected = base64.urlsafe_b64decode(pad(salt_b64)), base64.urlsafe_b64decode(pad(dk_b64))
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
    )
    return hmac.compare_digest(dk, expected)


def make_token(
    secret: str, subject: str, kind: str, ttl: timedelta, role: str, token_version: int = 0
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "typ": kind,
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(secret: str, token: str, kind: str) -> dict:
    payload = jwt.decode(
        token, secret, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]}
    )
    if payload.get("typ") != kind:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
