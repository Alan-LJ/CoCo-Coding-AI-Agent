from __future__ import annotations

from coco_code.agent import AgentMode
from coco_code.command.registry import CommandRegistry
from coco_code.command.types import CommandContext, CommandUI
from coco_code.permission import Mode as PermissionMode
from coco_code.permission import parse_mode

REVIEW_PROMPT = (
    "Please review the current code changes and context. Prioritize bugs, "
    "behavioral regressions, missing tests, security risks, and maintainability "
    "issues. Present findings first with concrete file or behavior references."
)


def make_help_handler(registry: CommandRegistry):
    async def handle_help(context: CommandContext, ui: CommandUI) -> None:
        name = context.args.strip().lstrip("/").lower()
        if name:
            command = registry.lookup(name)
            if command is None or command.hidden:
                ui.show_error(f"Unknown command: /{name}. Type /help to list commands.")
                return
            lines = [f"/{command.name}", command.description, f"Usage: {command.usage}"]
            if command.aliases:
                aliases = ", ".join(f"/{alias}" for alias in command.aliases)
                lines.append(f"Aliases: {aliases}")
            if command.argument_hint:
                lines.append(f"Args: {command.argument_hint}")
            ui.show_message("\n".join(lines))
            return

        commands = registry.visible()
        width = max((len(command.name) for command in commands), default=4)
        lines = ["Available commands:"]
        for command in commands:
            aliases = (
                f" ({', '.join('/' + alias for alias in command.aliases)})"
                if command.aliases
                else ""
            )
            lines.append(f"/{command.name.ljust(width)}  {command.description}{aliases}")
        ui.show_message("\n".join(lines))

    return handle_help


async def handle_status(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    status = ui.status_snapshot()
    lines = [
        "CoCo Code Status",
        f"Mode: {status.agent_mode.value} / {status.permission_mode}",
        f"Messages: {status.message_count}",
        f"Tokens: {status.estimated_tokens}",
        f"Tools: {status.tool_count}",
        f"Session: {status.session_id or '-'}",
        f"Model: {status.model or '-'}",
    ]
    ui.show_message("\n".join(lines))


async def handle_session(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    session = ui.session_snapshot()
    lines = [
        f"Session: {session.session_id or '-'}",
        f"Path: {session.session_path or '-'}",
        f"Messages: {session.message_count}",
    ]
    ui.show_message("\n".join(lines))


async def handle_memory(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    memory = ui.memory_snapshot()
    if not memory.text.strip() and not memory.files:
        ui.show_message("No memory index is loaded.")
        return
    lines = ["Memory"]
    if memory.files:
        lines.append("Files:")
        lines.extend(f"- {path}" for path in memory.files)
    if memory.text.strip():
        lines.append("Index:")
        lines.append(memory.text.strip())
    ui.show_message("\n".join(lines))


async def handle_permission(context: CommandContext, ui: CommandUI) -> None:
    if not context.args.strip():
        ui.show_message(f"Permission mode: {ui.status_snapshot().permission_mode}")
        return
    mode, ok = parse_mode(context.args)
    if not ok:
        ui.show_error(f"Unknown permission mode: {context.args}")
        return
    ui.set_permission_mode(mode)
    ui.refresh_status()
    ui.show_message(f"Permission mode: {mode}")


async def handle_compact(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    if not ui.is_idle():
        ui.show_error("Wait for the current task to finish before compacting.")
        return
    ui.run_compact()


async def handle_clear(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    ui.clear_history()
    ui.show_message("Cleared the visible history.")


async def handle_plan(context: CommandContext, ui: CommandUI) -> None:
    ui.set_agent_mode(AgentMode.PLAN)
    ui.set_permission_mode(PermissionMode.PLAN)
    ui.refresh_status()
    if context.args.strip():
        ui.send_user_message(
            context.args.strip(),
            display_label=f"/plan {context.args.strip()}",
            mode=AgentMode.PLAN,
            permission_mode=PermissionMode.PLAN,
        )
        return
    ui.show_message("Switched to plan mode.")


async def handle_do(context: CommandContext, ui: CommandUI) -> None:
    ui.set_agent_mode(AgentMode.DO)
    ui.set_permission_mode(PermissionMode.DEFAULT)
    ui.refresh_status()
    if context.args.strip():
        ui.send_user_message(
            context.args.strip(),
            display_label=f"/do {context.args.strip()}",
            mode=AgentMode.DO,
            permission_mode=PermissionMode.DEFAULT,
        )
        return
    ui.show_message("Switched to default execution mode.")


async def handle_review(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    ui.send_user_message(
        REVIEW_PROMPT,
        display_label="/review",
        mode=AgentMode.AGENT,
        permission_mode=None,
    )


async def handle_exit(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    ui.quit()


async def handle_resume(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    if not ui.is_idle():
        ui.show_error("Wait for the current task to finish before resuming a session.")
        return
    ui.show_resume()


async def handle_tools(context: CommandContext, ui: CommandUI) -> None:  # noqa: ARG001
    ui.show_tools()
