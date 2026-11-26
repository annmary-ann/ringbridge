"""LiveKitSip against a real LiveKit server (the dev stack, `poe up`).

Skipped when LiveKit is not reachable, unless RINGBRIDGE_REQUIRE_LIVEKIT=1 (set in CI's stack job).
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
from livekit import api

from ringbridge_server.settings import Settings
from ringbridge_server.telephony import ROOM_PREFIX, LiveKitSip, TrunkSpec

pytestmark = [pytest.mark.anyio, pytest.mark.livekit]


def _reachable(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 7880), 2):
            return True
    except OSError:
        return False


@pytest.fixture
async def livekit() -> AsyncIterator[LiveKitSip]:
    settings = Settings(_env_file=None)
    if not _reachable(settings.livekit_url):
        reason = f"LiveKit is not reachable at {settings.livekit_url}: start it with `poe up`"
        if os.environ.get("RINGBRIDGE_REQUIRE_LIVEKIT") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    sip = LiveKitSip(settings)
    yield sip
    await sip.aclose()


async def _inbound_trunk(sip: LiveKitSip, trunk_id: str) -> api.SIPInboundTrunkInfo:
    listed = await sip._lk().sip.list_inbound_trunk(
        api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
    )
    [trunk] = listed.items
    return trunk


async def test_trunk_and_dispatch_rule_lifecycle(livekit: LiveKitSip) -> None:
    spec = TrunkSpec(
        id=uuid.uuid4(),
        name=f"test-{uuid.uuid4().hex[:8]}",
        numbers=["+914842000123"],
        allowed_addresses=["203.0.113.0/24"],
        auth_username="pbx",
        auth_password="initial-secret",
    )
    trunk_id = await livekit.ensure_trunk(spec)
    rule_id = await livekit.ensure_dispatch(spec, trunk_id)
    try:
        info = await _inbound_trunk(livekit, trunk_id)
        assert list(info.numbers) == ["+914842000123"]
        assert list(info.allowed_addresses) == ["203.0.113.0/24"]
        assert info.name == f"ringbridge:{spec.name}"

        rules = await livekit._lk().sip.list_dispatch_rule(
            api.ListSIPDispatchRuleRequest(dispatch_rule_ids=[rule_id])
        )
        [rule] = rules.items
        assert list(rule.trunk_ids) == [trunk_id]
        assert rule.rule.dispatch_rule_individual.room_prefix == ROOM_PREFIX
        assert [a.agent_name for a in rule.room_config.agents] == ["ringbridge"]

        # Syncing again with the stored ids updates in place.
        updated = TrunkSpec(
            id=spec.id,
            name=spec.name,
            numbers=["+914842000123", "+914842000124"],
            livekit_trunk_id=trunk_id,
            livekit_dispatch_rule_id=rule_id,
        )
        assert await livekit.ensure_trunk(updated) == trunk_id
        assert await livekit.ensure_dispatch(updated, trunk_id) == rule_id
        info = await _inbound_trunk(livekit, trunk_id)
        assert list(info.numbers) == ["+914842000123", "+914842000124"]
        assert list(info.allowed_addresses) == []  # emptied, not left as it was

        # Deleted in LiveKit behind our back: the next sync recreates both.
        await livekit.remove_inbound(trunk_id, rule_id)
        trunk_id = await livekit.ensure_trunk(updated)
        rule_id = await livekit.ensure_dispatch(updated, trunk_id)
        assert trunk_id != updated.livekit_trunk_id
        assert rule_id != updated.livekit_dispatch_rule_id
        assert list((await _inbound_trunk(livekit, trunk_id)).numbers) == updated.numbers
    finally:
        await livekit.remove_inbound(trunk_id, rule_id)
    # Removing twice is not an error.
    await livekit.remove_inbound(trunk_id, rule_id)
    gone = await livekit._lk().sip.list_inbound_trunk(
        api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
    )
    assert list(gone.items) == []
