from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from coco_code.hook.event import Event
from coco_code.permission.matcher import Matcher

Payload = Mapping[str, Any]
CombineMode = Literal["all_of", "any_of"]
ActionType = Literal["shell", "prompt", "http", "subagent"]


@dataclass(frozen=True)
class AtomCondition:
    field: str
    matcher: Matcher


@dataclass(frozen=True)
class Condition:
    mode: CombineMode
    atoms: tuple[AtomCondition, ...]


@dataclass(frozen=True)
class ShellAction:
    command: str


@dataclass(frozen=True)
class PromptAction:
    text: str


@dataclass(frozen=True)
class HttpAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | None = None


@dataclass(frozen=True)
class SubagentAction:
    agent_name: str
    prompt: str


@dataclass(frozen=True)
class HookAction:
    type: ActionType
    value: ShellAction | PromptAction | HttpAction | SubagentAction


@dataclass(frozen=True)
class HookRule:
    name: str
    event: Event
    action: HookAction
    condition: Condition | None = None
    only_once: bool = False
    async_mode: bool = False
    timeout_seconds: float = 30.0
    source: str = ""
    index: int = 0
