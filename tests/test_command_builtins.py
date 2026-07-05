from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from coco_code.agent import AgentMode
from coco_code.command import (
    PUBLIC_COMMAND_NAMES,
    CommandMemory,
    CommandSession,
    CommandStatus,
    build_default_registry,
    parse_command,
)
from coco_code.command.types import CommandContext
from coco_code.permission import Mode as PermissionMode


@dataclass
class RecordingUI:
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sent: list[tuple[str, str | None, AgentMode | None, PermissionMode | None]] = field(
        default_factory=list
    )
    agent_mode: AgentMode = AgentMode.AGENT
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    compact_called: bool = False
    clear_called: bool = False
    resume_called: bool = False
    tools_called: bool = False
    quit_called: bool = False
    idle: bool = True

    def show_message(self, text: str) -> None:
        self.messages.append(text)

    def show_error(self, text: str) -> None:
        self.errors.append(text)

    def clear_history(self) -> None:
        self.clear_called = True

    def send_user_message(
        self,
        text: str,
        *,
        display_label: str | None = None,
        mode: AgentMode | None = None,
        permission_mode: PermissionMode | None = None,
    ) -> None:
        self.sent.append((text, display_label, mode, permission_mode))

    def set_agent_mode(self, mode: AgentMode) -> None:
        self.agent_mode = mode

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode

    def run_compact(self) -> None:
        self.compact_called = True

    def show_resume(self) -> None:
        self.resume_called = True

    def show_tools(self) -> None:
        self.tools_called = True

    def status_snapshot(self) -> CommandStatus:
        return CommandStatus("fake-model", self.agent_mode, self.permission_mode, 2, 42, 6, "sid")

    def session_snapshot(self) -> CommandSession:
        return CommandSession("sid", "session/path", 2)

    def memory_snapshot(self) -> CommandMemory:
        return CommandMemory("index", ("project:MEMORY.md",))

    def refresh_status(self) -> None:
        return None

    def quit(self) -> None:
        self.quit_called = True

    def is_idle(self) -> bool:
        return self.idle


def run_command(name: str, ui: RecordingUI, args: str = "") -> None:
    registry = build_default_registry()
    command = registry.lookup(name)
    assert command is not None
    raw = f"/{name} {args}".strip()
    asyncio.run(command.handler(CommandContext(parse_command(raw)), ui))


def test_register_builtins_public_commands_visible() -> None:
    registry = build_default_registry()
    assert tuple(item.name for item in registry.visible()) == tuple(sorted(PUBLIC_COMMAND_NAMES))
    for name in PUBLIC_COMMAND_NAMES:
        assert registry.lookup(name) is not None
    assert registry.lookup("exit") is not None
    assert "exit" not in [item.name for item in registry.visible()]


def test_help_lists_public_commands() -> None:
    ui = RecordingUI()
    run_command("help", ui)
    output = ui.messages[-1]
    for name in PUBLIC_COMMAND_NAMES:
        assert f"/{name}" in output
    assert "/exit" not in output


def test_status_prints_snapshot() -> None:
    ui = RecordingUI()
    run_command("status", ui)
    output = ui.messages[-1]
    assert "Mode:" in output
    assert "Tokens:" in output
    assert "Tools:" in output
    assert "Session:" in output


def test_compact_blocks_when_busy() -> None:
    ui = RecordingUI(idle=False)
    run_command("compact", ui)
    assert ui.errors
    assert ui.compact_called is False


def test_do_with_args_sends_execution_prompt() -> None:
    ui = RecordingUI()
    run_command("do", ui, "fix bug")
    assert ui.agent_mode == AgentMode.DO
    assert ui.permission_mode == PermissionMode.DEFAULT
    assert ui.sent == [("fix bug", "/do fix bug", AgentMode.DO, PermissionMode.DEFAULT)]


def test_review_sends_preset_prompt() -> None:
    ui = RecordingUI()
    run_command("review", ui)
    assert ui.sent
    assert "review" in ui.sent[0][0].lower()
    assert ui.sent[0][1] == "/review"
