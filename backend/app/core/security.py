"""Password hashing and JWT issuing/verification.

``passlib`` + ``bcrypt`` are pinned to versions that coexist on Windows/CPython
3.12; the hash helpers degrade gracefully if no backend is available so the
API can still boot in a fresh environment.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import settings

try:  # pragma: no cover - environment dependent
    from passlib.context import CryptContext

    _pwd_context: Any = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:  # pragma: no cover
    _pwd_context = None

_PBKDF2_ROUNDS = 260_000


def hash_password(password: str) -> str:
    if _pwd_context is not None:
        try:
            return _pwd_context.hash(password)
        except Exception:  # pragma: no cover - fall through to pbkdf2
            pass
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    if hashed.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = hashed.split("$")
            candidate = hashlib.pbkdf2_hmac(
                "sha256", plain.encode(), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(candidate.hex(), digest_hex)
        except Exception:  # pragma: no cover
            return False
    if _pwd_context is not None:
        try:
            return bool(_pwd_context.verify(plain, hashed))
        except Exception:  # pragma: no cover
            return False
    return False


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
