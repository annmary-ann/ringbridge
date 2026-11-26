"""Call events: what an agent worker reports to the control plane while a call runs.

Events are append-only facts. Each carries an `event_id` chosen by the worker (unique within the
call), so a batch can be retried after a timeout without creating duplicates, and a `seq`
giving the order in which things happened on the call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

EVENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
MAX_BATCH = 500

Speaker = Literal["caller", "agent"]
EndStatus = Literal["completed", "no_answer", "busy", "failed", "canceled"]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(pattern=EVENT_ID_PATTERN, description="Unique within the call")
    seq: int = Field(ge=0, description="Order of the event within the call")
    occurred_at: AwareDatetime


class CallStarted(_Event):
    """The call is connected and the agent is on the line."""

    type: Literal["call.started"] = "call.started"
    from_number: str | None = Field(default=None, max_length=32)
    to_number: str | None = Field(default=None, max_length=32)


class Turn(_Event):
    """One finished utterance by the caller or the agent."""

    type: Literal["turn"] = "turn"
    speaker: Speaker
    text: str = Field(max_length=20_000)
    language: str | None = Field(default=None, max_length=16, examples=["en-IN"])
    node: str | None = Field(default=None, description="Graph node the agent was in")
    interrupted: bool = Field(default=False, description="The agent was cut off (barge-in)")
    started_at: AwareDatetime | None = None


class ToolCall(_Event):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = Field(max_length=64)
    name: str = Field(max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    node: str | None = None


class ToolResult(_Event):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = Field(max_length=64)
    name: str = Field(max_length=100)
    ok: bool
    result: Any = None
    error: str | None = Field(default=None, max_length=2000)
    duration_ms: float | None = Field(default=None, ge=0)


class Transition(_Event):
    type: Literal["transition"] = "transition"
    from_node: str | None = None
    to_node: str
    reason: str | None = Field(default=None, max_length=500)


class Metric(_Event):
    type: Literal["metric"] = "metric"
    name: str = Field(max_length=100, examples=["voice_to_voice_ms", "stt_ms", "llm_ttft_ms"])
    value: float
    unit: str = Field(default="ms", max_length=16)
    turn_seq: int | None = Field(default=None, ge=0, description="The turn this measures")


class CallEnded(_Event):
    type: Literal["call.ended"] = "call.ended"
    status: EndStatus = "completed"
    reason: str = Field(max_length=64, examples=["caller_hangup", "agent_hangup", "transfer"])


CallEvent = Annotated[
    CallStarted | Turn | ToolCall | ToolResult | Transition | Metric | CallEnded,
    Field(discriminator="type"),
]


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[CallEvent] = Field(min_length=1, max_length=MAX_BATCH)

    @model_validator(mode="after")
    def _unique_ids(self) -> EventBatch:
        seen: set[str] = set()
        for e in self.events:
            if e.event_id in seen:
                raise ValueError(f"event_id {e.event_id!r} appears twice in the batch")
            seen.add(e.event_id)
        return self


def payload_of(event: _Event) -> dict[str, Any]:
    """The event-specific fields, for storage next to the common columns."""
    common = {"event_id", "seq", "occurred_at", "type"}
    return event.model_dump(mode="json", exclude=common)


# ------------------------------------------------------------------ transcript


class TranscriptLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    speaker: Speaker
    text: str
    at: datetime
    offset_ms: int | None = Field(description="Milliseconds since the call started")
    interrupted: bool = False
    node: str | None = None
    language: str | None = None


def build_transcript(turns: list[Turn], started_at: datetime | None) -> list[TranscriptLine]:
    """Order turns by `seq` (then time) and drop empty utterances."""
    lines = []
    for t in sorted(turns, key=lambda t: (t.seq, t.occurred_at)):
        text = t.text.strip()
        if not text:
            continue
        at = t.started_at or t.occurred_at
        offset = round((at - started_at).total_seconds() * 1000) if started_at else None
        lines.append(
            TranscriptLine(
                seq=t.seq,
                speaker=t.speaker,
                text=text,
                at=at,
                offset_ms=offset,
                interrupted=t.interrupted,
                node=t.node,
                language=t.language,
            )
        )
    return lines


def render_transcript(lines: list[TranscriptLine]) -> str:
    """Plain text, one line per utterance: `[01:05] Agent: ...`."""
    out = []
    for line in lines:
        stamp = ""
        if line.offset_ms is not None:
            secs = max(line.offset_ms, 0) // 1000
            stamp = f"[{secs // 60:02d}:{secs % 60:02d}] "
        cut = " [interrupted]" if line.interrupted else ""
        out.append(f"{stamp}{line.speaker.capitalize()}: {line.text}{cut}")
    return "\n".join(out) + ("\n" if out else "")
