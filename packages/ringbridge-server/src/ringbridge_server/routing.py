"""Which agent version answers a dialled number, and keeping LiveKit in step with trunks."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ringbridge_server.models import Agent, AgentVersion, PhoneNumber, SipTrunk
from ringbridge_server.telephony import SipControl, TrunkSpec

log = logging.getLogger("ringbridge.routing")

RejectReason = Literal["unknown_number", "number_not_bound", "no_published_version"]
_NOT_DIGITS = re.compile(r"[\s\-().]")


def normalize_number(raw: str) -> str:
    """`+91 484 200-0123` and `914842000123` both become `+914842000123`."""
    digits = _NOT_DIGITS.sub("", raw.strip())
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    return digits if digits.startswith("+") else "+" + digits


@dataclass(frozen=True)
class Route:
    number: PhoneNumber | None
    agent: Agent | None
    version: AgentVersion | None
    reject: RejectReason | None


async def resolve(session: AsyncSession, number: PhoneNumber | None) -> Route:
    """The pinned version if the number has one, otherwise the agent's latest version."""
    if number is None:
        return Route(None, None, None, "unknown_number")
    if number.agent_id is None:
        return Route(number, None, None, "number_not_bound")
    agent = await session.get(Agent, number.agent_id)
    if number.agent_version_id is not None:
        version = await session.get(AgentVersion, number.agent_version_id)
    else:
        version = await session.scalar(
            select(AgentVersion)
            .where(AgentVersion.agent_id == number.agent_id)
            .order_by(AgentVersion.version.desc())
            .limit(1)
        )
    if version is None:
        return Route(number, agent, None, "no_published_version")
    return Route(number, agent, version, None)


async def find_number(session: AsyncSession, dialled: str) -> PhoneNumber | None:
    return await session.scalar(
        select(PhoneNumber).where(PhoneNumber.e164 == normalize_number(dialled))
    )


# ------------------------------------------------------------------ LiveKit sync


async def trunk_numbers(session: AsyncSession, trunk_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(PhoneNumber.e164)
        .where(PhoneNumber.sip_trunk_id == trunk_id)
        .order_by(PhoneNumber.e164)
    )
    return list(rows)


async def sync_trunk(
    session: AsyncSession, sip: SipControl, trunk: SipTrunk, *, auth_password: str | None = None
) -> None:
    """Push the trunk and its numbers to LiveKit, recording the outcome on the row.

    A LiveKit failure never undoes the database change: the trunk is marked `error` with the
    reason, and `POST /v1/sip-trunks/{id}/sync` retries. Each LiveKit id is saved as soon as it
    exists, so a retry updates what was created instead of creating a duplicate.
    """
    if trunk.direction == "outbound":
        trunk.sync_status = "not_applicable"
        return
    spec = TrunkSpec(
        id=trunk.id,
        name=trunk.name,
        numbers=await trunk_numbers(session, trunk.id),
        allowed_addresses=list(trunk.allowed_addresses or []),
        auth_username=trunk.auth_username,
        auth_password=auth_password,
        livekit_trunk_id=trunk.livekit_trunk_id,
        livekit_dispatch_rule_id=trunk.livekit_dispatch_rule_id,
    )
    try:
        trunk.livekit_trunk_id = await sip.ensure_trunk(spec)
        trunk.livekit_dispatch_rule_id = await sip.ensure_dispatch(spec, trunk.livekit_trunk_id)
    except Exception as e:  # any LiveKit or network failure is recorded, not raised
        log.warning("LiveKit sync failed", extra={"trunk_id": str(trunk.id), "error": repr(e)})
        trunk.sync_status = "error"
        trunk.sync_error = f"{type(e).__name__}: {e}"[:500]
        return
    trunk.sync_status = "synced"
    trunk.sync_error = None
    trunk.synced_at = datetime.now(UTC)


async def sync_trunks(
    session: AsyncSession, sip: SipControl, trunk_ids: set[uuid.UUID | None]
) -> None:
    for trunk_id in sorted(t for t in trunk_ids if t is not None):
        trunk = await session.get(SipTrunk, trunk_id, with_for_update=True)
        if trunk is not None:
            await sync_trunk(session, sip, trunk)


async def count_numbers(session: AsyncSession, trunk_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(PhoneNumber)
            .where(PhoneNumber.sip_trunk_id == trunk_id)
        )
        or 0
    )
