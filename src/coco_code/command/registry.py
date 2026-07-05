from __future__ import annotations

from dataclasses import replace

from coco_code.command.types import Command


class CommandRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, command: Command) -> None:
        normalized = _normalize_command(command)
        keys = (normalized.name, *normalized.aliases)
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                raise RuntimeError(f"command conflict: {key}")
            if key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")
            seen.add(key)
        for key in keys:
            self._by_name[key] = normalized
        if not normalized.hidden:
            self._visible.append(normalized)
            self._visible.sort(key=lambda item: item.name)

    def lookup(self, name: str) -> Command | None:
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        return list(self._visible)

    def complete(self, prefix: str) -> list[Command]:
        normalized = prefix.strip()
        if normalized.startswith("/"):
            normalized = normalized[1:]
        normalized = normalized.lower()
        matches: list[Command] = []
        seen: set[str] = set()
        for command in self._visible:
            names = (command.name, *command.aliases)
            if any(name.startswith(normalized) for name in names) and command.name not in seen:
                matches.append(command)
                seen.add(command.name)
        return matches


def _normalize_command(command: Command) -> Command:
    name = command.name.strip().lower()
    aliases = tuple(alias.strip().lower() for alias in command.aliases)
    if not name:
        raise RuntimeError("command name cannot be empty")
    if any(not alias for alias in aliases):
        raise RuntimeError(f"command alias cannot be empty: {name}")
    return replace(command, name=name, aliases=aliases)
