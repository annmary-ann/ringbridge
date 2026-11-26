"""Short-lived tokens for agent workers.

A worker holds the long-lived `RINGBRIDGE_WORKER_TOKEN` and exchanges it at
`POST /internal/auth/token` for a JWT that expires in minutes. Every other internal route accepts
only that JWT, so a leaked request log or proxy capture is useful for minutes, not forever.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

import jwt

AUDIENCE = "ringbridge-internal"
SUBJECT = "agent-worker"
_ALGORITHM = "HS256"


def _signing_key(secret: str) -> bytes:
    """A key derived from the shared secret, so the secret itself never signs anything."""
    return hmac.new(secret.encode(), b"ringbridge worker jwt v1", hashlib.sha256).digest()


@dataclass(frozen=True)
class WorkerToken:
    token: str
    expires_at: int


def issue(secret: str, ttl_s: int, *, now: float | None = None) -> WorkerToken:
    issued = int(now if now is not None else time.time())
    claims = {
        "sub": SUBJECT,
        "aud": AUDIENCE,
        "iat": issued,
        "exp": issued + ttl_s,
        "jti": uuid.uuid4().hex,
    }
    return WorkerToken(jwt.encode(claims, _signing_key(secret), _ALGORITHM), issued + ttl_s)


def verify(secret: str, token: str) -> bool:
    try:
        claims = jwt.decode(
            token,
            _signing_key(secret),
            algorithms=[_ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except jwt.PyJWTError:
        return False
    return bool(claims.get("sub") == SUBJECT)
