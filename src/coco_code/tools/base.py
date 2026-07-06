from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

ToolParams = dict[str, Any]
JsonSchema = dict[str, Any]


class ConfirmationPolicy(StrEnum):
    NEVER = "never"
    REQUIRED = "required"


class ToolCategory(StrEnum):
    GENERAL = "general"
    FILE = "file"
    SEARCH = "search"
    SHELL = "shell"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: JsonSchema
    confirmation: ConfirmationPolicy
    category: ToolCategory = ToolCategory.GENERAL
    read_only: bool = False
    destructive: bool = False
    typical_scenarios: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    system: bool = False


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: ToolParams
    raw_arguments: str


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    tool_name: str
    ok: bool
    summary: str
    data: dict[str, Any]
    error: str | None
    elapsed_ms: int
    truncated: bool = False


@dataclass(frozen=True)
class ToolContext:
    workspace: Path
    timeout_seconds: float = 10.0
    confirm_timeout_seconds: float = 60.0
    max_output_chars: int = 20_000
    max_search_results: int = 100


class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def run(self, params: ToolParams, context: ToolContext) -> ToolResult: ...


ConfirmCallback = Callable[[ToolCall, ToolSpec], Awaitable[bool]]
