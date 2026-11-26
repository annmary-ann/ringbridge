"""Calls: creation and event ingestion by agent workers, transcripts and history for API users."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from ringbridge_core.events import (
    CallEnded,
    CallEvent,
    CallStarted,
    EventBatch,
    TranscriptLine,
    Turn,
    build_transcript,
    payload_of,
    render_transcript,
)
from ringbridge_server import routing
from ringbridge_server.api.deps import ProjectDep, SessionDep
from ringbridge_server.api.internal_auth import require_worker
from ringbridge_server.models import (
    DEFAULT_PROJECT_ID,
    Agent,
    AgentVersion,
    Call,
    PhoneNumber,
)
from ringbridge_server.models import CallEvent as CallEventRow

_EVENT = TypeAdapter[CallEvent](CallEvent)

CallDirection = Literal["inbound", "outbound", "web"]  # models.CALL_DIRECTIONS


# ------------------------------------------------------------------ schemas


class CallCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: CallDirection
    livekit_room: str = Field(min_length=1, max_length=128, description="Idempotency key")
    agent_version_id: uuid.UUID | None = None
    phone_number_id: uuid.UUID | None = None
    from_number: str | None = Field(default=None, max_length=32)
    to_number: str | None = Field(default=None, max_length=32)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    status: str
    agent_version_id: uuid.UUID | None
    phone_number_id: uuid.UUID | None
    from_number: str | None
    to_number: str | None
    livekit_room: str | None
    trace_id: str | None
    end_reason: str | None
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class IngestResult(BaseModel):
    accepted: int = Field(description="Events stored by this request")
    duplicates: list[str] = Field(description="Event ids already stored earlier; ignored")
    status: str = Field(description="The call's status after this batch")


class StoredEvent(BaseModel):
    event_id: str
    seq: int
    type: str
    occurred_at: datetime
    received_at: datetime
    payload: dict[str, Any]


class Transcript(BaseModel):
    call_id: uuid.UUID
    status: str
    complete: bool = Field(description="True once the call has ended")
    lines: list[TranscriptLine]


class InboundCall(BaseModel):
    """What the worker knows when LiveKit dispatches it into a new SIP call's room."""

    model_config = ConfigDict(extra="forbid")

    livekit_room: str = Field(min_length=1, max_length=128, description="Idempotency key")
    to_number: str = Field(min_length=3, max_length=32, description="The dialled number")
    from_number: str | None = Field(default=None, max_length=32, description="Caller ID")
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class RoutedAgent(BaseModel):
    id: uuid.UUID
    name: str
    version_id: uuid.UUID
    version: int
    spec: dict[str, Any] = Field(description="The published spec the worker must run")


class Caller(BaseModel):
    number: str | None
    contact: dict[str, Any] | None = Field(
        default=None, description="Matching contact, once contacts exist (#35); null for now"
    )


class InboundRoute(BaseModel):
    call: CallOut
    action: Literal["answer", "reject"]
    reason: str | None = Field(
        description="Why the call is rejected: unknown_number, number_not_bound or "
        "no_published_version. The worker hangs up without speaking."
    )
    agent: RoutedAgent | None
    caller: Caller


# ------------------------------------------------------------------ routers


internal = APIRouter(
    prefix="/internal/calls",
    tags=["internal (agent workers)"],
    dependencies=[Depends(require_worker)],
    responses={401: {"description": "Bad worker token"}, 503: {"description": "Disabled"}},
)
public = APIRouter(prefix="/v1/calls", tags=["calls"])


async def _call_or_404(
    session: SessionDep, project_id: uuid.UUID, call_id: uuid.UUID, *, lock: bool = False
) -> Call:
    stmt = select(Call).where(Call.id == call_id, Call.project_id == project_id)
    if lock:
        stmt = stmt.with_for_update()
    call = (await session.execute(stmt)).scalar_one_or_none()
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return call


async def _check_refs(session: SessionDep, project_id: uuid.UUID, body: CallCreate) -> None:
    if body.agent_version_id is not None:
        found = await session.scalar(
            select(AgentVersion.id)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(AgentVersion.id == body.agent_version_id, Agent.project_id == project_id)
        )
        if found is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown agent_version_id")
    if body.phone_number_id is not None:
        found = await session.scalar(
            select(PhoneNumber.id).where(
                PhoneNumber.id == body.phone_number_id, PhoneNumber.project_id == project_id
            )
        )
        if found is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown phone_number_id")


