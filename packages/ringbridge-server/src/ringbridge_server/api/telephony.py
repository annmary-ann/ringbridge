"""SIP trunks and phone numbers, and which agent each number answers with."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ringbridge_server import routing
from ringbridge_server.api.deps import ProjectDep, SessionDep, SipDep
from ringbridge_server.models import E164_PATTERN, Agent, AgentVersion, PhoneNumber, SipTrunk

trunks = APIRouter(prefix="/v1/sip-trunks", tags=["telephony"])
numbers = APIRouter(prefix="/v1/phone-numbers", tags=["telephony"])

OPEN_TRUNK_WARNING = (
    "open trunk: anyone who can reach the SIP port can call it; "
    "set allowed_addresses or auth_username/auth_password"
)


# ------------------------------------------------------------------ schemas


def _check_addresses(values: list[str]) -> list[str]:
    for v in values:
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError(f"{v!r} is not an IP address or CIDR range") from None
    return values


Addresses = Annotated[list[str], AfterValidator(_check_addresses)]
_PASSWORD = Field(default=None, description="Sent to LiveKit only; never stored or returned")


class TrunkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    direction: Literal["inbound", "outbound", "both"]
    provider: str | None = Field(default=None, max_length=50, examples=["twilio", "telnyx"])
    sip_address: str | None = Field(
        default=None, max_length=255, description="Provider's SIP host, for outbound calls"
    )
    allowed_addresses: Addresses = Field(default_factory=list, max_length=50)
    auth_username: str | None = Field(default=None, max_length=100)
    auth_password: SecretStr | None = _PASSWORD

    @model_validator(mode="after")
    def _auth_pair(self) -> TrunkCreate:
        if self.auth_password is not None and not self.auth_username:
            raise ValueError("auth_password needs auth_username")
        return self


class TrunkUpdate(BaseModel):
    """Send only the fields to change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=50)
    sip_address: str | None = Field(default=None, max_length=255)
    allowed_addresses: Addresses | None = Field(default=None, max_length=50)
    auth_username: str | None = Field(default=None, max_length=100)
    auth_password: SecretStr | None = _PASSWORD


class TrunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    direction: str
    provider: str | None
    sip_address: str | None
    allowed_addresses: list[str]
    auth_username: str | None
    numbers: list[str] = Field(default_factory=list)
    livekit_trunk_id: str | None
    livekit_dispatch_rule_id: str | None
    sync_status: str = Field(description="pending, synced, error or not_applicable (outbound)")
    sync_error: str | None
    synced_at: datetime | None
    created_at: datetime
    warnings: list[str] = Field(default_factory=list)


class NumberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    e164: str = Field(examples=["+914842000123"])
    sip_trunk_id: uuid.UUID
    label: str | None = Field(default=None, max_length=100)
    agent_id: uuid.UUID | None = None
    pinned_version: int | None = Field(
        default=None, ge=1, description="Answer with this version; omit to follow the latest"
    )

    @field_validator("e164")
    @classmethod
    def _e164(cls, v: str) -> str:
        return _valid_e164(v)


class NumberUpdate(BaseModel):
    """Send only the fields to change. `agent_id: null` unbinds; `pinned_version: null` unpins."""

    model_config = ConfigDict(extra="forbid")

    sip_trunk_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=100)
    agent_id: uuid.UUID | None = None
    pinned_version: int | None = Field(default=None, ge=1)


class RouteOut(BaseModel):
    agent_id: uuid.UUID | None
    agent_name: str | None
    agent_version_id: uuid.UUID | None
    version: int | None
    pinned: bool
    reject: str | None = Field(description="Why calls are rejected right now, if they are")


class NumberOut(BaseModel):
    id: uuid.UUID
    e164: str
    label: str | None
    sip_trunk_id: uuid.UUID | None
    created_at: datetime
    route: RouteOut


def _valid_e164(raw: str) -> str:
    number = routing.normalize_number(raw)
    if not re.fullmatch(E164_PATTERN, number):
        raise ValueError("must be an E.164 number like +914842000123")
    return number


# ------------------------------------------------------------------ helpers


async def _trunk_out(session: SessionDep, trunk: SipTrunk) -> TrunkOut:
    out = TrunkOut.model_validate(trunk)
    out.numbers = await routing.trunk_numbers(session, trunk.id)
    if trunk.direction != "outbound" and not trunk.allowed_addresses and not trunk.auth_username:
        out.warnings.append(OPEN_TRUNK_WARNING)
    return out


