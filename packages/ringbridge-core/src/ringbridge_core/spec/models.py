"""AgentSpec v1alpha1: the declarative definition of a Ringbridge voice agent (ADR-0005).

Structural rules (types, required fields, no unknown keys) live here. Cross-field rules
that need the whole spec (graph integrity, tool scoping, disclosures) live in `semantic.py`.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

API_VERSION = "ringbridge.dev/v1alpha1"

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")]
NodeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SlotName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Locale = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]
E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{6,14}$")]
ToolName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_KEY = re.compile(rf"^({'|'.join(_DAYS)})(-({'|'.join(_DAYS)}))?$")
_HOURS = re.compile(r"^(closed|([01][0-9]|2[0-3]):[0-5][0-9]-([01][0-9]|2[0-3]):[0-5][0-9])$")


class Strict(BaseModel):
    """Base for every spec model: unknown keys are errors, so typos never pass silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- metadata, language, voice


class Metadata(Strict):
    name: Slug = Field(description="Lowercase identifier, e.g. smile-dental-receptionist.")
    description: str | None = None


class LanguageConfig(Strict):
    default: Locale = Field(description="BCP 47 locale the agent starts in, e.g. en-IN.")
    allowed: list[Locale] = Field(
        default_factory=list, description="Other locales it may switch to."
    )
    detect: bool = Field(False, description="Detect the caller's language and switch if allowed.")


class ProviderRef(Strict):
    provider: NonEmpty = Field(description="Provider id, e.g. deepgram, cartesia, sarvam.")
    model: str | None = None
    voice: str | None = Field(None, description="TTS voice id.")
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class LLMRef(ProviderRef):
    temperature: float = Field(0.3, ge=0.0, le=2.0)


class VoiceOverride(Strict):
    stt: ProviderRef | None = None
    llm: LLMRef | None = None
    tts: ProviderRef | None = None


class VoiceConfig(Strict):
    engine: Literal["cascaded", "realtime"] = Field("cascaded", description="ADR-0003.")
    stt: ProviderRef
    llm: LLMRef
    tts: ProviderRef
    overrides: dict[Locale, VoiceOverride] = Field(
        default_factory=dict, description="Per-locale provider overrides (ADR-0014)."
    )


class Disclosures(Strict):
    greeting: str = Field("", description="Spoken first. Must say it is an AI and if recorded.")
    unsafe_disable_disclosure: bool = Field(
        False, description="Skip the disclosure check. You are responsible for legal compliance."
    )


class Business(Strict):
    timezone: NonEmpty = Field(description="IANA time zone, e.g. Asia/Kolkata.")
    hours: dict[str, str] = Field(
        default_factory=dict, description='Day or day range to "HH:MM-HH:MM" or "closed".'
    )
    knowledge: list[NonEmpty] = Field(default_factory=list, description="Knowledge files.")

    @field_validator("hours")
    @classmethod
    def _hours(cls, v: dict[str, str]) -> dict[str, str]:
        for day, span in v.items():
            if not _DAY_KEY.match(day):
                raise ValueError(f"unknown day {day!r}; use mon..sun or a range like mon-fri")
            if not _HOURS.match(span):
                raise ValueError(
                    f'hours for {day!r} must be "HH:MM-HH:MM" or "closed", got {span!r}'
                )
        return v


# ---------------------------------------------------------------- graph


SlotType = Literal[
    "string", "enum", "number", "boolean", "date", "time", "datetime_window", "phone", "email"
]


class SlotSpec(Strict):
    type: SlotType
    values: list[NonEmpty] | None = Field(None, description="Allowed values; enum slots only.")
    required: bool = True
    description: str | None = None

    @model_validator(mode="after")
    def _enum_values(self) -> SlotSpec:
        if self.type == "enum" and not self.values:
            raise ValueError("enum slots need a non-empty 'values' list")
        if self.type != "enum" and self.values is not None:
            raise ValueError("'values' is only allowed on enum slots")
        return self


class ConfirmBefore(Strict):
    confirm_before: ToolName = Field(description="Read back and require an explicit yes first.")


