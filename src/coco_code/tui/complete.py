from __future__ import annotations

from dataclasses import dataclass, field

from coco_code.command import Command, CommandRegistry

MAX_ROWS = 8


@dataclass
class CompletionMenu:
    items: list[Command] = field(default_factory=list)
    cursor: int = 0
    active: bool = False
    prefix: str = ""

    def update(self, input_text: str, registry: CommandRegistry) -> None:
        stripped = input_text.strip()
        if "\n" in input_text or not stripped.startswith("/") or " " in stripped:
            self.hide()
            return
        self.prefix = stripped
        self.items = registry.complete(stripped)
        self.active = bool(self.items)
        self.cursor = min(self.cursor, max(0, len(self.items) - 1))

    def single_completion(self) -> str | None:
        if len(self.items) == 1:
            return f"/{self.items[0].name} "
        return None

    def move_up(self) -> None:
        if not self.items:
            return
        self.cursor = (self.cursor - 1) % len(self.items)

    def move_down(self) -> None:
        if not self.items:
            return
        self.cursor = (self.cursor + 1) % len(self.items)

    def selected(self) -> Command | None:
        if not self.items:
            return None
        return self.items[self.cursor]

    def hide(self) -> None:
        self.items = []
        self.cursor = 0
        self.active = False
        self.prefix = ""

    def render(self, width: int = 80) -> str:
        if not self.active or not self.items:
            return ""
        start = max(0, min(self.cursor - MAX_ROWS + 1, len(self.items) - MAX_ROWS))
        end = min(len(self.items), start + MAX_ROWS)
        visible = self.items[start:end]
        name_width = max(len(item.name) for item in visible)
        lines: list[str] = []
        if start > 0:
            lines.append(f"... {start} more")
        for index, command in enumerate(visible, start=start):
            marker = ">" if index == self.cursor else " "
            line = f"{marker} /{command.name.ljust(name_width)}  {command.description}"
            lines.append(line[:width])
        if end < len(self.items):
            lines.append(f"... {len(self.items) - end} more")
        return "\n".join(lines)