async def _trunk_or_404(
    session: SessionDep, project_id: uuid.UUID, trunk_id: uuid.UUID
) -> SipTrunk:
    trunk = await session.scalar(
        select(SipTrunk)
        .where(SipTrunk.id == trunk_id, SipTrunk.project_id == project_id)
        .with_for_update()
    )
    if trunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SIP trunk not found")
    return trunk


async def _number_or_404(
    session: SessionDep, project_id: uuid.UUID, number_id: uuid.UUID
) -> PhoneNumber:
    number = await session.scalar(
        select(PhoneNumber).where(PhoneNumber.id == number_id, PhoneNumber.project_id == project_id)
    )
    if number is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "phone number not found")
    return number


async def _number_out(session: SessionDep, number: PhoneNumber) -> NumberOut:
    route = await routing.resolve(session, number)
    return NumberOut(
        id=number.id,
        e164=number.e164,
        label=number.label,
        sip_trunk_id=number.sip_trunk_id,
        created_at=number.created_at,
        route=RouteOut(
            agent_id=route.agent.id if route.agent else None,
            agent_name=route.agent.name if route.agent else None,
            agent_version_id=route.version.id if route.version else None,
            version=route.version.version if route.version else None,
            pinned=number.agent_version_id is not None,
            reject=route.reject,
        ),
    )


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


async def _binding(
    session: SessionDep,
    project_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    pinned_version: int | None,
) -> uuid.UUID | None:
    """Check the agent and pinned version; return the pinned version's id."""
    if agent_id is None:
        if pinned_version is not None:
            raise _unprocessable("pinned_version needs agent_id")
        return None
    agent = await session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.project_id == project_id)
    )
    if agent is None:
        raise _unprocessable("unknown agent_id")
    if pinned_version is None:
        return None
    version_id = await session.scalar(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == agent_id, AgentVersion.version == pinned_version
        )
    )
    if version_id is None:
        raise _unprocessable(f"agent {agent.name!r} has no version {pinned_version}")
    return version_id


# ------------------------------------------------------------------ trunks


@trunks.post(
    "", status_code=status.HTTP_201_CREATED, responses={409: {"description": "Name taken"}}
)
async def create_trunk(
    body: TrunkCreate, session: SessionDep, project_id: ProjectDep, sip: SipDep
) -> TrunkOut:
    """Register a SIP trunk. Inbound trunks are created in LiveKit straight away."""
    trunk = SipTrunk(
        project_id=project_id,
        **body.model_dump(exclude={"auth_password"}),
    )
    session.add(trunk)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a trunk named {body.name!r} already exists"
        ) from None
    password = body.auth_password.get_secret_value() if body.auth_password else None
    await routing.sync_trunk(session, sip, trunk, auth_password=password)
    await session.flush()
    await session.refresh(trunk)
    return await _trunk_out(session, trunk)


@trunks.get("")
async def list_trunks(session: SessionDep, project_id: ProjectDep) -> list[TrunkOut]:
    rows = await session.scalars(
        select(SipTrunk).where(SipTrunk.project_id == project_id).order_by(SipTrunk.name)
    )
    return [await _trunk_out(session, t) for t in rows]


@trunks.get("/{trunk_id}", responses={404: {"description": "Not found"}})
async def get_trunk(trunk_id: uuid.UUID, session: SessionDep, project_id: ProjectDep) -> TrunkOut:
    return await _trunk_out(session, await _trunk_or_404(session, project_id, trunk_id))


@trunks.patch("/{trunk_id}", responses={404: {"description": "Not found"}})
async def update_trunk(
    trunk_id: uuid.UUID,
    body: TrunkUpdate,
    session: SessionDep,
    project_id: ProjectDep,
    sip: SipDep,
) -> TrunkOut:
    trunk = await _trunk_or_404(session, project_id, trunk_id)
    for name in body.model_fields_set - {"auth_password"}:
        value = getattr(body, name)
        if name == "name" and value is None:
            raise _unprocessable("name cannot be null")
        setattr(trunk, name, [] if name == "allowed_addresses" and value is None else value)
    if body.auth_password is not None and not trunk.auth_username:
        raise _unprocessable("auth_password needs auth_username")
    password = body.auth_password.get_secret_value() if body.auth_password else None
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "a trunk with that name exists") from None
    await routing.sync_trunk(session, sip, trunk, auth_password=password)
    await session.flush()
    await session.refresh(trunk)
    return await _trunk_out(session, trunk)


@trunks.post("/{trunk_id}/sync", responses={404: {"description": "Not found"}})
async def resync_trunk(
    trunk_id: uuid.UUID, session: SessionDep, project_id: ProjectDep, sip: SipDep
) -> TrunkOut:
    """Push the trunk and its numbers to LiveKit again, e.g. after `sync_status: error`."""
    trunk = await _trunk_or_404(session, project_id, trunk_id)
    await routing.sync_trunk(session, sip, trunk)
    await session.flush()
    await session.refresh(trunk)
    return await _trunk_out(session, trunk)


