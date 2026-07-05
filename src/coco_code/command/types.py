from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coco_code.agent import AgentMode
from coco_code.permission import Mode as PermissionMode


class CommandKind(StrEnum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    is_command: bool
    name: str = ""
    args: str = ""
    raw: str = ""


@dataclass(frozen=True, slots=True)
class CommandStatus:
    model: str
    agent_mode: AgentMode
    permission_mode: PermissionMode
    message_count: int
    estimated_tokens: int
    tool_count: int
    session_id: str


@dataclass(frozen=True, slots=True)
class CommandSession:
    session_id: str
    session_path: str
    message_count: int


@dataclass(frozen=True, slots=True)
class CommandMemory:
    text: str
    files: tuple[str, ...] = ()


class CommandUI(Protocol):
    def show_message(self, text: str) -> None: ...

    def show_error(self, text: str) -> None: ...

    def clear_history(self) -> None: ...

    def send_user_message(
        self,
        text: str,
        *,
        display_label: str | None = None,
        mode: AgentMode | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> None: ...

    def set_agent_mode(self, mode: AgentMode) -> None: ...

    def set_permission_mode(self, mode: PermissionMode) -> None: ...

    def run_compact(self) -> None: ...

    def show_resume(self) -> None: ...

    def show_tools(self) -> None: ...

    def status_snapshot(self) -> CommandStatus: ...

    def session_snapshot(self) -> CommandSession: ...

    def memory_snapshot(self) -> CommandMemory: ...

    def refresh_status(self) -> None: ...

    def quit(self) -> None: ...

    def is_idle(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    parsed: ParsedCommand

    @property
    def args(self) -> str:
        return self.parsed.args


CommandHandler = Callable[[CommandContext, CommandUI], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    description: str
    usage: str
    kind: CommandKind
    handler: CommandHandler
    aliases: Sequence[str] = ()
    argument_hint: str = ""
    hidden: bool = False
