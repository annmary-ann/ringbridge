from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from ringbridge_core.events import (
    MAX_BATCH,
    EventBatch,
    ToolResult,
    Turn,
    build_transcript,
    payload_of,
    render_transcript,
)

T0 = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def turn(seq: int, speaker: str, text: str, seconds: float, **extra: Any) -> Turn:
    return Turn.model_validate(
        {"event_id": f"t{seq}", "seq": seq, "occurred_at": at(seconds), "speaker": speaker}
        | {"text": text}
        | extra
    )


def test_batch_parses_every_event_type_by_discriminator() -> None:
    batch = EventBatch.model_validate(
        {
            "events": [
                {"type": "call.started", "event_id": "a", "seq": 0, "occurred_at": T0},
                {"type": "turn", "event_id": "b", "seq": 1, "occurred_at": T0,
                 "speaker": "agent", "text": "Hello"},
                {"type": "tool_call", "event_id": "c", "seq": 2, "occurred_at": T0,
                 "tool_call_id": "x1", "name": "check_availability", "arguments": {"day": "mon"}},
                {"type": "tool_result", "event_id": "d", "seq": 3, "occurred_at": T0,
                 "tool_call_id": "x1", "name": "check_availability", "ok": True,
                 "result": [{"slot": "10:00"}], "duration_ms": 120},
                {"type": "transition", "event_id": "e", "seq": 4, "occurred_at": T0,
                 "from_node": "greet", "to_node": "book"},
                {"type": "metric", "event_id": "f", "seq": 5, "occurred_at": T0,
                 "name": "voice_to_voice_ms", "value": 640.5, "turn_seq": 1},
                {"type": "call.ended", "event_id": "g", "seq": 6, "occurred_at": T0,
                 "reason": "caller_hangup"},
            ]
        }
    )  # fmt: skip
    assert [e.type for e in batch.events] == [
        "call.started", "turn", "tool_call", "tool_result", "transition", "metric", "call.ended",
    ]  # fmt: skip
    result = batch.events[3]
    assert isinstance(result, ToolResult)
    assert payload_of(result) == {
        "tool_call_id": "x1",
        "name": "check_availability",
        "ok": True,
        "result": [{"slot": "10:00"}],
        "error": None,
        "duration_ms": 120.0,
    }


@pytest.mark.parametrize(
    ("event", "problem"),
    [
        ({"type": "nope", "event_id": "a", "seq": 0, "occurred_at": T0}, "union_tag_invalid"),
        ({"type": "turn", "event_id": "a", "seq": 0, "occurred_at": T0, "speaker": "bot",
          "text": "x"}, "literal_error"),
        ({"type": "metric", "event_id": "a", "seq": -1, "occurred_at": T0, "name": "m",
          "value": 1}, "greater_than_equal"),
        ({"type": "call.ended", "event_id": "a b", "seq": 0, "occurred_at": T0,
          "reason": "x"}, "string_pattern_mismatch"),
        ({"type": "call.ended", "event_id": "a", "seq": 0,
          "occurred_at": "2026-11-26T10:00:00", "reason": "x"}, "timezone_aware"),
        ({"type": "call.started", "event_id": "a", "seq": 0, "occurred_at": T0,
          "surprise": 1}, "extra_forbidden"),
    ],
)  # fmt: skip
def test_bad_events_are_rejected(event: dict[str, Any], problem: str) -> None:
    with pytest.raises(ValidationError) as info:
        EventBatch.model_validate({"events": [event]})
    assert problem in {e["type"] for e in info.value.errors()}


def test_batch_rejects_duplicate_ids_and_bad_sizes() -> None:
    e = {"type": "call.started", "event_id": "a", "seq": 0, "occurred_at": T0}
    with pytest.raises(ValidationError, match="appears twice"):
        EventBatch.model_validate({"events": [e, e]})
    with pytest.raises(ValidationError):
        EventBatch.model_validate({"events": []})
    many = [e | {"event_id": f"e{i}"} for i in range(MAX_BATCH + 1)]
    with pytest.raises(ValidationError):
        EventBatch.model_validate({"events": many})


def test_transcript_orders_by_seq_and_measures_from_call_start() -> None:
    turns = [
        turn(3, "caller", "  Tomorrow at ten?  ", 9.0),
        turn(1, "agent", "Hi, this is Smile Dental's assistant.", 1.2, node="greet"),
        turn(2, "caller", "", 4.0),  # empty STT result
        turn(4, "agent", "Let me check", 70.0, interrupted=True, started_at=at(65.5)),
    ]
    lines = build_transcript(turns, started_at=T0)
    assert [line.seq for line in lines] == [1, 3, 4]
    assert lines[1].text == "Tomorrow at ten?"
    assert [line.offset_ms for line in lines] == [1200, 9000, 65500]
    assert lines[0].node == "greet"
    assert render_transcript(lines) == (
        "[00:01] Agent: Hi, this is Smile Dental's assistant.\n"
        "[00:09] Caller: Tomorrow at ten?\n"
        "[01:05] Agent: Let me check [interrupted]\n"
    )


def test_transcript_without_a_start_time_has_no_offsets() -> None:
    lines = build_transcript([turn(1, "agent", "Hello", 3.0)], started_at=None)
    assert lines[0].offset_ms is None
    assert render_transcript(lines) == "Agent: Hello\n"
    assert render_transcript([]) == ""
