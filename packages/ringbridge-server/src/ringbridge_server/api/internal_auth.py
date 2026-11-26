"""Authentication for agent workers on /internal routes (see worker_auth.py)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from ringbridge_server import worker_auth
from ringbridge_server.api.deps import SettingsDep

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def _shared_secret(settings: SettingsDep) -> str:
    if settings.worker_token is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the internal API is disabled: set RINGBRIDGE_WORKER_TOKEN",
        )
    return settings.worker_token.get_secret_value()


def _bearer(authorization: str | None) -> str:
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers=_UNAUTHORIZED
        )
    return value


def require_worker(
    settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Accept only a short-lived worker JWT from POST /internal/auth/token."""
    secret = _shared_secret(settings)
    if not worker_auth.verify(secret, _bearer(authorization)):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired worker token: get a new one from /internal/auth/token",
            headers=_UNAUTHORIZED,
        )


class TokenOut(BaseModel):
    token: str
    token_type: str = "Bearer"  # noqa: S105 - the scheme name, not a secret
    expires_at: int  # Unix seconds


router = APIRouter(prefix="/internal/auth", tags=["internal (agent workers)"])


@router.post(
    "/token",
    responses={401: {"description": "Wrong secret"}, 503: {"description": "Disabled"}},
)
def issue_token(
    settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
) -> TokenOut:
    """Exchange the shared RINGBRIDGE_WORKER_TOKEN for a token that expires in minutes."""
    secret = _shared_secret(settings)
    if not hmac.compare_digest(_bearer(authorization).encode(), secret.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "wrong worker secret", headers=_UNAUTHORIZED
        )
    issued = worker_auth.issue(secret, settings.worker_token_ttl_s)
    return TokenOut(token=issued.token, expires_at=issued.expires_at)
