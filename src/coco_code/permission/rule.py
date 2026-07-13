from __future__ import annotations

import re
from dataclasses import dataclass, field

from coco_code.permission import Decision
from coco_code.permission.matcher import (
    Matcher,
    command_glob_to_regex,
    compile_matcher,
    match_glob,
    normalize_pathish,
    path_glob_to_regex,
)
from coco_code.permission.matcher import (
    escape_glob as escape_glob,
)


@dataclass(frozen=True, init=False)
class Rule:
    tool: str
    matcher: Matcher | None
    allow: bool
    raw_pattern: str = ""

    def __init__(
        self,
        tool: str,
        pattern: str | Matcher | None = "",
        allow: bool = True,
        *,
        matcher: Matcher | None = None,
        raw_pattern: str | None = None,
    ) -> None:
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "allow", allow)
        if matcher is not None:
            object.__setattr__(self, "matcher", matcher)
            object.__setattr__(self, "raw_pattern", raw_pattern or "")
            return
        if pattern is None:
            object.__setattr__(self, "matcher", None)
            object.__setattr__(self, "raw_pattern", raw_pattern or "")
            return
        if not isinstance(pattern, str):
            object.__setattr__(self, "matcher", pattern)
            object.__setattr__(self, "raw_pattern", raw_pattern or str(pattern))
            return
        raw = raw_pattern if raw_pattern is not None else pattern
        object.__setattr__(self, "raw_pattern", raw)
        object.__setattr__(
            self,
            "matcher",
            None if pattern == "" else compile_matcher(pattern, path_like=_path_like_tool(tool)),
        )

    @property
    def pattern(self) -> str:
        return self.raw_pattern

    def text(self) -> str:
        return self.tool if self.raw_pattern == "" else f"{self.tool}({self.raw_pattern})"


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        decision, matched, _rule = self.find_match(friendly, target)
        return decision, matched

    def find_match(self, friendly: str, target: str) -> tuple[Decision, bool, Rule | None]:
        for rule in self.deny:
            if _tool_matches(rule.tool, friendly) and match_rule(rule, target):
                return Decision.DENY, True, rule
        for rule in self.allow:
            if _tool_matches(rule.tool, friendly) and match_rule(rule, target):
                return Decision.ALLOW, True, rule
        return Decision.ALLOW, False, None


def parse_rule(value: str) -> tuple[Rule | None, str | None]:
    text = value.strip()
    if not text:
        return None, "empty rule"
    if "(" not in text and ")" not in text:
        return Rule(text, "", True), None
    if "(" not in text or not text.endswith(")"):
        return None, "rule must be Tool(pattern) or Tool"
    tool, pattern = text.split("(", 1)
    tool = tool.strip()
    raw_pattern = pattern[:-1].strip()
    if not tool:
        return None, "missing tool name"
    if raw_pattern == "":
        return Rule(tool, "", True), None
    try:
        matcher = compile_matcher(raw_pattern, path_like=_path_like_tool(tool))
    except ValueError as exc:
        return None, str(exc)
    return Rule(tool, allow=True, matcher=matcher, raw_pattern=raw_pattern), None


def match_rule(rule: Rule, target: str) -> bool:
    if rule.matcher is None:
        return True
    return rule.matcher.match(target)


def match_pattern(pattern: str, target: str) -> bool:
    if pattern == "":
        return True
    try:
        return compile_matcher(pattern, path_like=None).match(target)
    except ValueError:
        return match_glob(pattern, target, path_like=None)


def _tool_matches(pattern: str, value: str) -> bool:
    normalized_pattern = pattern.strip()
    normalized_value = value.strip()
    if any(char in normalized_pattern for char in "*?"):
        return (
            re.fullmatch(
                command_glob_to_regex(normalized_pattern),
                normalized_value,
                flags=re.IGNORECASE,
            )
            is not None
        )
    return normalized_pattern.casefold() == normalized_value.casefold()


def _normalize_pathish(value: str) -> str:
    return normalize_pathish(value)


def _command_glob_to_regex(pattern: str) -> str:
    return command_glob_to_regex(pattern)


def _path_glob_to_regex(pattern: str) -> str:
    return path_glob_to_regex(pattern)


def _path_like_tool(tool: str) -> bool | None:
    normalized = "".join(ch for ch in tool.casefold() if ch.isalnum())
    if normalized in {
        "read",
        "readfile",
        "readfiletool",
        "write",
        "writefile",
        "writefiletool",
        "edit",
        "editfile",
        "editfiletool",
        "glob",
        "globfiles",
        "globfilestool",
        "grep",
        "searchcode",
        "searchcodetool",
    }:
        return True
    if normalized in {"bash", "runcommand"}:
        return False
    return None
