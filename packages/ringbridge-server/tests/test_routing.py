"""Inbound routing: dialled number → agent version, as the worker sees it."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ringbridge_server import worker_auth
from ringbridge_server.routing import normalize_number

AUTH = {"authorization": f"Bearer {worker_auth.issue('test-worker-token', 3600).token}"}
NUMBER = "+914842000123"
OLD_DESCRIPTION = "  description: Front desk for a dental clinic in Kochi; English and Hindi."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+914842000123", NUMBER),
        ("914842000123", NUMBER),
        ("+91 484 200-0123", NUMBER),
        ("00914842000123", NUMBER),
        ("(484) 200.0123", "+4842000123"),
    ],
)
def test_normalize_number(raw: str, expected: str) -> None:
    assert normalize_number(raw) == expected


async def _setup(client: httpx.AsyncClient, spec_text: str, versions: int = 2) -> dict[str, str]:
    trunk = (
        await client.post(
            "/v1/sip-trunks",
            json={"name": "main", "direction": "inbound", "allowed_addresses": ["10.0.0.0/8"]},
        )
    ).json()
    agent = (await client.post("/v1/agents", json={"name": "smile-dental-receptionist"})).json()
    for n in range(versions):
        await client.post(
            f"/v1/agents/{agent['id']}/versions",
            content=spec_text.replace(OLD_DESCRIPTION, f"  description: v{n + 1}"),
            headers={"content-type": "application/yaml"},
        )
    number = (
        await client.post(
            "/v1/phone-numbers",
            json={"e164": NUMBER, "sip_trunk_id": trunk["id"], "agent_id": agent["id"]},
        )
    ).json()
    return {"agent": agent["id"], "number": number["id"]}


async def _inbound(client: httpx.AsyncClient, room: str, to: str = NUMBER, **extra: Any) -> Any:
    body = {"livekit_room": room, "to_number": to, "from_number": "+919800000001"} | extra
    r = await client.post("/internal/calls/inbound", json=body, headers=AUTH)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.mark.anyio
@pytest.mark.integration
async def test_call_is_answered_by_the_latest_version(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    ids = await _setup(client, spec_text)
    route = await _inbound(client, "call-1", to="914842000123")  # LiveKit may drop the +
    assert route["action"] == "answer"
    assert route["reason"] is None
    assert route["agent"]["id"] == ids["agent"]
    assert route["agent"]["version"] == 2
    assert route["agent"]["spec"]["metadata"]["description"] == "v2"
    assert route["caller"] == {"number": "+919800000001", "contact": None}

    call = route["call"]
    assert call["status"] == "ringing"
    assert call["direction"] == "inbound"
    assert call["phone_number_id"] == ids["number"]
    assert call["to_number"] == NUMBER

    # The worker then reports events against this call as usual.
    r = await client.post(
        f"/internal/calls/{call['id']}/events",
        json={
            "events": [
                {
                    "type": "call.started",
                    "event_id": "s",
                    "seq": 0,
                    "occurred_at": "2026-11-26T10:00:00Z",
                }
            ]
        },
        headers=AUTH,
    )
    assert r.json()["status"] == "in_progress"


@pytest.mark.anyio
@pytest.mark.integration
async def test_rebinding_applies_to_the_next_call_only(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    ids = await _setup(client, spec_text)
    first = await _inbound(client, "call-a")
    assert first["agent"]["version"] == 2

    await client.patch(f"/v1/phone-numbers/{ids['number']}", json={"pinned_version": 1})
    second = await _inbound(client, "call-b")
    assert second["agent"]["version"] == 1

    # Asking again for the first room keeps the decision made when that call arrived.
    r = await client.post(
        "/internal/calls/inbound",
        json={"livekit_room": "call-a", "to_number": NUMBER},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["agent"]["version"] == 2
    assert r.json()["call"]["id"] == first["call"]["id"]


@pytest.mark.anyio
@pytest.mark.integration
async def test_unknown_number_is_rejected_and_recorded(client: httpx.AsyncClient) -> None:
    route = await _inbound(client, "call-x", to="+15550100")
    assert route["action"] == "reject"
    assert route["reason"] == "unknown_number"
    assert route["agent"] is None
    call = (await client.get(f"/v1/calls/{route['call']['id']}")).json()
    assert call["status"] == "failed"
    assert call["end_reason"] == "unknown_number"
    assert call["ended_at"] is not None

    again = await _inbound(client, "call-x", to="+15550100")
    assert again["reason"] == "unknown_number"


@pytest.mark.anyio
@pytest.mark.integration
async def test_unbound_number_and_agent_without_versions(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    ids = await _setup(client, spec_text, versions=0)
    assert (await _inbound(client, "c1"))["reason"] == "no_published_version"
    await client.patch(f"/v1/phone-numbers/{ids['number']}", json={"agent_id": None})
    assert (await _inbound(client, "c2"))["reason"] == "number_not_bound"


@pytest.mark.anyio
@pytest.mark.integration
async def test_inbound_needs_a_worker_token(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/internal/calls/inbound", json={"livekit_room": "r", "to_number": NUMBER}
    )
    assert r.status_code == 401
