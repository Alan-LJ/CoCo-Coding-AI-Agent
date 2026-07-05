from __future__ import annotations

# ruff: noqa: E402,I001

from enum import IntEnum


class Mode(IntEnum):
    DEFAULT = 0
    ACCEPT_EDITS = 1
    PLAN = 2
    BYPASS = 3

    def __str__(self) -> str:
        return {
            Mode.DEFAULT: "default",
            Mode.ACCEPT_EDITS: "acceptEdits",
            Mode.PLAN: "plan",
            Mode.BYPASS: "bypassPermissions",
        }[self]


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    DENY_ONCE = 0
    ALLOW_ONCE = 1
    ALLOW_FOREVER = 2


class ApprovalError(RuntimeError):
    pass


def parse_mode(value: str) -> tuple[Mode, bool]:
    normalized = "".join(ch for ch in value.strip().lower() if ch.isalnum())
    modes = {
        "default": Mode.DEFAULT,
        "acceptedits": Mode.ACCEPT_EDITS,
        "plan": Mode.PLAN,
        "bypass": Mode.BYPASS,
        "bypasspermissions": Mode.BYPASS,
    }
    mode = modes.get(normalized)
    if mode is None:
        return Mode.DEFAULT, False
    return mode, True


from coco_code.permission.engine import Engine, check, mode_fallback, new_engine, start_mode  # noqa: E402
from coco_code.permission.persist import persist_local_allow  # noqa: E402

__all__ = [
    "ApprovalError",
    "Category",
    "Decision",
    "Engine",
    "Mode",
    "Outcome",
    "check",
    "mode_fallback",
    "new_engine",
    "parse_mode",
    "persist_local_allow",
    "start_mode",
]
