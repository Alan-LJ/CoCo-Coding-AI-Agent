from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from coco_code.command import CommandContext, build_default_registry, parse_command
from coco_code.command.skills import register_skill_commands, register_skill_management_command
from coco_code.skills.catalog import SkillCatalog


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def execute_command(self, name, args, ui):  # noqa: ARG002
        self.calls.append((name, args))


@dataclass
class SkillUI:
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    active: tuple[str, ...] = ()

    def show_message(self, text: str) -> None:
        self.messages.append(text)

    def show_error(self, text: str) -> None:
        self.errors.append(text)

    def list_active_skills(self) -> tuple[str, ...]:
        return self.active


def write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\nBody\n",
        encoding="utf-8",
    )


def make_catalog(tmp_path: Path) -> SkillCatalog:
    catalog = SkillCatalog(
        tmp_path,
        builtin_dir=tmp_path / "builtin",
        user_dir=tmp_path / "user",
        project_dir=tmp_path / "project",
    )
    catalog.reload()
    return catalog


def test_skill_commands_are_visible_and_dispatch_to_executor(tmp_path: Path) -> None:
    write_skill(tmp_path / "builtin", "review")
    catalog = make_catalog(tmp_path)
    registry = build_default_registry()
    executor = FakeExecutor()
    register_skill_commands(registry, catalog, executor)  # type: ignore[arg-type]
    command = registry.lookup("review")
    assert command is not None
    assert command.description.startswith("[skill]")
    asyncio.run(command.handler(CommandContext(parse_command("/review now")), SkillUI()))
    assert executor.calls == [("review", "now")]


def test_skill_management_list_info_active_and_reload(tmp_path: Path) -> None:
    write_skill(tmp_path / "builtin", "commit")
    catalog = make_catalog(tmp_path)
    registry = build_default_registry()
    reloaded = False

    def reload_callback() -> None:
        nonlocal reloaded
        reloaded = True

    register_skill_management_command(registry, catalog, reload_callback)
    command = registry.lookup("skill")
    assert command is not None
    ui = SkillUI(active=("commit",))
    asyncio.run(command.handler(CommandContext(parse_command("/skill list")), ui))
    assert "/commit" in ui.messages[-1]
    asyncio.run(command.handler(CommandContext(parse_command("/skill info commit")), ui))
    assert "Skill: commit" in ui.messages[-1]
    asyncio.run(command.handler(CommandContext(parse_command("/skill active")), ui))
    assert "commit" in ui.messages[-1]
    asyncio.run(command.handler(CommandContext(parse_command("/skill reload")), ui))
    assert reloaded is True


def test_reserved_skill_command_conflict_is_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path / "builtin", "clear")
    catalog = make_catalog(tmp_path)
    with pytest.raises(RuntimeError, match="reserved"):
        register_skill_commands(build_default_registry(), catalog, FakeExecutor())  # type: ignore[arg-type]


def test_default_registry_no_longer_has_hard_coded_review() -> None:
    registry = build_default_registry()
    assert registry.lookup("review") is None
