"""Password hashing and JWT issuance for ShopNest."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from .config import settings

_PBKDF_ROUNDS = 120_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    return hmac.compare_digest(computed.hex(), digest_hex)


def password_problems(password: str) -> list[str]:
    """Return every policy violation so the API can report them all at once."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    if not any(c.isdigit() for c in password):
        problems.append("password must contain a digit")
    if not any(c.isalpha() for c in password):
        problems.append("password must contain a letter")
    return problems


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or "")) and len(email) <= 254


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    minutes = settings.access_token_minutes if expires_minutes is None else expires_minutes
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "iss": "shopnest",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Raised when a bearer token cannot be trusted."""


def decode_access_token(token: str) -> dict[str, Any]:
    # FAULT: weak_auth drops expiry verification, so a stale token still works.
    verify_exp = not settings.fault_enabled("weak_auth")
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="shopnest",
            options={"verify_exp": verify_exp},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