Guardrail = ConfirmBefore


class Transition(Strict):
    to: NodeId
    when: NonEmpty = Field(description="Natural-language condition the runtime checks.")


class TransferConfig(Strict):
    mode: Literal["warm", "cold"] = "warm"
    to: E164
    brief: bool = Field(True, description="Warm only: speak a short brief to the human first.")
    fallback: Literal["take_message", "end_call"] = "take_message"
    ring_timeout_s: int = Field(25, ge=5, le=120)


class Node(Strict):
    goal: NonEmpty | None = None
    action: Literal["transfer"] | None = Field(
        None, description="A built-in action instead of a goal."
    )
    transfer: TransferConfig | None = None
    collect: dict[SlotName, SlotSpec] = Field(default_factory=dict)
    tools: list[ToolName] = Field(default_factory=list)
    guardrails: list[Guardrail] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    max_turns: int | None = Field(None, ge=1, le=100)
    silence_timeout_s: float | None = Field(None, ge=1, le=60)

    @model_validator(mode="after")
    def _goal_or_action(self) -> Node:
        if self.action is None and self.goal is None:
            raise ValueError("a node needs a 'goal' (conversation) or an 'action'")
        if self.action == "transfer" and self.transfer is None:
            raise ValueError("action 'transfer' needs a 'transfer' block")
        if self.action is None and self.transfer is not None:
            raise ValueError("'transfer' is only allowed with action: transfer")
        return self


class Graph(Strict):
    start: NodeId
    nodes: dict[NodeId, Node] = Field(min_length=1)


# ---------------------------------------------------------------- post-call


class OutcomeField(Strict):
    type: Literal["string", "enum", "number", "boolean"]
    values: list[NonEmpty] | None = None
    max_words: int | None = Field(None, ge=1, le=500)
    description: str | None = None

    @model_validator(mode="after")
    def _enum_values(self) -> OutcomeField:
        if self.type == "enum" and not self.values:
            raise ValueError("enum fields need a non-empty 'values' list")
        if self.type != "enum" and self.values is not None:
            raise ValueError("'values' is only allowed on enum fields")
        if self.max_words is not None and self.type != "string":
            raise ValueError("'max_words' is only allowed on string fields")
        return self


class SendAction(Strict):
    channel: Literal["sms", "whatsapp", "email"]
    template: Slug
    fallback: Literal["sms", "whatsapp", "email"] | None = None


class ScheduleCall(Strict):
    after: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*(m|h|d)$")] = Field(
        description="Delay like 30m, 2h, 1d."
    )
    within_window: bool = Field(True, description="Only inside the campaign's calling window.")


class FollowUp(Strict):
    when: NonEmpty = Field(description="Expression over outcome fields, e.g. outcome == 'booked'.")
    send: SendAction | None = None
    schedule_call: ScheduleCall | None = None

    @model_validator(mode="after")
    def _one_action(self) -> FollowUp:
        if (self.send is None) == (self.schedule_call is None):
            raise ValueError("a follow-up needs exactly one of 'send' or 'schedule_call'")
        return self


class PostCall(Strict):
    extract: dict[SlotName, OutcomeField] = Field(default_factory=dict)
    follow_ups: list[FollowUp] = Field(default_factory=list)


# ---------------------------------------------------------------- root


class AgentBody(Strict):
    language: LanguageConfig
    voice: VoiceConfig
    persona: NonEmpty
    disclosures: Disclosures = Field(default_factory=Disclosures)
    business: Business
    graph: Graph
    post_call: PostCall = Field(default_factory=PostCall)


class AgentSpec(Strict):
    """A Ringbridge agent definition (`apiVersion: ringbridge.dev/v1alpha1`, `kind: Agent`)."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        title="Ringbridge AgentSpec v1alpha1",
        json_schema_extra={"$id": "https://ringbridge.dev/schema/agent-v1alpha1.json"},
    )

    api_version: Literal["ringbridge.dev/v1alpha1"] = Field(alias="apiVersion")
    kind: Literal["Agent"]
    metadata: Metadata
    spec: AgentBody