@trunks.delete(
    "/{trunk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "Not found"},
        409: {"description": "Numbers still attached"},
        502: {"description": "LiveKit refused; nothing deleted"},
    },
)
async def delete_trunk(
    trunk_id: uuid.UUID, session: SessionDep, project_id: ProjectDep, sip: SipDep
) -> Response:
    trunk = await _trunk_or_404(session, project_id, trunk_id)
    if await routing.count_numbers(session, trunk.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "move or delete this trunk's phone numbers first"
        )
    try:
        await sip.remove_inbound(trunk.livekit_trunk_id, trunk.livekit_dispatch_rule_id)
    except Exception as e:  # keep the row so the LiveKit objects are not orphaned
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"LiveKit could not delete the trunk: {e}"
        ) from e
    await session.delete(trunk)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ numbers


@numbers.post(
    "", status_code=status.HTTP_201_CREATED, responses={409: {"description": "Number exists"}}
)
async def create_number(
    body: NumberCreate, session: SessionDep, project_id: ProjectDep, sip: SipDep
) -> NumberOut:
    await _trunk_or_404(session, project_id, body.sip_trunk_id)
    version_id = await _binding(session, project_id, body.agent_id, body.pinned_version)
    number = PhoneNumber(
        project_id=project_id,
        e164=body.e164,
        label=body.label,
        sip_trunk_id=body.sip_trunk_id,
        agent_id=body.agent_id,
        agent_version_id=version_id,
    )
    session.add(number)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{body.e164} is already registered"
        ) from None
    await routing.sync_trunks(session, sip, {body.sip_trunk_id})
    await session.refresh(number)
    return await _number_out(session, number)


@numbers.get("")
async def list_numbers(
    session: SessionDep,
    project_id: ProjectDep,
    sip_trunk_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[NumberOut]:
    stmt = select(PhoneNumber).where(PhoneNumber.project_id == project_id)
    if sip_trunk_id is not None:
        stmt = stmt.where(PhoneNumber.sip_trunk_id == sip_trunk_id)
    rows = await session.scalars(stmt.order_by(PhoneNumber.e164))
    return [await _number_out(session, n) for n in rows]


@numbers.get("/{number_id}", responses={404: {"description": "Not found"}})
async def get_number(
    number_id: uuid.UUID, session: SessionDep, project_id: ProjectDep
) -> NumberOut:
    return await _number_out(session, await _number_or_404(session, project_id, number_id))


@numbers.patch("/{number_id}", responses={404: {"description": "Not found"}})
async def update_number(
    number_id: uuid.UUID,
    body: NumberUpdate,
    session: SessionDep,
    project_id: ProjectDep,
    sip: SipDep,
) -> NumberOut:
    """Rebind, pin, unpin or move a number. Takes effect on the next call; nothing restarts."""
    number = await _number_or_404(session, project_id, number_id)
    fields = body.model_fields_set
    if "label" in fields:
        number.label = body.label
    if fields & {"agent_id", "pinned_version"}:
        agent_id = body.agent_id if "agent_id" in fields else number.agent_id
        # Changing the agent drops an old pin unless a new one is given.
        pinned = body.pinned_version if "pinned_version" in fields else None
        if "pinned_version" not in fields and agent_id == number.agent_id:
            pinned_id = number.agent_version_id
        else:
            pinned_id = await _binding(session, project_id, agent_id, pinned)
        number.agent_id = agent_id
        number.agent_version_id = pinned_id
    moved: set[uuid.UUID | None] = set()
    if "sip_trunk_id" in fields and body.sip_trunk_id != number.sip_trunk_id:
        if body.sip_trunk_id is None:
            raise _unprocessable("a number needs a SIP trunk")
        await _trunk_or_404(session, project_id, body.sip_trunk_id)
        moved = {number.sip_trunk_id, body.sip_trunk_id}
        number.sip_trunk_id = body.sip_trunk_id
    await session.flush()
    await routing.sync_trunks(session, sip, moved)
    return await _number_out(session, number)


@numbers.delete(
    "/{number_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Not found"}},
)
async def delete_number(
    number_id: uuid.UUID, session: SessionDep, project_id: ProjectDep, sip: SipDep
) -> Response:
    number = await _number_or_404(session, project_id, number_id)
    trunk_id = number.sip_trunk_id
    await session.delete(number)
    await session.flush()
    await routing.sync_trunks(session, sip, {trunk_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
