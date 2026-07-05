from __future__ import annotations

import pytest

from coco_code.command import Command, CommandContext, CommandKind, CommandRegistry, CommandUI


async def noop(context: CommandContext, ui: CommandUI) -> None:
    return None


def command(name: str, *aliases: str, hidden: bool = False) -> Command:
    return Command(
        name=name,
        aliases=aliases,
        description=f"{name} command",
        usage=f"/{name}",
        kind=CommandKind.LOCAL,
        handler=noop,
        hidden=hidden,
    )


def test_register_lookup_and_alias() -> None:
    registry = CommandRegistry()
    registry.register(command("Help", "H"))
    assert registry.lookup("help") is not None
    assert registry.lookup("HELP") is registry.lookup("h")


def test_duplicate_name_raises() -> None:
    registry = CommandRegistry()
    registry.register(command("help"))
    with pytest.raises(RuntimeError, match="help"):
        registry.register(command("HELP"))


def test_duplicate_alias_raises() -> None:
    registry = CommandRegistry()
    registry.register(command("help", "h"))
    with pytest.raises(RuntimeError, match="h"):
        registry.register(command("history", "h"))


def test_visible_sorted_and_hidden_excluded() -> None:
    registry = CommandRegistry()
    registry.register(command("status"))
    registry.register(command("help"))
    registry.register(command("secret", hidden=True))
    assert [item.name for item in registry.visible()] == ["help", "status"]


def test_complete_matches_names_and_aliases_without_hidden() -> None:
    registry = CommandRegistry()
    registry.register(command("status", "s"))
    registry.register(command("session"))
    registry.register(command("secret", "sec", hidden=True))
    assert [item.name for item in registry.complete("/s")] == ["session", "status"]
