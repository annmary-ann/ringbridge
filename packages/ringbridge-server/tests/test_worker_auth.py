"""Short-lived worker tokens."""

from __future__ import annotations

import time

import httpx
import jwt
import pytest

from ringbridge_server import worker_auth

SECRET = "test-worker-token"  # conftest.WORKER_TOKEN


def test_a_fresh_token_verifies() -> None:
    issued = worker_auth.issue(SECRET, 900)
    assert worker_auth.verify(SECRET, issued.token)
    assert issued.expires_at - time.time() == pytest.approx(900, abs=5)


def test_tokens_are_unique() -> None:
    assert worker_auth.issue(SECRET, 60).token != worker_auth.issue(SECRET, 60).token


@pytest.mark.parametrize(
    "token",
    [
        worker_auth.issue(SECRET, 60, now=time.time() - 3600).token,  # expired
        worker_auth.issue("another-secret", 60).token,  # wrong key
        jwt.encode({"sub": "agent-worker", "aud": "elsewhere", "exp": 2**40, "iat": 0}, "k"),
        "not-a-jwt",
        SECRET,  # the raw shared secret is not a token
    ],
)
def test_bad_tokens_fail(token: str) -> None:
    assert not worker_auth.verify(SECRET, token)


def test_token_signed_with_the_raw_secret_fails() -> None:
    """The signing key is derived from the secret, never the secret itself."""
    forged = jwt.encode(
        {"sub": "agent-worker", "aud": worker_auth.AUDIENCE, "exp": 2**40, "iat": 0}, SECRET
    )
    assert not worker_auth.verify(SECRET, forged)


@pytest.mark.anyio
@pytest.mark.integration
async def test_exchange_the_secret_for_a_token(client: httpx.AsyncClient) -> None:
    r = await client.post("/internal/auth/token", headers={"authorization": f"Bearer {SECRET}"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"

    use = {"authorization": f"Bearer {body['token']}"}
    room = {"direction": "web", "livekit_room": "r-auth"}
    assert (await client.post("/internal/calls", json=room, headers=use)).status_code == 201

    raw = {"authorization": f"Bearer {SECRET}"}
    r = await client.post("/internal/calls", json=room, headers=raw)
    assert r.status_code == 401
    assert "/internal/auth/token" in r.json()["detail"]


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic abc", "Bearer"])
async def test_token_endpoint_rejects_wrong_secrets(
    client: httpx.AsyncClient, header: str | None
) -> None:
    headers = {"authorization": header} if header else {}
    r = await client.post("/internal/auth/token", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
