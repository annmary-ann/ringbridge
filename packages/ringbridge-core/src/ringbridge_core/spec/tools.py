"""Built-in tools an AgentSpec node may list. Custom HTTP and MCP tools arrive in #30 and #43."""

from typing import Final

BUILTIN_TOOLS: Final[dict[str, str]] = {
    "calendar.availability": "Find open appointment slots.",
    "calendar.book": "Book an appointment.",
    "calendar.reschedule": "Move an existing appointment.",
    "calendar.cancel": "Cancel an existing appointment.",
    "crm.lookup_contact": "Look up the caller in the CRM.",
    "message.send": "Send an SMS, WhatsApp or email during the call.",
    "call.transfer": "Transfer the call to a person.",
    "call.end": "End the call politely.",
}

# Tools with side effects. A spec should guard these with confirm_before (warning if not).
SIDE_EFFECT_TOOLS: Final[frozenset[str]] = frozenset(
    {"calendar.book", "calendar.reschedule", "calendar.cancel", "message.send"}
)
