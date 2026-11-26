"""SIP trunks, phone numbers and their LiveKit sync (with a fake LiveKit)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from ringbridge_server.api.telephony import OPEN_TRUNK_WARNING
from ringbridge_server.testing import InMemorySip

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

NUMBER = "+914842000123"


async def _trunk(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    body = {"name": "main", "direction": "inbound", "allowed_addresses": ["203.0.113.0/24"]}
    r = await client.post("/v1/sip-trunks", json=body | fields)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _agent_with_versions(client: httpx.AsyncClient, spec_text: str, count: int) -> str:
    agent = (await client.post("/v1/agents", json={"name": "smile-dental-receptionist"})).json()
    old = "  description: Front desk for a dental clinic in Kochi; English and Hindi."
    for n in range(count):
        r = await client.post(
            f"/v1/agents/{agent['id']}/versions",
            content=spec_text.replace(old, f"  description: v{n + 1}"),
            headers={"content-type": "application/yaml"},
        )
        assert r.status_code == 201
    return str(agent["id"])


# ------------------------------------------------------------------ trunks


async def test_inbound_trunk_is_synced_to_livekit(
    client: httpx.AsyncClient, sip: InMemorySip
) -> None:
    trunk = await _trunk(client, auth_username="pbx", auth_password="s3cret-pass")
    assert trunk["sync_status"] == "synced"
    assert trunk["livekit_trunk_id"] in sip.trunks
    assert sip.rules[trunk["livekit_dispatch_rule_id"]] == trunk["livekit_trunk_id"]
    assert trunk["warnings"] == []
    assert "auth_password" not in trunk
    assert sip.passwords == ["s3cret-pass"]  # passed through to LiveKit once

    # A resync without a new password does not send (or clear) it.
    again = (await client.post(f"/v1/sip-trunks/{trunk['id']}/sync")).json()
    assert again["livekit_trunk_id"] == trunk["livekit_trunk_id"]
    assert sip.passwords == ["s3cret-pass", None]


async def test_open_trunk_warns_and_outbound_is_not_synced(client: httpx.AsyncClient) -> None:
    open_trunk = await _trunk(client, allowed_addresses=[])
    assert open_trunk["warnings"] == [OPEN_TRUNK_WARNING]
    outbound = await _trunk(client, name="out", direction="outbound", sip_address="sip.example")
    assert outbound["sync_status"] == "not_applicable"
    assert outbound["livekit_trunk_id"] is None
    assert outbound["warnings"] == []


async def test_livekit_failure_is_recorded_and_retried(
    client: httpx.AsyncClient, sip: InMemorySip
) -> None:
    sip.fail = True
    trunk = await _trunk(client)
    assert trunk["sync_status"] == "error"
    assert "LiveKit unreachable" in trunk["sync_error"]
    assert (await client.get(f"/v1/sip-trunks/{trunk['id']}")).json()["sync_status"] == "error"

    sip.fail = False
    fixed = (await client.post(f"/v1/sip-trunks/{trunk['id']}/sync")).json()
    assert fixed["sync_status"] == "synced"
    assert fixed["sync_error"] is None
    assert fixed["synced_at"] is not None


async def test_update_trunk(client: httpx.AsyncClient, sip: InMemorySip) -> None:
    trunk = await _trunk(client)
    r = await client.patch(
        f"/v1/sip-trunks/{trunk['id']}", json={"name": "renamed", "allowed_addresses": None}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["allowed_addresses"] == []
    assert sip.trunks[trunk["livekit_trunk_id"]].name == "renamed"
    bad = await client.patch(f"/v1/sip-trunks/{trunk['id']}", json={"auth_password": "x"})
    assert bad.status_code == 422
    assert (
        await client.patch(f"/v1/sip-trunks/{trunk['id']}", json={"name": None})
    ).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"name": "t", "direction": "sideways"},
        {"name": "t", "direction": "inbound", "allowed_addresses": ["not-an-ip"]},
        {"name": "t", "direction": "inbound", "auth_password": "p"},
        {"name": "", "direction": "inbound"},
    ],
)
async def test_bad_trunks_are_rejected(client: httpx.AsyncClient, body: dict[str, Any]) -> None:
    assert (await client.post("/v1/sip-trunks", json=body)).status_code == 422


async def test_trunk_names_are_unique(client: httpx.AsyncClient) -> None:
    await _trunk(client)
    assert (
        await client.post("/v1/sip-trunks", json={"name": "main", "direction": "inbound"})
    ).status_code == 409
    other = await _trunk(client, name="other")
    r = await client.patch(f"/v1/sip-trunks/{other['id']}", json={"name": "main"})
    assert r.status_code == 409


async def test_delete_trunk(client: httpx.AsyncClient, sip: InMemorySip) -> None:
    trunk = await _trunk(client)
    number = (
        await client.post("/v1/phone-numbers", json={"e164": NUMBER, "sip_trunk_id": trunk["id"]})
    ).json()
    assert (await client.delete(f"/v1/sip-trunks/{trunk['id']}")).status_code == 409
    await client.delete(f"/v1/phone-numbers/{number['id']}")

    sip.fail = True
    assert (await client.delete(f"/v1/sip-trunks/{trunk['id']}")).status_code == 502
    sip.fail = False
    assert (await client.delete(f"/v1/sip-trunks/{trunk['id']}")).status_code == 204
    assert sip.trunks == {}
    assert sip.rules == {}
    assert (await client.get(f"/v1/sip-trunks/{trunk['id']}")).status_code == 404
    assert (await client.get("/v1/sip-trunks")).json() == []


# ------------------------------------------------------------------ numbers


async def test_numbers_follow_their_trunk_into_livekit(
    client: httpx.AsyncClient, sip: InMemorySip
) -> None:
    a = await _trunk(client, name="a")
    b = await _trunk(client, name="b")
    r = await client.post(
        "/v1/phone-numbers", json={"e164": "+91 484 200-0123", "sip_trunk_id": a["id"]}
    )
    assert r.status_code == 201
    number = r.json()
    assert number["e164"] == NUMBER  # normalised
    assert sip.numbers(a["livekit_trunk_id"]) == [NUMBER]
    assert (await client.get(f"/v1/sip-trunks/{a['id']}")).json()["numbers"] == [NUMBER]

    moved = await client.patch(f"/v1/phone-numbers/{number['id']}", json={"sip_trunk_id": b["id"]})
    assert moved.json()["sip_trunk_id"] == b["id"]
    assert sip.numbers(a["livekit_trunk_id"]) == []
    assert sip.numbers(b["livekit_trunk_id"]) == [NUMBER]

    await client.delete(f"/v1/phone-numbers/{number['id']}")
    assert sip.numbers(b["livekit_trunk_id"]) == []
    assert (await client.get(f"/v1/phone-numbers/{number['id']}")).status_code == 404


async def test_binding_pinning_and_rebinding(client: httpx.AsyncClient, spec_text: str) -> None:
    trunk = await _trunk(client)
    agent_id = await _agent_with_versions(client, spec_text, 3)
    number = (
        await client.post("/v1/phone-numbers", json={"e164": NUMBER, "sip_trunk_id": trunk["id"]})
    ).json()
    assert number["route"]["reject"] == "number_not_bound"

    url = f"/v1/phone-numbers/{number['id']}"
    latest = (await client.patch(url, json={"agent_id": agent_id})).json()["route"]
    assert (latest["version"], latest["pinned"], latest["reject"]) == (3, False, None)

    pinned = (await client.patch(url, json={"pinned_version": 2})).json()["route"]
    assert (pinned["version"], pinned["pinned"]) == (2, True)
    relabelled = (await client.patch(url, json={"label": "front desk"})).json()
    assert relabelled["route"]["version"] == 2  # unrelated changes keep the pin

    unpinned = (await client.patch(url, json={"pinned_version": None})).json()["route"]
    assert (unpinned["version"], unpinned["pinned"]) == (3, False)

    unbound = (await client.patch(url, json={"agent_id": None})).json()["route"]
    assert unbound["reject"] == "number_not_bound"

    listed = (await client.get("/v1/phone-numbers", params={"sip_trunk_id": trunk["id"]})).json()
    assert [n["label"] for n in listed] == ["front desk"]


async def test_binding_is_validated(client: httpx.AsyncClient, spec_text: str) -> None:
    trunk = await _trunk(client)
    agent_id = await _agent_with_versions(client, spec_text, 1)
    base: dict[str, Any] = {"e164": NUMBER, "sip_trunk_id": trunk["id"]}
    cases: list[tuple[dict[str, Any], str]] = [
        ({"agent_id": str(uuid.uuid4())}, "unknown agent_id"),
        ({"agent_id": agent_id, "pinned_version": 9}, "has no version 9"),
        ({"pinned_version": 1}, "needs agent_id"),
    ]
    for extra, message in cases:
        r = await client.post("/v1/phone-numbers", json=base | extra)
        assert r.status_code == 422
        assert message in r.json()["detail"]
    r = await client.post("/v1/phone-numbers", json=base | {"sip_trunk_id": str(uuid.uuid4())})
    assert r.status_code == 404


async def test_bad_and_duplicate_numbers(client: httpx.AsyncClient) -> None:
    trunk = await _trunk(client)
    for bad in ("0484200012", "+0123456", "+91abc", "+1234567890123456"):
        r = await client.post("/v1/phone-numbers", json={"e164": bad, "sip_trunk_id": trunk["id"]})
        assert r.status_code == 422, bad
    ok = {"e164": NUMBER, "sip_trunk_id": trunk["id"]}
    assert (await client.post("/v1/phone-numbers", json=ok)).status_code == 201
    assert (await client.post("/v1/phone-numbers", json=ok)).status_code == 409
    number_id = (await client.get("/v1/phone-numbers")).json()[0]["id"]
    r = await client.patch(f"/v1/phone-numbers/{number_id}", json={"sip_trunk_id": None})
    assert r.status_code == 422
