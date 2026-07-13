from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from coco_code.permission import Mode as PermissionMode


class Source(IntEnum):
    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3

    def __str__(self) -> str:
        return {
            Source.BUILTIN: "builtin",
            Source.USER: "user",
            Source.PROJECT: "project",
            Source.PLUGIN: "plugin",
        }.get(self, "unknown")

    @property
    def priority(self) -> int:
        return {
            Source.PLUGIN: 0,
            Source.BUILTIN: 1,
            Source.USER: 2,
            Source.PROJECT: 3,
        }[self]


@dataclass(frozen=True)
class Definition:
    """SubAgent role definition loaded from Markdown frontmatter and body."""

    name: str
    description: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    model: str = "inherit"
    max_turns: int = 0
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    dont_ask: bool = False
    background: bool = False
    isolation: str = ""
    system_prompt: str = ""
    file_path: str = ""
    source: Source = Source.BUILTIN
    metadata: dict[str, object] = field(default_factory=dict)

    def is_fork(self) -> bool:
        return self.name == "__fork__"

    @property
    def path(self) -> Path | None:
        if not self.file_path or self.file_path.startswith("builtin:"):
            return None
        return Path(self.file_path)
