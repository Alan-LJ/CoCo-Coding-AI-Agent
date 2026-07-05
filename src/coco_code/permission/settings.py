from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from coco_code.permission import Category
from coco_code.permission.rule import Rule, RuleSet, parse_rule

if TYPE_CHECKING:
    from coco_code.tools.base import ToolCall


class SettingsError(ValueError):
    pass


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


def load_settings(path: str | Path) -> Settings:
    settings_path = Path(path).expanduser()
    if not settings_path.exists():
        return Settings()
    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsError(f"Invalid permission YAML in {settings_path}: {exc}") from exc
    except OSError as exc:
        raise SettingsError(f"Cannot read permission settings {settings_path}: {exc}") from exc
    if raw is None:
        return Settings()
    if not isinstance(raw, dict):
        raise SettingsError(f"Permission settings {settings_path} must be a mapping")
    return _parse_settings(raw, settings_path)


def to_rule_set(settings: Settings) -> RuleSet:
    rule_set = RuleSet()
    for text in settings.permissions.allow:
        rule, ok = parse_rule(text)
        if ok:
            rule_set.allow.append(Rule(friendly_name(rule.tool), rule.pattern, True))
    for text in settings.permissions.deny:
        rule, ok = parse_rule(text)
        if ok:
            rule_set.deny.append(Rule(friendly_name(rule.tool), rule.pattern, False))
    return rule_set


def friendly_name(internal: str) -> str:
    normalized = "".join(ch for ch in internal.casefold() if ch.isalnum())
    mapping = {
        "bash": "Bash",
        "runcommand": "Bash",
        "read": "Read",
        "readfile": "Read",
        "readfiletool": "Read",
        "write": "Write",
        "writefile": "Write",
        "writefiletool": "Write",
        "edit": "Edit",
        "editfile": "Edit",
        "editfiletool": "Edit",
        "glob": "Glob",
        "globfiles": "Glob",
        "globfilestool": "Glob",
        "grep": "Grep",
        "searchcode": "Grep",
        "searchcodetool": "Grep",
    }
    return mapping.get(normalized, internal)


def categorize(internal: str, read_only: bool) -> Category:
    if read_only:
        return Category.READ
    friendly = friendly_name(internal)
    if friendly in {"Write", "Edit"}:
        return Category.WRITE
    return Category.EXEC


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    args, ok = _extract_arguments(call)
    if not ok:
        return "", _looks_file_tool(call.name), False

    friendly = friendly_name(call.name)
    if friendly in {"Read", "Write", "Edit"}:
        path = args.get("path")
        return (path, True, True) if isinstance(path, str) and path.strip() else ("", True, False)
    if friendly == "Glob":
        target = args.get("path") or args.get("root") or args.get("pattern") or "."
        return (str(target), True, True) if isinstance(target, str) else ("", True, False)
    if friendly == "Grep":
        target = args.get("path") or args.get("root") or args.get("path_glob") or "."
        return (str(target), True, True) if isinstance(target, str) else ("", True, False)
    if friendly == "Bash":
        command = args.get("command")
        return (
            (command, False, True)
            if isinstance(command, str) and command.strip()
            else ("", False, False)
        )
    return "", False, False


def _parse_settings(raw: dict[str, Any], path: Path) -> Settings:
    default_mode = raw.get("default_mode", "")
    if default_mode is None:
        default_mode = ""
    if not isinstance(default_mode, str):
        raise SettingsError(f"permission settings {path}: default_mode must be a string")

    permissions_raw = raw.get("permissions", {})
    if permissions_raw is None:
        permissions_raw = {}
    if not isinstance(permissions_raw, dict):
        raise SettingsError(f"permission settings {path}: permissions must be a mapping")

    return Settings(
        default_mode=default_mode,
        permissions=PermissionsBlock(
            allow=_parse_string_list(permissions_raw.get("allow", []), path, "allow"),
            deny=_parse_string_list(permissions_raw.get("deny", []), path, "deny"),
        ),
    )


def _parse_string_list(raw: Any, path: Path, name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SettingsError(f"permission settings {path}: permissions.{name} must be a list")
    return [item for item in raw if isinstance(item, str) and item.strip()]


def _extract_arguments(call: ToolCall) -> tuple[dict[str, Any], bool]:
    arguments = getattr(call, "arguments", None)
    if isinstance(arguments, dict):
        return arguments, True

    raw = getattr(call, "input", None) or getattr(call, "raw_arguments", "")
    if isinstance(raw, dict):
        return raw, True
    if not isinstance(raw, str):
        return {}, False
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}, False
    return (decoded, True) if isinstance(decoded, dict) else ({}, False)


def _looks_file_tool(name: str) -> bool:
    return friendly_name(name) in {"Read", "Write", "Edit", "Glob", "Grep"}
