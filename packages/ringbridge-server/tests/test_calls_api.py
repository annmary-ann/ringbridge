"""Call creation, event ingestion and transcripts, against a real Postgres."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

AUTH = {"authorization": "Bearer test-worker-token"}  # conftest.WORKER_TOKEN
T0 = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def ev(event_id: str, seq: int, seconds: float, type_: str, **fields: Any) -> dict[str, Any]:
    return {"event_id": event_id, "seq": seq, "occurred_at": at(seconds), "type": type_} | fields


def say(seq: int, speaker: str, text: str, seconds: float, **fields: Any) -> dict[str, Any]:
    return ev(f"turn-{seq}", seq, seconds, "turn", speaker=speaker, text=text, **fields)


async def _call(client: httpx.AsyncClient, room: str = "room-1", **fields: Any) -> str:
    body = {"direction": "inbound", "livekit_room": room} | fields
    r = await client.post("/internal/calls", json=body, headers=AUTH)
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"])


async def _send(client: httpx.AsyncClient, call_id: str, *events: dict[str, Any]) -> Any:
    r = await client.post(
        f"/internal/calls/{call_id}/events", json={"events": list(events)}, headers=AUTH
    )
    assert r.status_code == 200, r.text
    return r.json()


CONVERSATION = [
    ev("start", 0, 0.0, "call.started", from_number="+919800000001", to_number="+914842000123"),
    say(1, "agent", "Hello, Smile Dental. This call is answered by an AI assistant.", 1.0),
    say(2, "caller", "I'd like a cleaning tomorrow morning.", 5.0),
    ev("tc-1", 3, 6.0, "tool_call", tool_call_id="x1", name="check_availability",
       arguments={"date": "2026-11-27"}),
    ev("tr-1", 4, 6.4, "tool_result", tool_call_id="x1", name="check_availability", ok=True,
       result=["10:00", "11:30"], duration_ms=400),
    say(5, "agent", "I have 10:00 or 11:30.", 7.0, node="book"),
    ev("m-5", 6, 7.0, "metric", name="voice_to_voice_ms", value=710.0, turn_seq=5),
    say(7, "caller", "Ten works.", 10.0),
    ev("end", 8, 75.0, "call.ended", reason="caller_hangup"),
]  # fmt: skip


async def test_a_full_call_produces_a_transcript(client: httpx.AsyncClient) -> None:
    call_id = await _call(client, from_number="+919800000001")
    assert (await client.get(f"/v1/calls/{call_id}")).json()["status"] == "queued"

    # The worker sends events in two batches, the second out of order.
    first = await _send(client, call_id, *CONVERSATION[:4])
    assert first == {"accepted": 4, "duplicates": [], "status": "in_progress"}
    second = await _send(client, call_id, *reversed(CONVERSATION[4:]))
    assert second["accepted"] == 5
    assert second["status"] == "completed"

    call = (await client.get(f"/v1/calls/{call_id}")).json()
    assert call["end_reason"] == "caller_hangup"
    assert call["answered_at"] is not None
    assert call["ended_at"] is not None
    assert call["to_number"] == "+914842000123"  # filled in from call.started

    transcript = (await client.get(f"/v1/calls/{call_id}/transcript")).json()
    assert transcript["complete"] is True
    assert [(line["speaker"], line["offset_ms"]) for line in transcript["lines"]] == [
        ("agent", 1000), ("caller", 5000), ("agent", 7000), ("caller", 10000),
    ]  # fmt: skip

    r = await client.get(f"/v1/calls/{call_id}/transcript", params={"format": "text"})
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.splitlines() == [
        "[00:01] Agent: Hello, Smile Dental. This call is answered by an AI assistant.",
        "[00:05] Caller: I'd like a cleaning tomorrow morning.",
        "[00:07] Agent: I have 10:00 or 11:30.",
        "[00:10] Caller: Ten works.",
    ]

    events = (await client.get(f"/v1/calls/{call_id}/events")).json()
    assert [e["seq"] for e in events] == list(range(9))
    tools = (
        await client.get(
            f"/v1/calls/{call_id}/events", params=[("type", "tool_call"), ("type", "tool_result")]
        )
    ).json()
    assert [e["payload"]["tool_call_id"] for e in tools] == ["x1", "x1"]
    assert tools[1]["payload"]["result"] == ["10:00", "11:30"]


async def test_retried_batches_do_not_duplicate_rows(client: httpx.AsyncClient) -> None:
    call_id = await _call(client)
    await _send(client, call_id, *CONVERSATION)
    again = await _send(client, call_id, *CONVERSATION[:3], say(9, "caller", "Bye", 76.0))
    assert again["accepted"] == 1
    assert again["duplicates"] == ["start", "turn-1", "turn-2"]
    assert again["status"] == "completed"  # a replayed call.started never reopens the call
    assert len((await client.get(f"/v1/calls/{call_id}/events")).json()) == 10


async def test_concurrent_retries_store_each_event_once(client: httpx.AsyncClient) -> None:
    call_id = await _call(client)
    results = await asyncio.gather(*(_send(client, call_id, *CONVERSATION) for _ in range(5)))
    assert sum(r["accepted"] for r in results) == len(CONVERSATION)
    assert len((await client.get(f"/v1/calls/{call_id}/events")).json()) == len(CONVERSATION)


async def test_failed_call_status_comes_from_call_ended(client: httpx.AsyncClient) -> None:
    call_id = await _call(client, direction="outbound")
    result = await _send(
        client, call_id, ev("end", 0, 30.0, "call.ended", status="no_answer", reason="timeout")
    )
    assert result["status"] == "no_answer"
    call = (await client.get(f"/v1/calls/{call_id}")).json()
    assert call["answered_at"] is None
    assert call["started_at"] is not None
    transcript = (await client.get(f"/v1/calls/{call_id}/transcript")).json()
    assert transcript == {"call_id": call_id, "status": "no_answer", "complete": True, "lines": []}


async def test_creating_a_call_is_idempotent_per_room(client: httpx.AsyncClient) -> None:
    first = await client.post(
        "/internal/calls", json={"direction": "web", "livekit_room": "r-9"}, headers=AUTH
    )
    again = await client.post(
        "/internal/calls", json={"direction": "web", "livekit_room": "r-9"}, headers=AUTH
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]


async def test_call_references_must_exist(client: httpx.AsyncClient) -> None:
    for field in ("agent_version_id", "phone_number_id"):
        r = await client.post(
            "/internal/calls",
            json={"direction": "inbound", "livekit_room": "r", field: str(uuid.uuid4())},
            headers=AUTH,
        )
        assert r.status_code == 422
        assert field in r.json()["detail"]


async def test_call_can_reference_a_published_version(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    agent = (await client.post("/v1/agents", json={"name": "smile-dental-receptionist"})).json()
    version = (
        await client.post(
            f"/v1/agents/{agent['id']}/versions",
            content=spec_text,
            headers={"content-type": "application/yaml"},
        )
    ).json()
    call_id = await _call(client, agent_version_id=version["id"])
    assert (await client.get(f"/v1/calls/{call_id}")).json()["agent_version_id"] == version["id"]


async def test_list_calls_newest_first_with_status_filter(client: httpx.AsyncClient) -> None:
    a = await _call(client, "room-a")
    b = await _call(client, "room-b")
    await _send(client, b, ev("end", 0, 1.0, "call.ended", reason="x"))
    assert [c["id"] for c in (await client.get("/v1/calls")).json()] == [b, a]
    queued = (await client.get("/v1/calls", params={"status": "queued"})).json()
    assert [c["id"] for c in queued] == [a]


async def test_bad_batches_are_rejected(client: httpx.AsyncClient) -> None:
    call_id = await _call(client)
    url = f"/internal/calls/{call_id}/events"
    dup = say(1, "agent", "hi", 1.0)
    assert (await client.post(url, json={"events": [dup, dup]}, headers=AUTH)).status_code == 422
    assert (await client.post(url, json={"events": []}, headers=AUTH)).status_code == 422
    missing = f"/internal/calls/{uuid.uuid4()}/events"
    assert (await client.post(missing, json={"events": [dup]}, headers=AUTH)).status_code == 404


async def test_internal_routes_need_the_worker_token(client: httpx.AsyncClient) -> None:
    body = {"direction": "web", "livekit_room": "r"}
    assert (await client.post("/internal/calls", json=body)).status_code == 401
    wrong = {"authorization": "Bearer nope"}
    r = await client.post("/internal/calls", json=body, headers=wrong)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_unknown_call_is_404(client: httpx.AsyncClient) -> None:
    missing = uuid.uuid4()
    for path in ("", "/events", "/transcript"):
        assert (await client.get(f"/v1/calls/{missing}{path}")).status_code == 404
