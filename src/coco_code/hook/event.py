from __future__ import annotations

from enum import StrEnum


class Event(StrEnum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"


BLOCKING_EVENTS: frozenset[Event] = frozenset(
    {Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT}
)


def is_blocking(event: Event) -> bool:
    return event in BLOCKING_EVENTS


def parse_event(value: str) -> Event | None:
    try:
        return Event(value)
    except ValueError:
        return None