# ------------------------------------------------------------------ internal routes


@internal.post("", status_code=status.HTTP_201_CREATED, responses={200: {"model": CallOut}})
async def create_call(
    body: CallCreate, response: Response, session: SessionDep, project_id: ProjectDep
) -> CallOut:
    """Register a call for a LiveKit room. Repeating it for the same room returns that call."""
    await _check_refs(session, project_id, body)
    new_id = await session.scalar(
        insert(Call)
        .values(project_id=project_id, **body.model_dump())
        .on_conflict_do_nothing(
            index_elements=["livekit_room"], index_where=text("livekit_room IS NOT NULL")
        )
        .returning(Call.id)
    )
    if new_id is None:
        response.status_code = status.HTTP_200_OK
    call = await session.scalar(select(Call).where(Call.livekit_room == body.livekit_room))
    if call is None or call.project_id != project_id:  # pragma: no cover - other tenant's room
        raise HTTPException(status.HTTP_409_CONFLICT, "room belongs to another call")
    return CallOut.model_validate(call)


@internal.post("/inbound", responses={200: {"model": InboundRoute}})
async def route_inbound(body: InboundCall, response: Response, session: SessionDep) -> InboundRoute:
    """Decide which agent version answers an inbound call, and register the call.

    The worker calls this once per room. The decision is stored on the call, so asking again
    for the same room returns the same answer even if the number was rebound in between.
    Rebinding a number affects the next call, with no restart anywhere.
    """
    existing = await session.scalar(select(Call).where(Call.livekit_room == body.livekit_room))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return await _decision(session, existing)

    number = await routing.find_number(session, body.to_number)
    route = await routing.resolve(session, number)
    values: dict[str, Any] = {
        "project_id": number.project_id if number else DEFAULT_PROJECT_ID,
        "direction": "inbound",
        "status": "ringing",
        "livekit_room": body.livekit_room,
        "phone_number_id": number.id if number else None,
        "agent_version_id": route.version.id if route.version else None,
        "from_number": body.from_number,
        "to_number": routing.normalize_number(body.to_number),
        "trace_id": body.trace_id,
    }
    if route.reject is not None:
        # Unrouted calls are recorded as failed, so they show up in call history.
        now = datetime.now(UTC)
        values |= {"status": "failed", "end_reason": route.reject, "started_at": now}
        values["ended_at"] = now
    created = await session.scalar(
        insert(Call)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=["livekit_room"], index_where=text("livekit_room IS NOT NULL")
        )
        .returning(Call.id)
    )
    # None means a concurrent request for the same room got there first: return its decision.
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    stored = await session.scalar(select(Call).where(Call.livekit_room == body.livekit_room))
    if stored is None:  # pragma: no cover - the row was just inserted or already existed
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "call vanished")
    return await _decision(session, stored)


async def _decision(session: SessionDep, call: Call) -> InboundRoute:
    caller = Caller(number=call.from_number)
    version = (
        await session.get(AgentVersion, call.agent_version_id) if call.agent_version_id else None
    )
    if version is None:
        return InboundRoute(
            call=CallOut.model_validate(call),
            action="reject",
            reason=call.end_reason or "no_published_version",
            agent=None,
            caller=caller,
        )
    agent = await session.get(Agent, version.agent_id)
    if agent is None:  # pragma: no cover - agent_versions.agent_id is a RESTRICT foreign key
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "agent missing")
    return InboundRoute(
        call=CallOut.model_validate(call),
        action="answer",
        reason=None,
        agent=RoutedAgent(
            id=agent.id,
            name=agent.name,
            version_id=version.id,
            version=version.version,
            spec=version.spec,
        ),
        caller=caller,
    )


