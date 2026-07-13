from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from coco_code.agent import AgentMode
from coco_code.command import (
    CommandMemory,
    CommandSession,
    CommandStatus,
    WorktreeSummary,
    build_default_registry,
    parse_command,
)
from coco_code.command.types import CommandContext
from coco_code.permission import Mode as PermissionMode


class StubAccessor:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.entered: list[str] = []
        self.exited: list[tuple[str, bool]] = []
        self.removed: list[tuple[str, bool]] = []

    async def create(self, name: str) -> tuple[str, str]:
        self.created.append(name)
        return f".coco-code/worktrees/{name}", f"worktree-{name}"

    def list(self) -> list[WorktreeSummary]:
        return [
            WorktreeSummary(
                name="demo",
                path=".coco-code/worktrees/demo",
                branch="worktree-demo",
                active=True,
                manual=True,
            )
        ]

    async def enter(self, name: str) -> None:
        self.entered.append(name)

    async def exit(self, action: str, discard: bool) -> bool:
        self.exited.append((action, discard))
        return action == "remove"

    async def remove(self, name: str, discard: bool) -> None:
        self.removed.append((name, discard))


@dataclass
class StubUI:
    accessor: StubAccessor | None = None
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def show_message(self, text: str) -> None:
        self.messages.append(text)

    def show_error(self, text: str) -> None:
        self.errors.append(text)

    def worktree_accessor(self):
        return self.accessor

    def clear_history(self) -> None: ...

    def clear_active_skills(self) -> None: ...

    def append_assistant_message(self, text: str) -> None: ...

    def reload_skills(self) -> None: ...

    def list_catalog_skills(self):
        return ()

    def list_active_skills(self):
        return ()

    def send_user_message(self, text: str, **kwargs) -> None: ...  # noqa: ANN003

    def set_agent_mode(self, mode: AgentMode) -> None: ...

    def set_permission_mode(self, mode: PermissionMode) -> None: ...

    def run_compact(self) -> None: ...

    def show_resume(self) -> None: ...

    def show_tools(self) -> None: ...

    def status_snapshot(self) -> CommandStatus:
        return CommandStatus("", AgentMode.AGENT, PermissionMode.DEFAULT, 0, 0, 0, "")

    def session_snapshot(self) -> CommandSession:
        return CommandSession("", "", 0)

    def memory_snapshot(self) -> CommandMemory:
        return CommandMemory("")

    def hook_rules(self):
        return []

    def hook_sources(self):
        return []

    def refresh_status(self) -> None: ...

    def quit(self) -> None: ...

    def is_idle(self) -> bool:
        return True


def run_worktree(args: str, ui: StubUI) -> None:
    command = build_default_registry().lookup("worktree")
    assert command is not None
    asyncio.run(command.handler(CommandContext(parse_command(f"/worktree {args}")), ui))


def test_worktree_command_registered() -> None:
    assert build_default_registry().lookup("worktree") is not None


def test_worktree_command_dispatches_subcommands() -> None:
    accessor = StubAccessor()
    ui = StubUI(accessor)
    run_worktree("create demo", ui)
    run_worktree("list", ui)
    run_worktree("enter demo", ui)
    run_worktree("exit --remove --discard", ui)
    run_worktree("remove demo --discard", ui)
    assert accessor.created == ["demo"]
    assert accessor.entered == ["demo"]
    assert accessor.exited == [("remove", True)]
    assert accessor.removed == [("demo", True)]
    assert any("demo" in message for message in ui.messages)


def test_worktree_command_reports_disabled() -> None:
    ui = StubUI(None)
    run_worktree("list", ui)
    assert ui.errors
