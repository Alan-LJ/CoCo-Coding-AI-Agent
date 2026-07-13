from __future__ import annotations

from coco_code.command.builtin_worktree import handle_worktree
from coco_code.command.handlers import (
    handle_clear,
    handle_compact,
    handle_do,
    handle_exit,
    handle_hooks,
    handle_memory,
    handle_permission,
    handle_plan,
    handle_resume,
    handle_session,
    handle_status,
    handle_tools,
    make_help_handler,
)
from coco_code.command.registry import CommandRegistry
from coco_code.command.types import Command, CommandKind

PUBLIC_COMMAND_NAMES = (
    "clear",
    "compact",
    "do",
    "help",
    "hooks",
    "memory",
    "permission",
    "plan",
    "session",
    "status",
    "worktree",
)


def build_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    _register_public(registry)
    _register_compat(registry)
    return registry


def _register_public(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="help",
            aliases=("h", "?"),
            description="Show available slash commands.",
            usage="/help [command]",
            argument_hint="Optional command name.",
            kind=CommandKind.LOCAL,
            handler=make_help_handler(registry),
        )
    )
    registry.register(
        Command(
            name="compact",
            aliases=("c",),
            description="Compact the current conversation context.",
            usage="/compact",
            kind=CommandKind.UI,
            handler=handle_compact,
        )
    )
    registry.register(
        Command(
            name="clear",
            description="Clear the visible history without deleting sessions.",
            usage="/clear",
            kind=CommandKind.UI,
            handler=handle_clear,
        )
    )
    registry.register(
        Command(
            name="plan",
            description="Switch to plan mode or send a plan-mode prompt.",
            usage="/plan [prompt]",
            argument_hint="Optional prompt to send in plan mode.",
            kind=CommandKind.UI,
            handler=handle_plan,
        )
    )
    registry.register(
        Command(
            name="do",
            description="Switch to execution mode or send an execution prompt.",
            usage="/do [prompt]",
            argument_hint="Optional prompt to send in execution mode.",
            kind=CommandKind.PROMPT,
            handler=handle_do,
        )
    )
    registry.register(
        Command(
            name="hooks",
            description="List loaded lifecycle hooks.",
            usage="/hooks",
            kind=CommandKind.LOCAL,
            handler=handle_hooks,
        )
    )
    registry.register(
        Command(
            name="session",
            description="Show current session details.",
            usage="/session",
            kind=CommandKind.LOCAL,
            handler=handle_session,
        )
    )
    registry.register(
        Command(
            name="memory",
            aliases=("mem",),
            description="Show loaded memory index information.",
            usage="/memory",
            kind=CommandKind.LOCAL,
            handler=handle_memory,
        )
    )
    registry.register(
        Command(
            name="permission",
            aliases=("perm",),
            description="Show or change permission mode.",
            usage="/permission [mode]",
            argument_hint="default, acceptEdits, plan, or bypassPermissions.",
            kind=CommandKind.LOCAL,
            handler=handle_permission,
        )
    )
    registry.register(
        Command(
            name="worktree",
            aliases=("wt",),
            description="Create, enter, list, exit, or remove Git worktrees.",
            usage="/worktree <create|list|enter|exit|remove> ...",
            argument_hint="create/list/enter/exit/remove",
            kind=CommandKind.LOCAL,
            handler=handle_worktree,
        )
    )
    registry.register(
        Command(
            name="status",
            aliases=("s",),
            description="Show model, mode, token, session, and tool status.",
            usage="/status",
            kind=CommandKind.LOCAL,
            handler=handle_status,
        )
    )


def _register_compat(registry: CommandRegistry) -> None:
    registry.register(
        Command(
            name="exit",
            description="Exit CoCo Code.",
            usage="/exit",
            kind=CommandKind.UI,
            handler=handle_exit,
            hidden=True,
        )
    )
    registry.register(
        Command(
            name="resume",
            description="Open the recent-session picker.",
            usage="/resume",
            kind=CommandKind.UI,
            handler=handle_resume,
            hidden=True,
        )
    )
    registry.register(
        Command(
            name="tools",
            description="Show available tools.",
            usage="/tools",
            kind=CommandKind.LOCAL,
            handler=handle_tools,
            hidden=True,
        )
    )
