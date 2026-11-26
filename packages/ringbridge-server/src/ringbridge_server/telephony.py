"""Keep LiveKit's SIP configuration in step with the trunks and numbers stored here.

For each inbound trunk, Ringbridge owns one LiveKit inbound trunk (which numbers and senders it
accepts) and one dispatch rule (each call gets its own room, and the Ringbridge agent worker is
dispatched into it). The worker then asks the control plane which agent version to run, so
rebinding a number takes effect on the next call without touching LiveKit.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from livekit import api

from ringbridge_server.settings import Settings

ROOM_PREFIX = "call-"
_NOT_FOUND = "not_found"


@dataclass(frozen=True)
class TrunkSpec:
    """What LiveKit should know about one inbound trunk."""

    id: uuid.UUID
    name: str
    numbers: list[str]
    allowed_addresses: list[str] = field(default_factory=list)
    auth_username: str | None = None
    auth_password: str | None = None  # only when it is being set or changed
    livekit_trunk_id: str | None = None
    livekit_dispatch_rule_id: str | None = None


class SipControl(Protocol):
    async def ensure_trunk(self, trunk: TrunkSpec) -> str:
        """Create or update the LiveKit inbound trunk; returns its id. Idempotent."""
        ...

    async def ensure_dispatch(self, trunk: TrunkSpec, livekit_trunk_id: str) -> str:
        """Create or update the dispatch rule for the trunk; returns its id. Idempotent."""
        ...

    async def remove_inbound(self, trunk_id: str | None, dispatch_rule_id: str | None) -> None:
        """Delete both from LiveKit. Missing ones are not an error."""
        ...

    async def aclose(self) -> None: ...


def _labels(trunk: TrunkSpec) -> tuple[str, str]:
    """Metadata and name that mark LiveKit objects as Ringbridge-managed."""
    return json.dumps({"ringbridge_trunk_id": str(trunk.id)}), f"ringbridge:{trunk.name}"


def _replace(current: list[str], wanted: list[str]) -> api.ListUpdate | None:
    """A list update that leaves exactly `wanted`.

    LiveKit treats an empty `set` as "no change", so emptying a list removes each item instead.
    """
    if wanted:
        return api.ListUpdate(set=wanted)
    if current:
        return api.ListUpdate(remove=current)
    return None


class LiveKitSip:
    """SipControl backed by the LiveKit server API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api: api.LiveKitAPI | None = None

    def _lk(self) -> api.LiveKitAPI:
        # Created lazily: the client needs a running event loop.
        if self._api is None:
            self._api = api.LiveKitAPI(
                self._settings.livekit_url,
                self._settings.livekit_api_key,
                self._settings.livekit_api_secret.get_secret_value(),
            )
        return self._api

    async def ensure_trunk(self, trunk: TrunkSpec) -> str:
        sip = self._lk().sip
        metadata, name = _labels(trunk)
        current = await self._current_trunk(trunk.livekit_trunk_id)
        if current is not None:
            info = await sip.update_inbound_trunk_fields(
                current.sip_trunk_id,
                numbers=_replace(list(current.numbers), trunk.numbers),
                allowed_addresses=_replace(
                    list(current.allowed_addresses), trunk.allowed_addresses
                ),
                auth_username=trunk.auth_username or "",
                auth_password=trunk.auth_password,
                name=name,
                metadata=metadata,
            )
        else:
            # New, or deleted in LiveKit behind our back: (re)create it.
            info = await sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name=name,
                        metadata=metadata,
                        numbers=trunk.numbers,
                        allowed_addresses=trunk.allowed_addresses,
                        auth_username=trunk.auth_username or "",
                        auth_password=trunk.auth_password or "",
                    )
                )
            )
        return str(info.sip_trunk_id)

    async def _current_trunk(self, trunk_id: str | None) -> api.SIPInboundTrunkInfo | None:
        if not trunk_id:
            return None
        found = await self._lk().sip.list_inbound_trunk(
            api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
        )
        return found.items[0] if found.items else None

    async def _rule_exists(self, rule_id: str) -> bool:
        found = await self._lk().sip.list_dispatch_rule(
            api.ListSIPDispatchRuleRequest(dispatch_rule_ids=[rule_id])
        )
        return bool(found.items)

    async def ensure_dispatch(self, trunk: TrunkSpec, livekit_trunk_id: str) -> str:
        sip = self._lk().sip
        metadata, name = _labels(trunk)
        trunk_id = livekit_trunk_id
        rule = api.SIPDispatchRule(
            dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix=ROOM_PREFIX)
        )
        rule_id = trunk.livekit_dispatch_rule_id
        if rule_id and await self._rule_exists(rule_id):
            ruled = await sip.update_dispatch_rule_fields(
                rule_id, trunk_ids=[trunk_id], rule=rule, name=name
            )
        else:
            ruled = await sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    dispatch_rule=api.SIPDispatchRuleInfo(
                        name=name,
                        metadata=metadata,
                        trunk_ids=[trunk_id],
                        rule=rule,
                        room_config=api.RoomConfiguration(
                            agents=[api.RoomAgentDispatch(agent_name=self._settings.agent_name)]
                        ),
                    )
                )
            )
        return str(ruled.sip_dispatch_rule_id)

    async def remove_inbound(self, trunk_id: str | None, dispatch_rule_id: str | None) -> None:
        sip = self._lk().sip
        try:
            if dispatch_rule_id:
                await sip.delete_dispatch_rule(
                    api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=dispatch_rule_id)
                )
        except api.ServerError as e:
            if e.code != _NOT_FOUND:
                raise
        try:
            if trunk_id:
                await sip.delete_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id))
        except api.ServerError as e:
            if e.code != _NOT_FOUND:
                raise

    async def aclose(self) -> None:
        if self._api is not None:
            await self._api.aclose()
            self._api = None
