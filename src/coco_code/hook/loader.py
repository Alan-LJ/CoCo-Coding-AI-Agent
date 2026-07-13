from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, TextIO

import yaml

from coco_code.hook.engine import HookEngine
from coco_code.hook.event import is_blocking, parse_event
from coco_code.hook.rule import (
    AtomCondition,
    Condition,
    HookAction,
    HookRule,
    HttpAction,
    PromptAction,
    ShellAction,
    SubagentAction,
)
from coco_code.permission.matcher import compile_structured_matcher

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smh]?)$")


def default_hook_paths(project_root: Path, home: Path | None = None) -> tuple[Path, Path]:
    home_path = home or Path.home()
    return (
        project_root / ".coco-code" / "hooks.yaml",
        home_path / ".coco-code" / "hooks.yaml",
    )


def load_hooks(
    project_root: Path,
    *,
    home: Path | None = None,
    stderr: TextIO | None = None,
) -> HookEngine:
    stderr = stderr or sys.stderr
    rules: list[HookRule] = []
    sources: list[Path] = []
    names: set[str] = set()
    for path in default_hook_paths(project_root, home):
        if not path.exists():
            continue
        sources.append(path)
        raw = _read_yaml(path, stderr)
        if raw is None:
            continue
        hooks = raw.get("hooks") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or not isinstance(hooks, list):
            print(f"hooks file {path}: top-level hooks must be a list, skipped", file=stderr)
            continue
        for index, item in enumerate(hooks):
            rule = _compile_rule(path, index, item, stderr)
            if rule is None:
                continue
            if rule.name in names:
                print(f'hook "{rule.name}": duplicate name, skipped', file=stderr)
                continue
            names.add(rule.name)
            rules.append(rule)
    return HookEngine(rules, sources)


def _read_yaml(path: Path, stderr: TextIO) -> dict[str, Any] | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"hooks file {path}: invalid YAML: {exc}", file=stderr)
        return None
    except OSError as exc:
        print(f"hooks file {path}: cannot read: {exc}", file=stderr)
        return None
    if raw is None:
        return {"hooks": []}
    if not isinstance(raw, dict):
        return None
    return raw


def _compile_rule(path: Path, index: int, raw: Any, stderr: TextIO) -> HookRule | None:
    source = f"{path}:{index + 1}"
    if not isinstance(raw, dict):
        print(f"hook {source}: rule must be a mapping, skipped", file=stderr)
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        print(f"hook {source}: name is required, skipped", file=stderr)
        return None
    name = name.strip()
    event_raw = raw.get("event")
    if not isinstance(event_raw, str):
        print(f'hook "{name}": event is required, skipped', file=stderr)
        return None
    event = parse_event(event_raw)
    if event is None:
        print(f'hook "{name}": unknown event "{event_raw}", skipped', file=stderr)
        return None
    async_mode = bool(raw.get("async", False))
    if async_mode and is_blocking(event):
        print(f'hook "{name}": async not allowed for blocking events, skipped', file=stderr)
        return None
    try:
        timeout_seconds = _parse_duration(raw.get("timeout", 30.0))
        condition = _compile_condition(raw.get("if"))
        action = _compile_action(name, raw.get("action"))
    except ValueError as exc:
        print(f'hook "{name}": {exc}, skipped', file=stderr)
        return None
    return HookRule(
        name=name,
        event=event,
        action=action,
        condition=condition,
        only_once=bool(raw.get("only_once", False)),
        async_mode=async_mode,
        timeout_seconds=timeout_seconds,
        source=str(path),
        index=index,
    )


def _compile_condition(raw: Any) -> Condition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("if must be a mapping")
    has_all = "all_of" in raw
    has_any = "any_of" in raw
    if has_all == has_any:
        raise ValueError("if must contain exactly one of all_of or any_of")
    mode = "all_of" if has_all else "any_of"
    atoms_raw = raw[mode]
    if not isinstance(atoms_raw, list):
        raise ValueError(f"{mode} must be a list")
    atoms: list[AtomCondition] = []
    for atom_raw in atoms_raw:
        if not isinstance(atom_raw, dict):
            raise ValueError("condition atom must be a mapping")
        field = atom_raw.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError("condition atom requires field")
        if "match" not in atom_raw:
            raise ValueError("condition atom requires match")
        matcher = compile_structured_matcher(atom_raw["match"], path_like=None)
        atoms.append(AtomCondition(field=field, matcher=matcher))
    return Condition(mode=mode, atoms=tuple(atoms))


def _compile_action(name: str, raw: Any) -> HookAction:
    if not isinstance(raw, dict):
        raise ValueError("action is required")
    action_type = raw.get("type")
    if action_type == "shell":
        command = raw.get("command")
        if not isinstance(command, str) or not command:
            raise ValueError("shell action requires command")
        return HookAction(type="shell", value=ShellAction(command=command))
    if action_type == "prompt":
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("prompt action requires text")
        return HookAction(type="prompt", value=PromptAction(text=text))
    if action_type == "http":
        url = raw.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("http action requires url")
        method = raw.get("method", "POST")
        if not isinstance(method, str) or not method:
            raise ValueError("http action method must be a string")
        headers_raw = raw.get("headers", {})
        if headers_raw is None:
            headers_raw = {}
        if not isinstance(headers_raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers_raw.items()
        ):
            raise ValueError("http action headers must be string pairs")
        body = raw.get("body")
        if body is not None and not isinstance(body, str):
            raise ValueError("http action body must be a string")
        return HookAction(
            type="http",
            value=HttpAction(url=url, method=method.upper(), headers=headers_raw, body=body),
        )
    if action_type == "subagent":
        agent_name = raw.get("agent_name")
        prompt = raw.get("prompt")
        if not isinstance(agent_name, str) or not agent_name:
            raise ValueError("subagent action requires agent_name")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("subagent action requires prompt")
        return HookAction(
            type="subagent",
            value=SubagentAction(agent_name=agent_name, prompt=prompt),
        )
    raise ValueError(f"unknown action type {action_type!r}")


def _parse_duration(raw: Any) -> float:
    if isinstance(raw, int | float):
        value = float(raw)
        if value <= 0:
            raise ValueError("timeout must be positive")
        return value
    if not isinstance(raw, str):
        raise ValueError("timeout must be a number or duration string")
    match = _DURATION_RE.match(raw.strip())
    if match is None:
        raise ValueError("invalid timeout")
    value = float(match.group(1))
    unit = match.group(2)
    multiplier = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
    seconds = value * multiplier
    if seconds <= 0:
        raise ValueError("timeout must be positive")
    return seconds
