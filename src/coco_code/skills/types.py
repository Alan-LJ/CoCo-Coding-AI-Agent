from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SkillMode(StrEnum):
    INLINE = "inline"
    FORK = "fork"


class SkillContext(StrEnum):
    NONE = "none"
    RECENT = "recent"
    FULL = "full"


class SkillSource(StrEnum):
    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    allowed_tools: tuple[str, ...] = ()
    mode: SkillMode = SkillMode.INLINE
    context: SkillContext = SkillContext.NONE
    model: str | None = None


@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    prompt_body: str
    entry_path: Path
    package_dir: Path
    source: SkillSource
    is_directory: bool


@dataclass(frozen=True)
class SkillCatalogItem:
    name: str
    description: str
    source: SkillSource
    mode: SkillMode
    entry_path: Path


@dataclass(frozen=True)
class SkillValidationIssue:
    skill_name: str
    tool_name: str
    message: str
