from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from coco_code.permission import Mode as PermissionMode
from coco_code.permission import parse_mode
from coco_code.subagent.definition import Definition, Source

UTF8_BOM = "\ufeff"
AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")
VALID_MODELS = {"inherit", "haiku", "sonnet", "opus"}
VALID_ISOLATION = {"", "worktree"}


class SubagentParseError(ValueError):
    pass


def parse_frontmatter_and_body(raw: str) -> tuple[dict[str, Any], str]:
    raw = raw.lstrip(UTF8_BOM)
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SubagentParseError("SubAgent file must start with YAML frontmatter delimiter '---'.")
    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise SubagentParseError("SubAgent frontmatter is missing closing '---' delimiter.")

    frontmatter = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1 :])
    try:
        loaded = yaml.safe_load(frontmatter) if frontmatter.strip() else {}
    except yaml.YAMLError as exc:
        raise SubagentParseError(f"Invalid SubAgent frontmatter YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SubagentParseError("SubAgent frontmatter must be a YAML mapping.")
    return loaded, body


def parse_definition(data: bytes, file_path: str, source: Source) -> Definition:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubagentParseError(f"SubAgent file must be UTF-8: {exc}") from exc
    frontmatter, body = parse_frontmatter_and_body(raw)
    return validate_meta(frontmatter, body, file_path, source)


def parse_file(path: str | Path, source: Source) -> Definition:
    resolved = Path(path)
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise SubagentParseError(f"Unable to read SubAgent file: {exc}") from exc
    return parse_definition(data, str(resolved), source)


def validate_meta(
    frontmatter: dict[str, Any],
    body: str,
    file_path: str,
    source: Source,
) -> Definition:
    name = _required_text(frontmatter, "name")
    if not AGENT_NAME_REGEX.fullmatch(name):
        raise SubagentParseError(
            "SubAgent name must match ^[A-Za-z][A-Za-z0-9\\-_]{0,31}$."
        )
    description = _required_text(frontmatter, "description")
    model = _model(frontmatter.get("model"), file_path)
    permission_mode, dont_ask = _permission_mode(frontmatter.get("permissionMode"), file_path)
    isolation = _isolation(frontmatter.get("isolation"), file_path)
    return Definition(
        name=name,
        description=description,
        tools=_string_list(frontmatter.get("tools"), "tools", file_path),
        disallowed_tools=_string_list(
            frontmatter.get("disallowedTools"), "disallowedTools", file_path
        ),
        model=model,
        max_turns=_non_negative_int(frontmatter.get("maxTurns"), "maxTurns", file_path),
        permission_mode=permission_mode,
        dont_ask=dont_ask,
        background=bool(frontmatter.get("background") or False),
        isolation=isolation,
        system_prompt=body,
        file_path=file_path,
        source=source,
        metadata=dict(frontmatter),
    )


def _required_text(frontmatter: dict[str, Any], field: str) -> str:
    value = frontmatter.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SubagentParseError(f"SubAgent frontmatter requires string field '{field}'.")
    return value.strip()


def _string_list(raw: Any, field: str, file_path: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        _warn(file_path, f"field {field!r} must be a list of strings; defaulting to empty")
        return ()
    values: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            values.append(item.strip())
        else:
            _warn(file_path, f"field {field!r} contains a non-string item; dropped")
    return tuple(values)


def _model(raw: Any, file_path: str) -> str:
    if raw is None or raw == "":
        return "inherit"
    if not isinstance(raw, str):
        _warn(file_path, f"unknown model {raw!r}; defaulting to inherit")
        return "inherit"
    value = raw.strip()
    normalized = value.casefold()
    if normalized in VALID_MODELS:
        return normalized
    _warn(file_path, f"unknown model {value!r}; defaulting to inherit")
    return "inherit"

def _isolation(raw: Any, file_path: str) -> str:
    if raw is None or raw == "":
        return ""
    if not isinstance(raw, str):
        _warn(file_path, f"unknown isolation {raw!r}; defaulting to none")
        return ""
    value = raw.strip().casefold()
    if value in VALID_ISOLATION:
        return value
    _warn(file_path, f"unknown isolation {raw!r}; defaulting to none")
    return ""

def _permission_mode(raw: Any, file_path: str) -> tuple[PermissionMode, bool]:
    if raw is None or raw == "":
        return PermissionMode.DEFAULT, False
    if not isinstance(raw, str):
        _warn(file_path, f"unknown permissionMode {raw!r}; defaulting to default")
        return PermissionMode.DEFAULT, False
    value = raw.strip()
    if value == "dontAsk":
        return PermissionMode.DEFAULT, True
    mode, ok = parse_mode(value)
    if ok:
        return mode, False
    _warn(file_path, f"unknown permissionMode {value!r}; defaulting to default")
    return PermissionMode.DEFAULT, False


def _non_negative_int(raw: Any, field: str, file_path: str) -> int:
    if raw is None or raw == "":
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int):
        _warn(file_path, f"field {field!r} must be a non-negative integer; defaulting to 0")
        return 0
    if raw < 0:
        _warn(file_path, f"field {field!r} must be a non-negative integer; defaulting to 0")
        return 0
    return raw


def _warn(file_path: str, message: str) -> None:
    print(f"[subagent] warn: {file_path}: {message}", file=sys.stderr)
