from __future__ import annotations

import re

_SLUG_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_SLUG_LENGTH = 64


def validate_slug(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError("worktree 名称不能为空")
    if len(name) > MAX_SLUG_LENGTH:
        raise ValueError(f"worktree 名称不能超过 {MAX_SLUG_LENGTH} 个字符")
    if name.startswith("/") or name.endswith("/"):
        raise ValueError("worktree 名称不能以 / 开头或结尾")
    if "//" in name:
        raise ValueError("worktree 名称不能包含连续的 /")
    for segment in name.split("/"):
        if segment in {".", ".."}:
            raise ValueError("worktree 名称不能包含 . 或 .. 段")
        if not _SLUG_SEGMENT.fullmatch(segment):
            raise ValueError("worktree 名称只能包含字母、数字、点、下划线、连字符和斜杠")


def flat_slug(name: str) -> str:
    return name.replace("/", "+")
