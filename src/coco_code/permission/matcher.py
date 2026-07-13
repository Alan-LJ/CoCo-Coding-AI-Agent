from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


class Matcher(Protocol):
    def match(self, value: str) -> bool: ...


@dataclass(frozen=True)
class ExactMatcher:
    value: str

    def match(self, value: str) -> bool:
        return value == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    pattern: str
    path_like: bool | None = None

    def match(self, value: str) -> bool:
        path_like = self.path_like
        normalized_pattern = normalize_pathish(self.pattern)
        normalized_value = normalize_pathish(value)
        if path_like is None:
            path_like = "/" in normalized_pattern or "/" in normalized_value
        regex = (
            path_glob_to_regex(normalized_pattern)
            if path_like
            else command_glob_to_regex(self.pattern)
        )
        candidate = normalized_value if path_like else value
        return re.fullmatch(regex, candidate) is not None

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    src: str
    compiled: re.Pattern[str]

    def match(self, value: str) -> bool:
        return self.compiled.search(value) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    inner: Matcher

    def match(self, value: str) -> bool:
        return not self.inner.match(value)

    def __str__(self) -> str:
        return f"!{self.inner}"


def compile_matcher(pattern: str, *, path_like: bool | None = False) -> Matcher:
    if pattern == "":
        raise ValueError("empty matcher pattern")
    prefix = pattern[0]
    rest = pattern[1:]
    if prefix == "=":
        return ExactMatcher(rest)
    if prefix == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as exc:
            raise ValueError(f"invalid regex {rest!r}: {exc}") from exc
    if prefix == "!":
        if not rest:
            raise ValueError("not matcher requires an inner pattern")
        return NotMatcher(compile_matcher(rest, path_like=path_like))
    return GlobMatcher(pattern, path_like)


def compile_structured_matcher(raw: Any, *, path_like: bool | None = False) -> Matcher:
    if not isinstance(raw, dict):
        raise ValueError("matcher must be a mapping")
    match_type = raw.get("type")
    if match_type == "not":
        if "inner" not in raw:
            raise ValueError("not matcher requires inner")
        return NotMatcher(compile_structured_matcher(raw["inner"], path_like=path_like))
    value = raw.get("value")
    if not isinstance(value, str):
        raise ValueError(f"{match_type or 'matcher'} matcher requires string value")
    if match_type == "exact":
        return ExactMatcher(value)
    if match_type == "glob":
        if value == "":
            raise ValueError("empty matcher pattern")
        return GlobMatcher(value, path_like)
    if match_type == "regex":
        try:
            return RegexMatcher(value, re.compile(value))
        except re.error as exc:
            raise ValueError(f"invalid regex {value!r}: {exc}") from exc
    raise ValueError(f"unknown matcher type {match_type!r}")


def match_glob(pattern: str, value: str, *, path_like: bool | None = None) -> bool:
    if pattern == "":
        return True
    return GlobMatcher(pattern, path_like).match(value)


def escape_glob(value: str) -> str:
    escaped: list[str] = []
    for char in value:
        if char in {"*", "?", "[", "]", "\\"}:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def normalize_pathish(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def command_glob_to_regex(pattern: str) -> str:
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


def path_glob_to_regex(pattern: str) -> str:
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
