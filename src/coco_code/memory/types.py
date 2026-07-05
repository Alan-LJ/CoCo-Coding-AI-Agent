from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal


class NoteType(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


class MemoryLevel(StrEnum):
    PROJECT = "project"
    USER = "user"


@dataclass(frozen=True)
class MemoryNote:
    level: MemoryLevel
    type: NoteType
    title: str
    slug: str
    content: str
    path: Path
    created: datetime
    updated: datetime


@dataclass(frozen=True)
class MemoryAction:
    action: Literal["create", "update", "delete"]
    level: MemoryLevel
    type: NoteType | None = None
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""
