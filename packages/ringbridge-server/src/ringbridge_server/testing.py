"""Test doubles that ship with the package, so tests elsewhere can reuse them."""

from __future__ import annotations

from ringbridge_server.telephony import TrunkSpec


class InMemorySip:
    """In-memory stand-in for LiveKit's SIP API, for tests and running without LiveKit.

    Set `fail = True` to make every call raise, as an unreachable LiveKit would.
    """

    def __init__(self) -> None:
        self.trunks: dict[str, TrunkSpec] = {}
        self.rules: dict[str, str] = {}
        self.fail = False
        self.passwords: list[str | None] = []
        self._next = 0

    def _id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}_{self._next}"

    async def ensure_trunk(self, trunk: TrunkSpec) -> str:
        if self.fail:
            raise ConnectionError("LiveKit unreachable")
        trunk_id = trunk.livekit_trunk_id or self._id("ST")
        self.trunks[trunk_id] = trunk
        self.passwords.append(trunk.auth_password)
        return trunk_id

    async def ensure_dispatch(self, trunk: TrunkSpec, livekit_trunk_id: str) -> str:
        rule_id = trunk.livekit_dispatch_rule_id or self._id("SDR")
        self.rules[rule_id] = livekit_trunk_id
        return rule_id

    async def remove_inbound(self, trunk_id: str | None, dispatch_rule_id: str | None) -> None:
        if self.fail:
            raise ConnectionError("LiveKit unreachable")
        self.trunks.pop(trunk_id or "", None)
        self.rules.pop(dispatch_rule_id or "", None)

    async def aclose(self) -> None:
        pass

    def numbers(self, trunk_id: str) -> list[str]:
        return self.trunks[trunk_id].numbers
