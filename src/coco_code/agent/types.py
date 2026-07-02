from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from coco_code.tools.base import ToolCall, ToolResult


class AgentMode(StrEnum):
    AGENT = "agent"
    PLAN = "plan"
    DO = "do"


class AgentStopReason(StrEnum):
    MODEL_DONE = "model_done"
    ITERATION_LIMIT = "iteration_limit"
    USER_CANCELLED = "user_cancelled"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    STREAM_ERROR = "stream_error"
    TOOL_ERROR = "tool_error"
    RUNTIME_ABORT = "runtime_abort"


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 8
    unknown_tool_limit: int = 2
    response_timeout_seconds: float = 300.0
    tool_timeout_seconds: float = 10.0
    confirm_timeout_seconds: float = 60.0
    read_tool_concurrency: int = 4


@dataclass(frozen=True)
class AgentRunRequest:
    text: str
    mode: AgentMode


@dataclass(frozen=True)
class AgentProgress:
    iteration: int
    max_iterations: int
    phase: str
    tool_name: str | None = None
    batch_index: int | None = None
    batch_total: int | None = None


class AgentEventType(StrEnum):
    MODE_CHANGED = "mode_changed"
    PROGRESS = "progress"
    TEXT_DELTA = "text_delta"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALLS = "tool_calls"
    TOOL_BATCH_STARTED = "tool_batch_started"
    TOOL_STARTED = "tool_started"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    text: str = ""
    mode: AgentMode | None = None
    progress: AgentProgress | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    stop_reason: AgentStopReason | None = None
    error: Exception | str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class StreamTurnResult:
    reply: str
    tool_calls: tuple[ToolCall, ...] = ()
    error: Exception | None = None


@dataclass(frozen=True)
class ToolBatch:
    calls: tuple[ToolCall, ...]
    concurrent: bool