@internal.post("/{call_id}/events", responses={404: {"description": "Call not found"}})
async def ingest_events(
    call_id: uuid.UUID, batch: EventBatch, session: SessionDep, project_id: ProjectDep
) -> IngestResult:
    """Store a batch of events. Safe to retry: events already stored are skipped by id.

    `call.started` moves the call to `in_progress`; `call.ended` sets its final status. Both
    apply only the first time, so retries and late duplicates never move a call backwards.
    """
    call = await _call_or_404(session, project_id, call_id, lock=True)
    rows = [
        {
            "project_id": call.project_id,
            "call_id": call.id,
            "event_id": e.event_id,
            "seq": e.seq,
            "type": e.type,
            "occurred_at": e.occurred_at,
            "payload": payload_of(e),
        }
        for e in batch.events
    ]
    inserted = set(
        await session.scalars(
            insert(CallEventRow)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["call_id", "event_id"])
            .returning(CallEventRow.event_id)
        )
    )

    for e in sorted(batch.events, key=lambda e: e.seq):
        if e.event_id not in inserted:
            continue
        if isinstance(e, CallStarted) and call.answered_at is None and call.ended_at is None:
            call.status = "in_progress"
            call.answered_at = e.occurred_at
            call.started_at = call.started_at or e.occurred_at
            call.from_number = call.from_number or e.from_number
            call.to_number = call.to_number or e.to_number
        elif isinstance(e, CallEnded) and call.ended_at is None:
            call.status = e.status
            call.ended_at = e.occurred_at
            call.end_reason = e.reason
            call.started_at = call.started_at or e.occurred_at

    duplicates = [e.event_id for e in batch.events if e.event_id not in inserted]
    return IngestResult(accepted=len(inserted), duplicates=duplicates, status=call.status)


# ------------------------------------------------------------------ public routes


@public.get("")
async def list_calls(
    session: SessionDep,
    project_id: ProjectDep,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CallOut]:
    """Most recent first."""
    stmt = select(Call).where(Call.project_id == project_id)
    if status_ is not None:
        stmt = stmt.where(Call.status == status_)
    rows = await session.scalars(
        stmt.order_by(Call.created_at.desc(), Call.id).limit(limit).offset(offset)
    )
    return [CallOut.model_validate(c) for c in rows]


@public.get("/{call_id}", responses={404: {"description": "Not found"}})
async def get_call(call_id: uuid.UUID, session: SessionDep, project_id: ProjectDep) -> CallOut:
    return CallOut.model_validate(await _call_or_404(session, project_id, call_id))


async def _events(
    session: SessionDep, call_id: uuid.UUID, *, types: tuple[str, ...] | None = None
) -> list[CallEventRow]:
    stmt = select(CallEventRow).where(CallEventRow.call_id == call_id)
    if types:
        stmt = stmt.where(CallEventRow.type.in_(types))
    return list(await session.scalars(stmt.order_by(CallEventRow.seq, CallEventRow.id)))


@public.get("/{call_id}/events", responses={404: {"description": "Not found"}})
async def list_events(
    call_id: uuid.UUID,
    session: SessionDep,
    project_id: ProjectDep,
    type_: Annotated[list[str] | None, Query(alias="type")] = None,
) -> list[StoredEvent]:
    """Every event in call order (`seq`). Filter with `?type=turn&type=tool_call`."""
    await _call_or_404(session, project_id, call_id)
    rows = await _events(session, call_id, types=tuple(type_) if type_ else None)
    return [
        StoredEvent(
            event_id=r.event_id,
            seq=r.seq,
            type=r.type,
            occurred_at=r.occurred_at,
            received_at=r.created_at,
            payload=r.payload,
        )
        for r in rows
    ]


@public.get(
    "/{call_id}/transcript",
    response_model=Transcript,
    responses={
        200: {"content": {"text/plain": {}}, "description": "JSON, or text with ?format=text"},
        404: {"description": "Not found"},
    },
)
async def get_transcript(
    call_id: uuid.UUID,
    session: SessionDep,
    project_id: ProjectDep,
    format_: Annotated[Literal["json", "text"], Query(alias="format")] = "json",
) -> Transcript | PlainTextResponse:
    call = await _call_or_404(session, project_id, call_id)
    turns = [
        _EVENT.validate_python(
            {
                **r.payload,
                "event_id": r.event_id,
                "seq": r.seq,
                "type": r.type,
                "occurred_at": r.occurred_at,
            }
        )
        for r in await _events(session, call_id, types=("turn",))
    ]
    lines = build_transcript([t for t in turns if isinstance(t, Turn)], call.started_at)
    if format_ == "text":
        return PlainTextResponse(render_transcript(lines))
    return Transcript(
        call_id=call.id, status=call.status, complete=call.ended_at is not None, lines=lines
    )
