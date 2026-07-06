from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable

from coco_code.command.registry import CommandRegistry
from coco_code.command.types import Command, CommandContext, CommandKind, CommandUI
from coco_code.skills.catalog import SkillCatalog
from coco_code.skills.executor import SkillExecutor
from coco_code.skills.types import Skill

SKILL_COMMAND_MARKER = "[skill]"
RESERVED_COMMANDS = frozenset(
    {
        "help",
        "h",
        "?",
        "clear",
        "compact",
        "c",
        "plan",
        "do",
        "session",
        "memory",
        "mem",
        "permission",
        "perm",
        "status",
        "s",
        "skill",
        "exit",
        "resume",
        "tools",
    }
)

ReloadCallback = Callable[[], Awaitable[None] | None]


def register_skill_commands(
    registry: CommandRegistry,
    catalog: SkillCatalog,
    executor: SkillExecutor,
) -> None:
    remove_skill_commands(registry)
    for skill in catalog.list():
        _reject_reserved(skill)
        registry.register(_skill_command(skill, executor))


def remove_skill_commands(registry: CommandRegistry) -> None:
    registry.remove_where(lambda command: command.description.startswith(SKILL_COMMAND_MARKER))


def register_skill_management_command(
    registry: CommandRegistry,
    catalog: SkillCatalog,
    reload_callback: ReloadCallback,
) -> None:
    if registry.lookup("skill") is not None:
        return

    async def handle_skill(context: CommandContext, ui: CommandUI) -> None:
        args = context.args.strip()
        if not args or args == "list":
            ui.show_message(_skill_list(catalog))
            return
        verb, _, rest = args.partition(" ")
        if verb == "info":
            name = rest.strip()
            if not name:
                ui.show_error("Usage: /skill info <name>")
                return
            skill = catalog.get_latest(name)
            if skill is None:
                ui.show_error(f"Unknown Skill: {name}")
                return
            ui.show_message(_skill_info(skill))
            return
        if verb == "active":
            active = ui.list_active_skills()
            ui.show_message("Active Skills: " + (", ".join(active) if active else "none"))
            return
        if verb == "reload":
            maybe_awaitable = reload_callback()
            if isawaitable(maybe_awaitable):
                await maybe_awaitable
            ui.show_message("Reloaded Skills.")
            return
        ui.show_error("Usage: /skill list | info <name> | active | reload")

    registry.register(
        Command(
            name="skill",
            description="Manage Skills.",
            usage="/skill list | info <name> | active | reload",
            argument_hint="list, info <name>, active, or reload.",
            kind=CommandKind.LOCAL,
            handler=handle_skill,
        )
    )


def _skill_command(skill: Skill, executor: SkillExecutor) -> Command:
    async def handle_skill_command(context: CommandContext, ui: CommandUI) -> None:
        await executor.execute_command(skill.meta.name, context.args, ui)

    return Command(
        name=skill.meta.name,
        description=f"{SKILL_COMMAND_MARKER} {skill.meta.description}",
        usage=f"/{skill.meta.name} [args]",
        argument_hint="Optional Skill arguments.",
        kind=CommandKind.PROMPT,
        handler=handle_skill_command,
    )


def _reject_reserved(skill: Skill) -> None:
    name = skill.meta.name.casefold()
    if name in RESERVED_COMMANDS:
        raise RuntimeError(
            f"Skill '{skill.meta.name}' conflicts with reserved slash command '/{name}'."
        )


def _skill_list(catalog: SkillCatalog) -> str:
    skills = catalog.list()
    if not skills:
        return "No Skills loaded."
    width = max(len(skill.meta.name) for skill in skills)
    lines = ["Skills:"]
    for skill in skills:
        lines.append(
            f"/{skill.meta.name.ljust(width)}  {skill.meta.description} "
            f"[{skill.meta.mode.value}, {skill.source.value}]"
        )
    return "\n".join(lines)


def _skill_info(skill: Skill) -> str:
    allowed = ", ".join(skill.meta.allowed_tools) if skill.meta.allowed_tools else "all tools"
    lines = [
        f"Skill: {skill.meta.name}",
        f"Description: {skill.meta.description}",
        f"Mode: {skill.meta.mode.value}",
        f"Context: {skill.meta.context.value}",
        f"Source: {skill.source.value}",
        f"Entry: {skill.entry_path}",
        f"Allowed tools: {allowed}",
    ]
    if skill.meta.model:
        lines.append(f"Model: {skill.meta.model}")
    return "\n".join(lines)
