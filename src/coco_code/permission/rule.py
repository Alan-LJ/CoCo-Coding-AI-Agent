from __future__ import annotations

import re
from dataclasses import dataclass, field

from coco_code.permission import Decision


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str
    allow: bool

    def text(self) -> str:
        return self.tool if self.pattern == "" else f"{self.tool}({self.pattern})"


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        decision, matched, _rule = self.find_match(friendly, target)
        return decision, matched

    def find_match(self, friendly: str, target: str) -> tuple[Decision, bool, Rule | None]:
        for rule in self.deny:
            if _tool_matches(rule.tool, friendly) and match_pattern(rule.pattern, target):
                return Decision.DENY, True, rule
        for rule in self.allow:
            if _tool_matches(rule.tool, friendly) and match_pattern(rule.pattern, target):
                return Decision.ALLOW, True, rule
        return Decision.ALLOW, False, None


def parse_rule(value: str) -> tuple[Rule, bool]:
    text = value.strip()
    if not text:
        return Rule("", "", False), False
    if "(" not in text and ")" not in text:
        return Rule(text, "", True), True
    if "(" not in text or not text.endswith(")"):
        return Rule("", "", False), False
    tool, pattern = text.split("(", 1)
    tool = tool.strip()
    pattern = pattern[:-1]
    if not tool or "(" in pattern:
        return Rule("", "", False), False
    return Rule(tool, pattern.strip(), True), True


def match_pattern(pattern: str, target: str) -> bool:
    if pattern == "":
        return True
    normalized_pattern = _normalize_pathish(pattern)
    normalized_target = _normalize_pathish(target)
    path_like = "/" in normalized_pattern or "/" in normalized_target
    regex = (
        _path_glob_to_regex(normalized_pattern) if path_like else _command_glob_to_regex(pattern)
    )
    candidate = normalized_target if path_like else target
    return re.fullmatch(regex, candidate) is not None


def escape_glob(value: str) -> str:
    escaped: list[str] = []
    for char in value:
        if char in {"*", "?", "[", "]", "\\"}:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def _tool_matches(pattern: str, value: str) -> bool:
    normalized_pattern = pattern.strip()
    normalized_value = value.strip()
    if any(char in normalized_pattern for char in "*?"):
        return (
            re.fullmatch(
                _command_glob_to_regex(normalized_pattern),
                normalized_value,
                flags=re.IGNORECASE,
            )
            is not None
        )
    return normalized_pattern.casefold() == normalized_value.casefold()


def _normalize_pathish(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _command_glob_to_regex(pattern: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            parts.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "*":
            while index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
        index += 1
    return "".join(parts)


def _path_glob_to_regex(pattern: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            parts.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                parts.append(".*")
                index += 2
                continue
            parts.append("[^/]*")
        elif char == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(char))
        index += 1
    return "".join(parts)
