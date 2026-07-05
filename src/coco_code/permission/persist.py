from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from coco_code.permission.rule import Rule, escape_glob
from coco_code.permission.sandbox import eval_symlinks_or_ancestor
from coco_code.permission.settings import Settings, extract_target, friendly_name, load_settings

if TYPE_CHECKING:
    from coco_code.permission.engine import Engine
    from coco_code.tools.base import ToolCall


def rule_for(engine: Engine, call: ToolCall) -> tuple[Rule, str, bool]:
    friendly = friendly_name(call.name)
    target, is_file, ok = extract_target(call)
    if not ok or not friendly:
        return Rule("", "", True), "", False

    pattern = _relative_target(engine, target) if is_file else target
    pattern = escape_glob(pattern)
    rule = Rule(friendly, pattern, True)
    return rule, rule.text(), True


def persist_local_allow(engine: Engine, call: ToolCall) -> None:
    rule, text, ok = rule_for(engine, call)
    if not ok:
        raise ValueError("Cannot create a permission rule for this tool call")

    path = Path(engine.local_path)
    settings = load_settings(path)
    if text not in settings.permissions.allow:
        settings.permissions.allow.append(text)
    _write_settings(path, settings)
    if rule not in engine.local.allow:
        engine.local.allow.append(rule)


def _relative_target(engine: Engine, target: str) -> str:
    root = Path(engine.root).expanduser().resolve(strict=False)
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = eval_symlinks_or_ancestor(candidate)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return target.replace("\\", "/")
    return relative.as_posix() or "."


def _write_settings(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, object] = {}
    if settings.default_mode:
        raw["default_mode"] = settings.default_mode
    raw["permissions"] = {
        "allow": settings.permissions.allow,
        "deny": settings.permissions.deny,
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
