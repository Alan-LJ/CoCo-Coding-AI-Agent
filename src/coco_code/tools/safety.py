from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".codeagent",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)

SENSITIVE_KEY_PARTS = ("api_key", "apikey", "token", "secret", "password", "passwd")


class ToolSafetyError(ValueError):
    pass


def resolve_workspace_path(workspace: Path, path: str | Path) -> Path:
    if str(path).strip() == "":
        raise ToolSafetyError("路径不能为空。")
    workspace_root = workspace.resolve(strict=False)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ToolSafetyError(f"路径越界：{path}") from exc
    return resolved


def ensure_text_file(path: Path) -> str:
    if not path.exists():
        raise ToolSafetyError(f"文件不存在：{path}")
    if path.is_dir():
        raise ToolSafetyError(f"目标是目录，不是文件：{path}")
    data = path.read_bytes()
    if b"\x00" in data:
        raise ToolSafetyError(f"拒绝读取二进制文件：{path}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolSafetyError(f"文件不是可解码的 UTF-8 文本：{path}") from exc


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", bool(text)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def summarize_params(params: dict[str, Any], max_value_chars: int = 160) -> str:
    safe: dict[str, Any] = {}
    for key, value in params.items():
        lowered = key.lower()
        if any(part in lowered for part in SENSITIVE_KEY_PARTS):
            safe[key] = "<redacted>"
            continue
        if isinstance(value, str) and len(value) > max_value_chars:
            safe[key] = f"{value[:max_value_chars]}... ({len(value)} chars)"
        else:
            safe[key] = value
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)


def is_ignored_path(
    path: Path,
    workspace: Path,
    ignored_dirs: Iterable[str] = IGNORED_DIRS,
) -> bool:
    workspace_root = workspace.resolve(strict=False)
    try:
        relative = path.resolve(strict=False).relative_to(workspace_root)
    except ValueError:
        return True
    return any(part in ignored_dirs for part in relative.parts)


def has_parent_traversal(pattern: str) -> bool:
    parts = Path(pattern).parts
    return any(part == ".." for part in parts)
