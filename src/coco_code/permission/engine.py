from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coco_code.permission import Category, Decision, Mode, parse_mode
from coco_code.permission.blacklist import _BLACKLIST, hits_blacklist
from coco_code.permission.rule import RuleSet
from coco_code.permission.sandbox import resolve_root, sandbox_ok
from coco_code.permission.settings import (
    Settings,
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)

if TYPE_CHECKING:
    from coco_code.tools.base import ToolCall, ToolSpec


@dataclass
class Engine:
    root: str
    blacklist: tuple[re.Pattern[str], ...] = _BLACKLIST
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: str = ""
    start_mode: Mode = Mode.DEFAULT

    def check(
        self,
        mode: Mode,
        call: ToolCall,
        spec_or_read_only: ToolSpec | bool,
    ) -> tuple[Decision, str]:
        read_only = _read_only(spec_or_read_only)
        friendly = friendly_name(call.name)
        category = categorize(call.name, read_only)
        target, is_file, ok = extract_target(call)

        if friendly == "Bash" and target and hits_blacklist(target):
            return Decision.DENY, f"Blocked by dangerous command blacklist: {target}"

        if is_file:
            if not ok:
                return Decision.DENY, "Cannot parse file path argument; blocked for safety."
            if not sandbox_ok(self, target):
                return Decision.DENY, f"Path is outside the project directory: {target}"

        for layer_name, rule_set in (
            ("local", self.local),
            ("project", self.project),
            ("user", self.user),
        ):
            decision, matched, rule = rule_set.find_match(friendly, target)
            if matched:
                if decision == Decision.DENY:
                    return (
                        decision,
                        f"Matched {layer_name} deny rule: {rule.text() if rule else ''}",
                    )
                return decision, ""

        decision = mode_fallback(mode, category)
        if decision == Decision.ASK:
            return (
                decision,
                f"{mode} mode requires approval for {category.name.lower()} operations.",
            )
        return decision, ""

    def persist_local_allow(self, call: ToolCall) -> None:
        from coco_code.permission.persist import persist_local_allow

        persist_local_allow(self, call)


def new_engine(root: str | Path) -> tuple[Engine, Exception | None]:
    try:
        resolved_root = resolve_root(root)
    except Exception as exc:
        fallback_root = str(root)
        fallback_local_path = str(Path(fallback_root) / ".coco-code" / "settings.local.yaml")
        return Engine(root=fallback_root, local_path=fallback_local_path), exc

    user_settings = _load_layer(Path.home() / ".coco-code" / "settings.yaml")
    project_settings = _load_layer(resolved_root / ".coco-code" / "settings.yaml")
    local_path = resolved_root / ".coco-code" / "settings.local.yaml"
    local_settings = _load_layer(local_path)
    start = _start_mode_from(local_settings, project_settings, user_settings)

    return (
        Engine(
            root=str(resolved_root),
            user=to_rule_set(user_settings),
            project=to_rule_set(project_settings),
            local=to_rule_set(local_settings),
            local_path=str(local_path),
            start_mode=start,
        ),
        None,
    )


def check(
    engine: Engine,
    mode: Mode,
    call: ToolCall,
    spec_or_read_only: ToolSpec | bool,
) -> tuple[Decision, str]:
    return engine.check(mode, call, spec_or_read_only)


def start_mode(engine: Engine) -> Mode:
    return engine.start_mode


def mode_fallback(mode: Mode, category: Category) -> Decision:
    if category == Category.READ or mode == Mode.BYPASS:
        return Decision.ALLOW
    if mode == Mode.ACCEPT_EDITS and category == Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def _load_layer(path: Path) -> Settings:
    try:
        return load_settings(path)
    except SettingsError:
        return Settings()


def _start_mode_from(local: Settings, project: Settings, user: Settings) -> Mode:
    for settings in (local, project, user):
        mode, ok = parse_mode(settings.default_mode)
        if ok:
            return mode
    return Mode.DEFAULT


def _read_only(spec_or_read_only: Any) -> bool:
    if isinstance(spec_or_read_only, bool):
        return spec_or_read_only
    return bool(getattr(spec_or_read_only, "read_only", False))
